"""Past grants configuration — metadata for each PDF in /past_grants/.

Used by the Company Brain sync pipeline to ingest past grant applications
as style examples and section structure references for the drafter.

Each entry contains:
- filename: PDF file in past_grants/
- title: Grant title
- funder: Funding body
- scheme: Grant scheme/program
- year: Submission year
- pi: Principal investigator
- themes: AltCarbon theme keys this grant is relevant to
- sections_learned: Key sections to extract as writing examples
- notes: Why this grant is valuable for the drafter
"""
from __future__ import annotations

from typing import Dict, List

PAST_GRANTS: List[Dict] = [
    {
        "filename": "672026001350_v1_710960 (1).pdf",
        "title": "ATRI Centre on Carbon Cycle Research",
        "funder": "ANRF (Anusandhan National Research Foundation)",
        "scheme": "ANRF Translational Research and Innovation (ATRI)",
        "year": 2026,
        "pi": "Dr. Sambuddha Misra",
        "institution": "IISc Bangalore",
        "themes": ["climatetech", "applied_earth_sciences", "ai_for_sciences"],
        "notes": (
            "Most recent proposal. Directly relevant — covers ERW MRV, "
            "laser ablation isotope measurements, soil carbon, ML for deployment "
            "optimization. Multi-PI consortium. TRL 4→7 framing. "
            "60-month duration, ₹33 Cr budget."
        ),
    },
    {
        "filename": "Misra_SJF 2020 Proposal (3).pdf",
        "title": "Role of CO2 in Amplifying Glacial-Interglacial Climate Cycles",
        "funder": "DST (Department of Science & Technology)",
        "scheme": "Swarnajayanti Fellowship",
        "year": 2020,
        "pi": "Dr. Sambuddha Misra",
        "institution": "IISc Bangalore",
        "themes": ["applied_earth_sciences", "climatetech"],
        "notes": (
            "Prestigious fellowship application. Excellent writing style — "
            "clear narrative arc, strong figures integration, detailed methodology. "
            "Earth sciences focus: boron isotope paleoclimate, CO2 reconstruction."
        ),
    },
    {
        "filename": "Sambuddha Misra_Summary (3).pdf",
        "title": "Role of CO2 in Amplifying Glacial-Interglacial Climate Cycles (Summary)",
        "funder": "DST",
        "scheme": "Swarnajayanti Fellowship (Summary)",
        "year": 2020,
        "pi": "Dr. Sambuddha Misra",
        "institution": "IISc Bangalore",
        "themes": ["applied_earth_sciences", "climatetech"],
        "notes": (
            "2-page summary version of the SJF proposal. Perfect example of "
            "concise executive summary writing for earth sciences grants."
        ),
    },
    {
        "filename": "Misra 2015 Proposal V07 (3).pdf",
        "title": "Reconstruction of Atmospheric CO2 Concentration Beyond Ice-Cores",
        "funder": "Cambridge / NERC",
        "scheme": "Research Fellowship",
        "year": 2015,
        "pi": "Dr. Sambuddha Misra",
        "institution": "University of Cambridge",
        "themes": ["applied_earth_sciences", "climatetech"],
        "notes": (
            "Compact 3-page proposal from Cambridge era. Excellent structure: "
            "Summary → Rationale → Objectives → Methodology → Research Plan → Deliverables. "
            "Good model for short-form grant applications."
        ),
    },
    {
        "filename": "182022008358_v1_382987 (3).pdf",
        "title": "Magnesium Isotope History of Cenozoic Seawater",
        "funder": "SERB (Science & Engineering Research Board)",
        "scheme": "Core Research Grant",
        "year": 2022,
        "pi": "Dr. Sambuddha Misra",
        "institution": "IISc Bangalore",
        "themes": ["applied_earth_sciences"],
        "notes": (
            "SERB CRG format — standard Indian research grant structure. "
            "28 pages with detailed methodology, budget, and timeline. "
            "Useful for learning SERB proposal conventions."
        ),
    },
    {
        "filename": "432021000314_v1_323513 (5).pdf",
        "title": "A Lead Laden Legacy of Indian Waterbodies: Quantification and Alleviation",
        "funder": "SERB",
        "scheme": "SUPRA (Scientific and Useful Profound Research Advancement)",
        "year": 2021,
        "pi": "Dr. Sambuddha Misra",
        "institution": "IISc Bangalore",
        "themes": ["applied_earth_sciences", "social_impact"],
        "notes": (
            "Multi-PI SUPRA proposal. 47 pages. Covers environmental remediation, "
            "bioremediation, Pb isotope fingerprinting. Good example of "
            "large-scale interdisciplinary proposal with social impact framing."
        ),
    },
]

# Quick lookup by filename
PAST_GRANTS_BY_FILE = {g["filename"]: g for g in PAST_GRANTS}
