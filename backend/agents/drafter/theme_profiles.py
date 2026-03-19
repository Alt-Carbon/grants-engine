"""Theme Profiles — domain-specific configuration for each company theme.

Each profile provides:
- domain_terms: vocabulary the drafter should use naturally
- evidence_queries: Pinecone search queries per section type → pulls targeted knowledge
- articulation_map: maps generic grant sections → company's 12-section articulation docs
- tone: framing guidance
- strengths: what to highlight for this theme (defaults — overridable via Drafter Settings UI)
- default_sections: theme-specific fallback sections (replaces generic 5)

NOTE ON STRENGTHS / COMPANY-SPECIFIC DEFAULTS:
    The `strengths`, `tone`, and `evidence_queries` values below are AltCarbon-specific
    defaults. They are NOT the only source of truth — the Drafter supports per-grant
    overrides via:
      1. `strengths_override` in individual draft settings (per-grant)
      2. `theme_settings` in agent_config (global per-theme override from UI)
    These defaults are used as fallback when no override is provided. To change them
    without modifying code, use the Drafter Settings UI or update agent_config in MongoDB.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ── Articulation section names (from Documents List / ToC) ─────────────────
# These are the 12 sections in AltCarbon's articulation documents
ARTICULATION_SECTIONS = [
    "Problem Statement",
    "Literature",
    "Solution",
    "Why Best Suited",
    "Collaborators",
    "Outputs",
    "Outcomes",
    "Project Plan",
    "Cobenefits",
    "Unit Economics",
    "Pricing",
    "Budget",
]


# ── Section → articulation mapping ─────────────────────────────────────────
# Maps common grant section names to which articulation sections to pull from
SECTION_TO_ARTICULATION: Dict[str, List[str]] = {
    # Grant section pattern → articulation sections to retrieve
    "project overview": ["Problem Statement", "Solution", "Outcomes"],
    "executive summary": ["Problem Statement", "Solution", "Outcomes"],
    "summary": ["Problem Statement", "Solution", "Outcomes"],
    "abstract": ["Problem Statement", "Solution"],
    "introduction": ["Problem Statement", "Literature"],
    "background": ["Problem Statement", "Literature"],
    "problem statement": ["Problem Statement", "Literature"],
    "literature review": ["Literature"],
    "technical approach": ["Solution", "Why Best Suited", "Project Plan"],
    "methodology": ["Solution", "Project Plan"],
    "research plan": ["Solution", "Project Plan", "Outputs"],
    "innovation": ["Solution", "Why Best Suited"],
    "technology": ["Solution", "Why Best Suited"],
    "team": ["Why Best Suited", "Collaborators"],
    "team & capabilities": ["Why Best Suited", "Collaborators"],
    "qualifications": ["Why Best Suited"],
    "partnerships": ["Collaborators"],
    "collaborators": ["Collaborators"],
    "consortium": ["Collaborators"],
    "budget": ["Budget", "Unit Economics", "Pricing"],
    "budget justification": ["Budget", "Unit Economics"],
    "financial plan": ["Budget", "Unit Economics", "Pricing"],
    "cost breakdown": ["Budget", "Unit Economics"],
    "impact": ["Outcomes", "Cobenefits"],
    "impact & outcomes": ["Outcomes", "Cobenefits"],
    "expected outcomes": ["Outcomes", "Outputs"],
    "deliverables": ["Outputs", "Project Plan"],
    "outputs": ["Outputs"],
    "milestones": ["Project Plan", "Outputs"],
    "timeline": ["Project Plan"],
    "work plan": ["Project Plan", "Outputs"],
    "sustainability": ["Cobenefits", "Unit Economics"],
    "scalability": ["Unit Economics", "Pricing", "Outcomes"],
    "commercialization": ["Unit Economics", "Pricing"],
    "market": ["Unit Economics", "Pricing"],
    "social impact": ["Cobenefits", "Outcomes"],
    "environmental impact": ["Cobenefits", "Outcomes"],
    "monitoring": ["Outputs", "Solution"],
    "mrv": ["Solution", "Outputs", "Why Best Suited"],
}


def get_articulation_sections(section_name: str) -> List[str]:
    """Given a grant section name, return which articulation sections to pull."""
    name_lower = section_name.lower().strip()
    # Exact match first
    if name_lower in SECTION_TO_ARTICULATION:
        return SECTION_TO_ARTICULATION[name_lower]
    # Partial match
    for pattern, arts in SECTION_TO_ARTICULATION.items():
        if pattern in name_lower or name_lower in pattern:
            return arts
    # Default: pull Problem Statement + Solution
    return ["Problem Statement", "Solution"]


# ── Theme profiles ─────────────────────────────────────────────────────────

THEME_PROFILES: Dict[str, Dict] = {
    # NOTE: Each theme's `strengths` list contains company-specific defaults.
    # These are overridable per-grant via strengths_override or globally via
    # theme_settings in agent_config (Drafter Settings UI). Do not delete defaults.
    "climatetech": {
        "display_name": "Climate Tech / CDR",
        "domain_terms": [
            "carbon dioxide removal (CDR)", "enhanced rock weathering (ERW)",
            "biochar", "soil carbon sequestration", "mineral dissolution",
            "cation release", "CO2 drawdown", "MRV (measurement, reporting, verification)",
            "carbon credits", "permanence", "additionality", "net negativity",
            "weathering rates", "silicate minerals", "basalt application",
            "soil amendment", "carbon accounting", "life cycle assessment",
        ],
        "tone": (
            "Lead with scientific rigor and quantified climate impact. "
            "Frame ERW and Biochar as proven, scalable CDR pathways backed by peer-reviewed science. "
            "Emphasize AltCarbon's unique MRV advantage — AI-driven measurement at the plot level. "
            "Use precise technical language but explain mechanisms for non-specialist reviewers."
        ),
        "strengths": [
            "Only CDR company with plot-level AI-driven MRV across ERW and Biochar",
            "Operational in Darjeeling (ERW) and Eastern India (Biochar) — real field data",
            "Carbon credit buyers: Google/Frontier, Stripe, Shopify, UBS, BCG, Mitsubishi",
            "Founded by 4th-gen tea planters — deep agronomic knowledge + tech capability",
            "Dual-pathway approach: ERW for long-term + Biochar for near-term credits",
        ],
        "evidence_queries": {
            "default": "AltCarbon CDR carbon removal climate technology MRV verification",
            "technical": "enhanced rock weathering ERW biochar methodology soil carbon measurement",
            "impact": "carbon credits tonnes removed climate impact drawdown verification",
            "team": "AltCarbon team founders Shrey Sparsh IISc Darjeeling expertise",
            "market": "carbon credit market CDR buyers pricing unit economics",
        },
        "default_sections": [
            {"name": "Executive Summary", "description": "High-level project summary with CDR pathway and expected tonnes removed", "word_limit": 500, "required": True, "order": 1},
            {"name": "Problem & Opportunity", "description": "Climate crisis context, CDR gap, and the specific opportunity this grant addresses", "word_limit": 600, "required": True, "order": 2},
            {"name": "Technical Approach", "description": "ERW/Biochar methodology, MRV system, field deployment plan", "word_limit": 800, "required": True, "order": 3},
            {"name": "Team & Track Record", "description": "Team qualifications, field experience, buyer relationships, prior grants", "word_limit": 400, "required": True, "order": 4},
            {"name": "Impact & Scalability", "description": "Tonnes of CDR, co-benefits, scaling pathway, market readiness", "word_limit": 500, "required": True, "order": 5},
            {"name": "Budget & Timeline", "description": "Cost breakdown, milestones, deliverables schedule", "word_limit": 400, "required": True, "order": 6},
        ],
    },

    "agritech": {
        "display_name": "AgriTech",
        "domain_terms": [
            "soil health", "crop yield improvement", "precision agriculture",
            "soil amendment", "tea cultivation", "regenerative agriculture",
            "farmer livelihoods", "smallholder farmers", "agronomic practices",
            "soil pH", "nutrient availability", "organic matter",
            "biochar application rates", "compost", "vermicompost",
            "agricultural extension", "field trials", "plot-level monitoring",
        ],
        "tone": (
            "Frame technology through agricultural impact — improved yields, soil health, farmer livelihoods. "
            "Emphasize real-world deployment in Darjeeling tea gardens and Eastern India smallholder farms. "
            "Lead with farmer outcomes, then the science. Use accessible language — "
            "reviewers may be agri-policy experts, not climate scientists."
        ),
        "strengths": [
            "4th-generation tea planters — deep agronomic domain expertise",
            "Active field operations across Darjeeling tea estates and Eastern India farms",
            "Biochar and ERW as soil amendments with proven yield co-benefits",
            "Plot-level monitoring shows measurable soil health improvements",
            "Direct farmer relationships — not just lab research",
        ],
        "evidence_queries": {
            "default": "AltCarbon agriculture soil health farming Darjeeling tea biochar",
            "technical": "soil amendment biochar ERW crop yield soil pH nutrient availability",
            "impact": "farmer livelihoods crop yield improvement soil health regenerative agriculture",
            "team": "AltCarbon founders tea planters Darjeeling agricultural experience",
            "market": "agriculture soil amendment market India smallholder farming",
        },
        "default_sections": [
            {"name": "Executive Summary", "description": "Project overview emphasizing agricultural impact and farmer outcomes", "word_limit": 500, "required": True, "order": 1},
            {"name": "Agricultural Context", "description": "Soil degradation challenge, farmer needs, regional agriculture overview", "word_limit": 500, "required": True, "order": 2},
            {"name": "Technical Approach", "description": "Soil amendment methodology, application protocols, monitoring plan", "word_limit": 700, "required": True, "order": 3},
            {"name": "Team & Field Experience", "description": "Agronomic expertise, farmer relationships, field deployment history", "word_limit": 400, "required": True, "order": 4},
            {"name": "Impact on Farmers & Soil", "description": "Expected yield improvements, soil health metrics, farmer livelihood outcomes", "word_limit": 500, "required": True, "order": 5},
            {"name": "Budget & Work Plan", "description": "Cost breakdown with field operations detail, timeline with planting seasons", "word_limit": 400, "required": True, "order": 6},
        ],
    },

    "ai_for_sciences": {
        "display_name": "AI for Sciences",
        "domain_terms": [
            "machine learning", "deep learning", "computer vision",
            "spectral analysis", "remote sensing", "satellite imagery",
            "geospatial AI", "predictive modeling", "neural networks",
            "sensor fusion", "IoT sensors", "data pipeline",
            "model validation", "ground truth", "training data",
            "automated MRV", "AI-driven measurement", "inference at scale",
        ],
        "tone": (
            "Lead with the AI/ML innovation and scientific methodology. "
            "Position AltCarbon as building foundational AI infrastructure for earth sciences. "
            "Emphasize novel technical contributions — not just applying off-the-shelf models. "
            "Use precise ML terminology. Cite the data advantage (real field data from active deployments)."
        ),
        "strengths": [
            "Proprietary AI-driven MRV system — not using third-party measurement",
            "Real ground-truth data from active CDR deployments (not simulated)",
            "ML models trained on actual field measurements from Darjeeling and Eastern India",
            "Sensor fusion: soil sensors + satellite imagery + spectral analysis",
            "Scalable inference pipeline — plot-level to regional monitoring",
        ],
        "evidence_queries": {
            "default": "AltCarbon AI machine learning MRV measurement technology data science",
            "technical": "AI MRV machine learning soil carbon measurement spectral analysis remote sensing",
            "impact": "automated verification measurement accuracy scalable monitoring",
            "team": "AltCarbon data science AI team IISc research capabilities",
            "market": "AI earth sciences MRV technology carbon measurement market",
        },
        "default_sections": [
            {"name": "Executive Summary", "description": "AI/ML innovation summary, scientific contribution, and practical application", "word_limit": 500, "required": True, "order": 1},
            {"name": "Scientific Background", "description": "State of the art in AI for earth sciences, measurement gaps, research questions", "word_limit": 600, "required": True, "order": 2},
            {"name": "Technical Innovation", "description": "ML architecture, data pipeline, training approach, validation methodology", "word_limit": 800, "required": True, "order": 3},
            {"name": "Data & Infrastructure", "description": "Training data sources, sensor deployment, compute requirements, ground truth collection", "word_limit": 500, "required": True, "order": 4},
            {"name": "Team & Research Capacity", "description": "AI/ML expertise, research partnerships, publication track record", "word_limit": 400, "required": True, "order": 5},
            {"name": "Expected Outcomes & Timeline", "description": "Model performance targets, deployment milestones, open-source contributions", "word_limit": 400, "required": True, "order": 6},
        ],
    },

    "applied_earth_sciences": {
        "display_name": "Applied Earth Sciences",
        "domain_terms": [
            "geochemistry", "mineralogy", "silicate weathering",
            "cation exchange capacity", "soil sampling", "XRF analysis",
            "mineral dissolution kinetics", "basalt", "wollastonite",
            "olivine", "alkalinity", "pH buffering",
            "stable isotopes", "metal stable isotopes", "laser ablation ICP-MS",
            "pedology", "soil profile", "field geochemistry",
        ],
        "tone": (
            "Deeply technical and scientifically rigorous. "
            "Position AltCarbon at the intersection of field geochemistry and applied climate science. "
            "Reference specific mineral systems, analytical methods, and quantitative results. "
            "This audience expects peer-review-level precision."
        ),
        "strengths": [
            "Field geochemistry data from real ERW deployments in tropical soils",
            "Mineral dissolution rate measurements under tropical conditions",
            "Integration of geochemical measurement with AI-driven MRV",
            "Collaboration potential with IISc and research institutions",
            "Applied science: translating lab geochemistry to field-scale CDR",
        ],
        "evidence_queries": {
            "default": "AltCarbon geochemistry ERW mineral weathering soil science field data",
            "technical": "enhanced rock weathering geochemistry mineral dissolution basalt tropical soils",
            "impact": "carbon sequestration measurement geochemical verification field trials",
            "team": "AltCarbon earth sciences research geochemistry expertise IISc",
            "market": "ERW field deployment weathering verification earth sciences application",
        },
        "default_sections": [
            {"name": "Research Summary", "description": "Core research question, geological context, expected scientific contribution", "word_limit": 500, "required": True, "order": 1},
            {"name": "Geological & Geochemical Background", "description": "Mineral systems, weathering mechanisms, current knowledge gaps", "word_limit": 600, "required": True, "order": 2},
            {"name": "Methodology", "description": "Field sampling, analytical methods, experimental design, data analysis", "word_limit": 800, "required": True, "order": 3},
            {"name": "Research Team & Facilities", "description": "PI qualifications, lab access, institutional partnerships", "word_limit": 400, "required": True, "order": 4},
            {"name": "Expected Results & Significance", "description": "Quantitative targets, publications, contribution to CDR science", "word_limit": 500, "required": True, "order": 5},
            {"name": "Budget & Timeline", "description": "Equipment, fieldwork, analysis costs with research milestones", "word_limit": 400, "required": True, "order": 6},
        ],
    },

    "social_impact": {
        "display_name": "Social Impact",
        "domain_terms": [
            "community development", "livelihood improvement", "rural employment",
            "gender equity", "smallholder empowerment", "capacity building",
            "just transition", "co-benefits", "SDGs", "sustainable development goals",
            "participatory approach", "stakeholder engagement", "social return on investment",
            "inclusive growth", "bottom-of-pyramid", "rural India",
        ],
        "tone": (
            "Lead with human impact and community outcomes. "
            "Frame CDR technology as a vehicle for rural development and equitable climate action. "
            "Emphasize farmer agency, local employment, and social co-benefits. "
            "Use impact measurement language (SDGs, SROI). Storytelling encouraged."
        ),
        "strengths": [
            "Direct farmer partnerships in Darjeeling and Eastern India — not extractive",
            "CDR operations create rural employment (rock application, monitoring, logistics)",
            "Founded by local community members (4th-gen tea planters)",
            "Co-benefits: improved soil → better yields → higher farmer income",
            "Just transition: climate action that benefits the most vulnerable",
        ],
        "evidence_queries": {
            "default": "AltCarbon social impact farmers community Darjeeling rural development",
            "technical": "soil amendment farmer livelihood yield improvement community benefits",
            "impact": "social impact rural employment farmer income gender equity SDGs",
            "team": "AltCarbon founders community Darjeeling tea planters farmer relationships",
            "market": "social impact climate action rural India community development",
        },
        "default_sections": [
            {"name": "Executive Summary", "description": "Project overview emphasizing social impact and community outcomes", "word_limit": 500, "required": True, "order": 1},
            {"name": "Community Context", "description": "Target community, challenges, needs assessment, stakeholder landscape", "word_limit": 500, "required": True, "order": 2},
            {"name": "Approach & Activities", "description": "How CDR operations create social value, community engagement plan", "word_limit": 600, "required": True, "order": 3},
            {"name": "Team & Community Relationships", "description": "Local presence, farmer partnerships, community trust, cultural competence", "word_limit": 400, "required": True, "order": 4},
            {"name": "Impact Measurement", "description": "SDG alignment, SROI indicators, livelihoods improved, jobs created", "word_limit": 500, "required": True, "order": 5},
            {"name": "Sustainability & Budget", "description": "Long-term community benefit model, cost per beneficiary, timeline", "word_limit": 400, "required": True, "order": 6},
        ],
    },

    "deeptech": {
        "display_name": "Deep Tech",
        "domain_terms": [
            "technology readiness level (TRL)", "proof of concept", "pilot scale",
            "hardware-software integration", "sensor technology", "IoT",
            "edge computing", "data infrastructure", "API architecture",
            "scalable systems", "patent", "intellectual property",
            "technology transfer", "commercialization pathway", "venture-scale",
        ],
        "tone": (
            "Position AltCarbon as a deep-tech venture building novel infrastructure. "
            "Emphasize the technology moat: proprietary MRV stack, hardware-software integration, "
            "data flywheel from field deployments. Frame in TRL language. "
            "Show the path from science to scalable product."
        ),
        "strengths": [
            "Proprietary MRV technology stack — not using third-party tools",
            "Hardware (sensors) + software (AI) + field operations integration",
            "Data moat: real field measurements that competitors don't have",
            "CDR market is venture-scale: $10B+ TAM by 2030",
            "Multiple revenue streams: carbon credits + technology licensing + data services",
        ],
        "evidence_queries": {
            "default": "AltCarbon technology deep tech MRV platform proprietary innovation",
            "technical": "MRV technology stack sensor AI platform architecture scalable system",
            "impact": "technology scalability commercialization carbon credit market venture",
            "team": "AltCarbon team technology expertise engineering capabilities",
            "market": "CDR market size technology licensing carbon credit pricing scaling",
        },
        "default_sections": [
            {"name": "Executive Summary", "description": "Technology innovation, market opportunity, and competitive advantage", "word_limit": 500, "required": True, "order": 1},
            {"name": "Technology Overview", "description": "Core technology, architecture, TRL, key innovations vs state of the art", "word_limit": 700, "required": True, "order": 2},
            {"name": "Technical Development Plan", "description": "R&D roadmap, prototype → pilot → scale milestones, IP strategy", "word_limit": 700, "required": True, "order": 3},
            {"name": "Team & Technical Capacity", "description": "Engineering team, research partnerships, infrastructure access", "word_limit": 400, "required": True, "order": 4},
            {"name": "Market & Commercialization", "description": "TAM, business model, customer validation, revenue projections", "word_limit": 500, "required": True, "order": 5},
            {"name": "Budget & Milestones", "description": "R&D investment breakdown, technical milestones, go/no-go decision points", "word_limit": 400, "required": True, "order": 6},
        ],
    },
}

# Fallback for grants that don't match any theme
DEFAULT_THEME = "climatetech"


def resolve_theme(themes: List[str]) -> str:
    """Pick the best matching theme profile from a grant's detected themes."""
    if not themes:
        return DEFAULT_THEME
    for t in themes:
        t_lower = t.lower().replace(" ", "_")
        if t_lower in THEME_PROFILES:
            return t_lower
        # Fuzzy matches
        if "climate" in t_lower or "cdr" in t_lower or "carbon" in t_lower:
            return "climatetech"
        if "agri" in t_lower or "farm" in t_lower:
            return "agritech"
        if "ai" in t_lower or "machine" in t_lower or "data" in t_lower:
            return "ai_for_sciences"
        if "earth" in t_lower or "geo" in t_lower:
            return "applied_earth_sciences"
        if "social" in t_lower or "impact" in t_lower or "community" in t_lower:
            return "social_impact"
        if "deep" in t_lower or "tech" in t_lower:
            return "deeptech"
    return DEFAULT_THEME


def get_theme_profile(theme_key: str) -> Dict:
    """Get the full theme profile dict. Falls back to climatetech."""
    return THEME_PROFILES.get(theme_key, THEME_PROFILES[DEFAULT_THEME])


def get_evidence_query(theme_key: str, section_name: str) -> str:
    """Build a Pinecone search query tailored to this theme + section."""
    profile = get_theme_profile(theme_key)
    queries = profile.get("evidence_queries", {})

    name_lower = section_name.lower()
    # Match section to query category
    if any(w in name_lower for w in ["technical", "method", "approach", "innovation", "technology", "research"]):
        return queries.get("technical", queries.get("default", ""))
    if any(w in name_lower for w in ["impact", "outcome", "result", "benefit", "scalab"]):
        return queries.get("impact", queries.get("default", ""))
    if any(w in name_lower for w in ["team", "qualif", "capab", "experience", "partner"]):
        return queries.get("team", queries.get("default", ""))
    if any(w in name_lower for w in ["budget", "cost", "market", "commercial", "financial", "pricing"]):
        return queries.get("market", queries.get("default", ""))
    return queries.get("default", "")
