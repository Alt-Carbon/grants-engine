# AltCarbon Grants Intelligence Engine

An AI-powered grant discovery, scoring, and drafting pipeline built for **AltCarbon** — a climate technology startup focused on carbon removal, MRV, agritech, AI for sciences, applied earth sciences, and social impact.

The engine continuously discovers grant opportunities from 100+ sources, scores them against AltCarbon's mission, surfaces the best ones for human review, and drafts applications section-by-section with AI assistance.

---

## Architecture Overview

```
                            DISCOVERY LAYER
  Tavily (keyword)  +  Exa (semantic)  +  Perplexity (live web)
              +  Direct crawl of 60+ known funder pages
                               |
                               v
                          SCOUT AGENT
  3-layer dedup  ->  Jina content fetch  ->  Haiku field extract
  Quality filter  ->  Upsert to grants_raw (MongoDB)
                               |
                               v
                         ANALYST AGENT
  Hard rules  ->  Perplexity funder research (cached 7 days)
  Claude Sonnet 6-dimension scoring  ->  Upsert to grants_scored
                               |
              +----------------+----------------+
              |                                 |
              v                                 v
       NEXT.JS FRONTEND                  NOTION SYNC
  Dashboard / Pipeline / Triage       Grant Pipeline DB
  Grant Detail Pages / Drafter        Agent Runs / Errors
  Mission Control / Audit Log         (secondary view)
              |
              v (pursue)
                        COMPANY BRAIN
  Notion MCP sync  ->  Pinecone vector search  ->  RAG retrieval
  Retrieves relevant past applications, org profile, expertise
                               |
                               v
                       DRAFTER AGENT
  Grant Reader  ->  Section Writer  ->  Section-by-section HITL
  Human reviews each section  ->  Exporter (Markdown / PDF)
                               |
                               v
                       REVIEWER AGENT
  Full-draft critique  ->  Revision suggestions
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 15 (App Router), TypeScript, Tailwind CSS, Recharts |
| **Auth** | NextAuth.js with Google OAuth |
| **Real-time** | Pusher (live comments, agent status) |
| **Agent orchestration** | LangGraph (stateful pipeline with HITL interrupts) |
| **LLMs** | Claude Sonnet 4.6 (scoring, drafting) + Claude Haiku 4.5 (extraction) |
| **Discovery** | Tavily Search, Exa Semantic Search, Perplexity Sonar Pro |
| **Content fetch** | Jina Reader (with plain HTTP fallback) |
| **Database** | MongoDB Atlas (grants, drafts, knowledge, checkpoints) |
| **Vector search** | Pinecone (knowledge base RAG) + MongoDB Atlas Vector Search |
| **Knowledge sync** | Notion MCP (live subprocess) + static profile fallback |
| **Notion integration** | Bi-directional: MCP for reads, `notion-client` SDK for writes |
| **Backend API** | FastAPI + Uvicorn (deployed on Railway) |
| **Scheduling** | APScheduler (48-hour scout cadence) |

---

## Project Structure

```
grants-engine/
├── backend/                        # FastAPI backend + all agents
│   ├── agents/
│   │   ├── scout.py                # Discovery: Tavily + Exa + Perplexity + direct crawl
│   │   ├── analyst.py              # Scoring: 6-dimension Claude Sonnet evaluation
│   │   ├── company_brain.py        # RAG: Notion MCP + Pinecone vector search
│   │   ├── reviewer.py             # Full draft critique
│   │   └── drafter/
│   │       ├── drafter_node.py     # LangGraph drafter node
│   │       ├── grant_reader.py     # Extract grant requirements
│   │       ├── section_writer.py   # Write each application section
│   │       └── exporter.py         # Export to Markdown/PDF
│   ├── integrations/
│   │   ├── notion_sync.py          # Notion write operations (grants, runs, errors)
│   │   ├── notion_config.py        # Notion DB IDs, property mappings, status maps
│   │   └── notion_mcp.py           # Notion MCP client singleton (live subprocess)
│   ├── knowledge/
│   │   ├── sync_profile.py         # Sync AltCarbon profile from Notion via MCP
│   │   └── altcarbon_profile.md    # Static company knowledge base (fallback)
│   ├── graph/
│   │   ├── graph.py                # LangGraph pipeline definition
│   │   ├── state.py                # GrantState TypedDict
│   │   ├── router.py               # Conditional routing logic
│   │   └── checkpointer.py         # MongoDB-backed checkpoint store
│   ├── db/
│   │   ├── mongo.py                # Motor client + collection accessors + indexes
│   │   └── pinecone_store.py       # Pinecone vector store for knowledge RAG
│   ├── config/
│   │   └── settings.py             # Pydantic settings (reads from .env)
│   ├── jobs/
│   │   ├── scout_job.py            # Scheduled scout runner
│   │   ├── knowledge_job.py        # Scheduled knowledge sync
│   │   └── backfill_job.py         # Backfill unprocessed raw grants
│   ├── utils/
│   │   ├── llm.py                  # Centralized LLM client (gateway + direct fallback)
│   │   └── parsing.py              # parse_json_safe + retry_async utilities
│   ├── main.py                     # FastAPI app + all API endpoints
│   └── requirements.txt
│
├── frontend/                       # Next.js 15 frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx          # Root layout with Sidebar + SessionProvider
│   │   │   ├── page.tsx            # Redirects to /dashboard
│   │   │   ├── login/              # Google OAuth login page
│   │   │   ├── dashboard/          # KPIs, activity charts, warnings, what's new
│   │   │   ├── pipeline/           # Pipeline view (Kanban board + table)
│   │   │   ├── triage/             # Shortlisted grants queue for human review
│   │   │   ├── grants/[id]/        # Full grant detail page (dedicated URL)
│   │   │   ├── drafter/            # AI drafter with section-by-section review
│   │   │   ├── monitoring/         # Mission Control (agent health, errors, runs)
│   │   │   ├── audit/              # Audit log (agent runs, events, errors)
│   │   │   ├── config/             # Agent configuration (weights, thresholds)
│   │   │   ├── knowledge/          # Knowledge base status and sync controls
│   │   │   └── api/                # Next.js API routes (proxy to FastAPI + MongoDB)
│   │   ├── components/
│   │   │   ├── Sidebar.tsx         # Navigation sidebar (8 pages)
│   │   │   ├── PipelineView.tsx    # Pipeline wrapper with filters + view toggle
│   │   │   ├── PipelineBoard.tsx   # Kanban board with drag-drop status changes
│   │   │   ├── PipelineTable.tsx   # Sortable/filterable data table
│   │   │   ├── GrantCard.tsx       # Compact grant card for board/list views
│   │   │   ├── GrantDetailSheet.tsx # Slide-over sheet for quick grant preview
│   │   │   ├── CommentThread.tsx   # Threaded comments with reactions + real-time
│   │   │   ├── GrantActivity.tsx   # Activity timeline per grant
│   │   │   ├── ScoreRadar.tsx      # Radar chart for 6-dimension scores
│   │   │   ├── StatusPicker.tsx    # Dropdown status changer
│   │   │   ├── StatusBadge.tsx     # Color-coded status label
│   │   │   ├── DeadlineChip.tsx    # Deadline urgency badge
│   │   │   ├── AgentControls.tsx   # Run buttons for Scout, Analyst, Drafter
│   │   │   ├── ActivityChart.tsx   # 30-day grant discovery chart
│   │   │   ├── WhatsNewDigest.tsx  # Summary digest for returning users
│   │   │   └── ManualGrantEntry.tsx # Manual grant URL entry form
│   │   ├── hooks/
│   │   │   ├── useGrantUrl.ts      # URL sync for grant selection (deep-linking)
│   │   │   └── useLastSeen.ts      # Track new/unseen grants
│   │   └── lib/
│   │       ├── queries.ts          # MongoDB queries + TypeScript interfaces
│   │       ├── mongodb.ts          # MongoDB client singleton
│   │       ├── auth.ts             # NextAuth configuration
│   │       ├── utils.ts            # Shared helpers (priority, theme labels)
│   │       └── generateIntelBrief.ts # Client-side intelligence brief (.md / .pdf)
│   ├── package.json
│   └── next.config.ts
│
├── .env.example                    # All required environment variables
├── .gitignore
└── README.md
```

---

## Frontend Pages

| Page | Route | Description |
|---|---|---|
| **Dashboard** | `/dashboard` | KPI cards, 30-day activity chart, pipeline summary, warnings banner, what's new digest |
| **Pipeline** | `/pipeline` | Kanban board (drag-drop) + table view with sorting, filters (theme, score, deadline, funding, geography), manual grant entry |
| **Shortlisted** | `/triage` | Triage queue for human review — one-click pursue/pass with score radar and evidence |
| **Grant Detail** | `/grants/[id]` | Full-page grant view: score breakdown (bars + radar), eligibility checklist, evidence, red flags, strategy, requirements, key dates, past winners, comments, activity log |
| **Drafter** | `/drafter` | AI drafting interface — select grant, stream sections, review/approve/revise, download intelligence brief (.md / .pdf) |
| **Mission Control** | `/monitoring` | Agent health, recent runs, error timeline, system status |
| **Audit Log** | `/audit` | Filterable log of all agent runs, events, and errors |
| **Config** | `/config` | Edit scoring weights, thresholds, search queries, agent parameters |
| **Knowledge** | `/knowledge` | Knowledge base chunks, sync status, last sync times |

### Grant Detail — Two Interaction Modes

1. **Quick preview (sheet)** — Click any grant in Pipeline/Kanban/Triage to open a slide-over panel with key details, score radar, eligibility, evidence, comments, and activity
2. **Full page** (`/grants/[id]`) — Click the expand button on the sheet to open a dedicated page with complete analysis, two-column layout, shareable URL, and inline status management

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `grants_raw` | Raw discovered grants before scoring. Unique index on `url_hash`. |
| `grants_scored` | Scored + ranked grants. Unique index on `url_hash`. |
| `grants_pipeline` | Active drafting pipelines (one per pursued grant). |
| `grant_drafts` | Individual draft versions (versioned per pipeline). |
| `grant_comments` | Threaded comments per grant (with reactions, pinning). |
| `knowledge_chunks` | Chunked Notion content for RAG. |
| `knowledge_sync_logs` | Audit trail of knowledge base sync runs. |
| `funder_context_cache` | Perplexity funder research (7-day TTL). |
| `agent_config` | Per-agent configuration (weights, thresholds, queries). |
| `graph_checkpoints` | LangGraph MongoDB checkpointer state. |
| `audit_logs` | All agent run events and actions. |
| `scout_runs` | Scout run statistics (queries run, grants found, saved). |

---

## Pinecone — Knowledge RAG Engine

Pinecone is the **primary vector database** powering the Company Brain's retrieval-augmented generation (RAG) pipeline. It stores AltCarbon's institutional knowledge as semantic embeddings, enabling the AI agents to retrieve relevant context when scoring grants and drafting applications.

### What Pinecone Manages

| Data | Source | Purpose |
|---|---|---|
| Company knowledge chunks | Notion workspace (9+ key pages) | RAG context for Analyst scoring and Drafter writing |
| Technical methodology docs | Notion (MRV Moat, ERW, Biochar) | Grounds AI responses in AltCarbon's actual capabilities |
| Past application content | Notion (past grants, proposals) | Style examples and positioning language for drafts |
| Team & vision docs | Notion (Introducing AltCarbon, Vision & Comms) | Company profile context for eligibility and fit assessment |
| Operational data | Notion (DRP, BRP, Gigaton Scale) | Quantitative evidence for grant applications |

### How It Works

```
Notion Workspace
      |
      v  (Notion MCP fetch)
Company Brain Sync
      |
      v  (chunk: 400 words, 80 overlap)
Claude Haiku Tagger
      |  - doc_type (company_overview, technical_methodology, etc.)
      |  - themes (climatetech, agritech, ai_for_sciences, etc.)
      |  - key_topics, contains_data, is_useful_for_grants
      v
OpenAI text-embedding-3-small (1536 dimensions)
      |
      +---> Pinecone (primary)     namespace: "knowledge"
      |       cosine similarity     index: "grants-engine"
      |       serverless (AWS us-east-1)
      |
      +---> MongoDB (fallback)     collection: knowledge_chunks
              Atlas Vector Search    index: "knowledge_vector_index"
```

### Index Configuration

| Setting | Value |
|---|---|
| **Index name** | `grants-engine` |
| **Dimensions** | 1536 |
| **Metric** | Cosine similarity |
| **Spec** | Serverless (AWS `us-east-1`) |
| **Namespace** | `knowledge` |
| **Embedding model** | OpenAI `text-embedding-3-small` |

### Vector Metadata Schema

Each vector in Pinecone carries rich metadata for filtered retrieval:

```
id:                  "{source_id}#{chunk_index}"
values:              [1536 floats]
metadata:
  content:           str    # Actual chunk text
  source:            str    # "notion" or "drive"
  source_id:         str    # Notion page ID
  source_title:      str    # Page title
  doc_type:          str    # company_overview | technical_methodology | team_bio | ...
  themes:            [str]  # climatetech | agritech | ai_for_sciences | ...
  key_topics:        [str]  # 2-4 keywords extracted by Claude Haiku
  contains_data:     bool   # Whether chunk has quantitative data
  is_useful_for_grants: bool
```

### Query Flow (When Scoring or Drafting a Grant)

1. **Build query** — grant title + AI reasoning + detected themes
2. **Embed query** — OpenAI `text-embedding-3-small`
3. **Search Pinecone** — cosine similarity, top 6, filtered by themes/doc_type
4. **Fallback to MongoDB** — if Pinecone returns empty or errors
5. **Final fallback** — static `altcarbon_profile.md` markdown file

### Graceful Degradation

Pinecone is **optional but recommended**. The system has a 4-level fallback:

| Priority | Source | When used |
|---|---|---|
| 1 | **Pinecone** vector search | Default when `PINECONE_API_KEY` is set |
| 2 | **MongoDB Atlas** Vector Search | Pinecone not configured or query fails |
| 3 | **MongoDB text search** | Vector search returns empty results |
| 4 | **Static profile** (`altcarbon_profile.md`) | All vector searches return nothing |

### Sync Schedule

| Trigger | Endpoint | Frequency |
|---|---|---|
| Automatic | `POST /cron/knowledge-sync` | Daily (via Railway cron) |
| Manual | `POST /run/knowledge-sync` | On-demand from frontend `/knowledge` page |
| Profile only | `POST /run/sync-profile` | On-demand (refreshes static fallback) |

Each sync logs results to `knowledge_sync_logs`:
```
{
  synced_at, notion_pages, drive_files,
  total_chunks, pinecone_vectors, duration_seconds
}
```

---

## Notion Integration

The engine syncs bidirectionally with Notion:

| Direction | Method | What |
|---|---|---|
| **Read** (knowledge) | Notion MCP (live subprocess) | Search workspace, fetch pages for Company Brain RAG |
| **Write** (pipeline) | `notion-client` Python SDK | Sync grants, agent runs, errors, triage decisions, draft sections |

**Notion databases:** Grant Pipeline, Agent Runs, Error Logs, Triage Decisions, Draft Sections, Knowledge Connections

The frontend is the **primary dashboard**. Notion serves as a secondary view for team members who prefer it.

---

## Scoring Dimensions

The Analyst agent scores each grant across 6 dimensions using Claude Sonnet:

| Dimension | Weight | What it measures |
|---|---|---|
| `theme_alignment` | 25% | How closely the grant matches AltCarbon's 6 focus areas |
| `eligibility_confidence` | 20% | Confidence that AltCarbon meets all requirements |
| `funding_amount` | 20% | Grant size relative to AltCarbon's needs (>$100K = high) |
| `deadline_urgency` | 15% | Lead time available (>3 months = optimal) |
| `geography_fit` | 10% | India or global eligibility (India explicit = max score) |
| `competition_level` | 10% | Estimated applicant pool (niche/selective = higher score) |

**Thresholds** (configurable in `/config`):
- `weighted_total >= 6.5` -> **High Priority (Pursue)**
- `weighted_total >= 5.0` -> **Medium Priority (Watch)**
- `weighted_total < 5.0` -> **Low Priority (Auto-pass)**

---

## API Endpoints

### Backend (FastAPI)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/run/scout` | Trigger full scout + analyst run |
| `POST` | `/run/knowledge-sync` | Sync Notion to knowledge base |
| `POST` | `/run/sync-profile` | Re-sync static AltCarbon profile from Notion via MCP |
| `POST` | `/triage/{grant_id}` | Human triage decision (pursue/watch/pass) |
| `POST` | `/draft/start/{grant_id}` | Start drafting pipeline for a grant |
| `POST` | `/draft/{thread_id}/approve` | Approve current draft section |
| `POST` | `/draft/{thread_id}/revise` | Request revision with feedback |
| `GET` | `/grants` | List all scored grants |
| `GET` | `/grants/{id}` | Get single grant detail |
| `GET` | `/health` | Health check |
| `GET` | `/status/notion-mcp` | Notion MCP connection health |
| `POST` | `/run/notion-mcp/reconnect` | Force reconnect Notion MCP |

### Frontend (Next.js API Routes)

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/grants/[id]` | Fetch full grant by ID from MongoDB |
| `POST` | `/api/grants/status` | Update grant status (with override tracking) |
| `POST` | `/api/grants/manual` | Submit manual grant URL for processing |
| `POST` | `/api/grants/[id]/comments` | Add comment to a grant |
| `GET` | `/api/grants/[id]/comments` | Fetch comments for a grant |
| `GET` | `/api/pipeline-summary` | Pipeline state snapshot for dashboard |
| `GET` | `/api/whats-new` | New discoveries digest since last visit |
| `POST` | `/api/run/scout` | Proxy to trigger scout run |
| `POST` | `/api/run/analyst` | Proxy to trigger analyst run |
| `POST` | `/api/drafter/trigger` | Proxy to start drafter |

---

## Quickstart

### 1. Clone and install dependencies

```bash
git clone https://github.com/Alt-Carbon/grants-engine.git
cd grants-engine

# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Configure environment

```bash
# Backend
cp backend/.env.example backend/.env

# Frontend
cp frontend/.env.example frontend/.env.local
```

### 3. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 4. Run the frontend

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — you'll be redirected to Google OAuth login, then to the Dashboard.

---

## Deployment

### Backend (Railway)

```bash
# Set all env vars in Railway dashboard, then:
railway up
```

The `backend/Dockerfile` handles the build including Node.js for Notion MCP server.

### Frontend (Railway / Vercel)

```bash
# Railway
railway up

# Or Vercel
vercel --prod
```

Set `FASTAPI_URL` in the frontend environment to point to the deployed backend.

---

## Key Design Decisions

**Search-first, not crawl-first** — Uses Tavily/Exa/Perplexity as discovery tools rather than crawling 60+ grant portals directly (JS-rendered pages, login walls).

**3-layer deduplication** — URL hash -> normalized URL hash (strips tracking params) -> content hash (title + funder). Catches the same grant from multiple search sources.

**Sheet + full page pattern** — Grant details open as a quick-preview sheet by default (stays in pipeline context). An expand button navigates to a dedicated `/grants/[id]` page with complete analysis, shareable URL, and inline collaboration.

**Frontend-first dashboard, Notion as secondary** — The Next.js frontend is the primary ops dashboard (pipeline, triage, drafter, monitoring). Notion sync runs in the background as a secondary view for team members who prefer it.

**Client-side intelligence briefs** — Intelligence briefs are generated client-side as Markdown/PDF (no server round-trip), using preloaded grant data for instant downloads.

**Notion MCP for reads, SDK for writes** — Company Brain reads from Notion via the MCP protocol (live subprocess). Grant pipeline sync writes via the `notion-client` Python SDK. This separation keeps reads fast and writes reliable.

**Idempotent saves** — All MongoDB writes use `update_one(..., upsert=True)`. Running the pipeline twice produces the same result as running it once.

**Funder context cache** — Perplexity funder research cached in MongoDB with 7-day TTL, reducing API costs on frequent runs.

---

## Environment Variables Reference

```bash
# Required
MONGODB_URI=mongodb+srv://...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
EXA_API_KEY=...

# Strongly recommended
PERPLEXITY_API_KEY=pplx-...       # funder enrichment
JINA_API_KEY=...                   # content fetching
OPENAI_API_KEY=sk-...              # embeddings for RAG

# Knowledge sync
NOTION_TOKEN=secret_...            # Notion API token
NOTION_KNOWLEDGE_BASE_PAGE_ID=...  # Root page for knowledge sync

# Pinecone (primary vector store for Company Brain RAG)
PINECONE_API_KEY=...               # Pinecone API key (optional — falls back to MongoDB Atlas Vector Search)
PINECONE_INDEX_NAME=grants-engine  # Index name (default: grants-engine)

# Frontend auth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
NEXTAUTH_SECRET=...
NEXTAUTH_URL=http://localhost:3000

# Backend auth
CRON_SECRET=<random string>
INTERNAL_SECRET=<random string>
FASTAPI_URL=http://localhost:8000   # Backend URL for frontend proxy

# Real-time
PUSHER_APP_ID=...
PUSHER_KEY=...
PUSHER_SECRET=...
PUSHER_CLUSTER=...

# Agent thresholds (optional — can also be set via /config)
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
