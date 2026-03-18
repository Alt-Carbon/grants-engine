# Agent Improvement Plan — Better Grant Applications

## Executive Summary

Your pipeline is already production-grade: Scout→Analyst→Guardrail→CompanyBrain→GrantReader→Drafter→Reviewer→Exporter. The biggest wins come from **closing feedback loops**, **adding self-critique before human review**, and **deepening funder intelligence**. Below are improvements ordered by impact.

---

## 1. DRAFTER — Highest Impact Improvements

### 1.1 Add Self-Critique Loop (Before Human Review)
**Problem**: Each section gets a single LLM call. The human reviewer catches issues that the LLM could have caught itself.

**Fix**: After writing each section, run a lightweight self-critique pass:
```python
# In section_writer.py, after initial write_section():
SELF_CRITIQUE_PROMPT = """Review this grant section you just wrote.

SECTION: {section_name}
CONTENT: {content}
EVALUATION CRITERIA: {criteria}
WORD LIMIT: {word_limit}

Score yourself on:
1. Does every paragraph directly address an evaluation criterion? (1-5)
2. Are all claims grounded in provided evidence? (1-5)
3. Is the word count within limit? (pass/fail)
4. Would a skeptical reviewer find unsupported assertions? (list them)
5. Is there a clear "so what" in every paragraph?

If any score < 4, rewrite the section addressing your own critique.
If all scores >= 4, return the section as-is.

Return JSON: {"needs_rewrite": bool, "critique": "...", "rewritten": "..." or null}"""
```
**Expected impact**: 30-40% fewer human revision cycles.

### 1.2 Auto-Resolve Evidence Gaps
**Problem**: `[EVIDENCE NEEDED: ...]` flags are surfaced but never automatically searched. The human has to fill them.

**Fix**: After section writing, parse evidence gaps and attempt Pinecone/Notion search:
```python
async def resolve_evidence_gaps(content: str, grant_themes: list) -> str:
    gaps = re.findall(r"\[EVIDENCE NEEDED: ([^\]]+)\]", content)
    for gap_desc in gaps:
        # Search Pinecone with the gap description as query
        results = search_similar(gap_desc, top_k=3, filter_dict={"themes": {"$in": grant_themes}})
        if results:
            best = results[0]
            evidence = best.get("content", "")[:500]
            # Replace the gap flag with found evidence + source attribution
            content = content.replace(
                f"[EVIDENCE NEEDED: {gap_desc}]",
                f"{evidence} [Source: {best.get('source_title', 'company knowledge')}]"
            )
        # If not found, keep the flag — human still needs to fill it
    return content
```

### 1.3 Evaluation Criteria Mapping (Pre-Writing Step)
**Problem**: The drafter writes sections generically, then hopes they address criteria. Funders score against specific rubrics.

**Fix**: Before writing any section, generate an explicit criteria→evidence→section map:
```
CRITERIA MAP:
- "Scientific rigor" (30% weight) → Evidence: ERW field trials, soil sampling data, peer-reviewed MRV → Sections: Technical Approach, Impact
- "Team capability" (20% weight) → Evidence: IISc affiliation, Frontier/Stripe buyers, Agarwal family legacy → Sections: Team, Why Best Suited
- "Scalability" (15% weight) → Evidence: Gigaton scale doc, Bengal expansion, multi-geography ops → Sections: Impact, Project Plan
```
Each section writer then gets its assigned criteria + evidence, ensuring complete coverage.

### 1.4 Funder Language Mirroring
**Problem**: The drafter uses AltCarbon's internal terminology. Funders often use different terms for the same concepts.

**Fix**: In `grant_reader.py`, extract the funder's key terms and phrases from the RFP. Pass these to the section writer:
```python
FUNDER_LANGUAGE_PROMPT = """Extract 15-20 key terms and phrases this funder uses repeatedly.
Focus on: what they call the problem, the solution type, impact metrics, and evaluation language.
Example: If the funder says "nature-based solutions" don't write "natural climate solutions".
"""
```
Add to `WRITE_PROMPT`: `FUNDER'S LANGUAGE (mirror these terms): {funder_terms}`

### 1.5 Competitive Differentiation Block
**Problem**: Drafts describe what AltCarbon does but don't argue why AltCarbon is better than alternatives.

**Fix**: Add a differentiation prompt component:
```
WHY ALTCARBON (weave these differentiators into your writing):
- Only CDR company combining ERW + Biochar (dual pathway)
- 4th-generation tea planters = trust with farmers (competitors lack this)
- Buyers include Frontier, Stripe, Shopify (market validation)
- IISc campus = academic rigor + startup speed
- Operating in India = lower cost per ton + massive scalability
```

---

## 2. REVIEWER — Close the Feedback Loop

### 2.1 Automated Revision Trigger
**Problem**: Reviewer scores sections, but revisions require a human to trigger `/resume/section-review` with "revise". For clear issues (score < 6), the system should auto-revise.

**Fix**: Add a `reviewer_to_drafter` feedback path in the LangGraph:
```python
def review_routing(state):
    review = state.get("review_result", {})
    min_score = min(s.get("score", 10) for s in review.get("section_scores", [{}]))

    if min_score < 6 and state.get("revision_count", 0) < 2:
        return "auto_revise"  # Send back to drafter with reviewer feedback
    elif review.get("verdict") in ("major_revisions", "reconsider"):
        return "human_review"  # Needs human decision
    else:
        return "export"  # Good enough to export
```
**Expected impact**: Faster turnaround — obvious issues fixed without human involvement.

### 2.2 Red-Team Reviewer (3rd Perspective)
**Problem**: Funder + Scientific reviewers look for quality. Nobody looks for weaknesses a competitor would exploit.

**Fix**: Add a "Red Team" reviewer perspective:
```
You are a competing applicant reading this proposal. Find every weakness:
- Where are the claims weakest?
- What would you say in YOUR application to make this one look bad?
- What objections would a skeptical panel member raise?
- Where does the proposal assume the reader already agrees?
```

### 2.3 Holistic Coherence Review
**Problem**: Reviewer scores sections individually but doesn't check cross-section coherence (e.g., budget matches project plan, impact claims match methodology).

**Fix**: After section-level review, add a holistic pass:
```
Read ALL sections as a complete application. Check:
1. Does the budget justify the activities in the Project Plan?
2. Do impact claims in Outcomes match the methodology in Technical Approach?
3. Is the narrative thread consistent from Problem Statement to Impact?
4. Are there contradictions between sections?
5. Is there unnecessary repetition?
```

---

## 3. ANALYST — Smarter Scoring

### 3.1 Calibrate Scores Against Real Outcomes
**Problem**: Thresholds (6.5 pursue, 5.0 watch) are arbitrary. You don't know if they predict actual success.

**Fix**: Add a calibration endpoint:
```python
async def calibrate_scoring():
    """Compare analyst scores against actual outcomes to tune thresholds."""
    outcomes = await grant_outcomes().find({}).to_list(100)

    won = [o for o in outcomes if o["outcome"] == "won"]
    rejected = [o for o in outcomes if o["outcome"] == "rejected"]

    avg_score_won = mean([o["weighted_score"] for o in won])
    avg_score_rejected = mean([o["weighted_score"] for o in rejected])

    # Which dimensions best predict winning?
    for dim in ["theme", "funding", "eligibility", "geography", "competition", "deadline"]:
        won_avg = mean([o.get(f"{dim}_score", 0) for o in won])
        rej_avg = mean([o.get(f"{dim}_score", 0) for o in rejected])
        # Dimensions with biggest gap between won/rejected are most predictive
```
Run this monthly. Adjust weights based on what actually predicts success.

### 3.2 Funder Relationship Score
**Problem**: A grant from Frontier (who already buys AltCarbon credits) scores the same as one from a brand-new funder.

**Fix**: Add a 7th scoring dimension — Funder Relationship:
```python
# Check if funder is in AltCarbon's buyer/partner list
known_funders = ["Frontier", "Google", "Stripe", "Shopify", "UBS", "BCG", "Mitsubishi"]
if any(f.lower() in funder.lower() for f in known_funders):
    relationship_score = 9  # Existing relationship = huge advantage
elif past_outcomes_with_funder:
    relationship_score = 7  # Applied before = some familiarity
else:
    relationship_score = 5  # New funder = neutral
```

### 3.3 Past Winners Analysis
**Problem**: Competition scoring is a guess. The analyst doesn't look at what types of orgs actually win.

**Fix**: When Perplexity deep research is used for high-scoring grants, add:
```
Also research: Who won this grant in previous rounds? What type of organizations?
What was the average grant size awarded? How many applications per cycle?
Does AltCarbon's profile (Indian startup, CDR, dual-pathway) match past winners?
```

---

## 4. SCOUT — Better Discovery

### 4.1 Funder Memory & Cycle Tracking
**Problem**: Scout searches generically every run. It doesn't remember that e.g., "XPRIZE Carbon" opens every Q1.

**Fix**: Add a `funder_cycles` collection:
```python
# After each scout run, record which funders had open grants
# Over time, build a cycle calendar:
{
    "funder": "XPRIZE",
    "grant_pattern": "Carbon Removal Prize",
    "typical_open_month": 1,  # January
    "typical_close_month": 4,  # April
    "last_seen": "2026-01-15",
    "frequency": "annual",
    "avg_award": 1000000,
}
# Scout can then proactively check known funder websites near cycle time
```

### 4.2 Outcome-Informed Search Queries
**Problem**: Scout uses generic CDR/biochar/ERW queries. It doesn't know which grant types AltCarbon actually wins.

**Fix**: Feed winning grant metadata back into search strategy:
```python
# If AltCarbon wins "agricultural innovation" grants more than "pure climate" grants,
# boost agritech search queries
won_themes = get_winning_themes()  # from grant_outcomes
query_weights = {theme: count/total for theme, count in won_themes.items()}
# Allocate more search budget to high-win-rate themes
```

### 4.3 Direct Funder Website Monitoring
**Problem**: Scout relies on search APIs which have delays. Major funders update their sites directly.

**Fix**: Maintain a list of 20-30 priority funder URLs. On each scout run, crawl them directly:
```python
PRIORITY_FUNDERS = [
    "https://frontierclimate.com/opportunities",
    "https://www.stripe.com/climate",
    "https://sustainability.google/climate/",
    "https://xprize.org/prizes",
    # ... 20 more
]
```

---

## 5. COMPANY BRAIN — Richer Knowledge

### 5.1 Per-Funder Knowledge Profiles
**Problem**: Company Brain serves the same context regardless of what the funder cares about.

**Fix**: For each major funder, curate a knowledge overlay:
```python
FUNDER_KNOWLEDGE_MAP = {
    "Frontier": {
        "emphasize": ["permanence", "MRV", "cost per ton", "scalability to gigatons"],
        "de_emphasize": ["social impact", "farmer income"],  # not their primary lens
        "key_evidence": ["Shopify report", "MRV Moat doc"],
    },
    "USAID": {
        "emphasize": ["farmer livelihoods", "gender equity", "India operations"],
        "de_emphasize": ["carbon credit market", "tech buyers"],
        "key_evidence": ["DRP social impact", "Bengal Renaissance"],
    },
}
```
Company Brain uses this to prioritize which knowledge chunks to surface per grant.

### 5.2 Evidence Strength Tagging
**Problem**: All knowledge chunks are treated equally. A peer-reviewed paper is weighted the same as an internal blog post.

**Fix**: Tag knowledge by evidence strength:
```python
EVIDENCE_TIERS = {
    "tier1": "Peer-reviewed publications, third-party audits, verified buyer data",
    "tier2": "Internal reports with data, MRV measurements, financial records",
    "tier3": "Blog posts, pitch decks, strategy documents",
}
# Section writer prefers tier1 evidence for scientific sections, tier2 for budget
```

---

## 6. GOLDEN EXAMPLES — Active Learning

### 6.1 Win/Loss Tagged Examples
**Problem**: Golden examples are auto-promoted at score 8.0+, but that's internal reviewer score. Actual grant outcomes matter more.

**Fix**: Tag golden examples with real outcomes:
```python
# When a grant outcome is recorded (won/rejected):
# 1. Find the golden example for that grant
# 2. Update its tag: "won" or "rejected"
# 3. Only inject "won" examples as few-shot — never inject rejected ones
# 4. If a high-scorer (8.0+) gets rejected, demote it from golden examples
```

### 6.2 External Winning Application Analysis
**Problem**: Few-shot examples are only from AltCarbon's past applications. You're learning from yourself.

**Fix**: Collect and index publicly available winning grant applications:
- Many funders publish summaries of funded projects
- XPRIZE, Wellcome Trust, Gates Foundation publish winning proposals
- Index these in Pinecone with `doc_type: "external_winner"` and use them as style reference

---

## 7. CROSS-AGENT — System-Level Improvements

### 7.1 End-to-End Quality Metrics Dashboard
Track per grant: Scout relevance score → Analyst weighted score → Reviewer scores → Actual outcome.
This lets you identify where the pipeline drops quality.

### 7.2 Parallel Section Writing
**Problem**: Sections are written sequentially with human review between each. This can take days for a 12-section application.

**Fix**: Option to write all sections in parallel (using the outline for coherence), then do a single batch review:
```python
# Write all sections concurrently
tasks = [write_section(s, ...) for s in sections]
results = await asyncio.gather(*tasks)
# Then coherence check + batch review
```
Human reviews the complete draft once instead of section-by-section.

### 7.3 Shared Evidence Map
**Problem**: Each section independently searches Pinecone. Section 3 might find perfect evidence that Section 7 also needs but doesn't know about.

**Fix**: Before writing any sections, build a shared evidence map:
```python
async def build_evidence_map(sections, grant, company_context):
    """Pre-fetch all evidence once, assign to sections."""
    all_evidence = {}
    for section in sections:
        evidence = await get_section_context(theme, section["name"], ...)
        all_evidence[section["name"]] = evidence

    # Cross-pollinate: if evidence is relevant to multiple sections, share it
    return all_evidence
```

---

## Priority Implementation Order

| Priority | Improvement | Agent | Effort | Impact |
|----------|-----------|-------|--------|--------|
| **P0** | Self-critique loop | Drafter | 1 day | High — fewer human revisions |
| **P0** | Evaluation criteria mapping | Drafter | 1 day | High — directly addresses funder scoring |
| **P0** | Holistic coherence review | Reviewer | 0.5 day | High — catches cross-section issues |
| **P1** | Auto-resolve evidence gaps | Drafter | 1 day | Medium — fills [EVIDENCE NEEDED] automatically |
| **P1** | Funder language mirroring | Drafter | 0.5 day | Medium — better funder alignment |
| **P1** | Automated revision trigger | Reviewer | 1 day | Medium — faster iteration |
| **P1** | Competitive differentiation block | Drafter | 0.5 day | Medium — stronger proposals |
| **P2** | Score calibration | Analyst | 1 day | Medium — better grant selection |
| **P2** | Funder relationship score | Analyst | 0.5 day | Medium — prioritize warm leads |
| **P2** | Per-funder knowledge profiles | Company Brain | 1 day | Medium — targeted context |
| **P2** | Red-team reviewer | Reviewer | 0.5 day | Medium — catches blind spots |
| **P3** | Funder cycle tracking | Scout | 1 day | Low-medium — proactive discovery |
| **P3** | Parallel section writing | Drafter | 1 day | Medium — faster turnaround |
| **P3** | Win/loss tagged examples | Golden Ex. | 0.5 day | Low — needs outcome data first |
| **P3** | Evidence strength tagging | Company Brain | 1 day | Low-medium — better sourcing |
