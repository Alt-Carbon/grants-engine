# AltCarbon Grants Intelligence Engine — Backend Reference

> FastAPI + LangGraph + MongoDB | Deployed on Railway

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Directory Structure](#directory-structure)
3. [LangGraph Pipeline](#langgraph-pipeline)
4. [Agents](#agents)
5. [API Endpoints](#api-endpoints)
6. [Database Layer](#database-layer)
7. [LLM Routing & Models](#llm-routing--models)
8. [Integrations](#integrations)
9. [Jobs & Scheduling](#jobs--scheduling)
10. [Notifications System](#notifications-system)
11. [Configuration](#configuration)
12. [Key Design Patterns](#key-design-patterns)

---

## Architecture Overview

```
                          Vercel AI Gateway
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
   OpenAI GPT-5.4    Anthropic Opus/Sonnet    Perplexity Sonar
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                         backend/utils/llm.py
                               │
        ┌──────────┬───────────┼───────────┬──────────┐
        │          │           │           │          │
      Scout    Analyst    Company Brain  Drafter   Reviewer
        │          │           │           │          │
        └──────────┴───────────┼───────────┴──────────┘
                               │
                        LangGraph Pipeline
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                 MongoDB   Pinecone    Notion
                 (state)   (vectors)   (Mission Control)
```

**Stack**: Python 3.11, FastAPI, LangGraph, MongoDB (Motor), Pinecone, Notion MCP, Pusher

---

## Directory Structure

```
backend/
├── main.py                          # FastAPI app — all endpoints (~2900 lines)
│
├── agents/                          # AI agents
│   ├── scout.py                    # Grant discovery (Tavily, Exa, Perplexity, direct crawl)
│   ├── analyst.py                  # Grant scoring & ranking (10-dimension scoring)
│   ├── company_brain.py            # Knowledge retrieval (Notion + Drive + Pinecone)
│   ├── reviewer.py                 # Final draft quality review
│   └── drafter/                    # Multi-step grant writing
│       ├── __init__.py
│       ├── drafter_node.py         # Section-by-section loop orchestration
│       ├── section_writer.py       # LLM-based section generation & revision
│       ├── grant_reader.py         # Grant document fetching & parsing
│       ├── draft_guardrail.py      # Pre-draft eligibility screening (Layer 2)
│       └── exporter.py             # Markdown assembly + MongoDB versioning
│
├── graph/                           # LangGraph pipeline orchestration
│   ├── state.py                    # GrantState TypedDict — single source of truth
│   ├── graph.py                    # Graph construction, compilation, singleton
│   ├── router.py                   # Conditional edge routing functions
│   └── checkpointer.py            # MongoDB-backed LangGraph checkpoint saver
│
├── db/                              # Database layer
│   ├── mongo.py                    # MongoDB client, collection accessors, indexes
│   └── pinecone_store.py           # Pinecone vector search (integrated inference)
│
├── integrations/                    # External services
│   ├── notion_mcp.py               # Notion MCP client (persistent subprocess)
│   ├── notion_config.py            # Notion DB IDs, status/theme/agent mappings
│   ├── notion_sync.py              # Write to Notion Mission Control (fire-and-forget)
│   └── notion_webhooks.py          # Incoming webhook handler (triage, section review)
│
├── jobs/                            # Scheduled jobs
│   ├── scheduler.py                # APScheduler (cron replacement for Railway)
│   ├── scout_job.py                # Scout pipeline invocation
│   ├── knowledge_job.py            # Knowledge sync invocation
│   └── backfill_job.py             # Data migration & dedup utilities
│
├── knowledge/                       # Knowledge base
│   ├── altcarbon_profile.md        # Static AltCarbon profile (~9.5K chars)
│   └── sync_profile.py             # Re-sync profile from Notion via MCP
│
├── notifications/                   # Notification system
│   └── hub.py                      # MongoDB + Pusher (in-app + real-time push)
│
├── utils/                           # Shared utilities
│   ├── llm.py                      # Centralized LLM client with fallback chains
│   └── parsing.py                  # JSON parsing (code fences, retries)
│
├── config/                          # Configuration
│   └── settings.py                 # Pydantic BaseSettings (all env vars)
│
├── scripts/                         # One-off utility scripts
└── tests/                           # Test utilities
```

---

## LangGraph Pipeline

### State Definition (`graph/state.py`)

```python
class GrantState(TypedDict):
    # Discovery
    raw_grants: List[Dict]                     # Scout output
    scored_grants: List[Dict]                  # Analyst output

    # Human Gate 1: Triage
    human_triage_decision: Optional[str]       # "pursue" | "pass" | "watch"
    selected_grant_id: Optional[str]           # MongoDB _id
    triage_notes: Optional[str]

    # Grant Reading
    grant_requirements: Optional[Dict]         # Parsed sections, criteria, budget
    grant_raw_doc: Optional[str]               # Raw fetched content

    # Company Brain
    company_context: Optional[str]             # Retrieved knowledge
    style_examples: Optional[str]              # Past grant chunks
    style_examples_loaded: bool

    # Draft Guardrail
    draft_guardrail_result: Optional[Dict]     # {passed, checks, reason}
    override_guardrails: bool

    # Drafter: Section Loop
    current_section_index: int
    approved_sections: Dict[str, Dict]         # section_name → {content, word_count}
    section_critiques: Dict[str, str]
    section_revision_instructions: Dict[str, str]

    # Human Gate 2: Section Review
    pending_interrupt: Optional[Dict]
    section_review_decision: Optional[str]     # "approve" | "revise"
    section_edited_content: Optional[str]

    # Reviewer
    reviewer_output: Optional[Dict]

    # Export
    draft_version: int
    draft_filepath: Optional[str]
    draft_filename: Optional[str]
    markdown_content: Optional[str]

    # Meta
    pipeline_id: Optional[str]
    thread_id: str
    run_id: str
    errors: List[str]
    audit_log: List[Dict]
```

### Graph Flow

```
START → scout → analyst → notify_triage
     → [INTERRUPT: human_triage]
          │
          ├── "pursue" → company_brain → grant_reader → draft_guardrail
          │                                                   │
          │                              ┌────────────────────┤
          │                              │                    │
          │                         (passed)             (failed)
          │                              │                    │
          │                    [INTERRUPT: drafter] ←┐   pipeline_update → END
          │                              │          │
          │                              ├──────────┘  (loop per section)
          │                              │
          │                          reviewer → export → END
          │
          └── "watch" / "pass" → pipeline_update → END
```

### Nodes (11 total)

| Node | File | Purpose |
|------|------|---------|
| `scout` | `agents/scout.py` | Discover grants via Tavily, Exa, Perplexity, direct crawl |
| `analyst` | `agents/analyst.py` | Score grants on 10 dimensions, apply thresholds |
| `notify_triage` | `agents/analyst.py` | Fire notification that triage is needed |
| `human_triage` | `graph/graph.py` | Placeholder — graph interrupts before this node |
| `company_brain` | `agents/company_brain.py` | Retrieve relevant company knowledge |
| `grant_reader` | `agents/drafter/grant_reader.py` | Fetch + parse the grant document |
| `draft_guardrail` | `agents/drafter/draft_guardrail.py` | AI-powered eligibility screening |
| `drafter` | `agents/drafter/drafter_node.py` | Write/revise one section per invocation |
| `reviewer` | `agents/reviewer.py` | Score final draft quality |
| `export` | `agents/drafter/exporter.py` | Assemble markdown + save versioned draft |
| `pipeline_update` | `graph/graph.py` | Update grant status for non-pursue paths |

### Routing Functions (`graph/router.py`)

| Function | Source Node | Routes |
|----------|------------|--------|
| `route_triage` | `human_triage` | "pursue" → `company_brain`, else → `pipeline_update` |
| `route_after_guardrail` | `draft_guardrail` | passed → `drafter`, failed → `pipeline_update` |
| `route_after_drafter` | `drafter` | all sections done → `reviewer`, else → `drafter` (loop) |

### Interrupt Points

The graph compiles with `interrupt_before=["human_triage", "drafter"]`:
- **human_triage**: Pauses for human triage decision (pursue/pass/watch)
- **drafter**: Pauses before each section for human review (approve/revise)

### Checkpointer (`graph/checkpointer.py`)

Custom `MongoCheckpointSaver` backed by `graph_checkpoints` collection. Stores full state JSON keyed by `(thread_id, checkpoint_id)`. Supports replay from any checkpoint.

---

## Agents

### Scout Agent (`agents/scout.py`)

**Purpose**: Discover grant opportunities from multiple sources.

**Search Sources** (4 channels, ~135 queries total):

| Source | Queries | Strategy |
|--------|---------|----------|
| **Tavily** | ~50 keyword queries | CDR, climate, agritech, India programs, funder-specific |
| **Exa** | ~25 semantic queries | Natural language (Exa's strength), with highlights |
| **Perplexity Sonar** | ~20 questions | Current programs, open calls, deep research |
| **Direct Crawl** | ~40 source URLs | Funders, foundations, govts, aggregators, accelerators |

**Pipeline per run**:
1. Run all Tavily queries in parallel (per-request delays)
2. Run all Exa queries in parallel (with highlights)
3. Run Perplexity queries in parallel (direct API preferred, gateway fallback)
4. Crawl known grant pages (DFIs, foundations, govt, aggregators)
5. Merge + 3-layer dedup: `url_hash` → `normalized_url_hash` → `content_hash`
6. Fetch full content per grant (Jina primary, plain HTTP fallback) with retry
7. LLM field extraction (GPT-5.4, 1024 tokens) — title, funder, deadline, funding, themes
8. Quality filter + upsert to `grants_raw`
9. Hand off to Analyst node

**Robustness**:
- `parse_json_safe()`: Handles code fences, prose prefix, array wrapping
- `retry_async()`: Exponential backoff (up to 3 attempts)
- Jina concurrency: 3 (respects 10 RPM free tier)
- Per-item enrichment timeout: 45s
- Upsert pattern (safe for replayed runs)

**Model**: `SCOUT_MODEL` = `openai/gpt-5.4`

---

### Analyst Agent (`agents/analyst.py`)

**Purpose**: Score and rank grants against AltCarbon's mission.

**Pipeline per grant**:
1. **Existence check** — skip if already in `grants_scored` (idempotent)
2. **Hard eligibility rules** — geography exclusions (US-only, EU-only, etc.), org type exclusions (university-only, govt-only), hold conditions → `auto_pass` immediately
3. **Currency normalization** — resolve unknown currencies via Perplexity (async)
4. **Funder enrichment** — Perplexity Sonar deep research, cached 7 days in MongoDB
5. **10-dimension scoring** — Claude Opus with retry (up to 3 attempts):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Theme alignment | 25% | CDR/climate/agri/earth sciences fit |
| Eligibility confidence | 20% | Can AltCarbon meet requirements? |
| Funding amount fit | 20% | Is funding level appropriate? |
| Deadline urgency | 15% | Time remaining to apply |
| Geography fit | 10% | India/global eligibility |
| Competition level | 10% | Expected competitiveness |

6. **Weighted total** → threshold-based recommendation:
   - **Pursue**: `weighted_total >= 6.5`
   - **Watch**: `5.0 <= weighted_total < 6.5`
   - **Pass**: `weighted_total < 5.0`
7. **Upsert** to `grants_scored` (keyed on `url_hash`, never creates duplicates)
8. **Audit** entry to `audit_logs` collection

**Key functions**:
- `parse_deadline(date_str)` — Parse deadline string → timezone-aware datetime (exported for reuse)
- `_hard_rules_check(grant)` — Geography/org-type/hold filters
- `_resolve_currency_async(grant)` — Perplexity-powered currency resolution

**Models**:
- `ANALYST_HEAVY` (`anthropic/claude-opus-4-6`): Scoring, deep research
- `ANALYST_LIGHT` (`openai/gpt-5.4`): Currency resolution, winners extraction
- `ANALYST_FUNDER` (`perplexity/sonar-deep-research`): Funder enrichment

---

### Company Brain Agent (`agents/company_brain.py`)

**Purpose**: Build and retrieve AltCarbon's knowledge base to ground the drafter.

**Knowledge Sources** (priority order):
1. **Documents List** (Notion DB) — Articulation docs (12-section structure)
2. **Notion MCP** — Key knowledge pages (search + fetch)
3. **Table of Content** (Notion DB) — Links to Google Drive docs
4. **Google Drive** — OAuth-based document export to plain text
5. **Static Profile** — Fallback (`altcarbon_profile.md`, ~9.5K chars)

**Sync Process**:
1. Query Notion for all knowledge sources
2. For each source: fetch content, chunk (400-word chunks, 80-word overlap)
3. Tag each chunk via LLM: `doc_type`, `themes`, `key_topics`, `contains_data`, `is_useful_for_grants`, `confidence`
4. Compute `content_hash` — skip unchanged chunks (incremental sync)
5. Upsert to MongoDB (`knowledge_chunks`) + Pinecone (server-side embedding)
6. Clean up stale chunks if document shrank

**Retrieval (at pipeline runtime)**:
- Pinecone vector search with `multilingual-e5-large` (integrated inference)
- Query: grant themes + requirements → top 6 matches
- Returns concatenated context for drafter

**Fallback chain**: MCP → Notion REST API → Static profile

**Model**: `BRAIN_MODEL` = `openai/gpt-5.4` (chunk tagging)

**Key Notion pages indexed** (9 pages):
Introducing Alt Carbon, MRV Moat, Vision & Comms, DRP, BRP, Biochar Expansion, Gigaton Scale, Shopify Report, Brand Guidebook

---

### Drafter Agent (multi-file)

**Purpose**: Write grant application sections one at a time with human review.

#### `drafter_node.py` — Orchestration

- Handles review decisions from previous interrupt (approve → save, revise → re-write)
- Determines next section from `grant_requirements.sections_required`
- Calls `section_writer` for the next section
- Sets `pending_interrupt` with section content for human review
- Syncs draft sections to Notion Mission Control

#### `section_writer.py` — LLM Section Generation

- **Grounded in**: company knowledge (`company_context`), style examples, grant criteria
- **Flags** `[EVIDENCE NEEDED: ...]` rather than inventing data
- **Supports revision** with critique + instructions from human review
- **Word limit enforcement** per section
- **Model-selectable**: Default GPT-5.4, option for Opus (user picks in UI)
- **Theme-specific voice/tone**: 6 theme agents with distinct styles (defined in `main.py`)

#### `grant_reader.py` — Document Fetching & Parsing

- **Jina Reader** primary (handles PDFs + messy HTML cleanly)
- **Firecrawl** fallback (if Jina fails or content is thin)
- **Claude Sonnet** parses into structured JSON:
  - `sections_required[]` — name, description, word_limit, required, order
  - `evaluation_criteria[]` — criterion, weight, description
  - `eligibility_checklist[]` — requirement, mandatory
  - `budget{}` — min, max, currency, allowable/restricted costs
  - `submission{}` — deadline, platform, file_format, special_instructions
- Falls back to 5 default sections if parsing fails

#### `draft_guardrail.py` — Eligibility Screening (Layer 2)

Two-layer defense preventing bad grants from reaching the drafter:

**Layer 1** (in `main.py` endpoint): Deterministic pre-checks using MongoDB data:
- Status check — reject if `auto_pass`, `pass`, or `watch`
- Deadline freshness — reject if expired
- Score floor — reject if `weighted_total < 4.0`
- Theme floor — reject if `scores.theme_alignment <= 2`

**Layer 2** (this node): LLM-powered deep validation after grant_reader:
- **Thematic scope** — does this grant fund CDR/climate/agri/earth sciences?
- **Eligibility** — can AltCarbon (Indian for-profit startup) meet all mandatory requirements?
- **Grant status** — is the program open, closed, expired, or future cycle?
- **Exclusions** — does "what we don't fund" match AltCarbon's work?

**Behavior**:
- Failed → status = `guardrail_rejected`, notification fired, Notion error logged
- LLM error → fail-open (pass through with warning)
- Override flag → preserves check results but forces `passed=True`

**Model**: `ANALYST_LIGHT` = `openai/gpt-5.4`

#### `exporter.py` — Draft Assembly

- Clean Markdown output: header + all approved sections + evidence gaps checklist
- Save to `/tmp/drafts/{filename}_v{version}.md`
- Save to MongoDB `grant_drafts` collection (versioned)
- Evidence gaps summary (internal, for manual fill)

---

### Reviewer Agent (`agents/reviewer.py`)

**Purpose**: Final quality review of the complete draft.

**Process**:
1. Reads all `approved_sections` as a complete document
2. Scores each section against grant's evaluation criteria
3. Produces review with:
   - Overall score (1-10)
   - Per-section critiques (strengths, issues, suggestions)
   - Top 3 recommended fixes
   - Critical evidence gaps
   - Ready-for-export verdict (score >= 6.5)

**Output**: Informational JSON review object — does **not** block export.

---

## API Endpoints

### Health & Status

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server health check |
| `GET` | `/status/notion-mcp` | MCP subprocess connection status |
| `POST` | `/run/notion-mcp/reconnect` | Force MCP reconnect |
| `GET` | `/status/knowledge-sources` | Notion workspace pages + indexed chunk count |
| `GET` | `/status/documents-list` | Documents List DB entries with sync status |
| `GET` | `/status/table-of-content` | Table of Content registry |
| `GET` | `/status/api-health` | External API health (Tavily, Exa, Perplexity, Jina, Pinecone) |
| `GET` | `/status/scout` | Scout agent status (last run, grants found) |
| `GET` | `/status/analyst` | Analyst agent status |
| `GET` | `/status/scheduler` | APScheduler jobs + next run times |
| `GET` | `/status/knowledge-pending` | Pending knowledge chunks to embed |
| `GET` | `/status/pipeline` | Active pipelines summary (counts by status) |
| `GET` | `/status/thread/{thread_id}` | Single thread state (current node, sections) |

### Scheduler Control

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/scheduler/pause` | Pause all scheduled jobs |
| `POST` | `/scheduler/resume` | Resume all scheduled jobs |

### Notifications

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications` | Get unread notifications (paginated) |
| `GET` | `/notifications/count` | Count unread notifications |
| `POST` | `/notifications/read` | Mark specific notification as read |
| `POST` | `/notifications/read-all` | Mark all notifications as read |

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/notion` | Incoming Notion webhook (HMAC-validated) |

### Scout & Discovery

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/cron/scout` | Cron trigger (48h interval) |
| `POST` | `/run/scout` | Manual Scout run |

### Knowledge Sync

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/cron/knowledge-sync` | Daily cron trigger |
| `POST` | `/run/knowledge-sync` | Manual knowledge sync |
| `POST` | `/run/sync-profile` | Re-sync AltCarbon profile from Notion |

### Analyst

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/run/analyst` | Re-run analyst on `grants_raw` |

### Pipeline Resume Points

| Method | Path | Request Body | Description |
|--------|------|-------------|-------------|
| `POST` | `/resume/triage` | `{grant_id, decision, notes}` | Resume from human_triage interrupt |
| `POST` | `/resume/section-review` | `{pipeline_id, section_name, decision, critique?, instructions?, edited_content?}` | Resume from drafter interrupt |
| `POST` | `/resume/start-draft` | `{grant_id, thread_id?, override_guardrails?, override_reason?}` | Start new draft pipeline for a grant |

#### `POST /resume/start-draft` — Detailed

**Request**:
```json
{
  "grant_id": "string (MongoDB ObjectId)",
  "thread_id": "string (optional, auto-generated if omitted)",
  "override_guardrails": false,
  "override_reason": "string (optional, logged for audit)"
}
```

**Layer 1 validation** (runs before pipeline starts, returns 422 on failure):
- Status not in `{auto_pass, pass, watch}`
- Deadline not expired
- `weighted_total >= 4.0`
- `scores.theme_alignment > 2`

**Response** (200):
```json
{
  "status": "draft_started",
  "thread_id": "draft_abc123_def456",
  "pipeline_id": "MongoDB ObjectId"
}
```

**Error** (422):
```json
{
  "detail": {
    "error": "predraft_validation_failed",
    "check": "deadline",
    "reason": "Grant deadline 2025-12-01 has expired",
    "grant_id": "..."
  }
}
```

### Drafter Chat

| Method | Path | Request Body | Description |
|--------|------|-------------|-------------|
| `POST` | `/drafter/chat` | `{grant_id, section_name, message, chat_history?, model?}` | Synchronous chat with section context |
| `POST` | `/drafter/chat/stream` | Same as above | Streaming chat (SSE `text/event-stream`) |
| `POST` | `/drafter/intelligence-brief` | `{grant_id, themes?}` | Generate strategic brief for a grant |
| `GET` | `/drafter/chat-history/{pipeline_id}` | — | Get full chat history |
| `PUT` | `/drafter/chat-history` | `{pipeline_id, sections}` | Update chat history |
| `DELETE` | `/drafter/chat-history/{pipeline_id}/{section_name}` | — | Clear section chat history |

### Drafts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/drafts/{thread_id}/download` | Download markdown draft file |

### Grant Management

| Method | Path | Request Body | Description |
|--------|------|-------------|-------------|
| `POST` | `/update/grant-status` | `{grant_id, status}` | Manually update grant status |
| `POST` | `/grants/manual` | `{url, title_override?, funder_override?, notes?}` | Manually add a grant by URL |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/backfill-fields` | Backfill missing fields in `grants_scored` |
| `POST` | `/admin/deduplicate` | Dedup grants by `content_hash` |
| `POST` | `/admin/notion-backfill` | Backfill Notion from MongoDB |

### Authentication

All endpoints (except `/health`) require `x-internal-key` header matching the `INTERNAL_API_KEY` env var. Validated via `verify_internal` FastAPI dependency.

---

## Database Layer

### MongoDB Collections

| Collection | Purpose | Key Indexes |
|-----------|---------|-------------|
| `grants_raw` | Raw discovered grants | `url_hash` (unique), `normalized_url_hash`, `content_hash`, `processed` |
| `grants_scored` | Scored grants with analysis | `url_hash` (unique), `status`, `deadline`, `weighted_total` |
| `grants_pipeline` | Pipeline execution state | `thread_id` (unique), `grant_id` |
| `grant_drafts` | Versioned draft sections | `pipeline_id`, `grant_id`, `version` |
| `knowledge_chunks` | Knowledge base chunks | `source_id + chunk_index` (unique), `content_hash` |
| `knowledge_sync_logs` | Sync history per source | `source_id`, `synced_at` |
| `graph_checkpoints` | LangGraph state snapshots | `thread_id`, `checkpoint_id` |
| `agent_config` | Agent runtime configuration | `agent` (unique) |
| `audit_logs` | Audit trail | `created_at`, `node` |
| `scout_runs` | Scout execution history | `started_at` |
| `funder_context_cache` | Funder research cache (7-day TTL) | `funder_key` |
| `deep_research_cache` | Grant research cache (7-day TTL) | `grant_key` |
| `drafter_chat_history` | Chat history per pipeline | `pipeline_id` (unique) |
| `notifications` | In-app notifications (30-day TTL) | `user_email`, `read`, `created_at` |

### Pinecone Vector Store

- **Index**: `grants-engine` (configurable)
- **Embedding model**: `multilingual-e5-large` (integrated inference — server-side)
- **Namespace**: `"knowledge"`
- **Record format**: `{id: "{source_id}#{chunk_index}", text: "...", source_id, chunk_index, doc_type, themes, ...}`
- **Batch upsert**: 20 records/batch, 1s delay between batches
- **Search**: Top 6 matches by default, filterable by metadata

---

## LLM Routing & Models

### Model Assignments

| Agent | Model ID | Provider | Use Case |
|-------|----------|----------|----------|
| Scout | `openai/gpt-5.4` | OpenAI | Grant extraction, field parsing |
| Analyst Heavy | `anthropic/claude-opus-4-6` | Anthropic | Scoring, deep research |
| Analyst Light | `openai/gpt-5.4` | OpenAI | Currency resolution, winners extraction |
| Analyst Funder | `perplexity/sonar-deep-research` | Perplexity | Funder enrichment |
| Company Brain | `openai/gpt-5.4` | OpenAI | Chunk tagging |
| Drafter (default) | `openai/gpt-5.4` | OpenAI | Section writing |
| Drafter (premium) | `anthropic/claude-opus-4-6` | Anthropic | Section writing (user-selectable) |
| Draft Guardrail | `openai/gpt-5.4` | OpenAI | Eligibility classification |
| Reviewer | `openai/gpt-5.4` | OpenAI | Quality scoring |

### Routing Architecture

```
All LLM calls → utils/llm.py → chat()
                                  │
                    ┌─────────────┤
                    │             │
              AI Gateway     Direct API
           (Vercel, primary)  (fallback)
                    │
              OpenAI-compatible SDK
```

### Fallback Chains

When a model's credits/quota are exhausted (429/402/403), the system auto-tries the next model:

| Primary | Fallback 1 | Fallback 2 |
|---------|-----------|-----------|
| `claude-opus-4-6` | `gpt-5.4` | `claude-sonnet-4-6` |
| `gpt-5.4` | `claude-opus-4-6` | `claude-sonnet-4-6` |

**Exhaustion handling**:
- 300s cooldown per model
- Fallback event logged to Notion Mission Control
- Critical severity log if entire chain fails

### `chat()` Function Signature

```python
async def chat(
    prompt: str,
    model: str = ANALYST_LIGHT,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    system: str | None = None,
) -> str
```

---

## Integrations

### Notion MCP (`integrations/notion_mcp.py`)

**Architecture**: Spawns `@notionhq/notion-mcp-server` as a persistent subprocess via Python `mcp` SDK. Connects at FastAPI startup, persists for app lifetime.

**High-level API**:
```python
mcp = NotionMCPClient()
await mcp.connect()                              # Spawn subprocess
results = await mcp.search("climate grants")     # Search Notion
content = await mcp.fetch_page(page_id)          # Read page content
blocks  = await mcp.get_block_children(page_id)  # Get child blocks
rows    = await mcp.query_data_source(ds_id)     # Query database
await mcp.update_page(page_id, properties)       # Update page
```

**Health check**: `GET /status/notion-mcp`
**Reconnect**: `POST /run/notion-mcp/reconnect`

### Notion Sync (`integrations/notion_sync.py`)

**Write-only** — syncs data FROM MongoDB TO Notion Mission Control. All calls are fire-and-forget (never block the caller).

**Sync targets**:

| Function | Target DB | Data |
|----------|-----------|------|
| `sync_scored_grant()` | Grant Pipeline | Full intelligence brief |
| `log_agent_run()` | Agent Runs | Agent name, duration, status |
| `log_error()` | Error Logs | Error, traceback, severity |
| `log_triage_decision()` | Triage Decisions | Grant, decision, notes |
| `sync_draft_section()` | Draft Sections | Section content, status |

### Notion Config (`integrations/notion_config.py`)

**Data Source IDs**:
- Grant Pipeline: `1b65cd69-...`
- Agent Runs: `1b75cd69-...`
- Error Logs: `1b85cd69-...`
- Triage Decisions: `1b95cd69-...`
- Draft Sections: `1ba5cd69-...`
- Knowledge Connections: `1ce5cd69-...`
- Documents List: `30d50d0e-...`

**Mappings**:
- `STATUS_MAP`: MongoDB status → Notion select name
- `THEME_DISPLAY`: Internal theme key → display name
- `AGENT_DISPLAY`: Agent key → display name (Scout, Analyst, Drafter, Knowledge Sync, Draft Guardrail)
- `get_priority_label(score)`: Score → priority label

### Notion Webhooks (`integrations/notion_webhooks.py`)

Incoming webhooks from Notion Mission Control:
- **HMAC signature validation** using `NOTION_WEBHOOK_SECRET`
- **Triage webhook**: Status change in Grant Pipeline → calls `POST /resume/triage`
- **Section review webhook**: Status change in Draft Sections → calls `POST /resume/section-review`

---

## Jobs & Scheduling

### APScheduler (`jobs/scheduler.py`)

Replaces Vercel cron on Railway deployment.

| Job | Schedule | Grace Period | Description |
|-----|----------|-------------|-------------|
| Scout | Every 48h | 1h for missed runs | Full grant discovery pipeline |
| Knowledge Sync | Daily 3 AM UTC | — | Sync Notion + Drive → Pinecone |
| Profile Sync | Weekly Sun 4 AM UTC | — | Re-sync `altcarbon_profile.md` |
| Notion Change Detection | Every 30 min | — | Polling fallback for webhooks |

**Control endpoints**: `POST /scheduler/pause`, `POST /scheduler/resume`, `GET /status/scheduler`

### Scout Job (`jobs/scout_job.py`)

- Creates `initial_state` with empty fields
- Invokes full graph (`START → scout → analyst → notify_triage`)
- Graph pauses at `human_triage` interrupt
- Returns `thread_id` for dashboard polling

### Knowledge Job (`jobs/knowledge_job.py`)

- Calls `CompanyBrainAgent.sync()`
- Updates Knowledge Connections DB with sync status
- Returns `chunks_upserted` count

---

## Notifications System

### Hub (`notifications/hub.py`)

**Two delivery paths**:
1. **MongoDB** `notifications` collection — in-app bell icon, 30-day TTL
2. **Pusher** real-time channel — browser push notifications

**All calls are fire-and-forget** — errors logged, never block the caller.

### Event Types

| Event | Priority | Trigger |
|-------|----------|---------|
| `scout_complete` | normal | Scout finishes discovering grants |
| `analyst_complete` | normal | Analyst finishes scoring |
| `triage_needed` | high | Grants ready for human triage |
| `high_score_grant` | high | Single grant scores >= 7.0 |
| `draft_section_ready` | normal | Section waiting for human review |
| `draft_complete` | normal | Full draft finished |
| `agent_error` | high | Agent failure |
| `deadline_warning` | high | Deadline approaching (<30 days) |
| `knowledge_sync` | normal | Knowledge sync completed |
| `guardrail_rejected` | high | Grant blocked by draft guardrail |

### `notify()` Signature

```python
async def notify(
    event_type: str,
    title: str,
    body: str,
    action_url: str = "/dashboard",
    priority: str = "normal",
    metadata: Optional[dict] = None,
    user_email: str = "all",
) -> None
```

---

## Configuration

### Environment Variables (`config/settings.py`)

| Variable | Description | Required |
|----------|-------------|----------|
| `MONGODB_URI` | MongoDB connection string | Yes |
| `INTERNAL_API_KEY` | API authentication key | Yes |
| `AI_GATEWAY_URL` | Vercel AI Gateway endpoint | Yes |
| `AI_GATEWAY_API_KEY` | Gateway API key | Yes |
| `ANTHROPIC_API_KEY` | Direct Anthropic fallback | No |
| `NOTION_TOKEN` | Notion API token | Yes |
| `NOTION_WEBHOOK_SECRET` | Webhook HMAC secret | No |
| `NOTION_KNOWLEDGE_BASE_PAGE_ID` | Root knowledge page | Yes |
| `PINECONE_API_KEY` | Pinecone API key | Yes |
| `PINECONE_INDEX_NAME` | Index name (default: `grants-engine`) | No |
| `TAVILY_API_KEY` | Tavily search API | Yes |
| `EXA_API_KEY` | Exa search API | Yes |
| `PERPLEXITY_API_KEY` | Perplexity API | Yes |
| `JINA_API_KEY` | Jina Reader API | No |
| `FIRECRAWL_API_KEY` | Firecrawl fallback | No |
| `GOOGLE_CLIENT_ID` | Google Drive OAuth | No |
| `GOOGLE_CLIENT_SECRET` | Google Drive OAuth | No |
| `GOOGLE_REFRESH_TOKEN` | Google Drive OAuth | No |
| `LANGCHAIN_API_KEY` | LangSmith tracing | No |
| `LANGCHAIN_TRACING_V2` | Enable tracing | No |
| `LANGCHAIN_PROJECT` | LangSmith project name | No |
| `PUSHER_APP_ID` | Pusher notifications | No |
| `NEXT_PUBLIC_PUSHER_KEY` | Pusher public key | No |
| `PUSHER_SECRET` | Pusher secret | No |
| `NEXT_PUBLIC_PUSHER_CLUSTER` | Pusher cluster | No |

### Agent Defaults

| Setting | Default | Description |
|---------|---------|-------------|
| `scout_frequency_hours` | 48 | Hours between scout runs |
| `pursue_threshold` | 6.5 | Score threshold for "pursue" |
| `watch_threshold` | 5.0 | Score threshold for "watch" |
| `min_funding_usd` | 3000 | Minimum funding to consider |

### Theme Categories (6)

| Key | Display Name |
|-----|-------------|
| `climatetech` | Climate Tech |
| `agritech` | AgriTech |
| `ai_for_sciences` | AI for Sciences |
| `applied_earth_sciences` | Applied Earth Sciences |
| `social_impact` | Social Impact |
| `deeptech` | Deep Tech |

---

## Key Design Patterns

### 1. Fire-and-Forget Safety
Notion sync, notifications, and logging **never block** the main pipeline. Errors are caught and logged, not propagated.

### 2. Idempotent Operations
Scout and knowledge sync can be replayed safely. All writes use upsert patterns keyed on content hashes.

### 3. Graceful Degradation
```
MCP → Notion REST API → Static Profile
Jina → Firecrawl → Raw HTTP
Opus → GPT-5.4 → Sonnet (fallback chain)
```

### 4. Two-Layer Guardrails
- **Layer 1** (endpoint): Fast deterministic checks (status, deadline, scores) → 422
- **Layer 2** (graph node): LLM-powered deep validation (scope, eligibility, exclusions)
- Fail-open on LLM errors (don't block on infra issues)

### 5. Incremental Sync
Content hashes prevent re-processing unchanged documents. Knowledge chunks, grant scoring, and profile sync all use hash-based dedup.

### 6. Evidence Flagging
Drafter uses `[EVIDENCE NEEDED: ...]` markers instead of hallucinating data. Reviewer identifies remaining gaps.

### 7. Checkpointing & Replay
Full LangGraph state saved at each node in MongoDB. Pipelines can be resumed from any interrupt point or replayed from checkpoints.

### 8. Versioned Drafts
Drafts are versioned in MongoDB (`grant_drafts` collection) and as markdown files (`_v1.md`, `_v2.md`). Each revision creates a new version.

### 9. Rate Limiting
- Jina: 3 concurrent requests (free tier: 10 RPM)
- Pinecone upserts: 20-record batches with 1s delay
- Search APIs: Per-request delays to avoid throttling

### 10. Audit Trail
Every node appends to `audit_log` in LangGraph state. Critical operations also write to `audit_logs` MongoDB collection. Override decisions include reason for compliance.
