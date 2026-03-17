# AltCarbon Grants Engine — System Architecture

## Overview

AI-powered grant discovery, scoring, drafting, and review engine. 5 AI agents orchestrated via LangGraph, backed by MongoDB, synced to Notion, deployed on Railway.

**Stack**: FastAPI + LangGraph (Python) | Next.js (TypeScript) | MongoDB | Pinecone

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (Next.js)                                │
│                                                                             │
│  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Dashboard │ │ Pipeline │ │ Drafter  │ │Reviewers │ │ Mission Control  │ │
│  │ KPIs      │ │ Kanban   │ │ Chat +   │ │ Funder + │ │ Agent health     │ │
│  │ Activity  │ │ Table    │ │ Sections │ │ Science  │ │ Run history      │ │
│  │ Warnings  │ │ Detail   │ │ Settings │ │ Settings │ │ Error timeline   │ │
│  └─────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
│        │             │            │             │                │           │
│  ──────┴─────────────┴────────────┴─────────────┴────────────────┴────────── │
│                          /api/* proxy routes (20+)                           │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ HTTP
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                        BACKEND (FastAPI — 50+ endpoints)                    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     LangGraph Pipeline                              │    │
│  │                                                                     │    │
│  │  ┌───────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐            │    │
│  │  │ Scout │──▶│ Analyst  │──▶│Pre-Triage│──▶│ Human   │            │    │
│  │  │       │   │          │   │Guardrail │   │ Triage  │            │    │
│  │  └───────┘   └──────────┘   └──────────┘   └────┬────┘            │    │
│  │                                                   │                │    │
│  │                                          pursue ──┤── pass         │    │
│  │                                                   ▼                │    │
│  │  ┌──────────────┐   ┌──────────┐   ┌──────────┐  ┌───────────┐   │    │
│  │  │Company Brain │──▶│  Grant   │──▶│ Drafter  │──▶│ Reviewer  │   │    │
│  │  │(knowledge)   │   │  Reader  │   │(sections)│   │(QA check) │   │    │
│  │  └──────────────┘   └──────────┘   └──────────┘  └─────┬─────┘   │    │
│  │                                                         │         │    │
│  │                                                         ▼         │    │
│  │                                                    ┌──────────┐   │    │
│  │                                                    │ Exporter │   │    │
│  │                                                    │(markdown)│   │    │
│  │                                                    └──────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────┐   │
│  │  Dual Reviewer    │  │ Feedback Learner  │  │  Eval Framework       │   │
│  │  (standalone)     │  │ (outcome → lessons)│  │  (LLM-as-Judge)      │   │
│  │  Funder + Science │  │  grant_outcomes   │  │  scores.jsonl         │   │
│  └───────────────────┘  └───────────────────┘  └───────────────────────┘   │
│                                                                             │
└──────────────┬──────────────────┬──────────────────┬───────────────────────┘
               │                  │                  │
    ┌──────────▼────────┐ ┌──────▼───────┐ ┌────────▼────────┐
    │     MongoDB       │ │   Pinecone   │ │    Notion       │
    │  14 collections   │ │  Vector DB   │ │  Bi-directional │
    │  grants, drafts,  │ │  Knowledge   │ │  sync (MCP +    │
    │  reviews, config  │ │  retrieval   │ │  REST API)      │
    └───────────────────┘ └──────────────┘ └─────────────────┘
```

---

## The 5 AI Agents

### 1. Scout — Discovery

```
Input:  Search queries (Tavily, Exa, Perplexity, direct crawl)
Output: grants_raw collection (deduplicated, enriched)
```

| Property | Detail |
|----------|--------|
| **Job** | Find every relevant grant opportunity before competitors |
| **Sources** | Tavily (keyword), Exa (semantic), Perplexity (deep research), 40+ direct URLs |
| **Dedup** | URL hash + content hash (catches reposted grants) |
| **Output** | title, funder, deadline, funding, eligibility, geography, themes |
| **Runtime** | 7-minute max, parallelized across all sources |
| **Identity** | `backend/agents/scout/skills.md` |
| **Config** | Custom queries, source toggles via agent_config |

### 2. Analyst — Scoring & Triage

```
Input:  grants_raw (unprocessed)
Output: grants_scored (6-dimension scores, recommended action)
```

| Property | Detail |
|----------|--------|
| **Job** | Score every grant and decide: pursue / watch / auto-pass |
| **Scoring** | 6 weighted dimensions (theme 25%, funding 20%, eligibility 20%, geography 15%, competition 10%, deadline 10%) |
| **Deep Analysis** | Fetches grant page, extracts eval criteria, eligibility checklist, past winners |
| **Hard Rules** | Auto-reject: <$3K funding, expired deadline |
| **Funder Context** | Perplexity deep research on funder priorities |
| **Identity** | `backend/agents/analyst/skills.md` |
| **Benchmark** | 25 labeled fixtures in `backend/benchmarks/` |

### 3. Drafter — Proposal Writing

```
Input:  Pursued grant + company knowledge + grant document
Output: Section-by-section draft in grant_drafts
```

| Property | Detail |
|----------|--------|
| **Job** | Write compelling, evidence-based grant proposals |
| **Theme Agents** | 6 specialized profiles (Climate Tech, AgriTech, AI, Earth Sciences, Social Impact, Deep Tech) |
| **Knowledge** | Section-specific RAG from Pinecone + Company Brain + past applications |
| **Grant Context** | Multi-page fetch: Tavily → Exa → Jina → Playwright → deep_analysis fallback |
| **Writing Styles** | Professional (corporate) or Scientific (academic) |
| **Feedback Learning** | Injects past grant outcomes ("Frontier rejected because MRV was vague") |
| **Settings** | `/drafter/settings` — tone, voice, temperature, custom instructions per theme |
| **Identity** | `backend/agents/drafter/skills.md` |

### 4. Dual Reviewer — Quality Assurance

```
Input:  Completed draft + grant context
Output: Funder + Scientific reviews in draft_reviews
```

| Property | Detail |
|----------|--------|
| **Job** | Review drafts from two independent perspectives before submission |
| **Funder Reviewer** | "Would I fund this?" — alignment, budget, competitiveness, compliance |
| **Scientific Reviewer** | "Is the science solid?" — methodology, MRV, data quality, novelty |
| **Strictness** | Configurable: lenient / balanced / strict |
| **Execution** | Both run in parallel (asyncio.gather) |
| **Settings** | `/reviewers/settings` — strictness, focus areas, custom criteria per perspective |
| **Identity** | `backend/agents/reviewer_agents/skills.md` |

### 5. Company Brain — Knowledge Retrieval

```
Input:  Query from any agent (drafter, analyst)
Output: Company context, style examples, factual data
```

| Property | Detail |
|----------|--------|
| **Job** | Provide accurate, up-to-date AltCarbon information to all agents |
| **Sources** | Notion MCP (live) → Static profile (fallback) → Pinecone (semantic) |
| **Key Data** | Founders, HQ, buyers, CDR pathways, field operations, 9 indexed Notion pages |
| **Identity** | `backend/agents/company_brain_agent/skills.md` |

---

## Data Flow — Grant Lifecycle

```
                    DISCOVERY                          SCORING
                    ────────                           ───────
   Tavily ──┐                                    ┌── 6-dimension scoring
   Exa    ──┼──▶ Scout ──▶ grants_raw ──▶ Analyst ──▶ grants_scored
   Perpl. ──┤      │          (dedup)        │           │
   Direct ──┘      │                         │           ├── pursue (6.5+)
                   │                         │           ├── watch (5.0-6.5)
                   │                    Deep Analysis    └── auto_pass (<5.0)
                   │                    Past Winners
                   │                    Funder Context
                   │
                   ▼
              Notion Sync ──▶ Grant Pipeline DB (Notion)


                    TRIAGE                           DRAFTING
                    ──────                           ────────
   grants_scored ──▶ Pre-Triage ──▶ Human ──▶ Grant Reader ──▶ Company Brain
        │            Guardrail      Triage       │                  │
        │                             │          │                  │
        │                        pursue/pass     ▼                  ▼
        │                             │     Parse RFP        Pinecone RAG
        │                             │     (Tavily→Exa      Style examples
        │                             │      →Jina→PW→       Static profile
        │                             │      deep_analysis)
        │                             │          │
        │                             ▼          ▼
        │                        Drafter Node ◀── Past Outcomes (feedback learning)
        │                             │
        │                    ┌────────┤────────┐
        │                    ▼        ▼        ▼
        │               Section 1  Section 2  Section N
        │               (theme-aware, RAG-grounded)
        │                    │
        │                    ▼
        │              Human Review (approve / revise)
        │                    │
        │                    ▼
        │               Reviewer ──▶ Exporter ──▶ grant_drafts


                    REVIEW                          FEEDBACK
                    ──────                          ────────
   grant_drafts ──▶ Dual Reviewer               grant_outcomes
        │           (parallel)                        │
        │              │                              │
        │     ┌────────┴────────┐              Record Outcome
        │     ▼                 ▼              (won/rejected)
        │  Funder            Scientific              │
        │  Perspective       Perspective              ▼
        │  (alignment,       (methodology,       LLM extracts
        │   budget,          MRV, data,          lessons
        │   compete)         novelty)                 │
        │     │                 │                     ▼
        │     └────────┬────────┘              feedback_learner
        │              ▼                       get_lessons_for_grant()
        │        draft_reviews                        │
        │                                             ▼
        │                                    Injected into next draft:
        │                                    "Last time with Frontier,
        │                                     they rejected because..."
```

---

## Database Schema (MongoDB — 14 Collections)

| Collection | Purpose | Key Indexes |
|------------|---------|-------------|
| `grants_raw` | Discovered grants (pre-scoring) | url_hash (unique), scraped_at, processed |
| `grants_scored` | Scored grants (source of truth for UI) | weighted_total desc, status, funder+title |
| `grants_pipeline` | Draft pipeline records | grant_id, thread_id (unique), status |
| `grant_drafts` | Versioned draft sections | grant_id, pipeline_id + version desc |
| `draft_reviews` | Funder + scientific reviews | grant_id + perspective |
| `grant_outcomes` | Won/rejected + funder feedback | grant_id (unique), funder, themes |
| `knowledge_chunks` | Vectorized company knowledge | source_id, doc_type, themes |
| `agent_config` | Per-agent settings (drafter, reviewer) | agent (unique) |
| `audit_logs` | All agent run events | created_at desc, node |
| `scout_runs` | Scout run statistics | run_at desc |
| `graph_checkpoints` | LangGraph state persistence | thread_id + checkpoint_id |
| `funder_context_cache` | Perplexity results (7-day TTL) | funder (unique) |
| `drafter_chat_history` | Per-user chat sessions | pipeline_id + user_email |
| `notifications` | User notifications (30-day TTL) | user_email + read + created_at |

---

## Agent Identity System (CLAUDE.md-style)

```
backend/agents/
├── agent_context.py              ← Loader + heartbeat updater
├── scout/
│   ├── skills.md                 ← WHO: Discovery agent
│   └── heartbeat.md              ← Auto: last run, grants found, errors
├── analyst/
│   └── skills.md                 ← WHO: Scoring agent, 6 dimensions
├── drafter/
│   ├── skills.md                 ← WHO: Proposal writer, 6 themes
│   ├── heartbeat.md              ← Auto: sections written, themes used
│   ├── drafter_node.py           ← LangGraph node
│   ├── section_writer.py         ← Core writing logic
│   ├── grant_reader.py           ← Multi-page RFP fetching
│   ├── theme_profiles.py         ← 6 theme configurations
│   ├── exporter.py               ← Markdown assembly
│   └── draft_guardrail.py        ← Pre-draft validation
├── reviewer_agents/
│   └── skills.md                 ← WHO: Dual reviewer (funder + scientific)
└── company_brain_agent/
    └── skills.md                 ← WHO: Knowledge retrieval
```

**skills.md** (static, human-edited):
- Identity, Capabilities, Instructions, Success Criteria, Constraints

**heartbeat.md** (auto-updated after each run):
- Last run time, status, metrics, recent history, errors
- Persisted to MongoDB for cross-instance consistency

---

## Evaluation & Benchmarking

### Analyst Benchmark (`backend/benchmarks/`)
```
25 labeled fixtures → _score_grant() → accuracy report
├── 5 PURSUE   (expected 6.5+)
├── 5 WATCH    (expected 5.0-6.5)
├── 5 AUTO_PASS (LLM scoring)
├── 5 AUTO_PASS (hard rules)
└── 5 EDGE CASES
+ 12 hard-rule unit tests (no LLM needed)
+ Calibration check (pursue avg > watch avg > auto_pass avg)
+ Field completeness (35 required fields)
```

### LLM-as-Judge Framework (`backend/evals/`)
```
Agent output → Judge LLM (Opus, temp=0.1) → structured scores → scores.jsonl

┌──────────────┬────────────────────────────────────────────────────┐
│ Scout Judge  │ Relevance, Eligibility, Data Quality, Timeliness, │
│              │ Strategic Value                                    │
├──────────────┼────────────────────────────────────────────────────┤
│ Drafter Judge│ Funder Alignment, Evidence Quality, Technical     │
│              │ Credibility, Clarity, Compliance, Differentiation │
├──────────────┼────────────────────────────────────────────────────┤
│ Reviewer     │ Specificity, Accuracy, Completeness,              │
│ Meta-Judge   │ Actionability, Calibration                        │
├──────────────┼────────────────────────────────────────────────────┤
│ Outcome Judge│ Score Accuracy, Review Accuracy, Verdict Accuracy,│
│              │ Feedback Coverage (uses REAL outcomes as ground    │
│              │ truth)                                             │
└──────────────┴────────────────────────────────────────────────────┘
```

### Improvement Loop
```
1. Edit agent prompt / settings
2. Tag: --prompt-version v1.1
3. Run:  python -m backend.evals.run_evals --agent drafter --prompt-version v1.1
4. Compare: python -m backend.evals.run_evals --compare v1.0 v1.1
5. Report: python -m backend.evals.run_evals --report
```

---

## External Services

| Service | Used By | Purpose |
|---------|---------|---------|
| **Claude (Opus/Sonnet)** | All agents | Primary LLM via AI Gateway |
| **GPT-5.4** | Scout, Drafter | Secondary LLM |
| **Pinecone** | Company Brain, Drafter | Vector search for knowledge retrieval |
| **Tavily** | Scout, Grant Reader | Keyword search + URL content extraction |
| **Exa** | Scout, Grant Reader | Semantic search + content fetching |
| **Perplexity** | Scout, Analyst | Deep research (funder context) |
| **Jina Reader** | Grant Reader | PDF + static HTML extraction |
| **Playwright** | Grant Reader | Last-resort JS rendering |
| **Notion** | All (sync) | Bi-directional: pipeline, runs, errors, drafts, knowledge |
| **MongoDB** | All | Primary data store (14 collections) |
| **Railway** | Deployment | Docker containers (backend + frontend) |

### LLM Routing & Fallback
```
Primary model → credit exhaustion (429/402)?
  → Next in fallback chain → exhausted?
    → Next → all exhausted?
      → Log to Notion Mission Control (Critical)
      → Raise RuntimeError

Chains:
  Opus → GPT-5.4 → Sonnet
  GPT-5.4 → Opus → Sonnet
```

---

## Frontend Pages

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/dashboard` | KPIs, activity chart, warnings, all grants table |
| Pipeline | `/pipeline` | Kanban board + table view, grant detail sheet |
| Drafter | `/drafter` | Section-by-section draft editor |
| Drafter Settings | `/drafter/settings` | Writing style, themes, custom instructions |
| Reviewers | `/reviewers` | Side-by-side funder vs scientific reviews |
| Reviewer Settings | `/reviewers/settings` | Strictness, focus areas, custom criteria |
| Mission Control | `/monitoring` | Agent health, run history, error timeline |
| Knowledge | `/knowledge` | Sync status, chunk counts, sources |
| Login | `/login` | Google OAuth (NextAuth) |

---

## Configuration

### Drafter Settings (stored in `agent_config.drafter`)
```json
{
  "writing_style": "professional | scientific",
  "temperature": 0.4,
  "custom_instructions": "Always mention IISc partnership...",
  "theme_settings": {
    "climatetech": {
      "tone": "Lead with scientific rigor...",
      "voice": "Authoritative scientist-practitioner",
      "temperature": 0.35,
      "strengths": ["Plot-level MRV", "Frontier/Stripe buyers", ...],
      "domain_terms": ["CDR", "ERW", "biochar", "MRV", ...],
      "custom_instructions": "For climate grants, emphasize..."
    }
  }
}
```

### Reviewer Settings (stored in `agent_config.reviewer`)
```json
{
  "funder": {
    "strictness": "balanced",
    "temperature": 0.3,
    "focus_areas": ["Budget justification", "Competitiveness", ...],
    "custom_criteria": ["Does it address data sovereignty?"],
    "custom_instructions": "Compare against Frontier purchase criteria"
  },
  "scientific": {
    "strictness": "strict",
    "temperature": 0.25,
    "focus_areas": ["Methodology", "MRV rigor", ...],
    "custom_instructions": "Pay attention to permanence claims"
  }
}
```

---

## Deployment (Railway)

```dockerfile
FROM python:3.11-slim
# Node.js 20 (for Notion MCP)
# Playwright + Chromium (for JS-heavy page fetching)
# pip install -r requirements.txt
# uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Frontend: Next.js standalone build, deployed as separate Railway service.
