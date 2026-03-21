# Grants Intelligence Engine — Developer Guide

> Complete developer reference for the AltCarbon Grants Intelligence Engine.
> Last updated: 2026-03-20

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [Backend Deep Dive](#5-backend-deep-dive)
   - 5.1 [FastAPI Application](#51-fastapi-application)
   - 5.2 [LangGraph Pipeline](#52-langgraph-pipeline)
   - 5.3 [Agents](#53-agents)
   - 5.4 [Integrations](#54-integrations)
   - 5.5 [Database Layer](#55-database-layer)
   - 5.6 [LLM Utilities](#56-llm-utilities)
   - 5.7 [Skills Registry](#57-skills-registry)
   - 5.8 [Jobs & Scheduling](#58-jobs--scheduling)
   - 5.9 [Configuration & Settings](#59-configuration--settings)
   - 5.10 [Error Handling](#510-error-handling)
6. [Frontend Deep Dive](#6-frontend-deep-dive)
   - 6.1 [Pages](#61-pages)
   - 6.2 [Components](#62-components)
   - 6.3 [API Routes](#63-api-routes)
   - 6.4 [Hooks](#64-hooks)
   - 6.5 [Libraries & Utilities](#65-libraries--utilities)
   - 6.6 [State Management](#66-state-management)
   - 6.7 [Styling](#67-styling)
7. [Data Flow](#7-data-flow)
8. [MongoDB Collections](#8-mongodb-collections)
9. [Environment Variables](#9-environment-variables)
10. [Deployment](#10-deployment)
11. [Authentication & Security](#11-authentication--security)
12. [Testing](#12-testing)
13. [Local Development](#13-local-development)

---

## 1. System Overview

The Grants Intelligence Engine is an AI-powered system that **discovers**, **scores**, **triages**, **drafts**, and **reviews** grant applications for AltCarbon — a deep tech climate & data science company focused on Carbon Dioxide Removal (CDR) via Enhanced Rock Weathering (ERW) and Biochar.

### What it does

| Stage | Agent | Action |
|-------|-------|--------|
| Discovery | **Scout** | Searches Tavily, Exa, Perplexity, and direct sources for new grants |
| Scoring | **Analyst** | Scores each grant on 6 dimensions, recommends pursue/watch/pass |
| Knowledge | **Company Brain** | Retrieves AltCarbon-specific context from Notion + MongoDB |
| Drafting | **Drafter** | Writes grant sections iteratively with self-critique and human review |
| Review | **Reviewer** | Scores final draft on funder alignment, scientific credibility, coherence |

### Key characteristics

- **LangGraph orchestration** with 13 nodes, 3 human interrupt points
- **MongoDB-backed checkpointing** for resumable pipelines
- **Notion bi-directional sync** — reads via MCP, writes via SDK
- **Multi-model LLM** with automatic fallback chains
- **Real-time updates** via Pusher
- **Google OAuth** restricted to `altcarbon.com` domain

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                       │
│  Pages: Dashboard │ Pipeline │ Triage │ Drafter │ Reviewer      │
│  51 API routes → proxy to FastAPI backend                       │
│  Real-time: Pusher │ Auth: NextAuth (Google OAuth)              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP (x-internal-secret)
┌──────────────────────────▼──────────────────────────────────────┐
│                       BACKEND (FastAPI)                          │
│  70+ REST endpoints │ LangGraph pipeline (13 nodes)             │
│  5 AI Agents │ MCP Hub │ Notion Sync │ APScheduler              │
└────┬──────────┬──────────┬──────────┬───────────────────────────┘
     │          │          │          │
  MongoDB    Notion     Pusher    AI Models
  (Motor)    (MCP+SDK)  (events)  (Gateway)
```

### LangGraph Pipeline Flow

```
START
  │
  ▼
scout ──► company_brain_load ──► analyst ──► pre_triage_guardrail
                                                    │
                                              notify_triage
                                                    │
                                          ┌─── human_triage ◄── [INTERRUPT: human decision]
                                          │
                              route_triage │
                    ┌───────────┴──────────┐
                    ▼                      ▼
             company_brain          pipeline_update ──► END
                    │
              grant_reader
                    │
            draft_guardrail
                    │
           route_after_guardrail
          ┌────────┴────────┐
          ▼                 ▼
       drafter ◄─┐    pipeline_update
          │      │
          │      │ (loop per section)
          │      │
   route_after_drafter
          │
          ▼
       export ──► reviewer ──► END
```

**Interrupt Points:**
1. `human_triage` — user decides pursue/watch/pass
2. `drafter` (per section) — user reviews/edits each section
3. `reviewer` — final review before export

---

## 3. Tech Stack

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11 | Runtime |
| FastAPI | latest | Web framework |
| LangGraph | 0.2+ | Agent orchestration |
| Motor | 3.5+ | Async MongoDB driver |
| Anthropic SDK | 0.40+ | Claude API |
| MCP SDK | 1.0+ | Model Context Protocol |
| APScheduler | 3.10+ | Job scheduling |
| Playwright | latest | Browser rendering |
| Tavily | latest | Web search |
| Exa | latest | Semantic search |
| Pinecone | 5.0+ | Vector database |

### Frontend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Next.js | 16.2 | React framework (App Router) |
| React | 19.2 | UI library |
| TypeScript | 5.6 | Type safety |
| Tailwind CSS | 3.4 | Styling |
| NextAuth | 5.0-beta | Authentication |
| Pusher.js | latest | Real-time events |
| Recharts | latest | Charts |
| @hello-pangea/dnd | latest | Drag-and-drop |
| Vitest | latest | Testing |

### Infrastructure
| Service | Purpose |
|---------|---------|
| Railway | Deployment (backend + frontend) |
| MongoDB Atlas | Database |
| Notion | Knowledge base + mission control |
| Pusher | Real-time notifications |
| Vercel AI Gateway | LLM routing |
| Pinecone | Vector search |
| Google OAuth | Authentication |

---

## 4. Project Structure

```
tehran/
├── backend/
│   ├── main.py                          # FastAPI app (70+ routes)
│   ├── Dockerfile                       # Python 3.11 + Node.js 20
│   ├── requirements.txt                 # Python dependencies
│   ├── Procfile                         # Railway entry point
│   ├── railway.toml                     # Railway deployment config
│   │
│   ├── config/
│   │   ├── settings.py                  # Pydantic Settings (50+ env vars)
│   │   ├── mcp_servers.yaml             # MCP server definitions
│   │   └── skills.yaml                  # Skill definitions
│   │
│   ├── db/
│   │   └── mongo.py                     # MongoDB client + collection helpers
│   │
│   ├── graph/
│   │   ├── graph.py                     # LangGraph builder (13 nodes)
│   │   ├── state.py                     # GrantState TypedDict
│   │   ├── router.py                    # Conditional routing functions
│   │   └── checkpointer.py             # MongoDB checkpoint saver
│   │
│   ├── agents/
│   │   ├── scout.py                     # Grant discovery agent
│   │   ├── analyst.py                   # Grant scoring agent
│   │   ├── company_brain.py             # Knowledge retrieval agent
│   │   ├── reviewer.py                  # Single reviewer
│   │   ├── dual_reviewer.py             # Dual funder+scientific+coherence
│   │   ├── pre_triage_guardrail.py      # Hard-rule filtering
│   │   ├── content_fetcher.py           # Grant document fetcher
│   │   ├── feedback_learner.py          # User feedback collector
│   │   ├── preference_learner.py        # User preference learning
│   │   ├── agent_context.py             # Skills + heartbeat loader
│   │   ├── golden_examples/
│   │   │   └── manager.py              # Past grant section manager
│   │   └── drafter/
│   │       ├── drafter_node.py          # Main section loop
│   │       ├── section_writer.py        # Per-section LLM writer
│   │       ├── grant_reader.py          # Grant document parser
│   │       ├── draft_guardrail.py       # Draftability validator
│   │       ├── exporter.py              # MongoDB + Drive export
│   │       └── theme_profiles.py        # Theme-specific guidance
│   │
│   ├── integrations/
│   │   ├── notion_mcp.py               # Notion MCP client (high-level)
│   │   ├── notion_sync.py              # Bi-directional Notion sync
│   │   ├── notion_config.py            # Notion DB IDs + mappings
│   │   ├── mcp_hub.py                  # Multi-server MCP manager
│   │   └── notion_webhooks.py          # Webhook handlers
│   │
│   ├── knowledge/
│   │   ├── altcarbon_profile.md         # Static company knowledge
│   │   ├── sync_profile.py             # Re-sync from Notion
│   │   └── past_grants_config.py       # Reference grant config
│   │
│   ├── jobs/
│   │   ├── scheduler.py                # APScheduler setup
│   │   ├── scout_job.py                # Cron scout discovery
│   │   ├── knowledge_job.py            # Cron knowledge sync
│   │   └── backfill_job.py             # Backfill operations
│   │
│   ├── utils/
│   │   ├── llm.py                      # Chat function, models, fallback
│   │   ├── parsing.py                  # JSON parsing, retry, API health
│   │   └── browser.py                  # Cloudflare browser rendering
│   │
│   ├── skills/
│   │   └── registry.py                 # Skill discovery + execution
│   │
│   ├── notifications/
│   │   └── hub.py                      # Pusher notifications
│   │
│   ├── scripts/
│   │   ├── run_scout_analyst.py        # Manual run script
│   │   ├── import_excel_grants.py      # Bulk import
│   │   └── reset_db.py                 # Database reset
│   │
│   ├── benchmarks/                      # Performance benchmarks
│   ├── evals/                           # Evaluation scripts
│   └── tests/                           # Test suite
│
├── frontend/
│   ├── src/
│   │   ├── app/                         # Next.js App Router
│   │   │   ├── layout.tsx              # Root layout (Sidebar + providers)
│   │   │   ├── page.tsx                # Redirect to /dashboard
│   │   │   ├── middleware.ts           # Auth middleware
│   │   │   ├── api/                    # 51 API routes
│   │   │   ├── dashboard/             # KPI dashboard
│   │   │   ├── pipeline/              # Kanban + table view
│   │   │   ├── drafter/               # Draft writing UI
│   │   │   ├── grants/[id]/           # Grant detail page
│   │   │   ├── reviewers/             # Review interface
│   │   │   ├── triage/                # Triage queue
│   │   │   ├── config/                # Agent config editor
│   │   │   ├── knowledge/             # Knowledge sync health
│   │   │   ├── audit/                 # Audit log
│   │   │   ├── monitoring/            # Mission control
│   │   │   └── login/                 # Google OAuth login
│   │   │
│   │   ├── components/                  # 31 React components
│   │   │   ├── ui/                     # Primitives (button, card, etc.)
│   │   │   ├── Sidebar.tsx
│   │   │   ├── PipelineView.tsx
│   │   │   ├── PipelineBoard.tsx
│   │   │   ├── PipelineTable.tsx
│   │   │   ├── GrantCard.tsx
│   │   │   ├── GrantDetailSheet.tsx
│   │   │   ├── GrantDetailPage.tsx
│   │   │   ├── ScoreRadar.tsx
│   │   │   ├── ActivityChart.tsx
│   │   │   └── ...
│   │   │
│   │   ├── hooks/                       # Custom hooks
│   │   │   ├── usePusher.ts
│   │   │   ├── useGrantUrl.ts
│   │   │   └── useLastSeen.ts
│   │   │
│   │   └── lib/                         # Utilities
│   │       ├── api.ts                  # Frontend API client
│   │       ├── auth.ts                 # NextAuth config
│   │       ├── mongodb.ts              # MongoDB connection
│   │       ├── queries.ts              # Server-side queries
│   │       ├── utils.ts                # Formatters + helpers
│   │       └── pusher.ts               # Pusher client
│   │
│   ├── next.config.mjs
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── Dockerfile
│   ├── railway.toml
│   └── package.json
│
├── grants_application_reference/        # 8 reference grants
├── .env.example                         # Environment template
├── README.md                            # Project overview
├── ARCHITECTURE.md                      # Architecture docs
├── SYSTEM_DESIGN.md                     # System design
└── pytest.ini                           # Test config
```

---

## 5. Backend Deep Dive

### 5.1 FastAPI Application

**File:** `backend/main.py`

The main application file contains 70+ route handlers organized by domain.

#### Route Categories

**Discovery & Scoring:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/run/scout` | `manual_scout()` | Trigger grant discovery |
| POST | `/run/analyst` | `manual_analyst()` | Score discovered grants |
| POST | `/run/analyst/rescore` | `rescore_analyst()` | Bulk re-score all grants |
| POST | `/run/analyst/rescore/{grant_id}` | `rescore_single_grant()` | Re-score one grant |
| GET | `/status/scout` | `scout_status()` | Scout agent status |
| GET | `/status/analyst` | `analyst_status()` | Analyst agent status |

**Triage & Pipeline:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/resume/triage` | `resume_triage()` | Human triage decision |
| POST | `/update/grant-status` | `update_grant_status_api()` | Change grant status |
| POST | `/grants/manual` | `add_manual_grant()` | Manually add a grant |
| POST | `/grants/replay` | `replay_grant()` | Replay grant through pipeline |

**Drafting:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/resume/start-draft` | `start_draft()` | Begin draft pipeline |
| POST | `/drafter/chat` | `drafter_chat()` | Interactive draft discussion |
| POST | `/drafter/chat/stream` | `drafter_chat_stream()` | Streaming draft responses |
| GET | `/drafter/chat-history/{pipeline_id}` | `get_chat_history()` | Get chat history |
| GET | `/drafter/chat-sessions/{pipeline_id}` | `list_chat_sessions()` | List sessions |
| POST | `/drafter/chat-sessions/{id}/{snap}/restore` | `restore_chat_snapshot()` | Restore snapshot |
| PUT | `/drafter/chat-history` | `save_chat_history()` | Save history |
| DELETE | `/drafter/chat-history/{id}/{section}` | `clear_section_history()` | Clear section chat |
| POST | `/resume/section-review` | `resume_section_review()` | Human section approval |
| GET | `/draft/{grant_id}/content` | `get_draft_content()` | Fetch draft sections |
| GET | `/drafts/{thread_id}/download` | `download_draft()` | Export PDF/DOCX |
| POST | `/drafter/intelligence-brief` | `intelligence_brief()` | Generate brief |

**Review & Outcomes:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/review/run` | `run_review()` | Execute reviewer |
| GET | `/review/{grant_id}` | `get_reviews()` | Fetch review report |
| POST | `/review/apply-suggestions` | `apply_suggestions()` | Apply reviewer feedback |
| POST | `/outcomes/record` | `record_grant_outcome()` | Log grant results |
| GET | `/outcomes/{grant_id}` | `get_grant_outcome()` | Get outcome |
| GET | `/outcomes/funder/{funder}` | `get_funder_insights_endpoint()` | Funder insights |

**Admin & Infrastructure:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| POST | `/cron/scout` | `cron_scout()` | Scheduled scout (requires cron_secret) |
| POST | `/cron/knowledge-sync` | `cron_knowledge_sync()` | Scheduled Notion sync |
| POST | `/run/knowledge-sync` | `manual_knowledge_sync()` | Manual knowledge sync |
| POST | `/run/sync-profile` | `manual_sync_profile()` | Re-sync AltCarbon profile |
| POST | `/run/sync-past-grants` | `sync_past_grants()` | Sync past grants |
| POST | `/admin/backfill-fields` | `admin_backfill_fields()` | Backfill missing fields |
| POST | `/admin/deduplicate` | `admin_deduplicate()` | Remove duplicates |
| POST | `/admin/notion-backfill` | `admin_notion_backfill()` | Notion backfill |
| GET | `/health` | `health()` | Health check |

**MCP & System Health:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/status/mcp` | `mcp_hub_status()` | MCP connection health |
| GET | `/status/mcp/{server}/tools` | `mcp_server_tools()` | List server tools |
| POST | `/run/mcp/{server}/reconnect` | `reconnect_mcp_server()` | Reconnect server |
| POST | `/run/mcp/reconnect-all` | `reconnect_all_mcp()` | Reconnect all MCP |
| POST | `/run/notion-mcp/reconnect` | `reconnect_notion_mcp()` | Reconnect Notion MCP |
| GET | `/status/notion-mcp` | `notion_mcp_status()` | Notion MCP status |

**Knowledge & Monitoring:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/status/knowledge-sources` | `knowledge_sources_status()` | Knowledge health |
| GET | `/status/knowledge-pending` | `knowledge_pending()` | Pending syncs |
| GET | `/status/documents-list` | `documents_list_status()` | Documents index |
| GET | `/status/table-of-content` | `table_of_content_status()` | ToC status |
| GET | `/status/pipeline` | `pipeline_status()` | Pipeline overview |
| GET | `/status/scheduler` | `scheduler_status()` | Scheduler status |
| GET | `/status/thread/{thread_id}` | `thread_status()` | Thread status |
| GET | `/status/api-health` | `api_health_status()` | API health |
| GET | `/status/skills` | `skills_status()` | Skills overview |
| GET | `/status/skills/{agent}` | `agent_skills()` | Per-agent skills |

**Notifications:**
| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/notifications` | `list_notifications()` | List notifications |
| GET | `/notifications/count` | `notification_count()` | Unread count |
| POST | `/notifications/read` | `mark_notifications_read()` | Mark read |
| POST | `/notifications/read-all` | `mark_all_notifications_read()` | Mark all read |
| POST | `/webhooks/notion` | `notion_webhook()` | Notion webhook |
| POST | `/api/notion-webhook/triage` | `notion_webhook_triage()` | Triage webhook |
| POST | `/api/notion-webhook/section-review` | `notion_webhook_section_review()` | Section review webhook |

#### Request Models (Pydantic)

```python
class TriageResumeRequest(BaseModel):
    thread_id: str
    grant_id: str
    decision: str          # "pursue" | "watch" | "pass"
    notes: Optional[str]

class StartDraftRequest(BaseModel):
    grant_id: str
    thread_id: Optional[str]

class DrafterChatRequest(BaseModel):
    pipeline_id: str
    section_name: str
    message: str
    model: Optional[str]

class ManualGrantRequest(BaseModel):
    title: str
    funder: str
    url: str
    funding_amount: Optional[str]
    deadline: Optional[str]
    description: Optional[str]

class RunReviewRequest(BaseModel):
    grant_id: str
    thread_id: Optional[str]

class ApplySuggestionsRequest(BaseModel):
    grant_id: str
    accepted_suggestions: list[str]
    rejected_suggestions: list[str]

class RecordOutcomeRequest(BaseModel):
    grant_id: str
    outcome: str           # "won" | "lost" | "pending"
    amount_received: Optional[float]
    notes: Optional[str]
```

---

### 5.2 LangGraph Pipeline

#### State Definition

**File:** `backend/graph/state.py`

```python
class GrantState(TypedDict):
    # Discovery
    raw_grants: list[dict]
    scout_status: str
    scout_error: Optional[str]

    # Knowledge
    company_context: str
    company_brain_status: str

    # Scoring
    scored_grants: list[dict]
    analyst_status: str

    # Triage
    triage_decision: str        # "pursue" | "watch" | "pass"
    triage_notes: str
    current_grant: dict

    # Drafting
    grant_requirements: dict     # Parsed grant doc
    sections_required: list[str]
    current_section_index: int
    approved_sections: dict      # {name: {content, word_count, revision_count}}
    section_critiques: dict      # {name: critique_text}
    pending_interrupt: dict      # For human review
    section_edited_content: str  # Human-edited version
    drafter_status: str

    # Review
    reviewer_output: dict
    reviewer_status: str

    # Pipeline
    pipeline_id: str
    thread_id: str
    status: str
    error: Optional[str]
```

#### Graph Builder

**File:** `backend/graph/graph.py`

The graph is compiled with 13 nodes and 3 conditional edges:

```python
def build_graph() -> StateGraph:
    graph = StateGraph(GrantState)

    # Add nodes
    graph.add_node("scout", scout_node)
    graph.add_node("company_brain_load", company_brain_load_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("pre_triage_guardrail", pre_triage_guardrail_node)
    graph.add_node("notify_triage", notify_triage_node)
    graph.add_node("human_triage", human_triage_node)
    graph.add_node("company_brain", company_brain_node)
    graph.add_node("grant_reader", grant_reader_node)
    graph.add_node("draft_guardrail", draft_guardrail_node)
    graph.add_node("drafter", drafter_node)
    graph.add_node("export", exporter_node)
    graph.add_node("reviewer", dual_reviewer_node)
    graph.add_node("pipeline_update", pipeline_update_node)

    # Linear edges
    graph.add_edge(START, "scout")
    graph.add_edge("scout", "company_brain_load")
    graph.add_edge("company_brain_load", "analyst")
    graph.add_edge("analyst", "pre_triage_guardrail")
    graph.add_edge("pre_triage_guardrail", "notify_triage")
    graph.add_edge("notify_triage", "human_triage")

    # Conditional edges
    graph.add_conditional_edges("human_triage", route_triage)
    graph.add_conditional_edges("draft_guardrail", route_after_guardrail)
    graph.add_conditional_edges("drafter", route_after_drafter)

    # Post-triage
    graph.add_edge("company_brain", "grant_reader")
    graph.add_edge("grant_reader", "draft_guardrail")
    graph.add_edge("export", "reviewer")
    graph.add_edge("reviewer", END)
    graph.add_edge("pipeline_update", END)

    return graph
```

#### Routing Functions

**File:** `backend/graph/router.py`

```python
def route_triage(state: GrantState) -> str:
    """Only 'pursue' goes to company_brain; else pipeline_update"""
    if state["triage_decision"] == "pursue":
        return "company_brain"
    return "pipeline_update"

def route_after_guardrail(state: GrantState) -> str:
    """If guardrail passed, proceed to drafter; else pipeline_update"""
    if state.get("drafter_status") == "guardrail_passed":
        return "drafter"
    return "pipeline_update"

def route_after_drafter(state: GrantState) -> str:
    """If all sections approved, export; else loop back to drafter"""
    if state["current_section_index"] >= len(state["sections_required"]):
        return "export"
    return "drafter"
```

#### Checkpointer

**File:** `backend/graph/checkpointer.py`

Custom MongoDB-backed checkpoint saver:

```python
class MongoCheckpointSaver:
    """Saves LangGraph state to MongoDB for pipeline resumption."""

    collection: str = "graph_checkpoints"

    async def put(self, thread_id: str, checkpoint_id: str, state: dict, metadata: dict):
        """Save checkpoint (upsert on thread_id + checkpoint_id)"""

    async def get(self, thread_id: str) -> Optional[dict]:
        """Get latest checkpoint for thread"""

    async def list(self, thread_id: str) -> list[dict]:
        """List all checkpoints for thread (sorted by timestamp)"""
```

**How it works:**
- Before each node, LangGraph saves the full `GrantState` to MongoDB
- On interrupt (triage, section review), the graph halts and state is persisted
- When resumed (via `/resume/triage` or `/resume/section-review`), the graph loads from checkpoint and continues

---

### 5.3 Agents

#### 5.3.1 Scout Agent

**File:** `backend/agents/scout.py`

**Purpose:** Discover new grant opportunities from multiple search backends.

**Search Sources:**

| Source | Type | Query Templates |
|--------|------|-----------------|
| Tavily | Web search | 8 templates (climate, biochar, ERW, CDR, etc.) |
| Exa | Semantic search | 10 templates |
| Perplexity | AI research | Via API + gateway |
| Direct crawl | RFP sites | RFPs.org, grants.gov, foundation websites |

**Enrichment Pipeline:**
1. For each discovered URL:
   - `_fetch_content()` — tries Jina Reader → plain HTTP → Cloudflare browser rendering
   - `_extract_grant_fields()` — Claude extracts: title, funder, deadline, funding, URL, description
2. Concurrent enrichment: 4 parallel tasks, 45s timeout per grant
3. Deduplication: URL hash → normalized URL → content hash

**Key Class:**
```python
class ScoutAgent:
    async def run(self, state: GrantState) -> dict:
        """Main orchestration: queries → enrichment → dedup → return raw_grants"""

    async def enrich(self, url: str) -> dict:
        """Fetch page content + extract structured fields"""

    async def safe_enrich(self, url: str) -> Optional[dict]:
        """enrich() with timeout + error handling"""
```

**Output:** `raw_grants[]` → list of discovered grants with structured fields

---

#### 5.3.2 Analyst Agent

**File:** `backend/agents/analyst.py`

**Purpose:** Score each discovered grant against AltCarbon's mission on 6 dimensions.

**Scoring Dimensions (weighted, sum = 1.0):**

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| `theme_alignment` | 0.25 | Match to AltCarbon's 6 themes |
| `eligibility_confidence` | 0.20 | How well AltCarbon fits eligibility |
| `funding_amount` | 0.20 | Attractiveness of funding size |
| `deadline_urgency` | 0.15 | Time remaining to apply |
| `geography_fit` | 0.10 | UK/India geographic match |
| `competition_level` | 0.10 | Expected competition level |

**Per-Grant Scoring Flow:**
1. **Pre-check:** Skip if already scored (idempotent)
2. **Hard rules:** Auto-pass if any fail:
   - Deadline < 30 days away
   - Funding < $3,000
   - Geography outside UK/India
   - Theme mismatch with all 6 themes
3. **Funder enrichment:** Perplexity lookup (cached 3 days in `funder_context_cache`)
4. **LLM scoring:** Claude Opus scores all 6 dimensions (JSON output, max_tokens=2048)
5. **Calculate weighted total:** Sum of (score × weight) per dimension
6. **Determine action:**
   - `weighted_total >= 6.5` → **pursue**
   - `weighted_total >= 5.0` → **watch**
   - `weighted_total < 5.0` → **pass**
7. **Upsert** to `grants_scored` (keyed on url_hash)
8. **Write audit** entry

**Red Flag System:**
- Each red flag applies a penalty (default: 0.5, max cumulative: 2.0)
- Red flags: vague eligibility, very high competition, geographic restrictions, etc.

**Key Function:**
```python
async def analyst_node(state: GrantState) -> dict:
    """Score all raw_grants, return scored_grants with recommendations"""
```

---

#### 5.3.3 Company Brain Agent

**File:** `backend/agents/company_brain.py`

**Purpose:** Retrieve and contextualize AltCarbon knowledge for grant-specific needs.

**Knowledge Sources (priority order):**
1. **Static profile** — `backend/knowledge/altcarbon_profile.md` (9.5K chars, always available)
2. **Notion MCP search** — live search of Knowledge Connections + key pages
3. **MongoDB chunks** — `knowledge_chunks` collection (vectorized sections)
4. **Fallback** — if MCP unavailable, use static profile only

**Two modes:**
- `company_brain_load_node()` — early pipeline: loads static company profile (cached)
- `company_brain_node()` — after triage: searches Notion for grant-specific context

**Knowledge Chunking:**
- `chunk_size`: 400 words
- `chunk_overlap`: 80 words
- `min_chunk_words`: 40
- Each chunk tagged by `doc_type` and `themes[]` via Claude

**Key Notion Pages Indexed (9 total):**
1. Introducing Alt Carbon
2. MRV Moat
3. Vision & Comms
4. Darjeeling Revival Project (DRP)
5. Bengal Renaissance Project (BRP)
6. Biochar Expansion
7. Gigaton Scale
8. Shopify Report
9. Brand Guidebook

**Output:** `company_context` → formatted string of relevant AltCarbon facts/projects/metrics

---

#### 5.3.4 Drafter Agent

**Files:** `backend/agents/drafter/` (6 files)

**Purpose:** Write each section of the grant application iteratively with self-critique.

**Components:**

| File | Purpose |
|------|---------|
| `drafter_node.py` | Main loop orchestration |
| `section_writer.py` | LLM section generation |
| `grant_reader.py` | Parse grant document, extract sections/criteria |
| `draft_guardrail.py` | Validate grant is draftable |
| `exporter.py` | Save to MongoDB + Google Drive |
| `theme_profiles.py` | Theme-specific writing guidance |

**Per-Section Flow:**
```
1. Load theme profile (e.g., "climatetech" → tone, evidence types)
2. Build criteria map (section → evaluator expectations)
3. Call Claude to write section (with company context + style examples)
4. Generate self-critique (coherence, evidence, clarity scores)
5. If critique < revision_threshold (6.0):
   → Generate revision instructions
   → Loop back to step 3 (max 3 attempts)
6. If approved OR max attempts reached:
   → Store in approved_sections
   → Interrupt for human review (pending_interrupt)
7. Human reviews:
   → "approve" → move to next section
   → "revise" → incorporate edit, re-critique, loop
8. After all sections approved:
   → Route to export
```

**Theme Profiles:**
Each of AltCarbon's 6 themes has specific writing guidance:
- `display_name`, `description`, `tone`
- `evidence_types` (what kind of evidence to cite)
- `common_criteria` (what evaluators look for)

**12-Section Articulation Structure:**
1. Problem Statement
2. Literature Review
3. Solution
4. Why Best Suited
5. Collaborators
6. Outputs
7. Outcomes
8. Project Plan
9. Co-benefits
10. Unit Economics
11. Pricing
12. Budget

**State Updates per section:**
```python
{
    "current_section_index": int,
    "approved_sections": {
        "section_name": {
            "content": str,
            "word_count": int,
            "revision_count": int
        }
    },
    "section_critiques": {"section_name": str},
    "pending_interrupt": {
        "section_name": str,
        "content": str,
        "critique": str
    }
}
```

---

#### 5.3.5 Reviewer Agent

**Files:** `backend/agents/reviewer.py` + `backend/agents/dual_reviewer.py`

**Purpose:** Score the complete draft and produce actionable feedback.

**Three Review Dimensions:**

| Dimension | What it evaluates | Score Range |
|-----------|------------------|-------------|
| Funder-centric | Does draft match funder's stated priorities? | 1-10 |
| Scientific credibility | Is evidence rigorous and well-sourced? | 1-10 |
| Coherence | Do sections tell a consistent story? | 1-10 |

**Web Research during review:**
- Latest company announcements
- Funder's recent funding decisions
- Competitive landscape
- Third-party validations

**Output:**
```python
reviewer_output = {
    "funder_score": float,
    "funder_notes": str,
    "credibility_score": float,
    "credibility_notes": str,
    "coherence_score": float,
    "coherence_notes": str,
    "overall_score": float,
    "ready_for_export": bool,  # True if overall >= 6.5
    "summary": str,
    "suggested_revisions": list[str]
}
```

**Thresholds:**
- `revision_threshold`: 6.0 — any dimension below this flags for revision
- `export_threshold`: 6.5 — overall score must meet this to be "ready"

**Accept/Reject Flow:**
- POST `/review/apply-suggestions` with accepted + rejected suggestion IDs
- Accepted suggestions are applied to draft sections automatically
- Rejected suggestions are logged with reason

---

### 5.4 Integrations

#### 5.4.1 Notion MCP Client

**File:** `backend/integrations/notion_mcp.py`

Wraps the MCP Hub to provide a high-level Notion API:

```python
class NotionMCPClient:
    async def search(self, query: str, page_size: int = 100) -> list[dict]:
        """Search Notion pages"""

    async def fetch_page(self, page_id: str) -> str:
        """Fetch page as markdown"""

    async def create_page(self, parent_id, title, content, properties) -> str:
        """Create new Notion page"""

    async def update_page(self, page_id, content, properties) -> bool:
        """Update existing page"""

    async def query_data_source(self, ds_id, filter, sorts) -> list[dict]:
        """Query a Notion database"""
```

**Connection:** Spawned as Node.js subprocess (`@notionhq/notion-mcp-server`), managed by MCP Hub. Auto-reconnects on failure.

---

#### 5.4.2 MCP Hub

**File:** `backend/integrations/mcp_hub.py`

Generic multi-server MCP client:

```python
class MCPHub:
    async def connect_all(self) -> None:
        """Spawn all enabled MCP servers (called at FastAPI startup)"""

    async def disconnect_all(self) -> None:
        """Cleanup all connections (called at shutdown)"""

    async def call_tool(self, server: str, tool: str, args: dict) -> Any:
        """Call a tool on a specific server"""

    async def list_tools(self, server: str) -> list[str]:
        """List available tools on a server"""

    async def health(self) -> dict:
        """Health status of all servers"""

    def is_connected(self, server: str) -> bool:
        """Check if server is connected"""
```

**Configuration:** `backend/config/mcp_servers.yaml`

```yaml
servers:
  notion:
    command: npx
    args: ["@notionhq/notion-mcp-server"]
    env_map:
      NOTION_TOKEN: NOTION_TOKEN
    required_env: [NOTION_TOKEN]
    enabled: true
    tags: [knowledge, sync]
```

---

#### 5.4.3 Notion Sync (Write Operations)

**File:** `backend/integrations/notion_sync.py`

Writes data back to Notion using the `notion-client` Python SDK:

| Function | Target DB | What it syncs |
|----------|-----------|---------------|
| `sync_grant_pipeline()` | Grant Pipeline | Grant details after scout/analyst |
| `log_agent_run()` | Agent Runs | Agent execution logs |
| `log_error()` | Error Logs | Exceptions + tracebacks |
| `log_triage_decision()` | Triage Decisions | Human triage choices |
| `sync_draft_section()` | Draft Sections | Completed draft sections |
| `update_knowledge_connection()` | Knowledge Connections | Sync status tracking |

---

#### 5.4.4 Notion Config

**File:** `backend/integrations/notion_config.py`

Maps Notion database IDs and field mappings:

```python
# Database IDs
GRANT_PIPELINE_DS    = "8e9cd5d9-0239-4072-8233-6006aa184e48"
AGENT_RUNS_DS        = "6848a08a-a5ab-4627-989b-22dac3195f42"
ERROR_LOGS_DS        = "2149b3a1-aa9c-456d-8daf-fce6858807be"
TRIAGE_DECISIONS_DS  = "3fc6834d-18b2-4e95-91dc-06ccca42b679"
DRAFT_SECTIONS_DS    = "c244df69-d74e-4703-ac88-d506c85aabe2"
KNOWLEDGE_CONNECTIONS_DS = "1ce5cd69-d174-40bc-9c6a-8277e7a692a4"
DOCUMENTS_LIST_DS    = "30d50d0e-c20e-8062-bdb6-000b82620d34"
MISSION_CONTROL_PAGE = "30b50d0e-c20e-8057-aee5-f775b9902c95"

# Theme mappings, status mappings, field name mappings
THEME_MAP = {...}
STATUS_MAP = {...}
```

---

### 5.5 Database Layer

**File:** `backend/db/mongo.py`

MongoDB connection using Motor (async) with collection accessors:

```python
async def get_db() -> AsyncIOMotorDatabase:
    """Returns 'altcarbon_grants' database"""

# Collection accessors (18 total)
def grants_raw_col()           # Discovered grants
def grants_scored_col()        # Scored grants
def grants_pipeline_col()      # Notion sync status
def grant_drafts_col()         # Completed drafts
def draft_reviews_col()        # Reviewer output
def graph_checkpoints_col()    # LangGraph state snapshots
def knowledge_chunks_col()     # Company brain indexed knowledge
def knowledge_sync_logs_col()  # Sync history
def funder_context_cache_col() # Perplexity enrichment cache (TTL: 3 days)
def agent_config_col()         # Agent settings
def audit_logs_col()           # Detailed event log
def scout_runs_col()           # Per-run tracking
def golden_examples_col()      # Past successful grant sections
def drafter_chat_history_col() # Interactive draft chats
def notion_page_cache_col()    # Cached Notion results
def draft_preferences_col()    # User preferences
def chat_snapshots_col()       # Saved conversation states
def grant_outcomes_col()       # Submission results
```

---

### 5.6 LLM Utilities

**File:** `backend/utils/llm.py`

#### Available Models

| Constant | Model ID | Usage |
|----------|----------|-------|
| `OPUS` | `anthropic/claude-opus-4-6` | Heavy: scoring, deep research |
| `SONNET` | `anthropic/claude-sonnet-4-6` | Medium: extraction, drafting |
| `HAIKU` | `anthropic/claude-haiku-4-5` | Light: tagging, validation |
| `GPT_5_4` | `openai/gpt-5.4` | Fallback tier |

#### Per-Agent Default Models

| Agent | Default Model | Use Case |
|-------|--------------|----------|
| Scout | GPT-5.4 | Extraction/scraping |
| Analyst (heavy) | Opus | 6D scoring, deep research |
| Analyst (light) | Haiku | Funder enrichment |
| Company Brain | GPT-5.4 | Chunk tagging |
| Drafter | GPT-5.4 | Section writing |
| Reviewer | Sonnet | Evaluation |

#### Core Chat Function

```python
async def chat(
    prompt: str,
    model: str = SONNET,
    system: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """Send prompt to LLM via AI Gateway or direct Anthropic API"""
```

#### Automatic Fallback Chain

When a model's credits are exhausted (429/402/quota error):
1. Try fallback model from `_FALLBACK_CHAINS[primary_model]`
2. Mark exhausted model with 60s cooldown
3. Log fallback event to Notion Mission Control
4. If ALL models exhausted → raise `CreditExhaustedError`

#### Client Configuration

The LLM client is OpenAI-compatible, pointing to either:
- **Vercel AI Gateway** (`AI_GATEWAY_URL` + `AI_GATEWAY_API_KEY`) — primary
- **Direct Anthropic API** (`ANTHROPIC_API_KEY`) — fallback

---

### 5.7 Skills Registry

**File:** `backend/skills/registry.py`

**Config:** `backend/config/skills.yaml`

A capability discovery + execution system with provider fallback:

```python
class SkillRegistry:
    async def execute(self, skill_name: str, **kwargs) -> Any:
        """Execute a skill with automatic provider fallback"""

    def for_agent(self, agent_name: str) -> list[dict]:
        """List skills available to a specific agent"""
```

**Provider Types:**
| Type | Description |
|------|-------------|
| `mcp` | Call tool on MCP server |
| `api` | Call Python async function |
| `internal` | Same as `api` |
| `static` | Call Python sync function |

**Example Skill Definition:**
```yaml
fetch_page:
  description: "Fetch a web page or Notion page content"
  category: "fetch"
  agents: ["scout", "company_brain", "drafter"]
  enabled: true
  providers:
    - name: "notion_mcp"
      type: "mcp"
      server: "notion"
      tool: "API-retrieve-page"
    - name: "jina_fallback"
      type: "api"
      function: "backend.utils.browser.fetch_url"
```

---

### 5.8 Jobs & Scheduling

**Files:** `backend/jobs/`

| File | Purpose |
|------|---------|
| `scheduler.py` | APScheduler setup (interval + cron triggers) |
| `scout_job.py` | Runs scout every 48 hours |
| `knowledge_job.py` | Runs knowledge sync daily |
| `backfill_job.py` | On-demand backfill operations |

**Cron Schedule:**
| Job | Frequency | Vercel Cron |
|-----|-----------|-------------|
| Scout discovery | Every 48 hours | `0 2 */2 * *` |
| Analyst scoring | Every 48 hours (after scout) | `0 4 */2 * *` |
| Knowledge sync | Daily | `0 6 * * *` |

---

### 5.9 Configuration & Settings

**File:** `backend/config/settings.py`

Pydantic Settings with 50+ environment variables:

#### Database
| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | required | MongoDB Atlas connection string |

#### AI Models
| Variable | Default | Description |
|----------|---------|-------------|
| `AI_GATEWAY_URL` | `https://ai-gateway.vercel.sh/v1` | Vercel AI Gateway |
| `AI_GATEWAY_API_KEY` | — | Gateway API key |
| `ANTHROPIC_API_KEY` | — | Fallback Anthropic key |
| `SCOUT_MODEL` | — | Override scout model |
| `ANALYST_HEAVY_MODEL` | — | Override analyst model |
| `DRAFTER_MODEL` | — | Override drafter model |

#### Search APIs
| Variable | Required | Description |
|----------|----------|-------------|
| `TAVILY_API_KEY` | Yes | Web search |
| `EXA_API_KEY` | No | Semantic search |
| `PERPLEXITY_API_KEY` | No | AI research |
| `JINA_API_KEY` | No | Page fetching |

#### Notion
| Variable | Required | Description |
|----------|----------|-------------|
| `NOTION_TOKEN` | Yes | Notion API token |
| `NOTION_KNOWLEDGE_BASE_PAGE_ID` | No | Scope sync to page |
| `NOTION_WEBHOOK_SECRET` | No | Webhook HMAC secret |

#### Agent Tuning
| Variable | Default | Description |
|----------|---------|-------------|
| `SCOUT_FREQUENCY_HOURS` | 48 | Discovery frequency |
| `PURSUE_THRESHOLD` | 6.5 | Min score to recommend "pursue" |
| `WATCH_THRESHOLD` | 5.0 | Min score for "watch" |
| `MIN_GRANT_FUNDING` | 3000 | Min funding in USD |
| `DEADLINE_URGENT_DAYS` | 30 | Days threshold for deadline urgency |
| `DEFAULT_SECTION_WORD_LIMIT` | 500 | Default section word limit |
| `MAX_REVISION_ATTEMPTS` | 3 | Max drafting revisions per section |
| `REVIEWER_REVISION_THRESHOLD` | 6.0 | Score below which section needs revision |
| `REVIEWER_EXPORT_THRESHOLD` | 6.5 | Score needed to pass export |

#### Scoring Weights
```python
SCORING_WEIGHTS = {
    "theme_alignment": 0.25,
    "eligibility_confidence": 0.20,
    "funding_amount": 0.20,
    "deadline_urgency": 0.15,
    "geography_fit": 0.10,
    "competition_level": 0.10,
}
```

---

### 5.10 Error Handling

**Multi-layer strategy:**

1. **Python Logging** — Standard `logging` module per file
2. **Notion Mission Control** — Critical errors logged via `log_error()`
3. **MongoDB Audit Logs** — All agent runs + state transitions recorded
4. **API Health Tracking** — External API failures tracked with cooldowns

**Common Pattern:**
```python
try:
    result = await agent_call()
except CreditExhaustedError:
    # Handled by fallback chain in llm.py
    pass
except Exception as e:
    logger.error("Error in %s: %s", agent_name, e, exc_info=True)
    await log_error(agent=agent_name, error=e, tb=traceback.format_exc())
```

**API Health Tracker** (`backend/utils/parsing.py`):
- Singleton: `api_health`
- Detects exhaustion signals (429, 402, quota errors)
- Per-API cooldown (60s)
- Tracks: Tavily, Exa, Jina, Perplexity

**JSON Parsing Safety** (`parse_json_safe()`):
- Handles code fences (```` ```json ````)
- Handles prose prefix before JSON
- Handles array wrapping
- Returns empty dict on failure (never crashes)

**Async Retry** (`retry_async()`):
- Exponential backoff
- Configurable max attempts (default: 3)
- Used for all LLM and API calls

---

## 6. Frontend Deep Dive

### 6.1 Pages

| Page | Path | Description |
|------|------|-------------|
| Login | `/login` | Google OAuth (altcarbon.com only) |
| Dashboard | `/dashboard` | KPI cards, activity chart, warnings banner |
| Pipeline | `/pipeline` | Kanban board + table view of all grants |
| Triage | `/triage` | Queue for new grants needing human triage |
| Grant Detail | `/grants/[id]` | Full grant detail with comments, activity |
| Drafter | `/drafter` | Draft writing interface |
| Drafter Settings | `/drafter/settings` | Configure drafter parameters |
| Reviewers | `/reviewers` | Review compliance/quality of drafts |
| Reviewer Settings | `/reviewers/settings` | Configure reviewer criteria |
| Config | `/config` | Agent configuration editor |
| Knowledge | `/knowledge` | Knowledge base health + sync |
| Audit | `/audit` | Audit/activity log |
| Monitoring | `/monitoring` | Mission Control dashboard |

---

### 6.2 Components

#### Layout & Navigation

**`Sidebar.tsx`** — Dark sidebar with navigation links:
- Dashboard, Pipeline, Drafter, Reviewers, Knowledge, Audit
- Theme: `#0f172a` bg, `#1e293b` hover, `#1d4ed8` active

**`SessionProvider.tsx`** — NextAuth wrapper

**`Toast.tsx`** — Context-based toast notifications:
- Types: success, error, warning, info
- Auto-dismisses after 4-6s
- Fixed bottom-left position

#### Grant Display Components

**`GrantCard.tsx`** — Compact card showing:
- Title, funder, funding amount
- Score badge, priority badge, theme labels
- Deadline chip, status badge

**`GrantDetailSheet.tsx`** — Modal view with:
- Deep analysis, eligibility details
- Contact info, past winners
- Full scoring radar chart

**`GrantDetailPage.tsx`** — Full page view with:
- Comments thread, activity timeline
- Agent controls, status picker
- Draft content viewer

**`ScoreRadar.tsx`** — Recharts radar chart of 6 scoring dimensions

**`ScoreBadge.tsx`** — Color-coded score display:
- Green: score >= 6.5
- Amber: score 5.0–6.5
- Red: score < 5.0

**`StatusBadge.tsx`** — Status labels:
- triage → "Shortlisted"
- pursue → "Pursue"
- drafting → "Drafting"
- draft_complete → "Draft Complete"

**`PriorityBadge.tsx`** — Priority (High/Medium/Low based on score)

**`DeadlineChip.tsx`** — Days-to-deadline with urgency color

#### Pipeline Components

**`PipelineView.tsx`** — Toggle between board and table views with filters

**`PipelineBoard.tsx`** — Kanban board with drag-and-drop:
- 6 columns: Shortlisted, Pursue, Hold, Drafting, Submitted, Rejected
- Uses `@hello-pangea/dnd`

**`PipelineTable.tsx`** — Sortable, paginated table:
- Status tabs for filtering
- Search by title/funder
- 50 items per page

**`StatusPicker.tsx`** — Dropdown to change grant status

**`ManualGrantEntry.tsx`** — Form to manually add a grant

**`Pagination.tsx`** — Page navigation

#### Dashboard Components

**`ActivityChart.tsx`** — Recharts line chart of grants discovered over time

**`WarningsBanner.tsx`** — Alert banner for:
- Urgent deadlines, empty shortlist
- Agent errors, stale knowledge

**`WhatsNewDigest.tsx`** — "Returning user" summary of recent activity

**`NotificationBell.tsx`** — Bell icon with unread count (Pusher-driven)

#### Drafter & Review

**`DrafterSettings.tsx`** — Configure drafter parameters (tone, focus)

**`ReviewerSettingsPanel.tsx`** — Configure reviewer criteria:
- Compliance, writing quality, outcome calibration

**`CommentThread.tsx`** — Nested comments on grant detail

**`GrantActivity.tsx`** — Timeline of agent actions

#### Agent Controls

**`AgentControls.tsx`** — Buttons to trigger Scout, Analyst, Drafter agents

#### UI Primitives (shadcn-style)

| Component | File | Description |
|-----------|------|-------------|
| Button | `ui/button.tsx` | Variant component with CVA |
| Card | `ui/card.tsx` | Container with header/content/footer |
| Badge | `ui/badge.tsx` | Badge primitive |
| Input | `ui/input.tsx` | Text input |
| Textarea | `ui/textarea.tsx` | Multiline input |

---

### 6.3 API Routes

The frontend has 51 Next.js API routes that proxy requests to the FastAPI backend.

#### Core Grant Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/grants/[id]` | Fetch single grant |
| POST | `/api/grants/status` | Update grant status |
| POST | `/api/grants/manual` | Create manual grant |
| POST | `/api/grants/replay` | Replay grant processing |
| GET | `/api/grants/[id]/comments` | Get comments |
| POST | `/api/grants/[id]/comments` | Add comment |
| DELETE | `/api/grants/[id]/comments/[commentId]` | Delete comment |
| POST | `/api/grants/[id]/drafter-settings` | Save drafter config |
| POST | `/api/grants/[id]/reviewer-settings` | Save reviewer config |
| POST | `/api/grants/[id]/reanalyze` | Trigger re-analysis |

#### Drafter Routes
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/drafter/chat` | LLM chat for section editing |
| POST | `/api/drafter/chat-stream` | Streamed chat response |
| GET | `/api/drafter/chat-sessions` | List chat sessions |
| GET | `/api/drafter/chat-sessions/[id]` | Get session details |
| GET | `/api/drafter/chat-history` | Get full chat history |
| POST | `/api/drafter/trigger` | Start drafting for grant |
| POST | `/api/drafter/intelligence-brief` | Generate brief |
| POST | `/api/drafter/section-review` | Review draft section |

#### Monitoring Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/status/scheduler` | Cron job status |
| GET | `/api/status/mcp` | MCP connection status |
| GET | `/api/status/documents-list` | Documents index status |
| GET | `/api/config` | Agent configs |
| POST | `/api/admin` | Admin operations |
| GET | `/api/audit` | Audit log entries |
| GET | `/api/activity` | Activity feed |
| GET | `/api/discoveries` | Recent discoveries |

#### Cron Routes
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/cron/scout` | Trigger scout discovery |
| POST | `/api/cron/analyst` | Trigger analyst scoring |

#### Outcomes & Drafts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/draft/[grantId]/content` | Export draft content |
| GET | `/api/outcomes/[grantId]` | Get outcome metrics |
| POST | `/api/outcomes/record` | Record outcome |

---

### 6.4 Hooks

#### `usePusher(channelName, eventName, handler)`
**File:** `frontend/src/hooks/usePusher.ts`

Subscribes to a Pusher channel for real-time updates:
```typescript
usePusher("grants-channel", "grant:updated", (data) => {
    // Handle real-time grant update
    refreshGrants();
});
```
Automatically unbinds on component unmount.

#### `useGrantUrl()`
**File:** `frontend/src/hooks/useGrantUrl.ts`

Syncs selected grant ID with URL search params:
```typescript
const [selectedGrantId, setSelectedGrantId] = useGrantUrl();
// URL: /pipeline?grant=abc123&comment=xyz
```
Handles shared links and comment scrolling.

#### `useLastSeen()`
**File:** `frontend/src/hooks/useLastSeen.ts`

Tracks last visit timestamp in localStorage:
```typescript
const { lastSeenAt, markSeen } = useLastSeen();
const isNew = isNewSince(grant.created_at, lastSeenAt);
```

---

### 6.5 Libraries & Utilities

#### `lib/api.ts` — Frontend API Client

```typescript
async function apiGet<T>(path: string): Promise<T>
async function apiPost<T>(path: string, body: any): Promise<T>
function getHeaders(contentType?: string): HeadersInit
function proxyHeaders(): HeadersInit
```

All requests include `x-internal-secret` and `x-user-email` headers.

#### `lib/queries.ts` — Server-Side MongoDB Queries

```typescript
interface Grant {
    _id: string;
    title: string;
    funder: string;
    funding_amount: string;
    deadline: string;
    url: string;
    description: string;
    scores: Record<string, number>;
    weighted_total: number;
    recommended_action: string;
    status: string;
    theme: string;
    // ... 27+ fields total
}

async function getGrantById(id: string): Promise<Grant>
async function getPipelineGrants(): Promise<PipelineRecord[]>
async function getDashboardStats(): Promise<DashboardStats>
async function getGrantsActivity(days: number): Promise<ActivityData>
async function getReviewableGrants(): Promise<Grant[]>
async function getTriageQueue(): Promise<Grant[]>
async function getKnowledgeStatus(): Promise<KnowledgeStatus>
async function getSyncLogs(limit: number): Promise<SyncLog[]>
async function getAgentConfig(): Promise<AgentConfig>
```

#### `lib/utils.ts` — Utility Functions

```typescript
function cn(...classes): string                    // Tailwind class merging
function getPriority(score: number): PriorityInfo  // Score → priority + CSS
function getThemeLabel(key: string): ThemeLabel     // Theme → color + label
function formatCurrency(amount: number): string    // $1.2M, $500K, $3,000
function formatRelativeTime(iso: string): string   // "5m ago", "2h ago"
function formatDateShort(iso: string): string      // "Mar 20"
function formatChars(chars: number): string        // "1.5k", "500"
```

#### `lib/auth.ts` — NextAuth Configuration

```typescript
// Google OAuth provider
// Restricted to @altcarbon.com domain
// Callbacks: signIn (email check), authorized (redirect), session
// Custom pages: /login for signIn/error
```

#### `lib/mongodb.ts` — Connection Pooling

```typescript
async function getDb(): Promise<Db>
// Dev: global singleton (avoids hot-reload reconnects)
// Prod: per-request connection
// Database: "altcarbon_grants"
```

---

### 6.6 State Management

The frontend uses minimal state management:

1. **React Context:**
   - `ToastContext` — global notification system
   - `SessionProvider` — NextAuth session state

2. **URL State:**
   - `useGrantUrl()` — grant selection synced to URL params

3. **Local Storage:**
   - `useLastSeen()` — last visit timestamp

4. **Server State:**
   - Direct API calls (no React Query / SWR)
   - Page-level data fetching in Server Components

5. **Real-Time:**
   - Pusher events via `usePusher()` hook

---

### 6.7 Styling

**Framework:** Tailwind CSS 3.4 (utility-first, no CSS modules)

**Color System:**

| Context | Color | When |
|---------|-------|------|
| Score ≥ 6.5 | Green (`text-green-600`) | Pursue-worthy |
| Score 5.0–6.5 | Amber (`text-amber-600`) | Watch |
| Score < 5.0 | Red (`text-red-600`) | Pass |
| Triage status | Amber | Shortlisted |
| Pursue status | Green | Active pursuit |
| Drafting | Purple | In progress |
| Draft complete | Indigo | Ready for review |

**Theme Colors:**
| Theme | Color |
|-------|-------|
| Climate Tech | Teal |
| Agri Tech | Green |
| AI for Sciences | Purple |
| Earth Sciences | Blue |
| Social Impact | Orange |
| Deep Tech | Pink |

**Sidebar Theme:**
- Background: `#0f172a`
- Hover: `#1e293b`
- Active: `#1d4ed8`

**Key Libraries:**
- `clsx` + `tailwind-merge` → `cn()` utility
- `lucide-react` — icons
- `recharts` — charts (RadarChart, LineChart)
- `@hello-pangea/dnd` — drag-and-drop for Kanban

---

## 7. Data Flow

### Full Pipeline Flow

```
1. DISCOVERY (Scout Agent)
   ├─ Input: Search queries (Tavily, Exa, Perplexity)
   ├─ Process: Fetch → Extract → Deduplicate
   ├─ Output: raw_grants[] → MongoDB:grants_raw
   └─ Sync: Notion Grant Pipeline

2. SCORING (Analyst Agent)
   ├─ Input: raw_grants[]
   ├─ Process: Hard rules → Funder enrichment → 6D scoring
   ├─ Output: scored_grants[] → MongoDB:grants_scored
   ├─ Action: pursue (≥6.5) / watch (≥5.0) / pass (<5.0)
   └─ Sync: Notion Grant Pipeline (updated)

3. TRIAGE (Human Gate)
   ├─ Input: scored_grants with recommended_action
   ├─ Process: Human reviews in UI → decides pursue/watch/pass
   ├─ Output: triage_decision stored in state
   └─ Sync: Notion Triage Decisions

4. KNOWLEDGE (Company Brain)
   ├─ Input: current_grant + triage_decision="pursue"
   ├─ Process: Search Notion → Tag chunks → Build context
   ├─ Output: company_context string
   └─ Storage: MongoDB:knowledge_chunks

5. READING (Grant Reader)
   ├─ Input: grant URL/document
   ├─ Process: Parse → Extract sections, criteria, budget
   ├─ Output: grant_requirements → sections_required[]
   └─ Guardrail: draft_guardrail validates draftability

6. DRAFTING (Drafter Agent, per section)
   ├─ Input: section_name + company_context + theme_profile
   ├─ Process: Write → Self-critique → Revise (up to 3x)
   ├─ Output: approved_sections → MongoDB:grant_drafts
   ├─ Human gate: Each section reviewed/edited by user
   └─ Sync: Notion Draft Sections

7. EXPORT (Exporter)
   ├─ Input: all approved_sections
   ├─ Process: Compile → Save to MongoDB + Google Drive
   └─ Output: Complete draft document

8. REVIEW (Reviewer Agent)
   ├─ Input: complete draft + grant criteria
   ├─ Process: Funder + Scientific + Coherence scoring
   ├─ Output: reviewer_output → MongoDB:draft_reviews
   ├─ Action: ready_for_export (≥6.5) or revision needed
   └─ Sync: Notion (if applicable)
```

### Frontend → Backend Communication

```
React Component
  ↓ (client-side fetch)
Next.js API Route (/api/*)
  ↓ (proxy with headers: x-internal-secret, x-user-email)
FastAPI Backend
  ↓ (async MongoDB / MCP / LLM calls)
Response (JSON or SSE stream)
  ↓
React Component (re-render)
  + Pusher event (real-time update to all clients)
```

---

## 8. MongoDB Collections

**Database:** `altcarbon_grants`

| Collection | Purpose | Key Indexes |
|-----------|---------|-------------|
| `grants_raw` | Discovered grants (scout output) | url_hash, timestamp, funder |
| `grants_scored` | Scored grants (analyst output) | _id, url_hash, status, recommended_action, theme |
| `grants_pipeline` | Notion sync status | grant_id, status, last_synced |
| `grant_drafts` | Completed drafts | grant_id, thread_id, status, created_at |
| `draft_reviews` | Reviewer output | grant_id, created_at |
| `graph_checkpoints` | LangGraph state snapshots | thread_id, checkpoint_id |
| `knowledge_chunks` | Company brain indexed knowledge | grant_id, doc_type, themes |
| `knowledge_sync_logs` | Sync history | source_page_id, synced_at |
| `funder_context_cache` | Perplexity enrichment (3-day TTL) | funder_name, expires_at |
| `agent_config` | Agent settings | — |
| `audit_logs` | Detailed event log | agent, timestamp, grant_id |
| `scout_runs` | Per-run tracking | started_at |
| `golden_examples` | Past successful grant sections | theme, section_name |
| `drafter_chat_history` | Interactive draft chats | pipeline_id, section_name |
| `notion_page_cache` | Cached Notion results | page_id, expires_at |
| `draft_preferences` | User drafting preferences | — |
| `chat_snapshots` | Saved conversation states | pipeline_id, snapshot_id |
| `grant_outcomes` | Submission results | grant_id, outcome_date |

---

## 9. Environment Variables

### Required

```bash
# Database
MONGODB_URI=mongodb+srv://...

# AI (one of these pairs)
AI_GATEWAY_URL=https://ai-gateway.vercel.sh/v1
AI_GATEWAY_API_KEY=...
# OR
ANTHROPIC_API_KEY=sk-ant-...

# Search (at least Tavily)
TAVILY_API_KEY=tvly-...

# Notion
NOTION_TOKEN=ntn_...

# Frontend Auth
AUTH_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FASTAPI_URL=http://localhost:8000

# Real-time
PUSHER_APP_ID=...
NEXT_PUBLIC_PUSHER_KEY=...
PUSHER_SECRET=...
NEXT_PUBLIC_PUSHER_CLUSTER=...

# API Security
INTERNAL_SECRET=...
CRON_SECRET=...
```

### Optional

```bash
# Additional search
EXA_API_KEY=...
PERPLEXITY_API_KEY=...
JINA_API_KEY=...

# Vector DB
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=grants-engine

# Notion advanced
NOTION_KNOWLEDGE_BASE_PAGE_ID=...
NOTION_WEBHOOK_SECRET=...

# Browser rendering
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_BROWSER_TOKEN=...

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_TEAM_ID=T...

# Observability
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=altcarbon-grants
LANGCHAIN_TRACING_V2=false

# Model overrides
SCOUT_MODEL=...
ANALYST_HEAVY_MODEL=...
DRAFTER_MODEL=...
```

---

## 10. Deployment

### Railway (Production)

Two separate Railway services:

**Backend Service:**
```toml
# backend/railway.toml
[build]
  builder = "dockerfile"

[deploy]
  healthcheckPath = "/health"
  healthcheckTimeout = 300
  restartPolicyType = "on_failure"
```

Dockerfile: Python 3.11-slim + Node.js 20 (for Notion MCP) + Playwright Chromium

**Frontend Service:**
```toml
# frontend/railway.toml
[build]
  builder = "dockerfile"

[deploy]
  healthcheckPath = "/api/health"
  healthcheckTimeout = 120
```

Dockerfile: Node 20-alpine, multi-stage build (deps → builder → runner), standalone output

### Vercel Cron (Alternative)

```json
// frontend/vercel.json
{
  "crons": [
    { "path": "/api/cron/scout",   "schedule": "0 2 */2 * *" },
    { "path": "/api/cron/analyst", "schedule": "0 4 */2 * *" },
    { "path": "/api/cron/knowledge-sync", "schedule": "0 6 * * *" }
  ]
}
```

---

## 11. Authentication & Security

### Google OAuth (Frontend)
- Provider: NextAuth v5 with Google OAuth
- Restricted to `@altcarbon.com` domain
- Login page: `/login`
- Session stored in JWT

### API Security (Backend)
| Endpoint Group | Auth Header | Description |
|---------------|-------------|-------------|
| `/cron/*` | `X-Cron-Secret` | Scheduled jobs |
| `/admin/*` | `X-Internal-Secret` | Admin operations |
| All frontend proxied | `x-internal-secret` + `x-user-email` | Normal operations |

### Notion Webhooks
- HMAC signature validation using `NOTION_WEBHOOK_SECRET`
- Signatures verified before processing payload

### CORS
- Configured in FastAPI middleware to allow frontend origin

---

## 12. Testing

### Backend Tests
**Config:** `pytest.ini` (`asyncio_mode = auto`, `testpaths = backend/tests`)

| Test File | Coverage |
|-----------|----------|
| `test_notion_sync.py` | Sync operations |
| `test_notion_sync_errors.py` | Error handling |
| `test_input_validation.py` | Request validation |
| `test_scoring_edge_cases.py` | Analyst scoring |
| `conftest.py` | Pytest fixtures |

**Debug Scripts:**
| Script | Purpose |
|--------|---------|
| `inspect_checkpoint.py` | Query checkpoint state |
| `check_drafter_status.py` | Drafter debugging |
| `check_drafter_candidates.py` | Find draftable grants |
| `cleanup_stalled_draft.py` | Recover stuck drafts |

### Frontend Tests
**Framework:** Vitest + Testing Library

### Benchmarks
| File | Purpose |
|------|---------|
| `benchmarks/fixtures.py` | Test data |
| `benchmarks/test_hard_rules.py` | Hard rule accuracy |
| `benchmarks/run_benchmarks.py` | Run all benchmarks |

---

## 13. Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- MongoDB (local or Atlas)
- At minimum: `TAVILY_API_KEY`, `ANTHROPIC_API_KEY` or `AI_GATEWAY_API_KEY`

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill environment variables
cp ../.env.example .env

# Start FastAPI
uvicorn backend.main:app --reload --port 8000
```

### Frontend Setup
```bash
cd frontend
npm install

# Copy and fill environment variables
cp .env.example .env.local

# Start Next.js dev server
npm run dev
```

### Key URLs (Local)
| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| Backend docs | http://localhost:8000/docs |
| Frontend | http://localhost:3000 |
| Health check | http://localhost:8000/health |

---

## Quick Reference

### Agent Pipeline in One Line

**Scout** (discover) → **Analyst** (score) → **Guardrail** (filter) → **Human Triage** → **Company Brain** (context) → **Grant Reader** (parse) → **Drafter** (write, per section, human review) → **Export** → **Reviewer** (score final draft)

### Key Thresholds

| Threshold | Value | Controls |
|-----------|-------|----------|
| Pursue threshold | 6.5 | Minimum weighted score to recommend "pursue" |
| Watch threshold | 5.0 | Minimum score for "watch" list |
| Min funding (USD) | $3,000 | Below this → auto-pass |
| Min funding (INR) | ₹150,000 | Below this → auto-pass |
| Deadline urgent | 30 days | Fewer days → auto-pass |
| Revision threshold | 6.0 | Section critique below this → revise |
| Export threshold | 6.5 | Overall review score needed |
| Max revisions | 3 | Per section |
| Red flag penalty | 0.5 | Per red flag |
| Red flag max | 2.0 | Maximum cumulative penalty |

### AltCarbon Themes

| Key | Display Name |
|-----|-------------|
| `climatetech` | Climate Tech |
| `agritech` | Agri Tech |
| `ai_for_sciences` | AI for Sciences |
| `applied_earth_sciences` | Applied Earth Sciences |
| `social_impact` | Social Impact |
| `deeptech` | Deep Tech |

---

*This document is auto-generated and should be updated as the codebase evolves.*
