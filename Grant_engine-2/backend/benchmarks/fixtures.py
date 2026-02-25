"""25 labeled grant fixtures for the analyst agent accuracy benchmark.

Each fixture represents a real-world grant scenario with a known expected outcome so
the benchmark runner can measure LLM scoring accuracy and hard-rule correctness.

Structure:
  - 5  PURSUE         (expected weighted_total ≥ 6.5)
  - 5  WATCH          (expected 5.0 ≤ score < 6.5)
  - 5  AUTO_PASS      (from LLM scoring, expected score < 5.0, no hard rule)
  - 5  AUTO_PASS      (from hard rules — caught before LLM call)
  - 5  EDGE CASES     (boundary or tricky inputs)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class GrantFixture:
    id: str
    name: str
    grant: Dict                        # input fields matching grants_raw schema
    expected_action: str               # "pursue" | "watch" | "auto_pass"
    hard_rule_fail: bool               # True → caught by _apply_hard_rules (no LLM)
    score_min: Optional[float]         # min acceptable weighted_total (None if hard_rule_fail)
    score_max: Optional[float]         # max acceptable weighted_total (None = no upper bound)
    notes: str
    accept_actions: Optional[List[str]] = None  # boundary cases: list of accepted outcomes


# ─────────────────────────────────────────────────────────────────────────────
# PURSUE — 5 fixtures  (expected weighted_total ≥ 6.5)
# ─────────────────────────────────────────────────────────────────────────────

BEZOS_CDR = GrantFixture(
    id="bezos_cdr_2026",
    name="Bezos Earth Fund Carbon Removal",
    grant={
        "title": "Bezos Earth Fund Carbon Removal 2026",
        "grant_name": "Bezos Earth Fund Carbon Removal 2026",
        "funder": "Bezos Earth Fund",
        "url": "https://www.bezosearthfund.org/grants/carbon-removal-2026",
        "url_hash": "bezos_cdr_2026_hash",
        "content_hash": "bezos_cdr_2026_content",
        "geography": "Global",
        "amount": "$500,000",
        "max_funding_usd": 500_000,
        "max_funding": 500_000,
        "currency": "USD",
        "deadline": "2026-09-30",
        "eligibility": (
            "Startups and research organizations globally. Working on carbon dioxide "
            "removal, MRV, or net-negative technologies. Seed to Series B stage."
        ),
        "themes_detected": ["climatetech", "ai_for_sciences"],
        "grant_type": "grant",
        "raw_content": (
            "The Bezos Earth Fund announces its 2026 Carbon Removal Program, offering grants "
            "up to $500,000 for innovative CDR approaches. Eligible applicants include startups, "
            "SMEs, and research institutions. Focus areas: direct air capture, enhanced weathering, "
            "soil carbon sequestration, and MRV technology development. India-based and global "
            "organizations are eligible. Rolling review process; applications close September 30, 2026."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="Perfect match: CDR/MRV theme, startup-eligible, $500K, global, India included",
)

EU_EIC_CLIMATE = GrantFixture(
    id="eu_eic_climate",
    name="EU EIC Accelerator Climate Deep Tech",
    grant={
        "title": "EU EIC Accelerator Climate & Deep Tech 2026",
        "grant_name": "EU EIC Accelerator Climate & Deep Tech 2026",
        "funder": "European Innovation Council",
        "url": "https://eic.ec.europa.eu/eic-funding-opportunities/eic-accelerator_en",
        "url_hash": "eu_eic_2026_hash",
        "content_hash": "eu_eic_2026_content",
        "geography": "Global",
        "amount": "€2,500,000",
        "max_funding_usd": 2_700_000,
        "max_funding": 2_500_000,
        "currency": "EUR",
        "deadline": "2026-10-15",
        "eligibility": (
            "Startups and SMEs at seed or growth stage globally. Climate technology, "
            "AI for climate, and deep tech focus. India-based companies eligible."
        ),
        "themes_detected": ["climatetech", "ai_for_sciences"],
        "grant_type": "grant",
        "raw_content": (
            "EIC Accelerator 2026 targets breakthrough innovations in climate technology and deep tech. "
            "Grant component up to €2.5M, plus equity option. Global applicants eligible, including India. "
            "Focuses on AI-powered climate solutions, carbon removal, MRV platforms, and environmental monitoring. "
            "Startup and SME eligible at seed through growth stage. Strong track record of funding "
            "climate tech companies from emerging markets."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="Excellent theme match, €2.5M funding, global+India eligible, startup-friendly",
)

BIRAC_AGRITECH = GrantFixture(
    id="birac_agritech_india",
    name="BIRAC Agri-Biotech India Program",
    grant={
        "title": "BIRAC Agri-Biotech Startup Program 2026",
        "grant_name": "BIRAC Agri-Biotech Startup Program 2026",
        "funder": "BIRAC (Biotechnology Industry Research Assistance Council)",
        "url": "https://www.birac.nic.in/agri-biotech-2026",
        "url_hash": "birac_agritech_hash",
        "content_hash": "birac_agritech_content",
        "geography": "India",
        "amount": "₹2,00,00,000",
        "max_funding_usd": 240_000,
        "max_funding": 20_000_000,
        "currency": "INR",
        "deadline": "2026-08-15",
        "eligibility": (
            "Indian startups and MSMEs in agritech, biotech, precision agriculture. "
            "DPIIT-recognized startups preferred. No more than 10 years old."
        ),
        "themes_detected": ["agritech"],
        "grant_type": "grant",
        "raw_content": (
            "BIRAC's Agri-Biotech Startup Program supports Indian agritech innovators with grants "
            "up to ₹2 Crore (~$240K). Eligible: DPIIT-recognized startups working on soil health, "
            "precision agriculture, crop technology, farmer technology platforms, and sustainable agriculture. "
            "India-only, explicit preference for rural impact. Soil carbon measurement and agri-data "
            "platforms are priority areas this cycle."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="India-explicit agritech match, ₹2Cr, DPIIT startup eligible — strong AltCarbon fit",
)

NSF_SBIR_AI = GrantFixture(
    id="nsf_sbir_ai_earth",
    name="NSF SBIR AI for Earth Sciences",
    grant={
        "title": "NSF SBIR Phase II — AI for Earth and Environmental Sciences",
        "grant_name": "NSF SBIR Phase II — AI for Earth and Environmental Sciences",
        "funder": "National Science Foundation (NSF)",
        "url": "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=5361",
        "url_hash": "nsf_sbir_ai_hash",
        "content_hash": "nsf_sbir_ai_content",
        "geography": "Global",
        "amount": "$750,000",
        "max_funding_usd": 750_000,
        "max_funding": 750_000,
        "currency": "USD",
        "deadline": "2026-11-01",
        "eligibility": (
            "Small businesses and startups globally applying AI to earth sciences, "
            "remote sensing, climate, or environmental monitoring. No US-only restriction."
        ),
        "themes_detected": ["ai_for_sciences", "applied_earth_sciences", "climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "NSF SBIR Phase II supports small businesses commercializing AI-driven solutions for Earth "
            "and environmental sciences. Funded activities: satellite data analysis, remote sensing ML, "
            "climate modeling, carbon flux prediction. Global applicants welcome. Grant size $750K. "
            "Strong alignment with climate tech and applied earth sciences. India-based startups eligible."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="3-theme overlap (AI+earth+climate), $750K, global, startup-focused",
)

CLIMATEWORKS_CDR = GrantFixture(
    id="climateworks_cdr",
    name="ClimateWorks CDR Startup Fund",
    grant={
        "title": "ClimateWorks Foundation CDR Startup Fund",
        "grant_name": "ClimateWorks Foundation CDR Startup Fund",
        "funder": "ClimateWorks Foundation",
        "url": "https://www.climateworks.org/grants/cdr-startup-fund",
        "url_hash": "climateworks_cdr_hash",
        "content_hash": "climateworks_cdr_content",
        "geography": "Global",
        "amount": "$300,000",
        "max_funding_usd": 300_000,
        "max_funding": 300_000,
        "currency": "USD",
        "deadline": "rolling",
        "eligibility": (
            "Early-stage startups working on carbon dioxide removal, MRV systems, "
            "or carbon accounting. Global eligibility. India-based applicants welcome."
        ),
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "ClimateWorks CDR Startup Fund offers grants of $100K–$300K to early-stage companies "
            "pioneering CDR solutions. Focus on innovative carbon removal technologies, measurement "
            "and monitoring systems, and MRV platforms. Rolling applications — no fixed deadline. "
            "Global eligible including India. Startup stage preferred."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="CDR/MRV focus, rolling deadline (must NOT block), $300K, global",
)


# ─────────────────────────────────────────────────────────────────────────────
# WATCH — 5 fixtures  (expected 5.0 ≤ score < 6.5)
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_ORG_IMPACT = GrantFixture(
    id="google_org_impact",
    name="Google.org Impact Challenge",
    grant={
        "title": "Google.org Impact Challenge 2026",
        "grant_name": "Google.org Impact Challenge 2026",
        "funder": "Google.org",
        "url": "https://impactchallenge.withgoogle.com/",
        "url_hash": "google_org_hash",
        "content_hash": "google_org_content",
        "geography": "Global",
        "amount": "$500,000",
        "max_funding_usd": 500_000,
        "max_funding": 500_000,
        "currency": "USD",
        "deadline": "2026-07-31",
        "eligibility": (
            "Nonprofits and social enterprises globally using technology for social good. "
            "Climate and AI applications encouraged but not exclusive."
        ),
        "themes_detected": ["climatetech", "social_impact"],
        "grant_type": "grant",
        "raw_content": (
            "Google.org Impact Challenge awards up to $500,000 to organizations using AI and "
            "technology to address societal challenges. Climate, education, and economic opportunity "
            "are priority areas. Receives 10,000+ applications each cycle — highly competitive. "
            "Nonprofits preferred; for-profit startups accepted in limited cases."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=6.49,
    notes="Good theme+funding but 10K+ applicants (competition_level low) and nonprofit preference",
)

DST_INDIA_DEEPTECH = GrantFixture(
    id="dst_india_deeptech",
    name="DST India Deep Tech Fund",
    grant={
        "title": "DST Deep Tech Startup Fund 2026",
        "grant_name": "DST Deep Tech Startup Fund 2026",
        "funder": "Department of Science & Technology, India",
        "url": "https://www.dst.gov.in/dst-deep-tech-startup-fund",
        "url_hash": "dst_india_hash",
        "content_hash": "dst_india_content",
        "geography": "India",
        "amount": "₹42,00,000",
        "max_funding_usd": 50_000,
        "max_funding": 4_200_000,
        "currency": "INR",
        "deadline": "2026-06-30",
        "eligibility": (
            "Indian deep tech startups. Sectors: semiconductor, advanced materials, robotics, "
            "biotech, AI. Not exclusively climate-focused."
        ),
        "themes_detected": ["ai_for_sciences"],
        "grant_type": "grant",
        "raw_content": (
            "DST's Deep Tech Startup Fund supports Indian technology startups with grants of ₹42 Lakhs. "
            "Eligible sectors: semiconductors, advanced materials, robotics, quantum tech, biotechnology, and AI. "
            "Not specifically focused on climate — generic deep tech mandate. India-only applicants. "
            "AltCarbon would qualify via AI-for-sciences angle but climate focus is secondary."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=6.49,
    notes="India geography+AI alignment, but generic tech not climate-specific; $50K modest",
)

ROCKEFELLER_FOOD = GrantFixture(
    id="rockefeller_food",
    name="Rockefeller Sustainable Food Systems Grant",
    grant={
        "title": "Rockefeller Foundation Sustainable Food Systems Grant",
        "grant_name": "Rockefeller Foundation Sustainable Food Systems Grant",
        "funder": "Rockefeller Foundation",
        "url": "https://www.rockefellerfoundation.org/grants/sustainable-food/",
        "url_hash": "rockefeller_food_hash",
        "content_hash": "rockefeller_food_content",
        "geography": "Global",
        "amount": "$200,000",
        "max_funding_usd": 200_000,
        "max_funding": 200_000,
        "currency": "USD",
        "deadline": "2026-05-15",
        "eligibility": (
            "Nonprofits, social enterprises, and startups working on sustainable food systems, "
            "nutrition, and agritech. Global."
        ),
        "themes_detected": ["agritech", "social_impact"],
        "grant_type": "grant",
        "raw_content": (
            "The Rockefeller Foundation's Sustainable Food Systems Grant funds organizations working "
            "to transform food supply chains for sustainability and nutrition equity. Focus on food "
            "security, agri-supply chains, urban agriculture, and farmer livelihoods. Climate-smart "
            "agriculture is a secondary theme. CDR and MRV are NOT priority areas. $200K, global."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=6.49,
    notes="Agritech partial match but food systems focus, not CDR/MRV; decent funding+geography",
)

FORD_CLIMATE_EQUITY = GrantFixture(
    id="ford_climate_equity",
    name="Ford Foundation Climate Equity Grant",
    grant={
        "title": "Ford Foundation Climate & Environmental Justice 2026",
        "grant_name": "Ford Foundation Climate & Environmental Justice 2026",
        "funder": "Ford Foundation",
        "url": "https://www.fordfoundation.org/work/our-grants/environment/",
        "url_hash": "ford_climate_hash",
        "content_hash": "ford_climate_content",
        "geography": "Global",
        "amount": "$250,000",
        "max_funding_usd": 250_000,
        "max_funding": 250_000,
        "currency": "USD",
        "deadline": "2026-08-01",
        "eligibility": (
            "Civil society organizations, community groups, and advocacy organizations focused "
            "on climate justice and social equity. India organizations eligible."
        ),
        "themes_detected": ["social_impact", "climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "Ford Foundation's Climate and Environmental Justice program supports community-based "
            "climate solutions. Priority areas: frontline communities, indigenous rights, climate "
            "policy advocacy, and just transition. Technology startups are less preferred — civil "
            "society and grassroots organizations are primary targets. $250K grant."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=6.49,
    notes="Social impact climate match but community/advocacy focus, not startup tech — eligibility concern",
)

UKRI_NET_ZERO = GrantFixture(
    id="ukri_net_zero",
    name="UKRI Innovate UK Net Zero Program",
    grant={
        "title": "UKRI Innovate UK Net Zero Innovation Fund 2026",
        "grant_name": "UKRI Innovate UK Net Zero Innovation Fund 2026",
        "funder": "UK Research and Innovation (UKRI)",
        "url": "https://www.ukri.org/opportunity/net-zero-innovation-fund/",
        "url_hash": "ukri_net_zero_hash",
        "content_hash": "ukri_net_zero_content",
        "geography": "UK-based (international collaboration permitted)",
        "amount": "£500,000",
        "max_funding_usd": 630_000,
        "max_funding": 500_000,
        "currency": "GBP",
        "deadline": "2026-09-01",
        "eligibility": (
            "UK-based companies primarily. International partners can join as collaborators "
            "but cannot be lead applicants."
        ),
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "Innovate UK's Net Zero Innovation Fund supports breakthrough clean technologies and "
            "net-zero solutions. Primarily for UK-based entities — India-based companies can "
            "participate as collaboration partners only. Lead applicant must be UK-registered. "
            "Strong climate theme but geographic mismatch for AltCarbon as lead. CDR, energy "
            "transition, and carbon accounting are priority areas."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=6.49,
    notes="Climate theme + good funding but UK-primary geography limits AltCarbon lead eligibility",
)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO_PASS (from scoring, no hard rule) — 5 fixtures  (expected score < 5.0)
# ─────────────────────────────────────────────────────────────────────────────

ARTS_COUNCIL = GrantFixture(
    id="arts_council",
    name="Arts Council Creative Grant",
    grant={
        "title": "Arts Council England — Creative Development Fund 2026",
        "grant_name": "Arts Council England — Creative Development Fund 2026",
        "funder": "Arts Council England",
        "url": "https://www.artscouncil.org.uk/creative-development-fund",
        "url_hash": "arts_council_hash",
        "content_hash": "arts_council_content",
        "geography": "UK only",
        "amount": "£50,000",
        "max_funding_usd": 63_000,
        "max_funding": 50_000,
        "currency": "GBP",
        "deadline": "2026-03-31",
        "eligibility": (
            "UK-registered arts and cultural organizations only. "
            "Science, technology, or environmental organizations are not eligible."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "Arts Council England's Creative Development Fund supports arts, culture, and creative "
            "sector organizations. Eligible: theatres, museums, galleries, dance companies, literature "
            "organizations. No technology, science, or environmental organizations eligible. UK only."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="Zero climate/tech theme, UK arts-only eligibility — lowest possible alignment",
)

DOE_US_ONLY = GrantFixture(
    id="doe_us_only_mfg",
    name="DOE Advanced Manufacturing US-Only",
    grant={
        "title": "DOE Office of Manufacturing — Advanced Industrial Processes 2026",
        "grant_name": "DOE Office of Manufacturing — Advanced Industrial Processes 2026",
        "funder": "US Department of Energy",
        "url": "https://www.energy.gov/eere/amo/advanced-manufacturing-2026",
        "url_hash": "doe_us_only_hash",
        "content_hash": "doe_us_only_content",
        "geography": "United States only",
        "amount": "$2,000,000",
        "max_funding_usd": 2_000_000,
        "max_funding": 2_000_000,
        "currency": "USD",
        "deadline": "2026-12-31",
        "eligibility": (
            "US-incorporated entities ONLY. Foreign entities expressly not eligible. "
            "Manufacturing sector focus."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "DOE Advanced Manufacturing program funds US-incorporated companies to improve industrial "
            "energy efficiency. Strictly US entities only — no international participation allowed. "
            "Focus on industrial processes, advanced materials, and manufacturing efficiency. "
            "Not aligned with carbon removal or climate tech themes specific to AltCarbon's work."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="Explicitly US-only → geography_fit=0; manufacturing not AltCarbon's theme",
)

GATES_PHARMA = GrantFixture(
    id="gates_pharma",
    name="Gates Foundation Drug Discovery Grant",
    grant={
        "title": "Bill & Melinda Gates Foundation — Drug Discovery Initiative",
        "grant_name": "Bill & Melinda Gates Foundation — Drug Discovery Initiative",
        "funder": "Bill & Melinda Gates Foundation",
        "url": "https://www.gatesfoundation.org/ideas/grants/drug-discovery",
        "url_hash": "gates_pharma_hash",
        "content_hash": "gates_pharma_content",
        "geography": "Global",
        "amount": "$1,000,000",
        "max_funding_usd": 1_000_000,
        "max_funding": 1_000_000,
        "currency": "USD",
        "deadline": "2026-04-30",
        "eligibility": (
            "Pharmaceutical research organizations, academic institutions, and biotech companies "
            "focused on neglected tropical diseases and infectious diseases."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "Gates Foundation Drug Discovery Initiative funds innovative pharmaceutical research to "
            "tackle neglected tropical diseases. Focus: malaria, tuberculosis, HIV, and emerging "
            "infectious diseases. Eligible: pharmaceutical companies, biotech firms, academic labs. "
            "No climate, environmental, or agritech connection. Healthcare/pharma only."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="Healthcare/pharma — zero theme overlap with AltCarbon climate/agritech focus",
)

URBAN_RE = GrantFixture(
    id="urban_real_estate",
    name="Urban Land Institute Real Estate Grant",
    grant={
        "title": "ULI Foundation — Urban Real Estate Innovation Grant",
        "grant_name": "ULI Foundation — Urban Real Estate Innovation Grant",
        "funder": "Urban Land Institute Foundation",
        "url": "https://uli.org/grants/urban-innovation/",
        "url_hash": "urban_re_hash",
        "content_hash": "urban_re_content",
        "geography": "North America",
        "amount": "$150,000",
        "max_funding_usd": 150_000,
        "max_funding": 150_000,
        "currency": "USD",
        "deadline": "2026-06-15",
        "eligibility": (
            "Real estate developers, urban planners, and property management companies. "
            "North America focused."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "The ULI Foundation Urban Real Estate Innovation Grant supports property developers and "
            "urban planners working on affordable housing, mixed-use development, and transit-oriented "
            "design. North America focused. Real estate and urban development only — no climate tech "
            "or agritech."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="Real estate development — no alignment with AltCarbon themes or sector",
)

MASTERCARD_FINTECH = GrantFixture(
    id="mastercard_fintech",
    name="Mastercard Financial Inclusion Grant",
    grant={
        "title": "Mastercard Center for Inclusive Growth — Fintech Innovation Grant",
        "grant_name": "Mastercard Center for Inclusive Growth — Fintech Innovation Grant",
        "funder": "Mastercard Center for Inclusive Growth",
        "url": "https://mastercardcenter.org/insights/fintech-innovation-grant/",
        "url_hash": "mastercard_fintech_hash",
        "content_hash": "mastercard_fintech_content",
        "geography": "Global (developing markets focus)",
        "amount": "$100,000",
        "max_funding_usd": 100_000,
        "max_funding": 100_000,
        "currency": "USD",
        "deadline": "2026-05-01",
        "eligibility": (
            "Fintech companies and payment solutions providers focused on financial inclusion "
            "in developing markets."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "Mastercard's Financial Inclusion grant supports fintech innovations serving unbanked "
            "populations. Focus: digital payments, mobile banking, micro-lending, and credit access "
            "for low-income communities. No climate or environmental mandate. Fintech and payments "
            "sector only. Developing markets including India eligible, but sector mismatch with AltCarbon."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="Fintech/payments — India eligible but zero sector alignment with AltCarbon",
)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO_PASS from hard rules — 5 fixtures  (hard_rule_fail=True, no LLM call)
# ─────────────────────────────────────────────────────────────────────────────

EXPIRED_2023 = GrantFixture(
    id="expired_2023",
    name="ClimateWorks 2023 Call (closed)",
    grant={
        "title": "ClimateWorks Foundation CDR Call 2023",
        "grant_name": "ClimateWorks Foundation CDR Call 2023",
        "funder": "ClimateWorks Foundation",
        "url": "https://www.climateworks.org/grants/2023-cdr-call",
        "url_hash": "expired_2023_hash",
        "content_hash": "expired_2023_content",
        "geography": "Global",
        "amount": "$200,000",
        "max_funding_usd": 200_000,
        "max_funding": 200_000,
        "currency": "USD",
        "deadline": "2023-03-15",
        "eligibility": "CDR startups globally.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": "ClimateWorks CDR Call 2023 — deadline was March 15, 2023.",
    },
    expected_action="auto_pass",
    hard_rule_fail=True,
    score_min=None,
    score_max=None,
    notes="Deadline 2023-03-15 has passed → _apply_hard_rules must catch this",
)

EXPIRED_2024 = GrantFixture(
    id="expired_2024",
    name="BIRAC 2024 Round (closed)",
    grant={
        "title": "BIRAC BIG 2024 Round",
        "grant_name": "BIRAC BIG 2024 Round",
        "funder": "BIRAC",
        "url": "https://www.birac.nic.in/big-2024",
        "url_hash": "expired_2024_hash",
        "content_hash": "expired_2024_content",
        "geography": "India",
        "amount": "₹50,00,000",
        "max_funding_usd": 60_000,
        "max_funding": 5_000_000,
        "currency": "INR",
        "deadline": "2024-06-30",
        "eligibility": "Indian startups in biotech and agritech.",
        "themes_detected": ["agritech"],
        "grant_type": "grant",
        "raw_content": "BIRAC BIG 2024 — deadline June 30, 2024.",
    },
    expected_action="auto_pass",
    hard_rule_fail=True,
    score_min=None,
    score_max=None,
    notes="Deadline 2024-06-30 has passed → hard rule catches",
)

MICRO_GRANT_500 = GrantFixture(
    id="micro_grant_500",
    name="Local Climate Micro-Grant ($500)",
    grant={
        "title": "Community Climate Action Micro-Grant",
        "grant_name": "Community Climate Action Micro-Grant",
        "funder": "Local Climate Foundation",
        "url": "https://localclimatefound.org/micro-grant",
        "url_hash": "micro_grant_500_hash",
        "content_hash": "micro_grant_500_content",
        "geography": "Global",
        "amount": "$500",
        "max_funding_usd": 500,
        "max_funding": 500,
        "currency": "USD",
        "deadline": "2026-12-31",
        "eligibility": "Individuals and small community groups for local climate action.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": "Small community grant of $500 for local climate projects.",
    },
    expected_action="auto_pass",
    hard_rule_fail=True,
    score_min=None,
    score_max=None,
    notes="max_funding_usd=500 < $3,000 minimum → funding hard rule catches",
)

JUST_UNDER_3K = GrantFixture(
    id="just_under_3k",
    name="Community Action Grant ($2,999)",
    grant={
        "title": "Community Action Climate Grant",
        "grant_name": "Community Action Climate Grant",
        "funder": "Community Climate Alliance",
        "url": "https://communityaction.org/climate-grant",
        "url_hash": "just_under_3k_hash",
        "content_hash": "just_under_3k_content",
        "geography": "Global",
        "amount": "$2,999",
        "max_funding_usd": 2_999,
        "max_funding": 2_999,
        "currency": "USD",
        "deadline": "2026-10-01",
        "eligibility": "Small organizations and startups.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": "Community climate grant at $2,999 — boundary test for minimum funding rule.",
    },
    expected_action="auto_pass",
    hard_rule_fail=True,
    score_min=None,
    score_max=None,
    notes="max_funding_usd=2999 — just below $3K minimum → hard rule catches",
)

BOTH_FAIL = GrantFixture(
    id="both_fail",
    name="Old Seed Grant (expired + underfunded)",
    grant={
        "title": "Old Climate Seed Grant 2022",
        "grant_name": "Old Climate Seed Grant 2022",
        "funder": "Climate Seed Fund",
        "url": "https://climateseedfund.org/2022",
        "url_hash": "both_fail_hash",
        "content_hash": "both_fail_content",
        "geography": "Global",
        "amount": "$1,000",
        "max_funding_usd": 1_000,
        "max_funding": 1_000,
        "currency": "USD",
        "deadline": "2022-01-01",
        "eligibility": "Any organization.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": "Old seed grant from 2022 — both expired and underfunded.",
    },
    expected_action="auto_pass",
    hard_rule_fail=True,
    score_min=None,
    score_max=None,
    notes="Both rules fail: funding=$1K AND deadline=2022. Funding rule is Rule 1 and wins.",
)


# ─────────────────────────────────────────────────────────────────────────────
# EDGE CASES — 5 fixtures  (boundary + tricky inputs)
# ─────────────────────────────────────────────────────────────────────────────

ROLLING_STRONG_CDR = GrantFixture(
    id="rolling_strong_cdr",
    name="Strong CDR Grant with Rolling Deadline",
    grant={
        "title": "Carbon180 CDR Innovation Grant",
        "grant_name": "Carbon180 CDR Innovation Grant",
        "funder": "Carbon180",
        "url": "https://carbon180.org/grants/cdr-innovation",
        "url_hash": "rolling_cdr_hash",
        "content_hash": "rolling_cdr_content",
        "geography": "Global",
        "amount": "$400,000",
        "max_funding_usd": 400_000,
        "max_funding": 400_000,
        "currency": "USD",
        "deadline": "rolling",
        "eligibility": (
            "Startups and SMEs working on carbon dioxide removal and MRV. "
            "Global eligibility including India."
        ),
        "themes_detected": ["climatetech", "ai_for_sciences"],
        "grant_type": "grant",
        "raw_content": (
            "Carbon180 CDR Innovation Grant offers funding for breakthrough CDR technologies. "
            "Rolling applications — apply anytime. $400K, global, startup-friendly. "
            "Focus: direct air capture, biochar, enhanced weathering, MRV systems."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="Rolling deadline must NOT trigger hard rule. Strong CDR match → expect pursue.",
)

NULL_FUNDING_CDR = GrantFixture(
    id="null_funding_cdr",
    name="CDR Grant with Undisclosed Funding",
    grant={
        "title": "Grantham Foundation CDR Research Award",
        "grant_name": "Grantham Foundation CDR Research Award",
        "funder": "Grantham Foundation",
        "url": "https://www.granthamfoundation.org/cdr-award",
        "url_hash": "null_funding_cdr_hash",
        "content_hash": "null_funding_cdr_content",
        "geography": "Global",
        "amount": "Not disclosed",
        "max_funding_usd": None,
        "max_funding": None,
        "currency": "USD",
        "deadline": "2026-11-30",
        "eligibility": "Organizations doing carbon removal research. Global, India eligible.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "Grantham Foundation CDR Research Award supports carbon removal and MRV innovation. "
            "Grant amount not publicly disclosed — selected applicants notified of amount. "
            "Global eligible, India included. CDR and climate tech focus."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=None,
    notes="max_funding=None must pass hard rules. CDR theme strong but unknown funding lowers score.",
    accept_actions=["watch", "pursue"],
)

XPRIZE_CARBON = GrantFixture(
    id="xprize_carbon",
    name="XPRIZE Carbon Removal ($50M Prize)",
    grant={
        "title": "XPRIZE Carbon Removal — Phase 3 Finalist Award",
        "grant_name": "XPRIZE Carbon Removal — Phase 3 Finalist Award",
        "funder": "XPRIZE Foundation",
        "url": "https://www.xprize.org/prizes/carbon-removal",
        "url_hash": "xprize_carbon_hash",
        "content_hash": "xprize_carbon_content",
        "geography": "Global",
        "amount": "$50,000,000",
        "max_funding_usd": 50_000_000,
        "max_funding": 50_000_000,
        "currency": "USD",
        "deadline": "2026-08-31",
        "eligibility": (
            "Any organization globally with a demonstrated CDR technology at pilot scale. "
            "India-based teams eligible."
        ),
        "themes_detected": ["climatetech", "ai_for_sciences", "applied_earth_sciences"],
        "grant_type": "prize",
        "raw_content": (
            "XPRIZE Carbon Removal is the world's largest incentive prize for carbon removal technology. "
            "$50M total prize pool. Phase 3 accepts teams with demonstrated pilot-scale CDR solutions. "
            "Global eligible. High competition — thousands of teams worldwide. "
            "MRV platform and measurement technology also eligible."
        ),
    },
    expected_action="pursue",
    hard_rule_fail=False,
    score_min=6.5,
    score_max=None,
    notes="Massive prize ($50M), perfect CDR theme — should pursue despite competition",
)

INDIA_WRONG_SECTOR = GrantFixture(
    id="india_only_wrong_sector",
    name="India-only Traditional Manufacturing Grant",
    grant={
        "title": "Make in India Manufacturing Innovation Fund",
        "grant_name": "Make in India Manufacturing Innovation Fund",
        "funder": "Ministry of Commerce, India",
        "url": "https://www.makeinindia.com/manufacturing-fund",
        "url_hash": "india_mfg_hash",
        "content_hash": "india_mfg_content",
        "geography": "India",
        "amount": "₹5,00,00,000",
        "max_funding_usd": 600_000,
        "max_funding": 50_000_000,
        "currency": "INR",
        "deadline": "2026-12-01",
        "eligibility": (
            "Indian manufacturers in traditional sectors: textiles, steel, automotive, "
            "electronics assembly."
        ),
        "themes_detected": [],
        "grant_type": "grant",
        "raw_content": (
            "Make in India Manufacturing Innovation Fund supports traditional manufacturing sectors. "
            "Eligible: textile mills, steel plants, automotive component makers, electronics assembly. "
            "No climate tech, agritech, or software companies eligible. India-only."
        ),
    },
    expected_action="auto_pass",
    hard_rule_fail=False,
    score_min=None,
    score_max=4.99,
    notes="India = geography_fit=10 but theme_alignment≈1 and eligibility≈0 → total score very low",
)

BOUNDARY_WATCH_PURSUE = GrantFixture(
    id="boundary_watch_pursue",
    name="Mixed Signals Grant (borderline ~6.0–6.5)",
    grant={
        "title": "Breakthrough Energy Seed Grant — Climate Tech 2026",
        "grant_name": "Breakthrough Energy Seed Grant — Climate Tech 2026",
        "funder": "Breakthrough Energy",
        "url": "https://breakthroughenergy.org/our-work/grants",
        "url_hash": "boundary_hash",
        "content_hash": "boundary_content",
        "geography": "Global",
        "amount": "$80,000",
        "max_funding_usd": 80_000,
        "max_funding": 80_000,
        "currency": "USD",
        "deadline": "2026-10-31",
        "eligibility": "Early-stage climate tech startups globally. Pre-seed and seed stage.",
        "themes_detected": ["climatetech"],
        "grant_type": "grant",
        "raw_content": (
            "Breakthrough Energy seed grants for early climate tech startups. $80K — modest but "
            "meaningful for pre-seed. Global eligible. Moderately selective. Strong climate theme "
            "alignment. AltCarbon would be a competitive applicant given CDR focus."
        ),
    },
    expected_action="watch",
    hard_rule_fail=False,
    score_min=5.0,
    score_max=None,
    notes="Borderline case — score near watch/pursue boundary. Both outcomes accepted.",
    accept_actions=["watch", "pursue"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Aggregated fixture lists
# ─────────────────────────────────────────────────────────────────────────────

ALL_FIXTURES: list[GrantFixture] = [
    # PURSUE
    BEZOS_CDR, EU_EIC_CLIMATE, BIRAC_AGRITECH, NSF_SBIR_AI, CLIMATEWORKS_CDR,
    # WATCH
    GOOGLE_ORG_IMPACT, DST_INDIA_DEEPTECH, ROCKEFELLER_FOOD, FORD_CLIMATE_EQUITY, UKRI_NET_ZERO,
    # AUTO_PASS from scoring
    ARTS_COUNCIL, DOE_US_ONLY, GATES_PHARMA, URBAN_RE, MASTERCARD_FINTECH,
    # AUTO_PASS from hard rules
    EXPIRED_2023, EXPIRED_2024, MICRO_GRANT_500, JUST_UNDER_3K, BOTH_FAIL,
    # EDGE CASES
    ROLLING_STRONG_CDR, NULL_FUNDING_CDR, XPRIZE_CARBON, INDIA_WRONG_SECTOR, BOUNDARY_WATCH_PURSUE,
]

# 20 fixtures that go through LLM scoring (hard_rule_fail=False)
LLM_FIXTURES: list[GrantFixture] = [f for f in ALL_FIXTURES if not f.hard_rule_fail]

# 5 fixtures caught by hard rules before the LLM
HARD_RULE_FIXTURES: list[GrantFixture] = [f for f in ALL_FIXTURES if f.hard_rule_fail]
