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
from backend.utils.parsing import parse_json_safe, retry_async

logger = logging.getLogger(__name__)

# ── Tavily queries ─────────────────────────────────────────────────────────────
DEFAULT_TAVILY_QUERIES: List[str] = [
    # Climate Tech & CDR — core
    "climatetech startup grant open call 2026",
    "carbon removal CDR MRV startup funding 2026",
    "net zero decarbonisation grant program 2026",
    "climate innovation fund open call for proposals 2026",
    "carbon credit verification technology grant 2026",
    "nature based solutions NBS funding opportunity 2026",
    "climate fintech grant accelerator 2026",
    "biochar enhanced weathering carbon sequestration grant 2026",
    "direct air capture DAC startup grant 2026",
    # Agritech / Soil
    "agritech soil carbon grant program 2026",
    "regenerative agriculture funding open call 2026",
    "sustainable food systems startup grant 2026",
    "precision agriculture technology grant 2026",
    # AI for Sciences
    "AI for climate science research grant 2026",
    "machine learning earth observation grant 2026",
    "AI scientific discovery grant program 2026",
    # Earth Sciences
    "applied earth sciences remote sensing grant 2026",
    "geospatial satellite land use grant 2026",
    "subsurface geology technology grant 2026",
    # India-specific — targeted by exact program names so Tavily returns program pages, not news
    "BIRAC BIG Biotechnology Ignition Grant open 2026",
    "BIRAC BIPP Biotechnology Industry Partnership Programme 2026",
    "BIRAC SBIRI Small Business Innovation Research Initiative open call 2026",
    "BIRAC ACE Accelerating Circular Economy startup grant 2026",
    "ANRF DPIIT startup grant call for proposals 2026",
    "ANRF Seed Grant new investigator 2026",
    "DST NIDHI PRAYAS startup grant application 2026",
    "DST SEED TIDE Technology Incubation grant 2026",
    "DST SERB startup research grant 2026 apply",
    "DST Climate Change Programme grant India open call 2026",
    "DBT Agribioinformatics soil carbon research grant 2026",
    "AIM Atal Innovation Mission startup grant India 2026",
    "MeitY startup tech grant India 2026",
    "TDB Technology Development Board India grant apply 2026",
    "Startup India SISFS seed fund startup grant 2026 apply",
    "India deep tech climate startup grant 2026",
    # India state government grants
    "Karnataka KSCST KBITS startup grant open call 2026",
    "Maharashtra MSINS startup innovation grant 2026",
    "Telangana T-Hub WE Hub grant program 2026",
    "StartupTN Tamil Nadu climatetech agritech grant 2026",
    "KSUM Kerala startup mission grant 2026",
    "iStart Rajasthan Gujarat i-Create grant 2026",
    "India state government startup grant climatetech agritech 2026",
    # Indian philanthropic & impact orgs
    "Tata Trusts climate environment grant India open call 2026",
    "Rohini Nilekani Philanthropies grant open application 2026",
    "Azim Premji Foundation environment climate grant India 2026",
    "Social Alpha innovation grant India climatetech apply 2026",
    "Villgro innovation fellowship grant India agritech 2026",
    "India Climate Collaborative grant open call 2026",
    # Social Impact
    "social impact climate startup funding 2026",
    "inclusive climate solutions grant 2026",
    "rural livelihoods climate resilience grant 2026",
    # DFIs & Multilateral
    "World Bank IFC grant facility climate startups 2026",
    "ADB AIIB climate finance grant 2026",
    "Green Climate Fund GCF readiness grant 2026",
    "USAID climate innovation grant 2026",
    "UNDP climate innovation grant 2026",
    "UNEP climate technology grant 2026",
    # Philanthropic
    "Bezos Earth Fund grant open call 2026",
    "Grantham Foundation climate grant 2026",
    "ClimateWorks Foundation grant 2026",
    "Rockefeller Foundation climate grant 2026",
    # Accelerators & challenges
    "Google.org Impact Challenge climate 2026",
    "XPRIZE carbon removal challenge 2026",
    "Microsoft Climate Innovation Fund 2026",
    "deep tech climate innovation grant India global 2026",
    # ── Australia & Pacific ─────────────────────────────────────────────────────
    "ARENA Australian Renewable Energy Agency grant open call 2026",
    "Australia cleantech startup grant CSIRO accelerating commercialisation 2026",
    "Australia climate tech innovation grant 2026",
    "New Zealand climate innovation fund grant 2026",
    # ── Canada ─────────────────────────────────────────────────────────────────
    "Canada SDTC cleantech grant open call 2026",
    "NRC IRAP Canada cleantech climate startup grant 2026",
    "Foresight CleanTech Canada funding 2026",
    "Canada climate innovation startup grant program 2026",
    # ── Southeast Asia ─────────────────────────────────────────────────────────
    "Singapore Enterprise cleantech startup grant 2026",
    "Indonesia climate technology grant program 2026",
    "Vietnam green innovation fund startup grant 2026",
    "Thailand NSTDA startup climate agritech grant 2026",
    "Philippines climate startup grant fund 2026",
    "Malaysia green technology grant open call 2026",
    "Southeast Asia climate innovation grant 2026",
    "ASEAN climate tech startup grant program 2026",
    "Temasek Foundation Southeast Asia climate grant 2026",
    # ── East Asia ──────────────────────────────────────────────────────────────
    "Japan NEDO green innovation fund grant 2026",
    "South Korea K-startup climate innovation grant 2026",
    "Taiwan climate tech startup grant program 2026",
    "Japan green technology startup grant open call 2026",
    # ── Africa ─────────────────────────────────────────────────────────────────
    "African Development Bank AfDB climate grant open call 2026",
    "Africa climate startup grant fund open applications 2026",
    "SEFA sustainable energy fund Africa grant 2026",
    "African Climate Foundation grant open call 2026",
    "Africa50 climate infrastructure grant 2026",
    "East Africa climate innovation fund grant 2026",
    "West Africa clean energy startup grant 2026",
    "South Africa cleantech climate grant program 2026",
    "USAID Power Africa grant open call 2026",
    "Africa climate agritech grant startup funding 2026",
    # ── Latin America ──────────────────────────────────────────────────────────
    "IDB Lab Latin America climate startup grant 2026",
    "CAF development bank climate innovation grant Latin America 2026",
    "CORFO Chile green innovation fund grant 2026",
    "BNDES Brazil climate startup grant 2026",
    "Latin America climate tech startup grant open call 2026",
    "Colombia Innpulsa clean energy grant 2026",
    "Mexico INADEM climate startup grant 2026",
    # ── Middle East & North Africa ─────────────────────────────────────────────
    "Islamic Development Bank ISDB climate grant 2026",
    "UAE climate innovation fund grant open call 2026",
    "Saudi Arabia climate startup grant Vision 2030 2026",
    "Masdar Abu Dhabi climate innovation grant 2026",
    "MENA climate tech grant startup program 2026",
    # ── UK (post-Brexit) ───────────────────────────────────────────────────────
    "Innovate UK net zero climate grant competition 2026",
    "UK Research Innovation UKRI climate startup grant 2026",
    "Carbon Trust UK climate grant fund 2026",
    "UK DESNZ energy innovation grant 2026",
    # ── Global / Thematic ──────────────────────────────────────────────────────
    "climate MRV carbon monitoring startup grant global 2026",
    "soil carbon sequestration grant developing countries 2026",
    "blue carbon mangrove seagrass grant fund 2026",
    "carbon markets integrity startup grant 2026",
    "climate adaptation resilience startup grant 2026",
    "clean cooking energy access Africa Asia grant 2026",
    # ── Philanthropic ──────────────────────────────────────────────────────────
    "Bloomberg Philanthropies Schmidt Futures climate grant open call 2026",
    "Open Philanthropy Skoll Foundation climate technology grant 2026",
    "Omidyar Network Laudes Foundation climate fintech grant 2026",
    "Breakthrough Energy Ventures climate startup grant program 2026",
    "Echoing Green social entrepreneur climate fellowship 2026",
    "philanthropic foundation climate technology startup grant open call 2026",
    "impact investment climate grant equity-free startup 2026",
    "Earthshot Prize Norrsken Foundation climate grant challenge 2026",
    # ── Challenges & Prizes ────────────────────────────────────────────────────
    "XPRIZE Earthshot Prize climate technology challenge 2026",
    "MIT Solve climate challenge open call for applications 2026",
    "global cleantech innovation programme GCIP open call 2026",
    "Climate Launchpad Hello Tomorrow deep tech climate challenge 2026",
    "Zayed Sustainability Prize climate innovation award 2026",
    "Mission Innovation challenge climate startup prize 2026",
    "carbon removal prize competition startup applications 2026",
    "climate innovation prize grant challenge application open 2026",
    # CDR-specific funders from manually curated tracker sheets
    "Cascade Climate CRN Enhanced Rock Weathering host site EOI 2026",
    "Carbon to Sea Initiative ocean alkalinity enhancement OAE RFP 2026",
    "CIEIF Climate Intervention Environmental Impact Fund grant 2026",
    "ClimeFi Adyen carbon removal RFP dual track 2026",
    "Milkywire Climate Transformation Fund CDR grant open 2026",
    # Space & Earth Observation — programs in Excel tracker
    "ESA InCubed earth observation commercial startup programme open 2026",
    "CASSINI Challenges EUSPA EU space programme startup application 2026",
    "ISRO RESPOND earth observation research grant India 2026",
    "NASA ROSES research opportunities space earth science 2026",
    # India specific programs found in Excel tracker
    "IndiaAI Innovation Challenge 2026 MeitY apply",
    "TDB Technology Development Board India startup grant 2026 apply",
    "NISE MNRE solar energy innovative projects PMSGY grant 2026",
    "BIRAC Green Hydrogen Mission startup grant 2026 apply",
    "DST India France ANR bilateral research grant 2026",
    "ISRO Venus archival data announcement of opportunity 2026",
    "NRSC ISRO respond proposal earth observation India 2026",
    # Global climate finance + food
    "Global Innovation Lab Climate Finance CPI 2026 call for ideas",
    "WFP Innovation Accelerator challenge food climate 2026",
    "ADB Climate Innovation Development Fund CIDF grant 2026",
    "Greentown Go Make accelerator 2026 RFA Shell Technip application",
    "LILAS4SOILS Horizon Europe soil carbon MRV farmer open call 2026",
    "Innovation Fund Denmark agriculture data horizon europe 2026",
    "Natural Resources Canada NRCan carbon capture FEED grant 2026",
    "UNDP young climate leaders direct funding Italy 2026",
    "Mitigation Action Facility call for projects 2026 climate",
]

# ── Exa semantic queries ───────────────────────────────────────────────────────
DEFAULT_EXA_QUERIES: List[str] = [
    # Core thematic
    "grant funding for startups measuring carbon removal and MRV verification",
    "funding for AI-powered environmental monitoring and earth observation tools",
    "grants for alternative carbon market infrastructure and registry startups",
    "research grants for satellite-based land use change detection and geospatial",
    "open calls for climate technology companies in India or globally",
    "philanthropic funding for soil carbon sequestration technology startups",
    "grant programs for AI applied to climate science and biodiversity monitoring",
    "accelerator program for deep tech climate startups with equity-free funding",
    "government grant program for cleantech and net zero startups",
    "international development finance for climate resilience and adaptation startups",
    # Major funders
    "Bezos Earth Fund open grant call for climate technology",
    "Green Climate Fund readiness support for developing countries",
    "EU Horizon Europe EIC Accelerator climate deep tech grant",
    "ARPA-E DOE energy innovation grant program open calls",
    "UKRI Innovate UK sustainability and net zero funding competition",
    # India — specific program searches to surface actual program pages, not news
    "BIRAC BIG Biotechnology Ignition Grant open call for proposals",
    "BIRAC SBIRI Small Business Innovation Research Initiative grant application",
    "ANRF India open grant call for startups and innovators",
    "DST NIDHI PRAYAS TIDE startup grant application open India",
    "DBT Department Biotechnology climate agritech grant India apply",
    "DST SERB Science Engineering Research Board startup grant",
    "AIM Atal Innovation Mission grant open call India startup",
    "TDB Technology Development Board India startup grant apply",
    "India startup grant for climate technology social impact",
    "Social Alpha Villgro India climate agritech startup grant open call",
    "Tata Trusts Rohini Nilekani grant India climate livelihoods",
    "India Climate Collaborative grant application open call",
    "CSRBOX India CSR grant for climate environment NGO startup",
    # Australia & Pacific
    "ARENA Australia renewable energy grant startup open call",
    "Australian clean energy climate startup grant funding program",
    "New Zealand climate innovation cleantech grant program",
    # Canada
    "SDTC Sustainable Development Technology Canada cleantech grant",
    "Canada NRC IRAP innovation assistance climate technology startup",
    # Southeast Asia
    "Singapore Enterprise Development Grant climate cleantech startup",
    "ASEAN Southeast Asia climate technology startup grant funding",
    "Indonesia Vietnam Thailand climate innovation grant program",
    "Temasek Foundation Southeast Asia environmental grant",
    # East Asia
    "Japan NEDO green innovation fund technology grant startup",
    "South Korea climate technology grant K-startup clean energy",
    # Africa
    "African Development Bank climate finance grant startup",
    "Africa climate technology innovation fund grant open call",
    "sub-Saharan Africa clean energy carbon grant program",
    "African Climate Foundation grant for climate startups",
    # Latin America
    "IDB Lab Latin America climate startup innovation grant",
    "CORFO Chile CAF Latin America green climate innovation fund",
    "Brazil climate technology BNDES startup grant",
    # MENA
    "UAE Saudi Arabia climate innovation fund grant startup",
    "Masdar Islamic Development Bank climate grant MENA",
    # UK
    "Innovate UK Carbon Trust climate net zero startup grant competition",
    "UK DESNZ climate energy innovation startup grant",
    # Global thematic
    "blue carbon ocean climate nature-based solutions grant",
    "climate adaptation resilience developing countries grant fund",
    "carbon markets MRV integrity monitoring startup global grant",
    # CDR-specific funders from Excel tracker — semantic search for these specific programs
    "Cascade Climate CRN enhanced rock weathering host site expression of interest",
    "Carbon to Sea ocean alkalinity enhancement OAE startup research grant",
    "CIEIF climate intervention environmental impact fund open grant application",
    "ClimeFi carbon dioxide removal RFP dual-track application 2026",
    "Milkywire CDR Climate Transformation Fund grant open call",
    # Space and Earth Observation — Excel tracker entries
    "ESA InCubed commercial earth observation startup funding programme",
    "CASSINI Challenges European space programme SME startup application",
    "ISRO RESPOND sponsored research earth observation grant India startup",
    "NASA ROSES research grants earth science remote sensing 2025 2026",
    # India programs from tracker
    "IndiaAI Innovation Challenge MeitY artificial intelligence climate agriculture",
    "TDB India startup grant call for proposals 2026 technology development board",
    "NISE MNRE solar energy innovative projects grant India",
    "BIRAC Green Hydrogen Mission biotech startup grant India 2026",
    # Global climate finance
    "Global Innovation Lab Climate Finance CPI call for ideas private capital",
    "WFP Innovation Accelerator food system climate challenge grant",
    "ADB Climate Innovation Development Fund CIDF open call",
    "Greentown Go Make cleantech accelerator Shell Technip Energies 2026",
    "LILAS4SOILS soil organic carbon MRV farmer test provider Horizon Europe",
    "Natural Resources Canada carbon capture storage FEED engineering grant",
    "UNDP young climate leaders innovative finance direct funding opportunity",
]

# ── Perplexity Sonar queries ────────────────────────────────────────────────────
DEFAULT_PERPLEXITY_QUERIES: List[str] = [
    "What grant programs are currently open for climate technology startups in 2026?",
    "List open calls for funding for carbon removal MRV and net-zero technology startups 2026",
    "What grants or accelerators are accepting applications from agritech and soil carbon startups in 2026?",
    "Open grant calls for AI applied to climate or earth sciences 2026",
    "Which foundations or government programs fund climate startups in India or globally right now?",
    "World Bank ADB IFC AIIB climate finance grant open calls 2026",
    "Bezos Earth Fund Grantham Foundation ClimateWorks open grant applications 2026",
    "Which BIRAC ANRF DST DBT AIM India government programs have open grant calls for startups in 2026? List with URLs",
    "EU Horizon EIC UKRI climate deep tech grant open calls 2026",
    "XPRIZE Google.org Microsoft climate innovation grant competition 2026",
    # New global coverage
    "What climate grants are open for startups in Africa and sub-Saharan Africa in 2026?",
    "List open climate technology grant programs for Southeast Asia and ASEAN startups 2026",
    "Australia ARENA CSIRO cleantech startup grant open calls 2026",
    "Canada SDTC NRC IRAP cleantech climate grant open applications 2026",
    "Japan NEDO South Korea climate innovation grant open calls 2026",
    "IDB Lab CORFO CAF Latin America climate startup grant open calls 2026",
    "UAE Masdar ISDB MENA climate innovation grant program 2026",
    "Innovate UK Carbon Trust UK climate net zero grant competition open 2026",
    "African Development Bank African Climate Foundation climate grant open 2026",
    "Singapore Temasek climate cleantech startup grant open calls 2026",
    # New from Excel tracker
    "What CDR-specific programs are open in 2026? Cascade Climate CRN, Carbon to Sea, CIEIF, ClimeFi, Milkywire CTF",
    "ESA InCubed CASSINI Challenges space earth observation startup grants open in 2026",
    "ISRO RESPOND NRSC NASA ROSES earth observation research grant open calls 2026",
    "IndiaAI Innovation Challenge TDB NISE MNRE BIRAC Green Hydrogen open calls India 2026",
    "Greentown Go Make WFP Innovation Accelerator ADB CIDF Global Innovation Lab climate grant 2026",
    "LILAS4SOILS MNRE EU Horizon Europe soil carbon MRV open calls 2026",
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
    ],
    "Government Programs": [
        {"funder": "EU EIC Accelerator", "url": "https://eic.ec.europa.eu/eic-funding-opportunities_en"},
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
  "notes": "<2-3 crisp sentences: what this program funds, who it targets, any key requirements or noteworthy conditions>"
}}

EXTRACTION RULES (follow strictly):
1. deadline — MANDATORY: extract ANY date that appears as a deadline, close date, or submission window end. Use 'Rolling' only if the grant explicitly says it accepts applications on a rolling or continuous basis. Use null only if no date is mentioned anywhere.
2. amount — extract the maximum award PER APPLICANT (not total fund size). E.g. if grant says "up to $500K per company", extract "$500K".
3. application_url — must link directly to an application form, portal, or submit page. Do NOT use the program overview or description page URL. Leave null if no direct apply link is found.
4. source_url — must be the funder's own official page for this specific grant. If content is from a news/blog/press article about the grant, look in the article for the funder's direct URL and use that instead.
5. eligibility — always include: eligible org types, geographic restrictions (including explicit exclusions like "US only", "UK registered only"), stage requirements, and sector focus. Write up to 200 words.
6. sponsor — use the full official organization name (e.g. "Bezos Earth Fund", not "BEF").
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
    "who should apply", "how to apply guide", "grant guide",
    "investor guide", "landscape report",
)
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


def _content_hash(title: str, funder: str) -> str:
    # If both are empty, fall back to a uuid-like hash to avoid false dedup
    if not title.strip() and not funder.strip():
        return hashlib.md5(os.urandom(16)).hexdigest()

    def norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"\s+", " ", s)
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
    # Block social media and blog platform URLs — these are mentions, not grant pages
    try:
        domain = urlparse(url_lower).netloc.replace("www.", "")
        if any(s in domain for s in _SOCIAL_MEDIA_DOMAINS):
            return "Social media/blog URL — not a grant page"
    except Exception:
        pass
    if any(p in title_lower for p in _JUNK_TITLE_PATTERNS):
        return f"Likely news/article: '{raw_title[:60]}'"
    if any(p in url_lower for p in _JUNK_URL_PATTERNS):
        return "Non-grant URL pattern"
    # Listicle pattern: "Top N companies/startups/tools/solutions" → not a grant page
    if re.search(r"\btop\s+\d+\b", title_lower) and any(
        w in title_lower for w in ("compan", "startup", "tool", "platform", "solution")
    ):
        return f"Listicle (not a grant page): '{raw_title[:60]}'"
    if not any(k in content_lower for k in _GRANT_KEYWORDS):
        return "No grant-related keywords in content"
    # Must have at least one action-oriented grant keyword — articles that merely
    # discuss grants typically lack phrases like "apply now", "eligibility criteria" etc.
    if not any(k in content_lower for k in _GRANT_ACTION_KEYWORDS):
        # Allow through if title clearly signals it's a grant/program page
        _TITLE_GRANT_SIGNALS = ("grant", "fund", "award", "prize", "fellowship",
                                "call for", "open call", "rfp", "accelerator")
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
        ], "agritech", 2),
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
        result = await retry_async(
            _do_fetch, retries=3, base_delay=4.0, label=f"jina:{url[:60]}"
        )
        await asyncio.sleep(_JINA_INTER_REQUEST_DELAY)
    return result or ""


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


async def _fetch_content(url: str, jina_key: str = "") -> str:
    # Skip Jina entirely for domains known to block it — saves 3×4s retry time
    if _should_skip_jina(url):
        logger.debug("Skipping Jina for known blocked domain: %s", url[:60])
        return await _fetch_plain(url)

    content = await _fetch_with_jina(url, jina_key)
    if len(content) > 300:
        return content
    logger.debug("Jina returned short content for %s — falling back to plain HTTP", url)
    return await _fetch_plain(url)


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

        result = await retry_async(_do, retries=3, base_delay=2.0, label=f"tavily:{query[:40]}")
        items = result or []
        logger.info("Tavily query=%r → %d results", query[:50], len(items))
        return items

    # ── Exa semantic search ────────────────────────────────────────────────────

    async def _exa_search(self, query: str) -> List[Dict]:
        if not self._exa:
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

        result = await retry_async(_do, retries=3, base_delay=2.0, label=f"exa:{query[:40]}")
        items = result or []
        logger.info("Exa query=%r → %d results", query[:50], len(items))
        return items

    # ── Perplexity Sonar search ────────────────────────────────────────────────

    async def _perplexity_search(self, query: str) -> List[Dict]:
        """Query Perplexity. Uses direct API key if available, gateway as fallback."""
        if self.perplexity_key:
            return await self._perplexity_direct(query)
        if self.gateway_key:
            return await self._perplexity_gateway(query)
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

        data = await retry_async(_do, retries=3, base_delay=2.0, label=f"perplexity-direct:{query[:40]}")
        if not data:
            return []

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

        answer = await retry_async(_do, retries=2, base_delay=2.0, label=f"perplexity-gw:{query[:40]}")
        if not answer:
            return []
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
        logger.info(
            "Scout starting: %d Tavily, %d Exa, %d Perplexity, %d direct sources",
            len(self.tavily_queries), len(self.exa_queries),
            len(self.perplexity_queries) if (self.perplexity_key or self.gateway_key) else 0,
            len(ALL_DIRECT_SOURCES) if self.enable_direct_crawl else 0,
        )

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
                item["eligibility"] = extracted.get("eligibility") or ""
                item["application_url"] = (
                    extracted.get("application_url") or item.get("url", "")
                )
                item["source_url"] = (
                    extracted.get("source_url") or item.get("url", "")
                )
                item["notes"] = extracted.get("notes") or ""
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

        # ── Quality filter + content-hash dedup + save ────────────────────────
        saved = []
        quality_rejected = 0
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
            "Scout: %d saved, %d quality-rejected, %d content-dupes",
            len(saved), quality_rejected, content_dupes,
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
            "content_dupes": content_dupes,
        }
        await scout_runs().insert_one(run_doc)
        await audit_logs().insert_one({
            "node": "scout",
            "action": f"Scout run complete: {len(saved)} new grants saved",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **run_doc,
        })

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
