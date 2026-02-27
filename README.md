# AltCarbon Grants Intelligence Engine

An AI-powered grant discovery, scoring, and drafting pipeline built for **AltCarbon** — a climate technology startup focused on carbon removal, MRV, agritech, AI for sciences, applied earth sciences, and social impact.

The engine continuously discovers grant opportunities from 100+ sources, scores them against AltCarbon's mission, surfaces the best ones for human review, and drafts applications section-by-section with AI assistance.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        DISCOVERY LAYER                          │
│  Tavily (keyword)  +  Exa (semantic)  +  Perplexity (live web)  │
│             +  Direct crawl of 60+ known funder pages           │
└──────────────────────────────┬──────────────────────────────────┘
                               │ raw grants (deduplicated)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SCOUT AGENT                              │
│  3-layer dedup  →  Jina content fetch  →  Haiku field extract   │
│  Quality filter  →  Upsert to grants_raw (MongoDB)              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                       ANALYST AGENT                             │
│  Hard rules  →  Perplexity funder research (cached 7 days)      │
│  Claude Sonnet 6-dimension scoring  →  Upsert to grants_scored  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   HUMAN TRIAGE      │  ← Streamlit UI
                    │  pursue / watch /   │
                    │  pass / report      │
                    └──────────┬──────────┘
                               │ pursue / watch
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      COMPANY BRAIN                              │
│  Notion + Google Drive sync  →  Vector search (embeddings)      │
│  Retrieves relevant past applications, org profile, expertise   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DRAFTER AGENT                                │
│  Grant Reader  →  Section Writer  →  Section-by-section HITL    │
│  Human reviews each section  →  Exporter (PDF/DOCX)            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     REVIEWER AGENT                              │
│  Full-draft critique  →  Revision suggestions                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Agent orchestration** | LangGraph (stateful pipeline with HITL interrupts) |
| **LLMs** | Claude Sonnet 4.6 (scoring, drafting) + Claude Haiku 4.5 (extraction) |
| **Discovery** | Tavily Search, Exa Semantic Search, Perplexity Sonar Pro |
| **Content fetch** | Jina Reader (with plain HTTP fallback) |
| **Database** | MongoDB Atlas (grants, drafts, knowledge, checkpoints) |
| **Vector search** | MongoDB Atlas Vector Search (knowledge base RAG) |
| **Knowledge sync** | Notion API + Google Drive API |
| **Backend API** | FastAPI + Uvicorn (deployed on Railway) |
| **Streamlit UI** | Streamlit (6 views, dark theme, real-time filters) |
| **Scheduling** | APScheduler (48-hour scout cadence) |

---

## Project Structure

```
grants-engine/                  # repo root
├── backend/                    # FastAPI backend + all agents
│   ├── agents/
│   │   ├── scout.py            # Discovery: Tavily + Exa + Perplexity + direct crawl
│   │   ├── analyst.py          # Scoring: 6-dimension Claude Sonnet evaluation
│   │   ├── company_brain.py    # RAG: Notion + Drive sync + vector search
│   │   ├── reviewer.py         # Full draft critique
│   │   └── drafter/
│   │       ├── drafter_node.py # LangGraph drafter node
│   │       ├── grant_reader.py # Extract grant requirements
│   │       ├── section_writer.py # Write each application section
│   │       └── exporter.py     # Export to PDF/DOCX
│   ├── graph/
│   │   ├── graph.py            # LangGraph pipeline definition
│   │   ├── state.py            # GrantState TypedDict
│   │   ├── router.py           # Conditional routing logic
│   │   └── checkpointer.py     # MongoDB-backed checkpoint store
│   ├── db/
│   │   └── mongo.py            # Motor client + collection accessors + indexes
│   ├── config/
│   │   └── settings.py         # Pydantic settings (reads from .env)
│   ├── jobs/
│   │   ├── scout_job.py        # Scheduled scout runner
│   │   ├── knowledge_job.py    # Scheduled knowledge sync
│   │   └── backfill_job.py     # Backfill unprocessed raw grants
│   ├── utils/
│   │   ├── llm.py              # Centralized LLM client (gateway + direct fallback)
│   │   └── parsing.py          # parse_json_safe + retry_async utilities
│   ├── main.py                 # FastAPI app + all API endpoints
│   └── requirements.txt
│
├── app/                        # Streamlit UI
│   ├── main.py                 # Entry point — 6 page navigation
│   ├── views/
│   │   ├── dashboard.py        # Stats, charts, full Grant Tracker table
│   │   ├── triage.py           # Human triage queue (pursue/watch/pass)
│   │   ├── pipeline.py         # All scored grants with full filters
│   │   ├── drafter.py          # Active draft management
│   │   ├── knowledge_health.py # Knowledge base sync status
│   │   └── agent_config.py     # Configure agent parameters
│   ├── db/
│   │   └── queries.py          # All MongoDB read/write functions for UI
│   ├── ui/
│   │   ├── icons.py            # Lucide SVG icon helpers + badge components
│   │   ├── filters.py          # Shared filter helpers (amount buckets, deadlines)
│   │   └── theme_toggle.py     # Light/dark theme toggle
│   ├── styles/
│   │   └── theme.css           # CSS variables for theming
│   └── requirements.txt
│
├── .streamlit/                 # Streamlit config
├── .env.example                # All required environment variables
├── .gitignore
└── README.md
```

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `grants_raw` | Raw discovered grants before scoring. Unique index on `url_hash`. |
| `grants_scored` | Scored + ranked grants. Unique index on `url_hash`. |
| `grants_pipeline` | Active drafting pipelines (one per pursued grant). |
| `grant_drafts` | Individual draft versions (versioned per pipeline). |
| `knowledge_chunks` | Chunked Notion + Drive content for RAG. |
| `knowledge_sync_logs` | Audit trail of knowledge base sync runs. |
| `funder_context_cache` | Perplexity funder research (7-day TTL). |
| `agent_config` | Per-agent configuration (weights, thresholds, queries). |
| `graph_checkpoints` | LangGraph MongoDB checkpointer state. |
| `audit_logs` | All agent run events and actions. |
| `scout_runs` | Scout run statistics (queries run, grants found, saved). |

---

## Scoring Dimensions

The Analyst agent scores each grant across 6 dimensions using Claude Sonnet:

| Dimension | Weight | What it measures |
|---|---|---|
| `theme_alignment` | 25% | How closely the grant matches AltCarbon's 5 focus areas |
| `eligibility_confidence` | 20% | Confidence that AltCarbon meets all requirements |
| `funding_amount` | 20% | Grant size relative to AltCarbon's needs (>$100K = high) |
| `deadline_urgency` | 15% | Lead time available (>3 months = optimal) |
| `geography_fit` | 10% | India or global eligibility (India explicit = max score) |
| `competition_level` | 10% | Estimated applicant pool (niche/selective = higher score) |

**Thresholds** (configurable in `agent_config`):
- `weighted_total >= 6.5` → **Pursue**
- `weighted_total >= 5.0` → **Watch**
- `weighted_total < 5.0` → **Auto-pass**

---

## Quickstart

### 1. Clone and install dependencies

```bash
git clone https://github.com/Alt-Carbon/grants-engine.git
cd grants-engine

# Backend
pip install -r backend/requirements.txt

# Streamlit UI
pip install -r app/requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in all API keys
```

**Required keys:**

| Variable | Source |
|---|---|
| `MONGODB_URI` | [MongoDB Atlas](https://cloud.mongodb.com) — free M0 cluster works |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `TAVILY_API_KEY` | [app.tavily.com](https://app.tavily.com) |
| `EXA_API_KEY` | [exa.ai](https://exa.ai) |

**Optional but recommended:**

| Variable | Purpose |
|---|---|
| `PERPLEXITY_API_KEY` | Funder research enrichment (greatly improves scores) |
| `JINA_API_KEY` | Content fetching (free tier = 10 RPM, paid = 200 RPM) |
| `OPENAI_API_KEY` | Knowledge base embeddings (required for RAG) |
| `NOTION_TOKEN` | Sync company profile from Notion |
| `GOOGLE_REFRESH_TOKEN` | Sync past applications from Google Drive |

### 3. Set up MongoDB Atlas Vector Search index

In your Atlas cluster, create a Vector Search index on `knowledge_chunks`:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1536,
      "similarity": "cosine"
    },
    { "type": "filter", "path": "doc_type" },
    { "type": "filter", "path": "themes" }
  ]
}
```

### 4. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 5. Run the Streamlit UI

```bash
streamlit run app/main.py
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/run/scout` | Trigger full scout + analyst run |
| `POST` | `/run/knowledge-sync` | Sync Notion + Drive to knowledge base |
| `POST` | `/triage/{grant_id}` | Human triage decision (pursue/watch/pass) |
| `POST` | `/draft/start/{grant_id}` | Start drafting pipeline for a grant |
| `POST` | `/draft/{thread_id}/approve` | Approve current draft section |
| `POST` | `/draft/{thread_id}/revise` | Request revision with feedback |
| `GET` | `/grants` | List all scored grants |
| `GET` | `/grants/{id}` | Get single grant detail |
| `GET` | `/health` | Health check |

---

## Streamlit UI — 6 Views

| View | Description |
|---|---|
| **Dashboard** | Pipeline funnel, theme chart, score distribution, full Grant Tracker table with filters and CSV export |
| **Triage Queue** | All unreviewed grants sorted by AI score. One-click pursue / watch / pass / report actions. |
| **Pipeline** | All scored grants with search, theme, type, amount, deadline, and status filters |
| **Drafter** | Active drafting sessions — section-by-section review and approval |
| **Knowledge Health** | Knowledge base chunk counts by source and type, last sync time |
| **Agent Config** | Edit scoring weights, thresholds, and custom search queries |

---

## Human-in-the-Loop (HITL) Gates

The LangGraph pipeline has two mandatory human checkpoints:

1. **Triage Gate** — After analyst scoring, a human reviews each grant in the Streamlit Triage view and decides: pursue, watch, or pass. Only `pursue` grants proceed to drafting.

2. **Section Review Gate** — During drafting, the agent pauses after writing each application section. The human can approve (move to next section) or provide revision feedback (the agent rewrites and re-presents).

---

## Deployment

### Backend (Railway)

```bash
# Set all env vars in Railway dashboard, then:
railway up
```

The `backend/railway.toml` and `backend/Procfile` handle the Railway deployment config.

### UI (Vercel or Streamlit Cloud)

**Streamlit Cloud:**
1. Connect your GitHub repo
2. Set main file: `app/main.py`
3. Add all env vars in the Streamlit Cloud secrets manager

**Vercel:**
```bash
vercel --prod
```

---

## Key Design Decisions

**Search-first, not crawl-first** — The old system tried to crawl 60+ grant portals directly (JS-rendered pages, login walls). The new system uses Tavily/Exa/Perplexity as discovery tools and only fetches content for URLs that have already been identified as relevant.

**3-layer deduplication** — URL hash → normalized URL hash (strips tracking params) → content hash (title + funder). This catches the same grant appearing at different URLs, with UTM parameters, or from multiple search sources.

**Idempotent saves** — All MongoDB writes use `update_one(..., upsert=True)` rather than `insert_one`. Running the pipeline twice produces the same result as running it once.

**Funder context cache** — Perplexity funder research results are cached in MongoDB with a 7-day TTL. The same funder is never queried twice within a week, significantly reducing API costs on frequent runs.

**Status correctness** — Auto-pass grants get `status="auto_pass"` in MongoDB, not `status="triage"`. The triage queue only shows grants that genuinely need human review.

---

## Environment Variables Reference

```bash
# Required
MONGODB_URI=mongodb+srv://...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
EXA_API_KEY=...

# Strongly recommended
PERPLEXITY_API_KEY=pplx-...   # funder enrichment
JINA_API_KEY=...               # content fetching
OPENAI_API_KEY=sk-...          # embeddings for RAG

# Knowledge sync (optional)
NOTION_TOKEN=secret_...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...

# Backend auth
CRON_SECRET=<random string>
INTERNAL_SECRET=<random string>

# Agent thresholds (optional — can also be set via UI)
PURSUE_THRESHOLD=6.5
WATCH_THRESHOLD=5.0
MIN_GRANT_FUNDING=3000

# LangSmith tracing (optional)
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=false
LANGCHAIN_PROJECT=altcarbon-grants
```

---

## License

Private — AltCarbon internal tooling.
