"""Judge prompt templates for each agent in the Grants Engine.

Each judge evaluates a specific agent's output on multiple dimensions,
returning structured JSON scores + reasoning.
"""

# ── Scout / Scraper Judge ─────────────────────────────────────────────────────

SCOUT_JUDGE_PROMPT = """You are evaluating a grant scraper agent's output for AltCarbon,
a climate tech / CDR company that does enhanced rock weathering and biochar.

The scraper found this grant opportunity:

GRANT TITLE: {title}
FUNDER: {funder}
URL: {url}
GEOGRAPHY: {geography}
FUNDING: {funding}
DEADLINE: {deadline}
ELIGIBILITY: {eligibility}
THEMES DETECTED: {themes}
RAW CONTENT (first 2000 chars):
{raw_content}

Score this scraped opportunity on each dimension (1-5 scale):

1. **Relevance** — Is this actually a grant opportunity AltCarbon could apply for? (vs. news article, expired, unrelated program)
2. **Eligibility Fit** — Does AltCarbon meet the stated eligibility criteria? (CDR company, India-based, startup stage)
3. **Data Quality** — Is the extracted data complete and accurate? (title, funder, deadline, funding amount all present and correct)
4. **Timeliness** — Is the deadline still open? Is this a current opportunity?
5. **Strategic Value** — How valuable is this opportunity for AltCarbon specifically? (funding size, funder prestige, theme alignment)

Respond ONLY with valid JSON:
{{
  "scores": {{
    "relevance": <int 1-5>,
    "eligibility_fit": <int 1-5>,
    "data_quality": <int 1-5>,
    "timeliness": <int 1-5>,
    "strategic_value": <int 1-5>
  }},
  "overall": <float 1-5>,
  "reasoning": "<1-2 sentence explanation>",
  "top_issue": "<biggest problem with this scraped result, or 'None' if clean>"
}}"""


# ── Drafter Judge ─────────────────────────────────────────────────────────────

DRAFTER_JUDGE_PROMPT = """You are a senior grant writing evaluator assessing a draft proposal
written by an AI drafter for AltCarbon, a climate tech company.

GRANT: {grant_title}
FUNDER: {funder}
THEMES: {themes}

EVALUATION CRITERIA (from the funder):
{criteria}

DRAFT SECTION: {section_name}
WORD LIMIT: {word_limit}
ACTUAL WORD COUNT: {word_count}

SECTION CONTENT:
{content}

Score this draft section on each dimension (1-5 scale):

1. **Funder Alignment** — Does it directly address what this funder values? Are evaluation criteria targeted?
2. **Evidence Quality** — Are claims backed by specific data, not vague assertions? Are [EVIDENCE NEEDED] gaps reasonable?
3. **Technical Credibility** — Is the science/methodology sound and specific? Would a domain expert find this convincing?
4. **Clarity & Structure** — Is it well-organized, concise, and jargon-appropriate for the audience?
5. **Compliance** — Does it stay within word limits? Follow the section description?
6. **Differentiation** — Does it make AltCarbon stand out? Or is it generic boilerplate?

Respond ONLY with valid JSON:
{{
  "scores": {{
    "funder_alignment": <int 1-5>,
    "evidence_quality": <int 1-5>,
    "technical_credibility": <int 1-5>,
    "clarity_structure": <int 1-5>,
    "compliance": <int 1-5>,
    "differentiation": <int 1-5>
  }},
  "overall": <float 1-5>,
  "reasoning": "<2-3 sentence assessment>",
  "top_weakness": "<single biggest weakness to fix>",
  "top_strength": "<single biggest strength>"
}}"""


# ── Reviewer Meta-Judge ───────────────────────────────────────────────────────

REVIEWER_JUDGE_PROMPT = """You are evaluating whether a grant reviewer agent's feedback is useful
and actionable. The reviewer was asked to critique a draft proposal.

GRANT: {grant_title}
FUNDER: {funder}
REVIEWER PERSPECTIVE: {perspective}

DRAFT (what was reviewed):
{draft_excerpt}

REVIEWER'S OUTPUT:
Overall Score: {reviewer_score}
Verdict: {verdict}
Summary: {summary}
Top Issues: {top_issues}
Strengths: {strengths}

Score the REVIEWER'S feedback quality on each dimension (1-5 scale):

1. **Specificity** — Are issues concrete and actionable? Or vague like "could be better"?
2. **Accuracy** — Are the flagged issues real problems? Or false positives?
3. **Completeness** — Did the reviewer catch the actual weaknesses? Any blind spots?
4. **Actionability** — Could someone improve the draft based on this feedback alone?
5. **Calibration** — Is the overall score appropriate? Too harsh? Too generous?

Respond ONLY with valid JSON:
{{
  "scores": {{
    "specificity": <int 1-5>,
    "accuracy": <int 1-5>,
    "completeness": <int 1-5>,
    "actionability": <int 1-5>,
    "calibration": <int 1-5>
  }},
  "overall": <float 1-5>,
  "reasoning": "<2-3 sentence assessment of the reviewer's quality>",
  "missed_issues": ["<issue the reviewer should have caught but didn't>"],
  "false_positives": ["<issue the reviewer flagged that isn't really a problem>"]
}}"""


# ── Outcome Prediction Judge ──────────────────────────────────────────────────
# Uses real grant outcomes to evaluate if the system would have predicted correctly

OUTCOME_JUDGE_PROMPT = """You are evaluating a grant intelligence system's prediction accuracy.

GRANT: {grant_title}
FUNDER: {funder}
ANALYST SCORE: {analyst_score}/10
INTERNAL FUNDER REVIEW SCORE: {funder_review_score}/10
INTERNAL SCIENTIFIC REVIEW SCORE: {scientific_review_score}/10
SYSTEM VERDICT: {system_verdict}

ACTUAL OUTCOME: {actual_outcome}
FUNDER FEEDBACK: {funder_feedback}

Evaluate the system's prediction:
1. **Score Accuracy** — Did the analyst score correctly predict the outcome? (high score + won = good, high score + rejected = bad)
2. **Review Accuracy** — Did the internal reviewers identify the actual issues the funder flagged?
3. **Verdict Accuracy** — Was the system's submit/revise verdict appropriate given the actual outcome?
4. **Feedback Coverage** — What percentage of the funder's actual feedback was predicted by the system's reviews?

Respond ONLY with valid JSON:
{{
  "scores": {{
    "score_accuracy": <int 1-5>,
    "review_accuracy": <int 1-5>,
    "verdict_accuracy": <int 1-5>,
    "feedback_coverage": <int 1-5>
  }},
  "overall": <float 1-5>,
  "reasoning": "<what the system got right and wrong>",
  "blind_spots": ["<issues the funder raised that the system completely missed>"],
  "correctly_predicted": ["<issues the system flagged that the funder confirmed>"]
}}"""
