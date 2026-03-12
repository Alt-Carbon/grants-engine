"""Scout Agent — discovers grant opportunities via Tavily + Exa + Perplexity + direct crawl.

Architecture:
  1. Run all Tavily keyword queries in parallel
  2. Run all Exa semantic queries in parallel (with highlights)
  3. Run all Perplexity Sonar queries in parallel (direct API preferred, gateway fallback)
  4. Crawl known grant pages directly (DFIs, foundations, govt programs, aggregators)
  5. Merge + deduplicate results by URL hash
  6. 3-layer dedup against existing DB (url_hash → normalized URL hash → content hash)
  7. Fetch full content for each new grant (Jina primary, plain HTTP fallback) with retry
  8. LLM field extraction with robust JSON parsing
  9. Quality filter + save via upsert to grants_raw
  10. Hand off raw_grants list to Analyst

Robustness features:
- parse_json_safe: handles code fences, prose prefix, array wrapping
- retry_async: exponential backoff on Jina/Tavily/Exa failures
- Jina concurrency limited to 3 (respects free-tier 10 RPM with per-request delay)
- Per-item enrichment timeout (45s) prevents hung grants from blocking the pipeline
- Direct-crawl has an overall 180s timeout guard
- insert_one → update_one upsert (safe for concurrent/replayed runs)
- grants_scored imported at module level (not inside hot paths)
- Perplexity URL regex strips trailing punctuation
- Quality filter runs on raw title BEFORE LLM extraction overwrites it
- max_tokens raised to 1024 for field extraction
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import httpx

from backend.db.mongo import grants_raw, grants_scored, scout_runs, audit_logs
from backend.graph.state import GrantState
from backend.utils.llm import chat, HAIKU
from backend.utils.parsing import parse_json_safe, retry_async, api_health, CreditExhaustedError

logger = logging.getLogger(__name__)

# ── Tavily queries ─────────────────────────────────────────────────────────────
DEFAULT_TAVILY_QUERIES: List[str] = [
    # ── CDR / Climate Core (merged from 9 → 4) ────────────────────────────────
    "carbon removal CDR ERW biochar MRV startup grant funding 2026",
    "climatetech net zero decarbonisation startup grant open call 2026",
    "carbon credit verification monitoring technology grant 2026",
    "nature based solutions climate adaptation resilience grant 2026",
    # ── Agritech / Soil ────────────────────────────────────────────────────────
    "agritech soil carbon regenerative agriculture grant program 2026",
    "precision agriculture farmer technology startup grant 2026",
    # ── AI for Sciences + Earth Sciences ────────────────────────────────────────
    "AI for climate science earth observation machine learning grant 2026",
    "remote sensing geospatial satellite land use grant 2026",
    # ── India — central government (exact program names) ───────────────────────
    "BIRAC BIG Biotechnology Ignition Grant open 2026",
    "BIRAC BIPP SBIRI ACE startup grant open call 2026",
    "ANRF DPIIT startup grant call for proposals 2026",
    "DST NIDHI PRAYAS SEED TIDE startup grant 2026",
    "DST SERB startup research grant 2026 apply",
    "DST Climate Change Programme grant India 2026",
    "DBT soil carbon agritech research grant India 2026",
    "AIM Atal Innovation Mission startup grant India 2026",
    "MeitY IndiaAI Innovation Challenge startup grant 2026",
    "TDB Technology Development Board India grant 2026",
    "Startup India SISFS seed fund startup grant 2026",
    "BIRAC Green Hydrogen Mission startup grant 2026",
    "NISE MNRE solar energy innovative projects grant 2026",
    # ── India — state government ───────────────────────────────────────────────
    "Karnataka KSCST KBITS startup grant 2026",
    "Maharashtra MSINS startup innovation grant 2026",
    "Telangana T-Hub WE Hub grant program 2026",
    "StartupTN Tamil Nadu climatetech agritech grant 2026",
    "KSUM Kerala startup mission grant 2026",
    "India state government startup grant climatetech agritech 2026",
    # ── India — philanthropic & impact ──────────────────────────────────────────
    "Tata Trusts Azim Premji climate environment grant India 2026",
    "Social Alpha Villgro innovation grant India climatetech agritech 2026",
    "India Climate Collaborative Rohini Nilekani grant open call 2026",
    # ── Social Impact ──────────────────────────────────────────────────────────
    "social impact inclusive climate solutions rural livelihoods grant 2026",
    # ── DFIs & Multilateral ──────────────────────────────────────────────────
    "World Bank IFC ADB AIIB climate finance grant startups 2026",
    "Green Climate Fund GCF readiness grant 2026",
    "USAID UNDP UNEP climate innovation grant 2026",
    # ── Philanthropic (merged) ─────────────────────────────────────────────────
    "Bezos Earth Fund ClimateWorks Grantham climate grant 2026",
    "Rockefeller Foundation Bloomberg Schmidt Futures climate grant 2026",
    "Breakthrough Energy Omidyar Laudes Foundation climate startup grant 2026",
    "Echoing Green Skoll Earthshot Prize climate fellowship 2026",
    # ── Accelerators & Challenges (merged from 8 → 3) ──────────────────────────
    "Google.org XPRIZE Microsoft climate innovation challenge 2026",
    "MIT Solve Climate Launchpad Hello Tomorrow deep tech challenge 2026",
    "global cleantech innovation programme GCIP Zayed Sustainability Prize 2026",
    # ── CDR-specific funders ────────────────────────────────────────────────────
    "Cascade Climate CRN Enhanced Rock Weathering host site EOI 2026",
    "Carbon to Sea CIEIF ClimeFi Milkywire CDR grant RFP 2026",
    # ── Space & Earth Observation ──────────────────────────────────────────────
    "ESA InCubed CASSINI earth observation startup programme 2026",
    "ISRO RESPOND NRSC earth observation research grant India 2026",
    "NASA ROSES earth science remote sensing grant 2026",
    # ── Australia & Pacific ──────────────────────────────────────────────────
    "ARENA Australia cleantech CSIRO startup grant 2026",
    "New Zealand climate innovation fund grant 2026",
    # ── Canada ────────────────────────────────────────────────────────────────
    "Canada SDTC NRC IRAP cleantech climate startup grant 2026",
    "Natural Resources Canada carbon capture FEED grant 2026",
    # ── Southeast Asia ────────────────────────────────────────────────────────
    "Singapore Enterprise cleantech startup grant 2026",
    "ASEAN Southeast Asia Temasek climate tech startup grant 2026",
    "Indonesia Thailand Vietnam climate innovation grant 2026",
    # ── East Asia ─────────────────────────────────────────────────────────────
    "Japan NEDO green innovation fund startup grant 2026",
    "South Korea K-startup climate innovation grant 2026",
    # ── Africa (7 → 2) ─────────────────────────────────────────────────────────
    "African Development Bank AfDB SEFA climate grant open call 2026",
    "Africa climate startup agritech innovation fund grant 2026",
    # ── Latin America (7 → 2) ──────────────────────────────────────────────────
    "IDB Lab CORFO CAF Latin America climate startup grant 2026",
    "Brazil BNDES Colombia Innpulsa climate innovation grant 2026",
    # ── MENA (5 → 2) ──────────────────────────────────────────────────────────
    "Islamic Development Bank UAE Masdar climate innovation grant 2026",
    "MENA climate tech startup grant program 2026",
    # ── UK ─────────────────────────────────────────────────────────────────────
    "Innovate UK UKRI Carbon Trust net zero climate grant 2026",
    "UK DESNZ energy innovation startup grant 2026",
    # ── Global / Thematic ──────────────────────────────────────────────────────
    "climate MRV soil carbon sequestration grant developing countries 2026",
    "climate adaptation resilience startup grant global 2026",
    "deep tech climate innovation grant India global 2026",
    # ── Global climate finance + food ──────────────────────────────────────────
    "Global Innovation Lab Climate Finance CPI 2026 call for ideas",
    "WFP Innovation Accelerator food climate challenge 2026",
    "ADB Climate Innovation Development Fund CIDF grant 2026",
    "Greentown Go Make accelerator 2026 RFA application",
    "LILAS4SOILS Horizon Europe soil carbon MRV open call 2026",
    "Mitigation Action Facility call for projects 2026 climate",
    "UNDP young climate leaders direct funding 2026",
    # ── Deep Tech ──────────────────────────────────────────────────────────────
    "deep tech frontier science startup grant 2026",
    "advanced materials nanotechnology quantum computing grant 2026",
    "synthetic biology biotech breakthrough innovation grant 2026",
    "deep tech hardware robotics advanced manufacturing grant India global 2026",
    # ── AI for Sciences ────────────────────────────────────────────────────────
    "AI artificial intelligence scientific discovery grant program 2026",
    "machine learning predictive model environmental data grant 2026",
    "AI data science climate agriculture research grant India 2026",
    # ── Applied Earth Sciences ─────────────────────────────────────────────────
    "earth science geology subsurface geophysics research grant 2026",
    "satellite remote sensing LIDAR mapping technology grant 2026",
    "geospatial earth observation land use monitoring grant India 2026",
    # ── Social Impact ──────────────────────────────────────────────────────────
    "social impact rural livelihoods community resilience grant 2026",
    "inclusive climate solutions marginalized communities grant India 2026",
    "farmer livelihoods rural development climate grant developing countries 2026",
    # ── AltCarbon-specific ───────────────────────────────────────────────────
    "enhanced rock weathering ERW startup grant funding 2026",
    "biochar carbon sequestration grant developing countries 2026",
    "MRV carbon monitoring verification startup grant 2026",
]

# ── Exa semantic queries ───────────────────────────────────────────────────────
DEFAULT_EXA_QUERIES: List[str] = [
    # ── Core thematic (natural language — Exa's strength) ──────────────────────
    "Grants and funding for startups building carbon removal measurement and verification tools",
    "Open calls for companies doing enhanced rock weathering or biochar carbon sequestration",
    "Funding programs for AI-powered environmental monitoring and earth observation startups",
    "Grants for soil carbon sequestration and regenerative agriculture technology companies",
    "Accelerator programs offering equity-free funding for deep tech climate startups",
    "Government grants for cleantech and net zero startups in developing countries",
    "Philanthropic foundations funding carbon dioxide removal CDR technology development",
    # ── Major funders ──────────────────────────────────────────────────────────
    "Bezos Earth Fund open grant opportunities for climate technology companies",
    "EU Horizon Europe EIC Accelerator open calls for climate and deep tech",
    "Green Climate Fund readiness grants for climate projects in developing countries",
    "UKRI Innovate UK funding competitions for net zero and sustainability startups",
    # ── India programs ─────────────────────────────────────────────────────────
    "BIRAC BIG SBIRI BIPP biotechnology startup grants open for applications India",
    "ANRF DST NIDHI PRAYAS TIDE startup grants currently accepting proposals India",
    "DST SERB science research grants for startups and investigators India",
    "AIM TDB MeitY startup grants for climate technology and AI India",
    "Indian philanthropic foundations funding climate and agritech startups",
    "India state government startup grants for climatetech and agritech companies",
    # ── CDR-specific funders ────────────────────────────────────────────────────
    "Cascade Climate CRN enhanced rock weathering host site expression of interest",
    "Carbon to Sea CIEIF ClimeFi Milkywire carbon removal grant programs open calls",
    # ── Space & Earth Observation ──────────────────────────────────────────────
    "ESA InCubed CASSINI earth observation startup funding programmes open calls",
    "ISRO RESPOND NASA ROSES earth science remote sensing research grants",
    # ── Regional coverage ──────────────────────────────────────────────────────
    "ARENA Australia cleantech renewable energy startup grants open for applications",
    "Canada SDTC NRC IRAP cleantech climate startup grants and funding",
    "Singapore ASEAN Southeast Asia climate technology startup grants and accelerators",
    "Japan NEDO South Korea climate green innovation fund grants for startups",
    "African Development Bank climate finance grants for startups and innovation",
    "IDB Lab CORFO CAF Latin America climate innovation grants for startups",
    "UAE Masdar ISDB MENA region climate technology innovation grants",
    "Innovate UK Carbon Trust net zero climate startup grant competitions",
    # ── Global thematic ────────────────────────────────────────────────────────
    "Climate adaptation resilience grants for developing countries and emerging markets",
    "Carbon markets MRV monitoring verification startup grants globally",
    "Deep tech frontier science grants for climate and environmental companies",
    # ── Global climate finance + food ──────────────────────────────────────────
    "Global Innovation Lab for Climate Finance calls for ideas and applications",
    "WFP Innovation Accelerator food system climate challenge applications open",
    "ADB Climate Innovation Development Fund CIDF grants open for proposals",
    "Soil carbon MRV farmer technology grants Horizon Europe open calls",
    # ── Deep Tech ──────────────────────────────────────────────────────────────
    "Grants for deep tech startups working on advanced materials nanotechnology or quantum computing",
    "Funding for frontier science and engineering breakthroughs in climate and environment",
    "Accelerators and grants for hardware robotics and advanced manufacturing startups",
    # ── AI for Sciences ────────────────────────────────────────────────────────
    "Grants for startups applying artificial intelligence and machine learning to scientific discovery",
    "Funding for AI-powered predictive modeling for environmental and climate applications",
    # ── Social Impact ──────────────────────────────────────────────────────────
    "Grants for inclusive climate solutions benefiting rural and marginalized communities",
    "Funding for social impact startups improving farmer livelihoods through climate technology",
    "Community resilience and rural development grants for climate adaptation in developing countries",
    # ── AltCarbon-specific ───────────────────────────────────────────────────
    "Grants for companies selling carbon credits to corporate buyers like Google Stripe Shopify",
    "Funding for Indian startups working on MRV platforms for carbon removal verification",
    "ERW enhanced rock weathering field trials grants and pilot funding opportunities",
    "Biochar production grants for developing country climate startups",
    "CDR buyer programs accepting Indian companies for carbon removal credit purchases",
]

# ── Perplexity Sonar queries ────────────────────────────────────────────────────
DEFAULT_PERPLEXITY_QUERIES: List[str] = [
    "What grant programs are currently open for climate technology startups in 2026?",
    "List open calls for funding for carbon removal MRV and net-zero technology startups 2026",
    "What grants or accelerators are accepting applications from agritech and soil carbon startups in 2026?",
    "Which foundations or government programs fund climate startups in India or globally right now?",
    "World Bank ADB IFC AIIB climate finance grant open calls 2026",
    "Bezos Earth Fund Grantham Foundation ClimateWorks open grant applications 2026",
    "Which BIRAC ANRF DST DBT AIM India government programs have open grant calls for startups in 2026? List with URLs",
    "EU Horizon EIC UKRI climate deep tech grant open calls 2026",
    "XPRIZE Google.org Microsoft climate innovation grant competition 2026",
    # Global coverage
    "Australia ARENA CSIRO Canada SDTC NRC IRAP cleantech startup grant open calls 2026",
    "Japan NEDO South Korea climate innovation grant open calls 2026",
    "IDB Lab CORFO Latin America UAE Masdar ISDB MENA climate grant 2026",
    "Innovate UK Carbon Trust climate net zero grant competition open 2026",
    "Africa AfDB SEFA Southeast Asia ASEAN climate startup grant open 2026",
    # CDR + Earth Observation specific
    "What CDR-specific programs are open in 2026? Cascade Climate CRN, Carbon to Sea, CIEIF, ClimeFi, Milkywire CTF",
    "ESA InCubed CASSINI ISRO RESPOND NASA ROSES earth observation grants open 2026",
    "IndiaAI Innovation Challenge TDB NISE MNRE BIRAC Green Hydrogen open calls India 2026",
    "Greentown Go Make WFP Innovation Accelerator ADB CIDF Global Innovation Lab climate grant 2026",
    "LILAS4SOILS EU Horizon Europe soil carbon MRV open calls 2026",
    # Deep Tech + AI for Sciences + Social Impact
    "What grants fund deep tech startups working on advanced materials, nanotechnology, or frontier science in 2026?",
    "Which AI for science or machine learning research grants are open for startups in India or globally in 2026?",
    "What social impact grants fund rural livelihoods, inclusive climate solutions, or community resilience in 2026?",
    # AltCarbon-specific
    "What grants fund enhanced rock weathering ERW or biochar carbon sequestration startups in 2026?",
    "Which MRV and carbon verification technology grants are open for Indian companies in 2026?",
    "What CDR buyer programs or advance market commitments accept Indian companies for carbon removal credits?",
]

# ── Direct source URLs to crawl ────────────────────────────────────────────────
DIRECT_SOURCE_URLS: Dict[str, List[Dict[str, str]]] = {
    "DFI": [
        {"funder": "IFC", "url": "https://www.ifc.org/en/what-we-do/sector-expertise/climate-finance"},
        {"funder": "World Bank CIF", "url": "https://www.climateinvestmentfunds.org/programs"},
        {"funder": "World Bank", "url": "https://www.worldbank.org/en/programs/apply-for-funding"},
        {"funder": "ADB", "url": "https://www.adb.org/what-we-do/topics/climate-change/overview"},
        {"funder": "AIIB", "url": "https://www.aiib.org/en/about-aiib/who-we-are/partnership/index.html"},
        {"funder": "GCF", "url": "https://www.greenclimate.fund/projects/pipeline"},
        {"funder": "GCF Readiness", "url": "https://www.greenclimate.fund/readiness"},
        {"funder": "GEF SGP", "url": "https://www.thegef.org/who-we-are/secretariat/grants"},
        {"funder": "US DFC", "url": "https://www.dfc.gov/what-we-offer/financing"},
        {"funder": "EIB", "url": "https://www.eib.org/en/projects/index.htm"},
        {"funder": "KfW", "url": "https://www.kfw.de/international-financing/"},
    ],
    "Philanthropic": [
        {"funder": "Bezos Earth Fund", "url": "https://www.bezosearthfund.org/grants"},
        {"funder": "Grantham Foundation", "url": "https://www.granthamfoundation.org/grants"},
        {"funder": "Rockefeller Foundation", "url": "https://www.rockefellerfoundation.org/grants/"},
        {"funder": "ClimateWorks Foundation", "url": "https://www.climateworks.org/grants/"},
        {"funder": "Wellcome Trust", "url": "https://wellcome.org/grant-funding"},
        {"funder": "MacArthur Foundation", "url": "https://www.macfound.org/programs/what-we-fund"},
        {"funder": "Hewlett Foundation", "url": "https://hewlett.org/grants/"},
        {"funder": "Packard Foundation", "url": "https://www.packard.org/grants-and-investments/"},
        {"funder": "Gates Foundation", "url": "https://www.gatesfoundation.org/our-work/programs/global-development"},
        {"funder": "Ford Foundation", "url": "https://www.fordfoundation.org/work/our-grants/"},
        {"funder": "Gordon Betty Moore Foundation", "url": "https://www.moore.org/grants"},
        {"funder": "Rohini Nilekani Philanthropies", "url": "https://rohininilekani.org/"},
        {"funder": "Tata Trusts", "url": "https://www.tatatrusts.org/"},
        {"funder": "Azim Premji Philanthropic Initiative", "url": "https://azimpremjiphilanthropic.org/"},
        # Expanded philanthropic sources
        {"funder": "Bloomberg Philanthropies", "url": "https://www.bloomberg.org/environment/"},
        {"funder": "Schmidt Futures", "url": "https://www.schmidtfutures.com/our-work/grants/"},
        {"funder": "Eric & Wendy Schmidt Fund", "url": "https://www.schmidtfamily.foundation/climate"},
        {"funder": "Open Philanthropy", "url": "https://www.openphilanthropy.org/grants/?focus-area=climate-change"},
        {"funder": "Omidyar Network", "url": "https://omidyar.com/our-work/"},
        {"funder": "Laudes Foundation", "url": "https://www.laudesfoundation.org/our-grants/"},
        {"funder": "Skoll Foundation", "url": "https://skoll.org/about/grant-making/"},
        {"funder": "Draper Richards Kaplan Foundation", "url": "https://www.drkfoundation.org/apply/"},
        {"funder": "Generation Foundation", "url": "https://www.generationfoundation.org/"},
        {"funder": "Breakthrough Energy", "url": "https://www.breakthroughenergy.org/"},
        {"funder": "Patrick J McGovern Foundation", "url": "https://www.mcgovern.org/"},
        {"funder": "Clif Bar Family Foundation", "url": "https://www.clifbarfamilyfoundation.org/grants"},
        {"funder": "Convergence Blended Finance", "url": "https://www.convergence.finance/funding-opportunities"},
        {"funder": "Sequoia Climate Fund", "url": "https://www.sequoia.com/climate"},
        {"funder": "MAVA Foundation", "url": "https://www.mava-foundation.org/funding/"},
        {"funder": "Esmee Fairbairn Foundation", "url": "https://esmeefairbairn.org.uk/"},
        {"funder": "Echoing Green", "url": "https://echoinggreen.org/fellowship/"},
        {"funder": "Autodesk Foundation", "url": "https://www.autodesk.org/grants"},
    ],
    "Challenges & Prizes": [
        {"funder": "XPRIZE Competitions", "url": "https://www.xprize.org/prizes"},
        {"funder": "Earthshot Prize", "url": "https://earthshotprize.org/"},
        {"funder": "MIT Solve Challenges", "url": "https://solve.mit.edu/challenges"},
        {"funder": "Hult Prize", "url": "https://hultprize.org/"},
        {"funder": "Global Cleantech Innovation Programme", "url": "https://www.globalcleantechinnovation.org/"},
        {"funder": "Mission Innovation Challenges", "url": "https://mission-innovation.net/our-work/innovation-challenges/"},
        {"funder": "Norrsken Foundation Prize", "url": "https://www.norrsken.org/"},
        {"funder": "Zayed Sustainability Prize", "url": "https://www.zayedsustainabilityprize.com/en-us/apply.html"},
        {"funder": "Katerva Award", "url": "https://katerva.net/"},
        {"funder": "Unilever Young Entrepreneurs Awards", "url": "https://www.unilever.com/"},
        {"funder": "Schwab Foundation Social Entrepreneur", "url": "https://www.schwabfound.org/apply"},
        {"funder": "Cartier Womens Initiative", "url": "https://www.cartierwomensinitiative.com/"},
        {"funder": "Anthem Awards Sustainability", "url": "https://www.anthemawards.com/"},
        {"funder": "Climate Launchpad", "url": "https://climatelaunchpad.org/"},
        {"funder": "Hello Tomorrow Challenge", "url": "https://hello-tomorrow.org/"},
        {"funder": "Start Codon Climate Cohort", "url": "https://www.startcodon.co/"},
        {"funder": "Unreasonable Group", "url": "https://unreasonablegroup.com/initiatives/"},
        {"funder": "Dell Technologies Climate Prize", "url": "https://www.delltechnologies.com/"},
        {"funder": "WEF UpLink Climate", "url": "https://uplink.weforum.org/"},
        {"funder": "AI for Good Grant", "url": "https://aiforgood.itu.int/"},
    ],
    "Climate Funders": [
        {"funder": "Frontier AMC", "url": "https://frontierclimate.com/"},
        {"funder": "Carbon180", "url": "https://carbon180.org/funding"},
        {"funder": "XPRIZE", "url": "https://www.xprize.org/prizes"},
        {"funder": "Spark Climate Solutions", "url": "https://www.sparkclimatesolutions.org/"},
        {"funder": "Global Methane Hub", "url": "https://www.globalmethanehub.org/"},
        {"funder": "Energy Foundation", "url": "https://www.energyfoundation.org/grantmaking/"},
        {"funder": "Climate Collective India", "url": "https://climatecollective.org/"},
        {"funder": "Third Derivative D3", "url": "https://third-derivative.org/"},
        {"funder": "Builders Initiative", "url": "https://www.buildersinitiative.org/"},
        {"funder": "Trellis Climate", "url": "https://www.trellisclimate.org/"},
        # CDR-specific funders discovered from manually curated grant sheets
        {"funder": "Cascade Climate CRN", "url": "https://cascadeclimate.org/blog/crn-eoi"},
        {"funder": "Carbon to Sea Initiative", "url": "https://www.carbontosea.org/"},
        {"funder": "CIEIF CDR Fund", "url": "https://cieif.org/"},
        {"funder": "ClimeFi CDR RFP", "url": "https://climefi.com/blog-posts/climefi-and-adyen-launch-new-dual-track-rfp-for-carbon-removal"},
        {"funder": "Milkywire Climate Transformation Fund", "url": "https://milkywire.com/"},
        {"funder": "Puro.earth CDR Marketplace", "url": "https://puro.earth/"},
    ],
    "Government Programs": [
        {"funder": "EU EIC Accelerator", "url": "https://eic.ec.europa.eu/eic-funding-opportunities_en"},
        {"funder": "EU Horizon Europe Cluster 5", "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search;callCode=HORIZON-CL5"},
        {"funder": "EU Horizon Europe Cluster 6", "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search;callCode=HORIZON-CL6"},
        {"funder": "NASA SBIR", "url": "https://sbir.nasa.gov/solicitations"},
        {"funder": "UK SBRI", "url": "https://www.gov.uk/government/collections/sbri-the-small-business-research-initiative"},
        {"funder": "Swiss Climate Foundation", "url": "https://www.swissclimatefoundation.ch/en/apply/"},
        {"funder": "NSF SBIR", "url": "https://www.nsf.gov/eng/iip/sbir/"},
        {"funder": "DOE ARPA-E", "url": "https://arpa-e.energy.gov/technologies/programs"},
        {"funder": "USAID", "url": "https://www.usaid.gov/work-usaid/find-a-funding-opportunity"},
        {"funder": "UKRI Innovate UK", "url": "https://www.ukri.org/opportunity/"},
        # BIRAC — CFP hub + known major programs (plain HTTP used, bypasses Jina 402)
        {"funder": "BIRAC", "url": "https://birac.nic.in/cfp.php"},
        {"funder": "BIRAC BIG", "url": "https://birac.nic.in/webcontent/1665_BIRAC_BIG_Scheme.pdf"},
        {"funder": "BIRAC BIPP", "url": "https://birac.nic.in/bipp.php"},
        {"funder": "BIRAC SBIRI", "url": "https://birac.nic.in/sbiri.php"},
        # DST — hub + key programs
        {"funder": "DST India CFP", "url": "https://dst.gov.in/callforproposals"},
        {"funder": "DST NIDHI", "url": "https://www.dst.gov.in/national-initiative-developing-and-harnessing-innovations-nidhi"},
        {"funder": "DST SERB SUPRA", "url": "https://www.serb.gov.in/supra.php"},
        {"funder": "DST Climate Change Programme", "url": "https://dst.gov.in/scientific-programmes/climate-change-programme"},
        # ANRF — online portal with all active calls
        {"funder": "ANRF India", "url": "https://anrfonline.in/ANRF/HomePage"},
        {"funder": "ANRF Current CFP", "url": "https://anrfonline.in/ANRF/CurrentCFP"},
        # Startup India / AIM / MeitY
        {"funder": "Startup India SISFS", "url": "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"},
        {"funder": "AIM ANIC", "url": "https://aim.gov.in/"},
        {"funder": "MeitY Startup Hub", "url": "https://msh.gov.in/"},
        {"funder": "TDB India", "url": "https://www.tdb.gov.in/"},
        {"funder": "NABARD", "url": "https://www.nabard.org/"},
        # Indian CSR and impact funders
        {"funder": "CSRBOX India Grants", "url": "https://csrbox.org/India-CSR-Grants_India-grant-funding/"},
        {"funder": "IndiaGrants", "url": "https://indiagrants.org/"},
        {"funder": "Social Alpha Grants", "url": "https://www.socialalpha.org/"},
        {"funder": "Villgro India", "url": "https://villgro.org/"},
        {"funder": "India Climate Collaborative", "url": "https://indiaclimate.org/"},
        # International
        {"funder": "Mitigation Action Facility", "url": "https://mitigation-action.org/call-for-projects-2026/"},
        {"funder": "ESA Kick-Start", "url": "https://business.esa.int/funding/open-competitive-calls"},
        {"funder": "NASA ROSES", "url": "https://science.nasa.gov/researchers/solicitations/roses-2025/"},
    ],
    "Aggregators": [
        # Hub pages — each is expanded into individual grant URLs via _extract_hub_subgrants()
        {"funder": "Grants.gov", "url": "https://www.grants.gov/search-grants?oppStatuses=forecasted%7Copen"},
        {"funder": "F6S Programs", "url": "https://www.f6s.com/programs"},
        {"funder": "EU Funding Tenders", "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search"},
        {"funder": "Devex", "url": "https://www.devex.com/funding"},
        {"funder": "CSRBOX", "url": "https://csrbox.org/India-CSR-Grants_India-grant-funding/"},
        {"funder": "IndiaGrants", "url": "https://indiagrants.org/"},
        # Extra seed sources from the LangSmith scout that produced good results
        {"funder": "Startup Grants India", "url": "https://www.startupgrantsindia.com/"},
        {"funder": "And Purpose Grants", "url": "https://andpurpose.world/grants/"},
        {"funder": "Grant Repository (Notion)", "url": "https://grantrepository.notion.site/Welcome-Founders-270d3c1b4a3680f3ba32f2eb8f09e9c3"},
        {"funder": "Alan Arguello Accelerators", "url": "https://www.alanarguello.me/blog/accelerators"},
        {"funder": "FundsForNGOs", "url": "https://www2.fundsforngos.org/category/climate-change/"},
        {"funder": "Climate Finance Lab", "url": "https://www.climatefinancelab.org/apply"},
        {"funder": "Wren Climate Collective", "url": "https://www.wren.co/open-grants"},
        {"funder": "remove.global India", "url": "https://remove.global/india-accelerator"},
        {"funder": "Milkywire CDR", "url": "https://milkywire.com/"},
    ],
    "Accelerators": [
        {"funder": "Google.org Impact Challenge", "url": "https://impactchallenge.withgoogle.com/"},
        {"funder": "Microsoft Climate Innovation Fund", "url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/climate-innovation-fund"},
        {"funder": "Social Alpha", "url": "https://www.socialalpha.org/"},
        {"funder": "Villgro", "url": "https://villgro.org/"},
        {"funder": "India Climate Collaborative", "url": "https://indiaclimate.org/"},
        {"funder": "Uplink UNDP", "url": "https://uplink.undp.org/"},
        {"funder": "IFC She Wins Climate", "url": "https://www.ifc.org/en/what-we-do/sector-expertise/gender/gender-Inclusive-climate-investment/she-wins-climate"},
        {"funder": "Global Innovation Fund", "url": "https://www.globalinnovation.fund/apply-for-funding"},
        {"funder": "Wellcome Climate Impacts", "url": "https://wellcome.org/grant-funding/schemes/climate-impacts-awards"},
        {"funder": "AI for Climate Bezos", "url": "https://aiforclimateandnature.org/"},
    ],
    "Australia & Pacific": [
        {"funder": "ARENA", "url": "https://arena.gov.au/funding/"},
        {"funder": "CSIRO ON Prime", "url": "https://www.csiro.au/en/work-with-us/funding-programs"},
        {"funder": "Accelerating Commercialisation AU", "url": "https://business.gov.au/grants-and-programs/accelerating-commercialisation"},
        {"funder": "CEFC Australia", "url": "https://www.cefc.com.au/investment-approach/how-we-invest/"},
        {"funder": "Breakthrough Victoria", "url": "https://www.breakthroughvictoria.com/investments"},
        {"funder": "New Zealand MBIE Callaghan", "url": "https://www.callaghaninnovation.govt.nz/grants/"},
        {"funder": "Clean Energy Council AU", "url": "https://www.cleanenergycouncil.org.au/"},
    ],
    "Canada": [
        {"funder": "SDTC", "url": "https://www.sdtc.ca/en/apply/"},
        {"funder": "NRC IRAP", "url": "https://nrc.canada.ca/en/support-technology-innovation/"},
        {"funder": "Foresight CleanTech", "url": "https://foresightcac.com/funding-navigator/"},
        {"funder": "MaRS Discovery District", "url": "https://www.marsdd.com/"},
        {"funder": "Emissions Reduction Alberta", "url": "https://eralberta.ca/funding-opportunities/"},
        {"funder": "NSERC Canada", "url": "https://www.nserc-crsng.gc.ca/Professors-Professeurs/RPP-PP/index_eng.asp"},
        {"funder": "BDC Climate Fund", "url": "https://www.bdc.ca/en/bdc-capital/cleantech"},
    ],
    "Southeast Asia": [
        {"funder": "Enterprise Singapore", "url": "https://www.enterprisesg.gov.sg/financial-assistance/grants"},
        {"funder": "Startup SG", "url": "https://www.startupsg.gov.sg/programmes/4896/seeds-capital"},
        {"funder": "Temasek Foundation", "url": "https://www.temasekfoundation.org/"},
        {"funder": "NTU Sustainability", "url": "https://www.ntu.edu.sg/research/research-careers-funding/funding-opportunities"},
        {"funder": "USAID ASEAN", "url": "https://www.usaid.gov/asia-regional"},
        {"funder": "BERD Indonesia", "url": "https://brin.go.id/en/"},
        {"funder": "NSTDA Thailand", "url": "https://www.nstda.or.th/en/funding/"},
        {"funder": "Vietnam MOST", "url": "https://www.most.gov.vn/en/"},
        {"funder": "Malaysia Green Tech Corporation", "url": "https://www.greentechmalaysia.my/"},
        {"funder": "Philippines DOST", "url": "https://www.dost.gov.ph/"},
        {"funder": "Rajawali Foundation", "url": "https://rajawali-foundation.org/"},
        {"funder": "Patamar Capital", "url": "https://www.patamar.com/"},
    ],
    "East Asia": [
        {"funder": "NEDO Japan", "url": "https://www.nedo.go.jp/english/introducing_index.html"},
        {"funder": "JST Japan", "url": "https://www.jst.go.jp/EN/"},
        {"funder": "KOICA South Korea", "url": "https://www.koica.go.kr/koica_en/"},
        {"funder": "KIAT South Korea", "url": "https://www.kiat.or.kr/site/eng/main.do"},
        {"funder": "Korea Green Growth Trust Fund", "url": "https://www.greengrowthknowledge.org/"},
        {"funder": "ITRI Taiwan", "url": "https://www.itri.org.tw/english/"},
    ],
    "Africa": [
        {"funder": "African Development Bank Climate", "url": "https://www.afdb.org/en/topics-and-sectors/sectors/climate-change"},
        {"funder": "SEFA", "url": "https://www.afdb.org/en/topics-and-sectors/initiatives-partnerships/sustainable-energy-fund-for-africa"},
        {"funder": "African Climate Foundation", "url": "https://africanclimate.org/grants/"},
        {"funder": "Africa50", "url": "https://www.africa50.com/"},
        {"funder": "Power Africa USAID", "url": "https://www.usaid.gov/powerafrica"},
        {"funder": "GreenTec Capital Africa", "url": "https://greentec-capital.com/"},
        {"funder": "Catalyst Fund Africa", "url": "https://catalyst.fund/"},
        {"funder": "Shell Foundation Africa", "url": "https://www.shellfoundation.org/"},
        {"funder": "Africa Enterprise Challenge Fund", "url": "https://www.aecfafrica.org/"},
        {"funder": "East Africa Climate Innovation", "url": "https://www.theclimateconnection.org/"},
        {"funder": "South Africa Green Fund", "url": "https://www.dbsa.org/green-fund"},
        {"funder": "Mastercard Foundation Africa", "url": "https://mastercardfdn.org/"},
        {"funder": "Tony Elumelu Foundation", "url": "https://www.tonyelumelufoundation.org/teep"},
    ],
    "Latin America": [
        {"funder": "IDB Lab", "url": "https://bidlab.org/en/calls"},
        {"funder": "CAF Development Bank", "url": "https://www.caf.com/en/currently/calls-for-proposals/"},
        {"funder": "CORFO Chile", "url": "https://www.corfo.cl/sites/cpp/convocatorias"},
        {"funder": "BNDES Brazil Climate", "url": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/"},
        {"funder": "Innpulsa Colombia", "url": "https://www.innpulsacolombia.com/"},
        {"funder": "CONACYT Mexico", "url": "https://conacyt.mx/convocatorias/"},
        {"funder": "FONTAGRO", "url": "https://www.fontagro.org/calls/"},
        {"funder": "LACLIMA", "url": "https://laclima.org/"},
        {"funder": "Climateworks Latin America", "url": "https://www.climateworks.org/region/latin-america/"},
    ],
    "Middle East & North Africa": [
        {"funder": "ISDB Climate", "url": "https://www.isdb.org/what-we-fund"},
        {"funder": "Masdar Clean Energy", "url": "https://masdar.ae/"},
        {"funder": "UAE Ministry Climate Change", "url": "https://www.moccae.gov.ae/en/knowledge-and-statistics/climate-change.aspx"},
        {"funder": "Saudi Aramco Sustainability", "url": "https://www.aramco.com/en/sustainability"},
        {"funder": "Arab Fund", "url": "https://arabfund.org/en/financing"},
        {"funder": "RCREEE", "url": "https://www.rcreee.org/"},
        {"funder": "MENA Catalyst", "url": "https://menacatalyst.com/"},
    ],
    "UK Standalone": [
        {"funder": "Innovate UK KTN", "url": "https://iuk.ktn-uk.org/opportunities/"},
        {"funder": "Carbon Trust Grants", "url": "https://www.carbontrust.com/our-work/grants-and-funding"},
        {"funder": "UKRI Net Zero", "url": "https://www.ukri.org/opportunity/?filter_council=innovate-uk&filter_keyword=net+zero"},
        {"funder": "DESNZ UK Energy Innovation", "url": "https://www.gov.uk/guidance/energy-innovation"},
        {"funder": "Natural Environment Research Council", "url": "https://www.ukri.org/councils/nerc/funding-opportunities/"},
        {"funder": "UK Space Agency Earth Observation", "url": "https://www.gov.uk/guidance/uk-space-agency-funding"},
    ],
    # Indian state government startup / science / climate programs.
    # Each state entry is the canonical program page — crawled directly so we
    # don't miss calls that Tavily or Exa overlook.
    "India State Programs": [
        # Karnataka — largest tech + agritech cluster for AltCarbon
        {"funder": "KSCST Karnataka", "url": "https://kscst.org.in/"},
        {"funder": "KBITS Karnataka", "url": "https://kbits.karnataka.gov.in/"},
        {"funder": "Startup Karnataka", "url": "https://startupkarnataka.gov.in/"},
        {"funder": "KIADB Karnataka Agri", "url": "https://www.kiadb.in/"},
        # Maharashtra — Mumbai + Pune startup + MSINS grants
        {"funder": "MSINS Maharashtra", "url": "https://msins.in/"},
        {"funder": "MCED Maharashtra", "url": "https://mced.in/"},
        # Telangana — T-Hub + WE Hub programs
        {"funder": "T-Hub Telangana", "url": "https://t-hub.co/programs"},
        {"funder": "WE Hub Telangana", "url": "https://wehub.telangana.gov.in/"},
        {"funder": "TSIC Telangana", "url": "https://tsic.telangana.gov.in/"},
        # Tamil Nadu
        {"funder": "StartupTN Tamil Nadu", "url": "https://www.startuptn.in/"},
        {"funder": "EDII Tamil Nadu", "url": "https://www.edii.tn.gov.in/"},
        # Kerala — KSUM is very active for climate/agritech
        {"funder": "KSUM Kerala", "url": "https://startupmission.kerala.gov.in/"},
        {"funder": "KSIDC Kerala", "url": "https://www.ksidc.org/"},
        # Gujarat
        {"funder": "i-Create Gujarat", "url": "https://www.icreate.org.in/"},
        {"funder": "GUSEC Gujarat", "url": "https://gusec.edu.in/"},
        # Rajasthan
        {"funder": "iStart Rajasthan", "url": "https://istart.rajasthan.gov.in/"},
        # Andhra Pradesh
        {"funder": "APNRT Andhra Pradesh", "url": "https://www.apnrt.in/"},
        {"funder": "AP Innovation Society", "url": "https://apinnovationsociety.com/"},
        # Madhya Pradesh
        {"funder": "MP Startup Centre", "url": "https://mpstartup.in/"},
        # Haryana
        {"funder": "Startup Haryana", "url": "https://startupharyana.gov.in/"},
        # Delhi
        {"funder": "Startup Delhi", "url": "https://dipp.gov.in/start-up-india"},
        # Uttar Pradesh
        {"funder": "Startup UP", "url": "https://invest.up.gov.in/startup/"},
        # Punjab
        {"funder": "Invest Punjab Startup", "url": "https://www.investpunjab.gov.in/"},
        # Pan-India NABARD for agritech specifically
        {"funder": "NABARD Agri Grant", "url": "https://www.nabard.org/content1.aspx?id=591&catid=23&mid=530"},
    ],
    "Space & Earth Observation": [
        # ESA programs — earth observation + InCubed
        {"funder": "ESA InCubed", "url": "https://incubed.esa.int/welcome-to-the-incubed-programme/"},
        {"funder": "ESA Kick-Start Activity", "url": "https://business.esa.int/funding/open-competitive-calls"},
        # CASSINI — EU space programme for startups & SMEs
        {"funder": "CASSINI Challenges EUSPA", "url": "https://www.euspa.europa.eu/cassinichallenges"},
        # Indian space programs
        {"funder": "ISRO RESPOND", "url": "https://www.isro.gov.in/ISRO_HINDI/RESPOND_BASKET_2025.html"},
        {"funder": "ISRO Venus Archival Data AO", "url": "https://www.isro.gov.in/AO_utilizing_archival_data_Planet_Venus.html"},
        {"funder": "NRSC ISRO Proposal", "url": "https://www.nrsc.gov.in/nrscnew/Respond_proposal_submission.php"},
        {"funder": "NASA ROSES", "url": "https://science.nasa.gov/researchers/solicitations/roses-2025/"},
    ],
    "Energy & Climate Research": [
        # MNRE/NISE — solar energy & new renewable
        {"funder": "MNRE Research Portal", "url": "https://research.mnre.gov.in/"},
        {"funder": "NISE MNRE PMSGY", "url": "https://www.nise.res.in/"},
        # TDB — specific 2026 startup call
        {"funder": "TDB Startup Call 2026", "url": "https://tdb.gov.in/call-proposal-empowering-tech-startups"},
        # IndiaAI — new MeitY initiative
        {"funder": "IndiaAI Innovation Challenge", "url": "https://indiaai.gov.in/"},
        # ADB Climate Innovation Development Fund
        {"funder": "ADB CIDF", "url": "https://www.adb.org/what-we-do/funds/climate-innovation-development-fund"},
        # Natural Resources Canada — carbon capture
        {"funder": "NRCan Carbon Capture FEED", "url": "https://natural-resources.canada.ca/funding-partnerships/energy-innovation-program/carbon-capture-front-end-engineering-design"},
        # WFP Innovation Accelerator
        {"funder": "WFP Innovation Accelerator", "url": "https://innovation.wfp.org/wfp-innovation-challenge"},
        # EU soil / agri programs
        {"funder": "LILAS4SOILS Open Call", "url": "https://www.lilas4soils.eu/"},
        # Greentown Go Make accelerator
        {"funder": "Greentown Go Make", "url": "https://greentownlabs.com/go-make-2026-rfa/"},
        # Global Innovation Lab for Climate Finance (CPI)
        {"funder": "Global Innovation Lab for Climate Finance", "url": "https://www.climatepolicyinitiative.org/lab-call-for-ideas/"},
        # UNDP Youth Climate Leaders
        {"funder": "UNDP Young Climate Leaders", "url": "https://climatepromise.undp.org/"},
        # Innovation Fund Denmark agriculture
        {"funder": "Innovation Fund Denmark AgData", "url": "https://innovationsfonden.dk/en/p/international-collaborations/"},
        # Mitigation Action Facility (already in Govt Programs, keep here too for visibility)
        {"funder": "Mitigation Action Facility", "url": "https://mitigation-action.org/call-for-projects-2026/"},
    ],
}

ALL_DIRECT_SOURCES: List[Dict[str, str]] = [
    src for srcs in DIRECT_SOURCE_URLS.values() for src in srcs
]

# ── LLM field extraction prompt ────────────────────────────────────────────────
EXTRACTION_SYSTEM = (
    "You are a grant data extraction specialist. "
    "Return ONLY valid JSON — no prose, no markdown, no explanation."
)

EXTRACTION_PROMPT = """Extract structured grant information from this grant page content.

Source URL: {url}
Page Title: {raw_title}

Content:
{content}

Return this exact JSON (no other text):
{{
  "grant_name": "<official grant/program name as stated on the page>",
  "sponsor": "<full legal name of the funding organization>",
  "grant_type": "<grant | prize | challenge | accelerator | fellowship | contract | loan | equity | other>",
  "geography": "<eligible countries/regions exactly as stated — e.g. 'India only', 'Global', 'US and EU'>",
  "amount": "<funding amount per applicant exactly as stated — e.g. 'up to $500,000', 'EUR 150,000'; capture what each applicant receives, not total program budget>",
  "max_funding_usd": <integer USD value per applicant — best conversion; null ONLY if truly no amount mentioned anywhere>,
  "currency": "<3-letter code: USD EUR GBP INR, default USD>",
  "deadline": "<application deadline EXACTLY as stated — e.g. 'March 31, 2026', 'Rolling', 'Ongoing'; extract ANY close/submission/deadline date visible; null ONLY if absolutely no date found>",
  "eligibility": "<who can apply: org type (startup/NGO/university), stage (seed/early/growth), sector, geography restrictions including any specific country/region exclusions — max 200 words>",
  "themes": "<key program focus areas and funding priorities — e.g. 'CDR, MRV, climate tech, India early-stage startups'>",
  "application_url": "<DIRECT link to the application form or portal — NOT the program overview page; fill only if you see a dedicated apply/submit/portal link; else null>",
  "source_url": "<the funder's own official grant program page URL; if this content came from a news article or blog mentioning the grant, provide the funder's direct grant page URL if visible in the content; otherwise use {url}>",
  "past_winners_url": "<URL of a past winners / previous awardees / funded projects / portfolio page if visible in the content — e.g. '/awardees', '/winners', '/portfolio'; null if not found>",
  "about_opportunity": "<2-4 sentences describing what this grant/program funds, its objectives, and what successful applicants receive — include any mentorship, networking, or non-monetary benefits>",
  "eligibility_details": "<detailed eligibility: org types (startup/NGO/university/for-profit), stage (seed/early/growth), sector restrictions, geography (countries/regions), team size, revenue thresholds, registration requirements, any exclusions — max 300 words>",
  "application_process": "<how to apply: portal/email/form, required documents (pitch deck, financials, LOI, etc.), number of stages (LOI → full proposal → interview), timeline, any registration prerequisites — max 200 words>",
  "notes": "<2-3 crisp sentences: what this program funds, who it targets, any key requirements or noteworthy conditions>"
}}

EXTRACTION RULES (follow strictly):
1. deadline — MANDATORY: extract ANY date that appears as a deadline, close date, or submission window end. Use 'Rolling' only if the grant explicitly says it accepts applications on a rolling or continuous basis. Use null only if no date is mentioned anywhere.
2. amount — extract the maximum award PER APPLICANT (not total fund size). E.g. if grant says "up to $500K per company", extract "$500K".
3. application_url — must link directly to an application form, portal, or submit page. Do NOT use the program overview or description page URL. Leave null if no direct apply link is found.
4. source_url — must be the funder's own official page for this specific grant. If content is from a news/blog/press article about the grant, look in the article for the funder's direct URL and use that instead.
5. eligibility — always include: eligible org types, geographic restrictions (including explicit exclusions like "US only", "UK registered only"), stage requirements, and sector focus. Write up to 200 words.
6. sponsor — use the full official organization name (e.g. "Bezos Earth Fund", not "BEF").
8. about_opportunity — describe what the grant funds, its goals, and benefits (monetary and non-monetary). If the page is a listing/aggregator, summarize the specific opportunity being described.
9. eligibility_details — be thorough: include org type, stage, sector, geography, team/revenue requirements, registration prerequisites, and any exclusions. More detailed than the short 'eligibility' field.
10. application_process — describe how to apply step-by-step: portal vs email, required documents, number of review stages, timeline if mentioned. Write "Not specified" if no process details are given.
7. Indian currency notation — CRITICAL for Indian grants:
   "1 lakh" = 100,000  |  "10 lakh" = 1,000,000  |  "1 crore" = 10,000,000
   Indian comma grouping: "5,00,000" = 500,000 (NOT 5,000 — Indian style groups by 2 after first 3)
   Examples:
     "₹50 lakh"     → amount="₹50 lakh",     max_funding_usd=5000000,  currency="INR"
     "₹2 crore"     → amount="₹2 crore",      max_funding_usd=20000000, currency="INR"
     "Rs. 30,00,000" → amount="Rs. 30,00,000", max_funding_usd=3000000,  currency="INR"
     "₹1.5 lakh"   → amount="₹1.5 lakh",    max_funding_usd=150000,   currency="INR"
   Always set currency="INR" for rupee amounts — do NOT convert to USD in max_funding_usd."""

# ── URL helpers ─────────────────────────────────────────────────────────────────
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
})

_SOCIAL_MEDIA_DOMAINS = frozenset({
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "threads.net", "reddit.com", "t.co",
    "medium.com", "substack.com",
})

_JUNK_TITLE_PATTERNS = (
    "press release", "news:", "newsletter", "blog post", "annual report",
    "impact report", "conference recap", "webinar", "event recap",
    "linkedin post", "twitter thread",
    # Listicles / market reports — these mention grants but are not grant pages
    "top companies", "top startups", "to watch", "best companies",
    "best startups", "companies to watch", "startups to watch",
    "investment landscape", "market report", "market overview",
    "industry report", "state of the market", "market analysis",
    "state of cdr", "state of carbon", "financing report",
    "investor guide", "landscape report",
)
# Trusted grant aggregator domains — these list real grant opportunities,
# so we bypass _JUNK_URL_PATTERNS and relax action keyword requirements.
_TRUSTED_GRANT_AGGREGATORS = frozenset({
    "finetrain.com",
    "startupgrantsindia.com",
    "fundsforngos.org",
    "grantwatch.com",
    "instrumentl.com",
    "opengranting.com",
    "fundingcircle.com",
    "grants.gov",
    "grants.gov.in",
    "seedfund.startupindia.gov.in",
    "icar.org.in",
    "dst.gov.in",
    "birac.nic.in",
    "anrfonline.in",
    "startupindia.gov.in",
})

_JUNK_URL_PATTERNS = (
    "/news/", "/blog/", "/press-release/", "/press_release/",
    "/events/", "/media/", "/webinar/", "/articles/",
    "/post/", "/posts/", "/status/",
    # Research/report pages — usually about grants, not actual grant pages
    "/report/", "/reports/", "/research/", "/publication/", "/publications/",
    "/insights/", "/resources/resource/", "/thought-leadership/",
)
_GRANT_KEYWORDS = (
    "apply", "application", "grant", "funding", "fund", "award", "prize",
    "call for", "open call", "deadline", "eligib", "proposal", "submit",
    "accelerator", "fellowship", "competition", "rfp", "rfq",
)
# At least one of these "action" keywords must appear — articles that merely
# mention grants rarely use these verbs in an instructional context.
_GRANT_ACTION_KEYWORDS = (
    "apply now", "how to apply", "application deadline", "submit your",
    "applications open", "open for applications", "call for proposals",
    "eligibility criteria", "who can apply", "submit a proposal",
    "apply by", "applications close", "deadline to apply",
    "nominations welcome", "expressions of interest", "eoi",
    "register your interest", "request for applications", "rfa",
    "application form", "application portal", "grant application",
    "closes on", "closing date", "submit by", "last date",
    "open call", "invite applications", "accepting applications",
)

# Perplexity URL cleaner: strip common trailing punctuation
_URL_TRAILING_JUNK = re.compile(r"[.,;:!?\)\]]+$")

# ── Hub page sub-grant expansion ───────────────────────────────────────────────
# These domains host multiple individual grant calls on a single listing page.
# After fetching the hub, we extract each sub-grant URL and enrich it separately.
# This is how the LangSmith scout got 8+ BIRAC entries from a single BIRAC page.
_HUB_SUBGRANT_PATTERNS: Dict[str, List[re.Pattern]] = {
    # BIRAC CFP hub: each call is at cfp_view.php?id=NNN
    "birac.nic.in": [
        re.compile(r"cfp_view\.php\?id=\d+(?:&[^\s\"'<>]*)?"),
    ],
    # DST call-for-proposals listing: /callforproposals/some-title
    "dst.gov.in": [
        re.compile(r"/callforproposals/[a-z0-9][a-z0-9\-_/]+"),
    ],
    # ANRF online portal — match program/scheme/call pages, exclude non-grant paths.
    # ANRF uses paths like /ANRF/CallForProposal, /ANRF/CurrentCFP, /ANRF/ListScheme.
    # Excluded prefixes: resources/ (CSS/JS assets), internal pages, irrelevant fellowships.
    # NOTE: keep relevant fellowships like ECRG, JC Bose, VAJRA, SRG — they are grant programs.
    "anrfonline.in": [
        re.compile(
            r"/ANRF/(?!"
            r"resources/|HomePage\b|AnrfPDF\b|index\b|Abstract|Login|Register|"
            r"Women_\w+|Tetra\b|Sire\b|Contact\b|About\b|Faq\b|Circulars?\b|"
            r"Covid_19\b|seminar_symposia\b|nationalScienceChair\b|IMPRINT2C\b|"
            r"maha_Instructions\b|serbPowerInstructions\b|Weaker_section\b|"
            r"matrics_new\b|PMProfessorship\b"
            r")[A-Za-z][A-Za-z0-9_\-/]{4,}",
            re.I
        ),
    ],
    # Startup India individual scheme pages
    "startupindia.gov.in": [
        re.compile(r"/content/sih/en/[a-z0-9\-_/]+-scheme[a-z0-9\-_.]*\.html"),
    ],
    # Finetrain grant aggregator — individual grant pages
    "finetrain.com": [
        re.compile(r"/grants?/[a-z0-9][a-z0-9\-_/]+", re.I),
        re.compile(r"/funding/[a-z0-9][a-z0-9\-_/]+", re.I),
        re.compile(r"/opportunities?/[a-z0-9][a-z0-9\-_/]+", re.I),
    ],
    # StartupGrantsIndia — individual grant/scheme pages
    "startupgrantsindia.com": [
        re.compile(r"/grants?/[a-z0-9][a-z0-9\-_/]+", re.I),
        re.compile(r"/scheme/[a-z0-9][a-z0-9\-_/]+", re.I),
        re.compile(r"/funding/[a-z0-9][a-z0-9\-_/]+", re.I),
    ],
    # FundsForNGOs — individual opportunity pages
    "fundsforngos.org": [
        re.compile(r"/latest-funds-for-ngos/[a-z0-9][a-z0-9\-_/]+", re.I),
    ],
}


def _extract_hub_subgrants(hub_url: str, content: str) -> List[str]:
    """Given a hub/aggregator page URL and its fetched content, extract individual
    grant sub-page URLs. Returns full absolute URLs, deduplicated."""
    from urllib.parse import urljoin
    parsed = urlparse(hub_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")

    sub_urls: List[str] = []
    for domain_key, patterns in _HUB_SUBGRANT_PATTERNS.items():
        if domain_key not in domain:
            continue
        for pat in patterns:
            for match in pat.finditer(content):
                raw = match.group(0)
                # Build absolute URL
                if raw.startswith("http"):
                    full = raw
                elif raw.startswith("/"):
                    full = base + raw
                else:
                    full = urljoin(hub_url, raw)
                # Strip trailing junk
                full = _URL_TRAILING_JUNK.sub("", full)
                if full != hub_url and len(full) > 20:
                    sub_urls.append(full)
        break  # only apply patterns for the first matched domain key

    # Deduplicate preserving order
    seen: set = set()
    result = []
    for u in sub_urls:
        if u not in seen:
            seen.add(u)
            result.append(u)

    if result:
        logger.info("Hub expansion: %s → %d sub-grant URLs", hub_url[:60], len(result))
    return result


def _url_hash(url: str) -> str:
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


def _normalized_url_hash(url: str) -> str:
    try:
        parsed = urlparse(url.strip().lower())
        netloc = parsed.netloc.replace("www.", "")
        params = {k: v for k, v in parse_qs(parsed.query).items()
                  if k not in _TRACKING_PARAMS}
        query = urlencode(sorted(params.items()), doseq=True)
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{netloc}{path}{'?' + query if query else ''}"
        return hashlib.md5(normalized.encode()).hexdigest()
    except Exception:
        return _url_hash(url)


# ── Deadline regex fallback ──────────────────────────────────────────────────
_DEADLINE_PATTERNS = [
    # "deadline: 31 March 2026" / "closes: March 31, 2026" / "due date: 2026-03-31"
    re.compile(
        r"(?:deadline|closes?|closing\s*date|due\s*date|submit\s*by|last\s*date"
        r"|applications?\s*due)\s*[:–—-]?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
        re.I,
    ),
    # Standalone date patterns near grant keywords: "31 March 2026"
    re.compile(r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", re.I),
    # "March 31, 2026"
    re.compile(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})", re.I),
]


def _extract_deadline_regex(content: str) -> Optional[str]:
    """Try to extract a deadline date from raw content using regex patterns.
    Returns the first match or None."""
    # Search the first 5000 chars — deadlines are usually near the top
    text = content[:5000]
    for pat in _DEADLINE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


_CONTENT_HASH_FILLER = re.compile(
    r"\b(grant|program|programme|scheme|fund|call|open|application|"
    r"20\d{2}|funding|initiative|opportunity)\b",
    re.I,
)


def _content_hash(title: str, funder: str) -> str:
    # If both are empty, fall back to a uuid-like hash to avoid false dedup
    if not title.strip() and not funder.strip():
        return hashlib.md5(os.urandom(16)).hexdigest()

    def norm(s: str) -> str:
        s = s.lower().strip()
        s = _CONTENT_HASH_FILLER.sub("", s)  # strip filler words before hashing
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"[^\w\s]", "", s)
        return s

    return hashlib.md5(f"{norm(title)}|{norm(funder)}".encode()).hexdigest()


def _is_quality_grant(raw_title: str, url: str, content: str) -> Optional[str]:
    """Return disqualification reason or None. Checks raw_title BEFORE LLM extraction."""
    title_lower = (raw_title or "").lower()
    url_lower = (url or "").lower()
    content_lower = (content or "").lower()

    if len(content_lower) < 200:
        return "Content too short"

    # Determine if this URL is from a trusted grant aggregator
    is_trusted = False
    try:
        domain = urlparse(url_lower).netloc.replace("www.", "")
        if any(s in domain for s in _SOCIAL_MEDIA_DOMAINS):
            return "Social media/blog URL — not a grant page"
        is_trusted = domain in _TRUSTED_GRANT_AGGREGATORS
    except Exception:
        pass

    if any(p in title_lower for p in _JUNK_TITLE_PATTERNS):
        return f"Likely news/article: '{raw_title[:60]}'"
    # Trusted aggregators may have /blog/ or /articles/ in their URLs for real listings
    if not is_trusted and any(p in url_lower for p in _JUNK_URL_PATTERNS):
        return "Non-grant URL pattern"
    # Listicle pattern: "Top 10...", "Best 15...", "7 Funding...", "10 Best..." → not a grant page
    if re.search(r"(?i)\b(?:top|best|leading)\s+\d+\b|\b\d+\s+(?:top|best|leading)\b", title_lower) and any(
        w in title_lower for w in ("compan", "startup", "tool", "platform", "solution",
                                    "funding", "investor", "venture", "vc ", "firm")
    ):
        return f"Listicle (not a grant page): '{raw_title[:60]}'"
    if not any(k in content_lower for k in _GRANT_KEYWORDS):
        return "No grant-related keywords in content"
    # Trusted aggregators list real grants — skip action keyword check
    if is_trusted:
        return None
    # Must have at least one action-oriented grant keyword — articles that merely
    # discuss grants typically lack phrases like "apply now", "eligibility criteria" etc.
    if not any(k in content_lower for k in _GRANT_ACTION_KEYWORDS):
        # Allow through if title clearly signals it's a grant/program page
        _TITLE_GRANT_SIGNALS = ("grant", "fund", "award", "prize", "fellowship",
                                "call for", "open call", "rfp", "accelerator",
                                "rfa", "eoi", "challenge", "competition",
                                "programme", "scheme")
        if not any(k in title_lower for k in _TITLE_GRANT_SIGNALS):
            return "No action keywords — likely an article about grants, not a grant page"
    return None


def _detect_themes(text: str) -> List[str]:
    """Classify grant into AltCarbon's 6 themes based on keyword density.

    A theme requires at least `min_hits` distinct keyword matches to qualify,
    preventing false positives from stray mentions (e.g. a climate grant that
    says "rural community" once should NOT be tagged Social Impact).
    """
    t = text.lower()
    themes = []

    # (keywords, theme_key, min_hits) — higher min_hits for themes with generic keywords
    THEME_RULES = [
        ([
            "climate", "carbon", "net zero", "decarboni", "emission", "cdr", "mrv",
            "cleantech", "clean energy", "renewable", "solar", "wind", "green hydrogen",
            "nature based", "biodiversity", "ocean", "methane", "ghg", "greenhouse",
            "biochar", "enhanced weathering", "direct air capture", "dac", "blue carbon",
        ], "climatetech", 1),
        ([
            "agri", "soil carbon", "farming", "crop", "food security", "land use",
            "precision agriculture", "agroforestry", "livestock", "fisheries",
            "regenerative agriculture", "soil health",
            "enhanced rock weathering", "basalt", "soil amendment", "crop yield",
            "farmer technology",
        ], "agritech", 1),
        ([
            "artificial intelligence", "machine learning", "ai for", "deep learning",
            "nlp", "computer vision", "neural network", "data science", "predictive model",
        ], "ai_for_sciences", 1),
        ([
            "earth science", "remote sensing", "satellite", "geology", "geospatial",
            "subsurface", "lidar", "mapping", "geophysics", "hydrogeology",
        ], "applied_earth_sciences", 1),
        ([
            "social impact", "livelihood", "marginalized", "poverty alleviation",
            "gender equity", "vulnerable communities", "inclusive development",
            "community resilience", "rural development",
        ], "social_impact", 2),
        ([
            "deep tech", "deeptech", "frontier tech", "breakthrough", "advanced materials",
            "quantum", "biotech", "synthetic biology", "nanotechnology", "robotics",
            "novel hardware", "photonics", "semiconduct", "fusion", "space tech",
            "advanced manufacturing", "lab-grown", "gene editing", "crispr",
        ], "deeptech", 1),
    ]

    for keywords, theme_key, min_hits in THEME_RULES:
        hits = sum(1 for k in keywords if k in t)
        if hits >= min_hits:
            themes.append(theme_key)

    return themes


# ── Relevance pre-scoring (no LLM call) ────────────────────────────────────────
# Lightweight 0-1 score using themes_detected + keyword matching.
# Grants scoring < 0.3 are saved with processed=True, pre_filtered=True — skips analyst.

_CORE_THEME_SCORES: Dict[str, float] = {
    "climatetech": 0.35,
    "agritech": 0.25,
    "ai_for_sciences": 0.15,
    "applied_earth_sciences": 0.15,
    "social_impact": 0.10,
    "deeptech": 0.15,
}

_ALTCARBON_KEYWORDS = frozenset({
    "erw", "enhanced rock weathering", "biochar", "mrv", "cdr",
    "carbon removal", "carbon dioxide removal", "basalt", "soil carbon",
    "rock dust", "mineral weathering", "feluda", "isometric",
    "carbon credit", "carbon verification", "dac",
})

_GEO_BOOST_KEYWORDS = frozenset({
    "india", "indian", "south asia", "global", "worldwide", "international",
    "developing countr", "emerging market", "asia", "asia-pacific", "apac",
    "saarc", "brics", "g20", "lmic", "global south",
})


def _relevance_prescore(grant: Dict) -> float:
    """Compute a 0–1 relevance score using already-computed themes + keyword matching.

    Returns a float between 0.0 and 1.0. Grants below 0.3 are irrelevant to AltCarbon.
    """
    score = 0.0

    # Theme hits (take the max single-theme score, plus 0.05 for each additional theme)
    themes = grant.get("themes_detected") or []
    if themes:
        theme_scores = [_CORE_THEME_SCORES.get(t, 0.0) for t in themes]
        score += max(theme_scores)
        if len(theme_scores) > 1:
            score += (len(theme_scores) - 1) * 0.05

    # AltCarbon-specific keyword boost
    text_lower = (
        (grant.get("raw_content") or "")[:5000]
        + " " + (grant.get("title") or "")
        + " " + (grant.get("notes") or "")
    ).lower()
    ac_hits = sum(1 for kw in _ALTCARBON_KEYWORDS if kw in text_lower)
    score += min(ac_hits * 0.08, 0.30)  # cap at 0.30

    # Geography boost
    geo_text = (
        (grant.get("geography") or "")
        + " " + (grant.get("eligibility") or "")
        + " " + text_lower[:2000]
    ).lower()
    if any(kw in geo_text for kw in _GEO_BOOST_KEYWORDS):
        score += 0.10

    return min(score, 1.0)


# ── HTTP fetch helpers ─────────────────────────────────────────────────────────

# Domains where Jina always returns 402 (Indian govt portals, some protected pages).
# For these we go straight to plain HTTP — skipping 3×4s retries against Jina.
_SKIP_JINA_DOMAINS = frozenset({
    # Indian central government
    "birac.nic.in", "dst.gov.in", "anrfonline.in", "startupindia.gov.in",
    "aim.gov.in", "msh.gov.in", "tdb.gov.in", "nabard.org",
    "sfacindia.com", "dbt.gov.in", "isro.gov.in", "nrsc.gov.in",
    "research.mnre.gov.in", "nise.res.in", "indiaai.gov.in", "aikosh.indiaai.gov.in",
    "onlinedst.gov.in",
    # Indian state government startup / science programs
    "kscst.org.in", "kbits.karnataka.gov.in", "startupkarnataka.gov.in",
    "kiadb.in", "msins.in", "mced.in", "t-hub.co", "wehub.telangana.gov.in",
    "tsic.telangana.gov.in", "startuptn.in", "edii.tn.gov.in",
    "startupmission.kerala.gov.in", "ksidc.org", "icreate.org.in",
    "gusec.edu.in", "istart.rajasthan.gov.in", "apnrt.in",
    "apinnovationsociety.com", "mpstartup.in", "startupharyana.gov.in",
    "invest.up.gov.in", "investpunjab.gov.in",
})

# Full browser headers for plain-HTTP fallback — Indian government portals often
# block requests without Accept-Language or with an obviously bot-like User-Agent.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# Jina concurrency: keep to 3 with a small delay between requests to stay
# within the free-tier limit of 10 RPM (6s per request at concurrency 1 is
# safest, but 3-concurrent with ~1s sleep per batch keeps us under 20 RPM).
_JINA_SEM: asyncio.Semaphore | None = None
_JINA_INTER_REQUEST_DELAY = 1.0  # seconds between Jina requests per slot


def _get_jina_sem() -> asyncio.Semaphore:
    global _JINA_SEM
    if _JINA_SEM is None:
        _JINA_SEM = asyncio.Semaphore(3)
    return _JINA_SEM


async def _fetch_with_jina(url: str, api_key: str = "") -> str:
    """Fetch page content via Jina Reader with rate-limit-aware concurrency."""
    if api_health.is_exhausted("jina"):
        logger.debug("Skipping Jina (exhausted) for %s — falling back to plain HTTP", url[:60])
        return ""

    jina_url = f"https://r.jina.ai/{url.strip()}"
    headers: Dict[str, str] = {
        "X-Return-Format": "markdown",
        "X-With-Links-Summary": "false",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def _do_fetch() -> str:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.get(jina_url, headers=headers)
            if r.status_code in (402, 429):
                raise httpx.HTTPStatusError(
                    f"Jina rate limit {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()
            return r.text.strip()[:80_000]

    sem = _get_jina_sem()
    async with sem:
        try:
            result = await retry_async(
                _do_fetch, retries=3, base_delay=4.0, label=f"jina:{url[:60]}", service="jina"
            )
        except CreditExhaustedError:
            return ""
        await asyncio.sleep(_JINA_INTER_REQUEST_DELAY)
    if result is None:
        return ""
    api_health.record_success("jina")
    return result


async def _fetch_plain(url: str) -> str:
    """Plain HTTP GET with full browser headers — required for Indian govt portals."""
    async def _do_fetch() -> str:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.get(url, headers=_BROWSER_HEADERS)
            r.raise_for_status()
            return r.text[:60_000]

    result = await retry_async(_do_fetch, retries=2, base_delay=2.0, label=f"plain:{url[:60]}")
    return result or ""


def _should_skip_jina(url: str) -> bool:
    """Return True for domains that always return 402/403 from Jina — go straight to plain HTTP."""
    try:
        domain = urlparse(url).netloc.replace("www.", "").lower()
        # Exact-domain match
        if domain in _SKIP_JINA_DOMAINS:
            return True
        # All Indian government TLD subdomains (.gov.in and .nic.in)
        if domain.endswith(".gov.in") or domain.endswith(".nic.in"):
            return True
    except Exception:
        pass
    return False


async def _fetch_with_browser(url: str) -> str:
    """Headless browser fallback — used when Jina + plain HTTP both fail.

    Handles JS-rendered portals, Cloudflare challenges, and SPAs.
    Returns empty string if browser is unavailable or fetch fails.
    """
    try:
        from backend.utils.browser import browser_fetch, is_available
        if not is_available():
            return ""
        content = await browser_fetch(url, timeout=45.0)
        if content:
            logger.info("Browser fallback succeeded for %s (%d chars)", url[:60], len(content))
        return content
    except Exception as e:
        logger.debug("Browser fallback failed for %s: %s", url[:60], e)
        return ""


async def _fetch_content(url: str, jina_key: str = "") -> str:
    # Skip Jina entirely for domains known to block it — saves 3×4s retry time
    if _should_skip_jina(url):
        logger.debug("Skipping Jina for known blocked domain: %s", url[:60])
        content = await _fetch_plain(url)
        if len(content) > 300:
            return content
        # Plain HTTP also failed — try headless browser
        return await _fetch_with_browser(url)

    content = await _fetch_with_jina(url, jina_key)
    if len(content) > 300:
        return content
    logger.debug("Jina returned short content for %s — falling back to plain HTTP", url)
    content = await _fetch_plain(url)
    if len(content) > 300:
        return content
    # Both Jina and plain HTTP failed — try headless browser
    return await _fetch_with_browser(url)


class ScoutAgent:
    def __init__(
        self,
        tavily_api_key: str = "",
        exa_api_key: str = "",
        jina_api_key: str = "",
        perplexity_api_key: str = "",
        gateway_api_key: str = "",
        gateway_url: str = "https://ai-gateway.vercel.sh/v1",
        custom_tavily_queries: Optional[List[str]] = None,
        custom_exa_queries: Optional[List[str]] = None,
        custom_perplexity_queries: Optional[List[str]] = None,
        max_results_per_query: int = 10,
        enable_direct_crawl: bool = True,
    ):
        self.tavily_key = tavily_api_key
        self.exa_key = exa_api_key
        self.jina_key = jina_api_key
        self.perplexity_key = perplexity_api_key  # direct API key (preferred)
        self.gateway_key = gateway_api_key          # gateway fallback for Perplexity
        self.gateway_url = gateway_url
        self.tavily_queries = custom_tavily_queries or DEFAULT_TAVILY_QUERIES
        self.exa_queries = custom_exa_queries or DEFAULT_EXA_QUERIES
        self.perplexity_queries = custom_perplexity_queries or DEFAULT_PERPLEXITY_QUERIES
        self.max_results = max_results_per_query
        self.enable_direct_crawl = enable_direct_crawl

        self._tavily = None
        if tavily_api_key:
            try:
                from tavily import TavilyClient
                self._tavily = TavilyClient(api_key=tavily_api_key)
            except ImportError:
                logger.warning("tavily-python not installed. Run: pip install tavily-python")

        self._exa = None
        if exa_api_key:
            try:
                from exa_py import Exa
                self._exa = Exa(api_key=exa_api_key)
            except ImportError:
                logger.warning("exa-py not installed. Run: pip install exa-py")

    # ── LLM field extraction ───────────────────────────────────────────────────

    async def _extract_grant_fields(self, url: str, raw_title: str, content: str) -> dict:
        """Use Claude Haiku to extract structured grant fields. Robust JSON parsing."""
        if len(content) < 150:
            return {}
        prompt = EXTRACTION_PROMPT.format(
            url=url,
            raw_title=raw_title,
            content=content[:6000],
        )
        try:
            raw = await chat(
                prompt,
                model=HAIKU,
                max_tokens=1024,   # was 600 — raised to prevent JSON truncation
                system=EXTRACTION_SYSTEM,
            )
            return parse_json_safe(raw)
        except Exception as e:
            logger.debug("Grant field extraction failed for %s: %s", url, e)
            return {}

    # ── Tavily keyword search ──────────────────────────────────────────────────

    async def _tavily_search(self, query: str) -> List[Dict]:
        if not self._tavily:
            return []
        if api_health.is_exhausted("tavily"):
            logger.debug("Skipping Tavily (exhausted): %s", query[:50])
            return []

        async def _do():
            result = await asyncio.to_thread(
                self._tavily.search,
                query=query,
                search_depth="advanced",
                max_results=self.max_results,
                include_raw_content=True,
            )
            items = []
            for r in result.get("results", []):
                url = r.get("url", "")
                if not url:
                    continue
                items.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "url_hash": _url_hash(url),
                    "raw_content": r.get("raw_content") or r.get("content", ""),
                    "source": "tavily",
                    "relevance_score": r.get("score", 0.5),
                })
            return items

        try:
            result = await retry_async(_do, retries=3, base_delay=2.0, label=f"tavily:{query[:40]}", service="tavily")
        except CreditExhaustedError:
            return []
        if result is None:
            return []
        api_health.record_success("tavily")
        logger.info("Tavily query=%r → %d results", query[:50], len(result))
        return result

    # ── Exa semantic search ────────────────────────────────────────────────────

    async def _exa_search(self, query: str) -> List[Dict]:
        if not self._exa:
            return []
        if api_health.is_exhausted("exa"):
            logger.debug("Skipping Exa (exhausted): %s", query[:50])
            return []

        async def _do():
            result = await asyncio.to_thread(
                self._exa.search_and_contents,
                query,
                num_results=self.max_results,
                text={"max_characters": 3000},
                highlights={"num_sentences": 5, "highlights_per_url": 3},
            )
            items = []
            for r in result.results:
                url = r.url or ""
                if not url:
                    continue
                # Combine highlights + text for richer content
                highlights = getattr(r, "highlights", None) or []
                highlight_text = " ".join(highlights) if highlights else ""
                page_text = getattr(r, "text", None) or ""
                combined = f"{highlight_text}\n\n{page_text}".strip()
                items.append({
                    "title": r.title or "",
                    "url": url,
                    "url_hash": _url_hash(url),
                    "raw_content": combined,
                    "source": "exa",
                    "relevance_score": getattr(r, "score", 0.5) or 0.5,
                })
            return items

        try:
            result = await retry_async(_do, retries=3, base_delay=2.0, label=f"exa:{query[:40]}", service="exa")
        except CreditExhaustedError:
            return []
        if result is None:
            return []
        api_health.record_success("exa")
        logger.info("Exa query=%r → %d results", query[:50], len(result))
        return result

    # ── Perplexity Sonar search ────────────────────────────────────────────────

    async def _perplexity_search(self, query: str) -> List[Dict]:
        """Query Perplexity. Prefers AI Gateway; falls back to direct API key."""
        if api_health.is_exhausted("perplexity"):
            logger.debug("Skipping Perplexity (exhausted): %s", query[:50])
            return []
        if self.gateway_key:
            return await self._perplexity_gateway(query)
        if self.perplexity_key:
            return await self._perplexity_direct(query)
        return []

    async def _perplexity_direct(self, query: str) -> List[Dict]:
        """Direct Perplexity API — uses citations field for reliable URL extraction."""
        payload = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a grant research assistant. List specific active grant programs "
                        "with their official names, funders, and URLs. Include full https:// links."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "return_citations": True,
            "search_recency_filter": "month",
        }

        async def _do():
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.perplexity_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                r.raise_for_status()
                return r.json()

        try:
            data = await retry_async(_do, retries=3, base_delay=2.0, label=f"perplexity-direct:{query[:40]}", service="perplexity")
        except CreditExhaustedError:
            return []
        if not data:
            return []

        api_health.record_success("perplexity")
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        # Prefer structured citations, fallback to URL regex
        citations: List[str] = data.get("citations", [])
        text_urls = _extract_urls_from_text(answer)
        all_urls = list(dict.fromkeys(citations + text_urls))[:15]

        return [
            {
                "title": "",
                "url": url,
                "url_hash": _url_hash(url),
                "raw_content": "",   # will be fetched individually in enrich step
                "source": "perplexity",
                "relevance_score": 0.75,
            }
            for url in all_urls
        ]

    async def _perplexity_gateway(self, query: str) -> List[Dict]:
        """Perplexity via Vercel AI Gateway (OpenAI-compat API)."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.gateway_key, base_url=self.gateway_url)

        async def _do():
            response = await client.chat.completions.create(
                model="perplexity/sonar-pro",
                max_tokens=1024,
                messages=[
                    {
                        "role": "system",
                        "content": "List specific active grant programs with full https:// URLs.",
                    },
                    {"role": "user", "content": query},
                ],
            )
            return response.choices[0].message.content or ""

        try:
            answer = await retry_async(_do, retries=2, base_delay=2.0, label=f"perplexity-gw:{query[:40]}", service="perplexity")
        except CreditExhaustedError:
            return []
        if not answer:
            return []
        api_health.record_success("perplexity")
        urls = _extract_urls_from_text(answer)[:15]
        return [
            {
                "title": "",
                "url": url,
                "url_hash": _url_hash(url),
                "raw_content": "",
                "source": "perplexity",
                "relevance_score": 0.70,
            }
            for url in urls
        ]

    # ── Direct source crawl ────────────────────────────────────────────────────

    async def _crawl_direct_source(self, source: Dict[str, str]) -> Optional[Dict]:
        url = source["url"]
        funder = source["funder"]
        content = await _fetch_content(url, self.jina_key)
        if len(content) < 100:
            logger.debug("Direct crawl: no content for %s", url)
            return None
        return {
            "title": f"{funder} — Grant Opportunities",
            "url": url,
            "url_hash": _url_hash(url),
            "raw_content": content,
            "source": "direct",
            "funder": funder,
            "relevance_score": 0.8,
        }

    async def _crawl_all_direct_sources(self) -> List[Dict]:
        if not self.enable_direct_crawl:
            return []

        logger.info("Direct crawl: fetching %d known grant source pages", len(ALL_DIRECT_SOURCES))

        async def _safe_crawl(source: Dict[str, str]) -> Optional[Dict]:
            try:
                return await asyncio.wait_for(
                    self._crawl_direct_source(source), timeout=45.0
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug("Direct crawl failed for %s: %s", source["url"], e)
                return None

        # Apply overall 180s timeout to the entire direct crawl phase
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(_safe_crawl(s) for s in ALL_DIRECT_SOURCES)),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Direct crawl hit 180s global timeout — partial results used")
            results = []

        valid = [r for r in results if r is not None]
        logger.info(
            "Direct crawl: %d/%d sources returned content", len(valid), len(ALL_DIRECT_SOURCES)
        )
        return valid

    # ── Main scout run ─────────────────────────────────────────────────────────

    async def run(self) -> List[Dict]:
        """Run full scout: all search sources in parallel → dedup → enrich → save."""
        import traceback as _tb

        _run_start = datetime.now(timezone.utc)

        logger.info(
            "Scout starting: %d Tavily, %d Exa, %d Perplexity, %d direct sources",
            len(self.tavily_queries), len(self.exa_queries),
            len(self.perplexity_queries) if (self.perplexity_key or self.gateway_key) else 0,
            len(ALL_DIRECT_SOURCES) if self.enable_direct_crawl else 0,
        )

        try:
            return await self._run_inner()
        except Exception as exc:
            elapsed = (datetime.now(timezone.utc) - _run_start).total_seconds()
            try:
                from backend.integrations.notion_sync import log_error, log_agent_run
                await log_error(
                    agent="scout",
                    error=exc,
                    tb=_tb.format_exc(),
                    severity="Critical",
                )
                await log_agent_run(
                    agent="scout",
                    status="Failed",
                    trigger="Manual",
                    started_at=_run_start,
                    duration_seconds=elapsed,
                    errors=1,
                    summary=f"Scout failed: {str(exc)[:200]}",
                )
            except Exception:
                logger.debug("Notion error sync skipped (scout failure)", exc_info=True)
            raise

    async def _run_inner(self) -> List[Dict]:
        """Inner scout logic, wrapped by run() for error handling."""

        # ── Run all searches in parallel ──────────────────────────────────────
        tavily_tasks = [self._tavily_search(q) for q in self.tavily_queries]
        exa_tasks = [self._exa_search(q) for q in self.exa_queries]
        perplexity_tasks = (
            [self._perplexity_search(q) for q in self.perplexity_queries]
            if (self.perplexity_key or self.gateway_key) else []
        )

        search_results, direct_results = await asyncio.gather(
            asyncio.gather(*(tavily_tasks + exa_tasks + perplexity_tasks)),
            self._crawl_all_direct_sources(),
        )

        # ── Hub expansion: extract sub-grant URLs from listing pages ─────────
        # For hub pages (BIRAC CFP, DST CFP, ANRF), each individual call on the
        # page becomes a separate discovery item — same approach the LangSmith scout
        # uses to produce 8+ BIRAC entries from a single BIRAC hub page.
        hub_expansions: List[Dict] = []
        for item in direct_results:
            sub_urls = _extract_hub_subgrants(item.get("url", ""), item.get("raw_content", ""))
            for sub_url in sub_urls:
                hub_expansions.append({
                    "title": "",
                    "url": sub_url,
                    "url_hash": _url_hash(sub_url),
                    "raw_content": "",   # will be fetched in enrich step
                    "source": "hub_expansion",
                    "funder": item.get("funder", ""),
                    "relevance_score": 0.85,
                })

        if hub_expansions:
            logger.info("Hub expansion: %d additional sub-grant URLs discovered", len(hub_expansions))

        # ── In-memory dedup by url_hash ───────────────────────────────────────
        seen_hashes: set = set()
        unique: List[Dict] = []
        for batch in [*search_results, direct_results, hub_expansions]:
            for item in batch:
                h = item["url_hash"]
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    unique.append(item)

        logger.info("Scout: %d unique URLs after in-memory dedup (incl. hub expansions)", len(unique))

        # ── DB dedup (3-layer) ────────────────────────────────────────────────
        col = grants_raw()
        scored_col = grants_scored()

        known_url_hashes: set = set()
        known_norm_hashes: set = set()
        known_content_hashes: set = set()

        async for doc in col.find({}, {"url_hash": 1, "url": 1, "content_hash": 1}):
            known_url_hashes.add(doc.get("url_hash"))
            if doc.get("url"):
                known_norm_hashes.add(_normalized_url_hash(doc["url"]))
            if doc.get("content_hash"):
                known_content_hashes.add(doc["content_hash"])

        async for doc in scored_col.find({}, {"url": 1, "content_hash": 1, "url_hash": 1}):
            if doc.get("url"):
                known_norm_hashes.add(_normalized_url_hash(doc["url"]))
            if doc.get("url_hash"):
                known_url_hashes.add(doc["url_hash"])
            if doc.get("content_hash"):
                known_content_hashes.add(doc["content_hash"])

        new_grants = []
        for item in unique:
            if item["url_hash"] in known_url_hashes:
                continue
            norm_h = _normalized_url_hash(item["url"])
            if norm_h in known_norm_hashes:
                logger.debug("Normalized URL duplicate, skipping: %s", item["url"])
                continue
            item["normalized_url_hash"] = norm_h
            known_norm_hashes.add(norm_h)
            known_url_hashes.add(item["url_hash"])
            new_grants.append(item)

        logger.info("Scout: %d new grants not in DB", len(new_grants))

        # ── Enrich: fetch content + theme detect + LLM extraction ─────────────
        enrich_sem = asyncio.Semaphore(4)

        async def enrich(item: Dict) -> Dict:
            async with enrich_sem:
                # Preserve the raw title BEFORE LLM extraction (used by quality filter)
                raw_title = item.get("title", "")

                # Fetch full content if we don't have enough
                if len(item.get("raw_content", "")) < 400:
                    item["raw_content"] = await _fetch_content(item["url"], self.jina_key)

                content = item.get("raw_content", "")

                # Theme detection (runs on raw content — no LLM needed)
                item["themes_detected"] = _detect_themes(content + " " + raw_title)

                # LLM field extraction
                extracted = await self._extract_grant_fields(item["url"], raw_title, content)

                # Merge extracted fields, preserving raw values as fallback
                item["grant_name"] = (
                    extracted.get("grant_name")
                    or raw_title
                )
                # Keep `title` as alias for compatibility with existing queries
                item["title"] = item["grant_name"]
                item["funder"] = (
                    extracted.get("sponsor")
                    or item.get("funder")
                    or _extract_funder_from_url(item["url"])
                )
                item["grant_type"] = extracted.get("grant_type") or "grant"
                item["geography"] = extracted.get("geography") or ""
                item["amount"] = extracted.get("amount") or ""
                item["max_funding"] = extracted.get("max_funding_usd")
                item["max_funding_usd"] = item["max_funding"]
                item["currency"] = extracted.get("currency") or "USD"
                item["deadline"] = extracted.get("deadline")
                # Deadline regex fallback: when LLM returns null, try common patterns
                if not item["deadline"]:
                    item["deadline"] = _extract_deadline_regex(content)
                item["eligibility"] = extracted.get("eligibility") or ""
                item["application_url"] = (
                    extracted.get("application_url") or item.get("url", "")
                )
                item["source_url"] = (
                    extracted.get("source_url") or item.get("url", "")
                )
                item["notes"] = extracted.get("notes") or ""
                item["about_opportunity"] = extracted.get("about_opportunity") or ""
                item["eligibility_details"] = extracted.get("eligibility_details") or ""
                item["application_process"] = extracted.get("application_process") or ""
                item["themes_text"] = extracted.get("themes") or ""
                item["past_winners_url"] = extracted.get("past_winners_url") or None
                item["last_verified_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                item["processed"] = False
                item["scraped_at"] = datetime.now(timezone.utc).isoformat()
                item["_raw_title"] = raw_title  # preserve for quality filter
                return item

        # Wrap each enrich in a per-item timeout
        async def safe_enrich(item: Dict) -> Optional[Dict]:
            try:
                return await asyncio.wait_for(enrich(item), timeout=45.0)
            except asyncio.TimeoutError:
                logger.warning("Enrich timeout for %s", item.get("url"))
                return None
            except Exception as e:
                logger.warning("Enrich error for %s: %s", item.get("url"), e)
                return None

        enriched_raw = await asyncio.gather(*(safe_enrich(g) for g in new_grants))
        enriched = [g for g in enriched_raw if g is not None]

        # ── Quality filter + pre-score gate + content-hash dedup + save ──────
        saved = []
        quality_rejected = 0
        pre_filtered = 0
        content_dupes = 0

        for grant in enriched:
            if not grant.get("raw_content"):
                quality_rejected += 1
                continue

            # Quality check on the ORIGINAL raw title (before LLM extraction)
            reject_reason = _is_quality_grant(
                grant.get("_raw_title", grant.get("title", "")),
                grant.get("url", ""),
                grant.get("raw_content", ""),
            )
            if reject_reason:
                logger.debug("Quality rejected (%s): %s", reject_reason, grant.get("url"))
                quality_rejected += 1
                continue

            # Layer 3: content-hash dedup
            ch = _content_hash(grant.get("title", ""), grant.get("funder", ""))
            grant["content_hash"] = ch
            if ch in known_content_hashes:
                logger.debug(
                    "Content-hash duplicate (%s / %s) — skipping",
                    grant.get("title", "")[:40], grant.get("funder", ""),
                )
                content_dupes += 1
                continue
            known_content_hashes.add(ch)

            # Relevance pre-score gate: skip analyst for clearly irrelevant grants
            prescore = _relevance_prescore(grant)
            grant["relevance_prescore"] = round(prescore, 3)
            if prescore < 0.3:
                logger.debug(
                    "Pre-filtered (score=%.2f): %s",
                    prescore, grant.get("title", "")[:50],
                )
                grant["processed"] = True
                grant["pre_filtered"] = True
                pre_filtered += 1
                # Still save to DB but mark as processed so analyst skips it
                try:
                    await col.update_one(
                        {"url_hash": grant["url_hash"]},
                        {"$setOnInsert": grant},
                        upsert=True,
                    )
                except Exception:
                    pass
                continue

            # Clean up internal tracking field
            grant.pop("_raw_title", None)

            # Upsert (safe for concurrent/replayed runs — unique index on url_hash)
            try:
                from pymongo.errors import DuplicateKeyError
                await col.update_one(
                    {"url_hash": grant["url_hash"]},
                    {"$setOnInsert": grant},
                    upsert=True,
                )
                saved.append(grant)
            except DuplicateKeyError:
                logger.debug("Race-condition duplicate for url_hash %s — skipped", grant["url_hash"])
            except Exception as e:
                logger.warning("Failed to save grant %s: %s", grant.get("url"), e)

        logger.info(
            "Scout: %d saved, %d quality-rejected, %d pre-filtered, %d content-dupes",
            len(saved), quality_rejected, pre_filtered, content_dupes,
        )

        # ── Log run stats ─────────────────────────────────────────────────────
        run_doc = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "tavily_queries": len(self.tavily_queries),
            "exa_queries": len(self.exa_queries),
            "perplexity_queries": len(self.perplexity_queries) if (self.perplexity_key or self.gateway_key) else 0,
            "direct_sources_crawled": len(ALL_DIRECT_SOURCES) if self.enable_direct_crawl else 0,
            "total_found": len(unique),
            "new_grants": len(saved),
            "quality_rejected": quality_rejected,
            "pre_filtered": pre_filtered,
            "content_dupes": content_dupes,
        }
        await scout_runs().insert_one(run_doc)
        await audit_logs().insert_one({
            "node": "scout",
            "action": f"Scout run complete: {len(saved)} new grants saved",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **run_doc,
        })

        # ── Notion Mission Control sync ──────────────────────────────────
        try:
            from backend.integrations.notion_sync import log_agent_run
            await log_agent_run(
                agent="scout",
                status="Completed",
                trigger="Manual",
                started_at=datetime.now(timezone.utc),
                grants_found=len(saved),
                errors=0,
                summary=f"Discovered {len(unique)} grants, saved {len(saved)} new. "
                        f"{quality_rejected} quality-rejected, {pre_filtered} pre-filtered, "
                        f"{content_dupes} content-dupes.",
            )
        except Exception:
            logger.debug("Notion sync skipped (scout run)", exc_info=True)

        # Log API health at end of run
        health = api_health.get_status()
        exhausted_svcs = [s for s, v in health.items() if v.get("status") == "exhausted"]
        if exhausted_svcs:
            logger.warning("Scout complete: %d grants saved. EXHAUSTED APIs: %s", len(saved), ", ".join(exhausted_svcs))
        else:
            logger.info("Scout complete: %d grants saved to grants_raw", len(saved))
        return saved


def _extract_funder_from_url(url: str) -> str:
    try:
        domain = urlparse(url).netloc.replace("www.", "")
        parts = domain.split(".")
        return parts[0].replace("-", " ").title() if parts else domain
    except Exception:
        return "Unknown"


def _extract_urls_from_text(text: str) -> List[str]:
    """Extract https:// URLs from text, stripping trailing punctuation."""
    raw_urls = re.findall(r"https?://[^\s\)\]\"\'>,]+", text)
    cleaned = []
    seen = set()
    for u in raw_urls:
        u = _URL_TRAILING_JUNK.sub("", u)
        if u not in seen and len(u) > 12:
            cleaned.append(u)
            seen.add(u)
    return cleaned


async def scout_node(state: GrantState) -> Dict:
    """LangGraph node: run Scout, populate raw_grants (new + backlog)."""
    from backend.config.settings import get_settings
    s = get_settings()

    cfg_doc = await __import__("backend.db.mongo", fromlist=["agent_config"]).agent_config().find_one(
        {"agent": "scout"}
    ) or {}

    agent = ScoutAgent(
        tavily_api_key=s.tavily_api_key,
        exa_api_key=s.exa_api_key,
        jina_api_key=s.jina_api_key,
        perplexity_api_key=s.perplexity_api_key,
        gateway_api_key=s.ai_gateway_api_key,
        gateway_url=s.ai_gateway_url,
        custom_tavily_queries=cfg_doc.get("custom_queries") or None,
        max_results_per_query=cfg_doc.get("max_results_per_query", 10),
        enable_direct_crawl=cfg_doc.get("enable_direct_crawl", True),
    )

    newly_saved = await agent.run()

    # Also pick up any unprocessed grants from prior runs (backlog)
    col = grants_raw()
    backlog = await col.find({"processed": False}).to_list(length=500)
    logger.info("Scout node: %d newly saved, %d backlog unprocessed", len(newly_saved), len(backlog))

    seen: set = {g.get("url_hash") for g in newly_saved if g.get("url_hash")}
    for g in backlog:
        if g.get("url_hash") not in seen:
            seen.add(g.get("url_hash"))
            newly_saved.append(g)

    return {
        "raw_grants": newly_saved,
        "audit_log": state.get("audit_log", []) + [{
            "node": "scout",
            "ts": datetime.now(timezone.utc).isoformat(),
            "grants_found": len(newly_saved),
        }],
    }
