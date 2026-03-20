# Grants Intelligence Engine — Exhaustive Developer Reference

> Every parameter, edge case, error handler, label, and logic flow — line by line.
> Last updated: 2026-03-20

---

## Table of Contents

- [Part 1: LangGraph Pipeline Core](#part-1-langgraph-pipeline-core)
- [Part 2: GrantState — Every Field](#part-2-grantstate--every-field)
- [Part 3: Routing Logic — Every Branch](#part-3-routing-logic--every-branch)
- [Part 4: MongoDB Checkpointer — Every Method](#part-4-mongodb-checkpointer--every-method)
- [Part 5: Settings — Every Parameter](#part-5-settings--every-parameter)
- [Part 6: LLM Utilities — Models, Fallbacks, Error Detection](#part-6-llm-utilities--models-fallbacks-error-detection)
- [Part 7: JSON Parsing & Retry — Every Edge Case](#part-7-json-parsing--retry--every-edge-case)
- [Part 8: API Health Tracker — Credit Exhaustion System](#part-8-api-health-tracker--credit-exhaustion-system)
- [Part 9: Pre-Triage Guardrail — Every Check](#part-9-pre-triage-guardrail--every-check)
- [Part 10: MCP Hub — Connection Lifecycle](#part-10-mcp-hub--connection-lifecycle)
- [Part 11: Notification Hub — Every Event Type](#part-11-notification-hub--every-event-type)
- [Part 12: Theme Profiles — Every Theme](#part-12-theme-profiles--every-theme)
- [Part 13: Notion Config — Every Label & Mapping](#part-13-notion-config--every-label--mapping)
- [Part 14: MongoDB Collections — Every Index](#part-14-mongodb-collections--every-index)
- [Part 15: Scout Agent — Complete Logic](#part-15-scout-agent--complete-logic)
- [Part 16: Analyst Agent — Scoring Formula](#part-16-analyst-agent--scoring-formula)
- [Part 17: Drafter Agent — Section Loop](#part-17-drafter-agent--section-loop)
- [Part 18: Reviewer Agent — Dual Review](#part-18-reviewer-agent--dual-review)
- [Part 19: Company Brain — Knowledge Retrieval](#part-19-company-brain--knowledge-retrieval)
- [Part 20: Notion Sync — Every Function](#part-20-notion-sync--every-function)
- [Part 21: Notion MCP Client — Every Method](#part-21-notion-mcp-client--every-method)
- [Part 22: Scheduler & Jobs — Every Cron](#part-22-scheduler--jobs--every-cron)
- [Part 23: Backfill & Dedup — Complete Logic](#part-23-backfill--dedup--complete-logic)
- [Part 24: Profile Sync — Every Step](#part-24-profile-sync--every-step)
- [Part 25: FastAPI Routes — Every Endpoint](#part-25-fastapi-routes--every-endpoint)
- [Part 26: Frontend — Every Component](#part-26-frontend--every-component)
- [Part 27: Frontend API Routes — Every Proxy](#part-27-frontend-api-routes--every-proxy)
- [Part 28: Frontend Utilities & Hooks](#part-28-frontend-utilities--hooks)
- [Part 29: Configuration Files — Every Setting](#part-29-configuration-files--every-setting)
- [Part 30: Skills Registry — Every Skill](#part-30-skills-registry--every-skill)
- [Part 31: MCP Servers Config — Every Server](#part-31-mcp-servers-config--every-server)

---

## Part 1: LangGraph Pipeline Core

**File:** `backend/graph/graph.py` (187 lines)

### Graph Nodes (13 total)

| Node Name | Function | Import Source |
|-----------|----------|--------------|
| `scout` | `scout_node` | `backend.agents.scout` |
| `company_brain_load` | `company_brain_load_node` | `backend.agents.company_brain` |
| `analyst` | `analyst_node` | `backend.agents.analyst` |
| `pre_triage_guardrail` | `pre_triage_guardrail_node` | `backend.agents.pre_triage_guardrail` |
| `notify_triage` | `notify_triage_node` | `backend.agents.analyst` |
| `human_triage` | `human_triage_node` | defined in `graph.py` itself |
| `company_brain` | `company_brain_node` | `backend.agents.company_brain` |
| `grant_reader` | `grant_reader_node` | `backend.agents.drafter.grant_reader` |
| `draft_guardrail` | `draft_guardrail_node` | `backend.agents.drafter.draft_guardrail` |
| `drafter` | `drafter_node` | `backend.agents.drafter.drafter_node` |
| `reviewer` | `dual_reviewer_node` | `backend.agents.dual_reviewer` |
| `export` | `exporter_node` | `backend.agents.drafter.exporter` |
| `pipeline_update` | `pipeline_update_node` | defined in `graph.py` itself |

### Edge Map (complete)

```
START ──────────► scout
scout ──────────► company_brain_load
company_brain_load ► analyst
analyst ────────► pre_triage_guardrail
pre_triage_guardrail ► notify_triage
notify_triage ──► human_triage
human_triage ───► [CONDITIONAL: route_triage]
                   ├── "company_brain" → company_brain
                   └── "pipeline_update" → pipeline_update
company_brain ──► grant_reader
grant_reader ───► draft_guardrail
draft_guardrail ► [CONDITIONAL: route_after_guardrail]
                   ├── "drafter" → drafter
                   └── "pipeline_update" → pipeline_update
drafter ────────► [CONDITIONAL: route_after_drafter]
                   ├── "drafter" → drafter (LOOP)
                   ├── "export" → export
                   └── "pipeline_update" → pipeline_update
export ─────────► reviewer
reviewer ───────► END
pipeline_update ► END
```

### Interrupt Points

```python
builder.compile(
    checkpointer=saver,
    interrupt_before=["human_triage", "drafter"],
)
```

- **`human_triage`** — Graph pauses BEFORE this node. Resumed via `POST /resume/triage` with `human_triage_decision` and `selected_grant_id`.
- **`drafter`** — Graph pauses BEFORE each iteration. Resumed via `POST /resume/section-review` with `section_review_decision` and optional `section_edited_content`.

### `human_triage_node()` — Line 37

```python
async def human_triage_node(state: GrantState) -> Dict:
```

**Parameters:** `state: GrantState`
**Returns:** `{"audit_log": [...]}` — appends triage event to audit log
**Logic:** Placeholder node. The actual decision is injected into state before resumption. This node only records the audit entry.
**Audit entry fields:**
- `node`: `"human_triage"`
- `ts`: UTC ISO timestamp
- `decision`: value from `state["human_triage_decision"]`
- `grant_id`: value from `state["selected_grant_id"]`

### `pipeline_update_node()` — Line 50

```python
async def pipeline_update_node(state: GrantState) -> Dict:
```

**Parameters:** `state: GrantState`
**Returns:** `{"audit_log": [...]}` — appends pipeline update event

**Logic flow:**
1. Get `grant_id` from `state["selected_grant_id"]`
2. Check `draft_guardrail_result` — if present and `passed=False`, set `decision = "guardrail_rejected"`
3. Otherwise, use `state["human_triage_decision"]` (default: `"pass"`)
4. **Edge case: `decision == "pursue"`** — This should never reach pipeline_update in normal flow. If it does (e.g., empty sections from grant_reader), skip the DB update to avoid reverting the "drafting" status.
5. If `grant_id` exists, update `grants_scored` collection: `{"$set": {"status": decision}}`

**Error handling:**
- `ObjectId(grant_id)` conversion wrapped in try/except
- MongoDB update failure logged as warning, never raises
- Audit entry always written regardless of DB errors

**Labels used:**
- `"guardrail_rejected"` — status set when draft guardrail fails
- `"pass"` — default triage decision
- `"pursue"` — skipped in this node (special case)

### `compile_graph()` — Line 167

```python
def compile_graph(checkpointer: MongoCheckpointSaver | None = None):
```

**Parameters:**
- `checkpointer`: Optional `MongoCheckpointSaver` instance. If `None`, creates a new one.

**Returns:** Compiled LangGraph `CompiledGraph`

### `get_graph()` — Line 182

```python
def get_graph():
```

**Singleton pattern.** Creates the compiled graph on first call, reuses on subsequent calls. Thread-safe by Python's GIL.

---

## Part 2: GrantState — Every Field

**File:** `backend/graph/state.py` (65 lines)

```python
class GrantState(TypedDict):
```

### Discovery Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `raw_grants` | `List[Dict]` | Scout output — raw discovered grants | `scout_node` |
| `scored_grants` | `List[Dict]` | Analyst output — scored + ranked | `analyst_node` |

### Triage Fields (Human Gate 1)
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `human_triage_decision` | `Optional[str]` | `"pursue"` \| `"pass"` \| `"watch"` | Frontend via `/resume/triage` |
| `selected_grant_id` | `Optional[str]` | MongoDB `_id` of chosen grant | Frontend via `/resume/triage` |
| `triage_notes` | `Optional[str]` | Human notes on triage decision | Frontend via `/resume/triage` |

### Grant Reading Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `grant_requirements` | `Optional[Dict]` | Structured grant doc: `{sections_required, evaluation_criteria, budget_info, ...}` | `grant_reader_node` |
| `grant_raw_doc` | `Optional[str]` | Raw fetched HTML/markdown content of grant page | `grant_reader_node` |

### Company Brain Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `company_profile` | `Optional[str]` | General AltCarbon profile (loaded before analyst) | `company_brain_load_node` |
| `company_context` | `Optional[str]` | Grant-specific knowledge retrieval | `company_brain_node` |
| `style_examples` | `Optional[str]` | Past grant application text chunks | `company_brain_node` |
| `style_examples_loaded` | `bool` | Whether golden examples were loaded | `company_brain_node` |

### Draft Guardrail Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `draft_guardrail_result` | `Optional[Dict]` | `{passed: bool, checks: [...], reason: str}` | `draft_guardrail_node` |
| `override_guardrails` | `bool` | Skip guardrail (manual override) | Frontend |

### Drafter Theme/Outline Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `grant_theme` | `Optional[str]` | Resolved theme key (e.g., `"climatetech"`) | `drafter_node` |
| `draft_outline` | `Optional[str]` | Narrative outline for cross-section coherence | `drafter_node` |
| `criteria_map` | `Optional[Dict]` | `{section_name: criteria_evidence_mapping}` | `drafter_node` |
| `funder_terms` | `Optional[str]` | Extracted funder language/terms to mirror | `drafter_node` |

### Drafter Section Loop Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `current_section_index` | `int` | Which section is being drafted (0-based) | `drafter_node` |
| `approved_sections` | `Dict[str, Dict]` | `{section_name: {content, word_count, ...}}` | `drafter_node` |
| `section_critiques` | `Dict[str, str]` | `{section_name: critique_text}` | `drafter_node` |
| `section_revision_instructions` | `Dict[str, str]` | `{section_name: revision_instructions}` | `drafter_node` |
| `section_revision_counts` | `Dict[str, int]` | `{section_name: number_of_revisions}` | `drafter_node` |

### Section Review Fields (Human Gate 2)
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `pending_interrupt` | `Optional[Dict]` | `{section_name, content, critique, ...}` — current section awaiting review | `drafter_node` |
| `section_review_decision` | `Optional[str]` | `"approve"` \| `"revise"` | Frontend via `/resume/section-review` |
| `section_edited_content` | `Optional[str]` | Human-edited content (if revise) | Frontend via `/resume/section-review` |

### Reviewer Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `reviewer_output` | `Optional[Dict]` | `{funder_score, credibility_score, coherence_score, overall_score, suggested_revisions, ...}` | `dual_reviewer_node` |

### Export Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `draft_version` | `int` | Version counter for this draft | `exporter_node` |
| `draft_filepath` | `Optional[str]` | Local file path of exported draft | `exporter_node` |
| `draft_filename` | `Optional[str]` | Filename for download | `exporter_node` |
| `markdown_content` | `Optional[str]` | Full assembled markdown of draft | `exporter_node` |

### Meta Fields
| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `pipeline_id` | `Optional[str]` | MongoDB `_id` of the grants_pipeline record | `start_draft` route |
| `thread_id` | `str` | LangGraph thread identifier (UUID) | Created at pipeline start |
| `run_id` | `str` | LangGraph run identifier | Created at pipeline start |
| `errors` | `List[str]` | Accumulated error messages | Any node |
| `audit_log` | `List[Dict]` | Chronological list of node executions | Every node |

---

## Part 3: Routing Logic — Every Branch

**File:** `backend/graph/router.py` (57 lines)

### `route_triage(state)` — Line 7

```python
def route_triage(state: GrantState) -> str:
```

**Input:** Full `GrantState`
**Output:** `"company_brain"` or `"pipeline_update"`

**Logic:**
1. `decision = state.get("human_triage_decision", "pass")` — defaults to `"pass"` if missing
2. **Edge case:** If `decision == "pursue"` but `selected_grant_id` is `None`/empty → routes to `"pipeline_update"` (safety: can't pursue without a grant)
3. If `decision == "pursue"` and grant_id exists → `"company_brain"`
4. All other decisions (`"pass"`, `"watch"`, unknown strings) → `"pipeline_update"`

**Edge cases handled:**
- Missing `human_triage_decision` key → defaults to `"pass"`
- `"pursue"` without `selected_grant_id` → treated as failed triage
- Unknown decision values (typos, etc.) → routed to `pipeline_update`

---

### `route_after_guardrail(state)` — Line 25

```python
def route_after_guardrail(state: GrantState) -> str:
```

**Input:** Full `GrantState`
**Output:** `"drafter"` or `"pipeline_update"`

**Logic:**
1. `result = state.get("draft_guardrail_result") or {}` — handles both `None` and missing key
2. If `result.get("passed", False)` is `True` → `"drafter"`
3. Otherwise → `"pipeline_update"`

**Design decision (line 29 comment):**
> "Defaults to failed (fail-closed) if guardrail result is missing or malformed. This ensures LLM/infrastructure failures block progress rather than silently passing."

**Edge cases handled:**
- `draft_guardrail_result` is `None` → `{}` → `passed` defaults to `False` → pipeline_update
- `draft_guardrail_result` missing `passed` key → defaults to `False` → pipeline_update
- `draft_guardrail_result.passed = True` → drafter

---

### `route_after_drafter(state)` — Line 37

```python
def route_after_drafter(state: GrantState) -> str:
```

**Input:** Full `GrantState`
**Output:** `"drafter"` (loop), `"export"`, or `"pipeline_update"`

**Logic:**
1. `sections = state["grant_requirements"]["sections_required"]` (with safe gets)
2. `approved = state.get("approved_sections") or {}`
3. **Edge case:** If `sections` is empty (grant_reader failed) → `"pipeline_update"` to avoid infinite drafter loop
4. If `len(approved) >= len(sections)` → all sections done → `"export"`
5. Otherwise → `"drafter"` (loop back for next section)

**Edge cases handled:**
- `grant_requirements` is `None` → `{}` → `sections = []` → `pipeline_update`
- `sections_required` key missing → `[]` → `pipeline_update`
- `approved_sections` is `None` → `{}` → `len(approved) = 0`

---

### `route_after_reviewer(state)` — Line 54

```python
def route_after_reviewer(state: GrantState) -> str:
```

**Always returns `"export"`**. The reviewer score is informational only — it never blocks the pipeline. This is a deliberate design choice: review results are displayed to the user but don't gate export.

---

## Part 4: MongoDB Checkpointer — Every Method

**File:** `backend/graph/checkpointer.py` (226 lines)

### Class: `MongoCheckpointSaver(BaseCheckpointSaver)`

**Collection:** `graph_checkpoints`

### Helper Methods

#### `_get_thread_id(config)` — Line 34
```python
def _get_thread_id(self, config: RunnableConfig) -> str:
```
Extracts `config["configurable"]["thread_id"]`. **Raises `KeyError` if missing** (intentional — thread_id is required).

#### `_checkpoint_id(config)` — Line 37
```python
def _checkpoint_id(self, config: RunnableConfig) -> Optional[str]:
```
Extracts `config["configurable"].get("checkpoint_id")`. Returns `None` if not set.

### Sync Interface (Lines 42-62)

All three sync methods (`get_tuple`, `list`, `put`) raise `NotImplementedError("Use async interface")`. LangGraph uses the async interface exclusively in this app.

### `aget_tuple(config)` — Line 66

```python
async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
```

**Parameters:** `config` with `thread_id` (required) and `checkpoint_id` (optional)

**Logic:**
1. Extract `thread_id` and `checkpoint_id` from config
2. Query `graph_checkpoints` collection:
   - If `checkpoint_id` provided: `find_one({"thread_id": tid, "checkpoint_id": cid})`
   - If not: `find_one({"thread_id": tid}, sort=[("checkpoint_id", -1)])` — **gets latest checkpoint**
3. Parse `doc["checkpoint"]` and `doc["metadata"]` from JSON strings
4. Build `CheckpointTuple(config, checkpoint, metadata, parent_config)`

**Error handling:**
- MongoDB read failure (line 78): catches `Exception`, logs error, returns `None`
- JSON decode failure (line 88): catches `json.JSONDecodeError` and `KeyError`, logs corruption error, returns `None`
- Missing document: returns `None` (not an error)

**Edge cases:**
- `metadata` field missing from doc → defaults to `"{}"` (empty JSON)
- `parent_checkpoint_id` missing → `parent_config = None`

---

### `alist(config, *, filter, before, limit)` — Line 117

```python
async def alist(self, config, *, filter=None, before=None, limit=None) -> AsyncIterator[CheckpointTuple]:
```

**Parameters:**
- `config`: `Optional[RunnableConfig]` — if `None`, returns immediately (empty iterator)
- `filter`: `Optional[Dict[str, Any]]` — metadata filter, keys prefixed with `"metadata."` for MongoDB query
- `before`: `Optional[RunnableConfig]` — unused in this implementation
- `limit`: `Optional[int]` — max results

**Logic:**
1. Build query: `{"thread_id": tid}`
2. Add filter keys with `metadata.` prefix
3. Find with `sort=[("checkpoint_id", -1)]` (newest first)
4. Apply `limit` if set
5. Yield `CheckpointTuple` for each doc

**Edge cases:**
- `config is None` → `return` (empty iterator, no error)
- `filter` dict applied with dot-notation prefix for nested MongoDB fields

---

### `aput(config, checkpoint, metadata, new_versions)` — Line 165

```python
async def aput(self, config, checkpoint, metadata, new_versions) -> RunnableConfig:
```

**Parameters:**
- `config`: Config with `thread_id` and parent `checkpoint_id`
- `checkpoint`: `Checkpoint` dict with `"id"` key
- `metadata`: `CheckpointMetadata` dict
- `new_versions`: Any (unused in this implementation)

**MongoDB operation:**
```python
await col.update_one(
    {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
    {"$set": {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": parent_id,
        "checkpoint": json.dumps(checkpoint),     # Full state as JSON string
        "metadata": json.dumps(dict(metadata)),
        "saved_at": _utcnow(),                    # ISO timestamp
    }},
    upsert=True,                                   # Create if not exists
)
```

**Error handling:** Catches `Exception`, logs error, **re-raises** (line 195). Unlike reads, write failures MUST propagate to LangGraph so it knows the save failed.

**Returns:** Config with `thread_id` and `checkpoint_id`

---

### `aput_writes(config, writes, task_id)` — Line 203

```python
async def aput_writes(self, config, writes, task_id) -> None:
```

**Purpose:** Store pending writes alongside the checkpoint for debugging.

**MongoDB operation:**
```python
await col.update_one(
    {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
    {"$set": {
        f"pending_writes.{task_id}": [
            {"channel": c, "value": json.dumps(v)} for c, v in writes
        ]
    }},
)
```

**Error handling:** Catches `Exception`, logs warning, **does NOT re-raise** (non-critical).

---

## Part 5: Settings — Every Parameter

**File:** `backend/config/settings.py` (188 lines)

### Default Scoring Weights (Line 12)

```python
_DEFAULT_SCORING_WEIGHTS = {
    "theme_alignment":        0.25,
    "eligibility_confidence": 0.20,
    "funding_amount":         0.20,
    "deadline_urgency":       0.15,
    "geography_fit":          0.10,
    "competition_level":      0.10,
}
# Sum = 1.0 (required)
```

### Default Exchange Rates (Line 22)

```python
_DEFAULT_EXCHANGE_RATES = {
    "USD": 1.0, "INR": 83.5, "EUR": 0.92, "GBP": 0.79,
    "CAD": 1.36, "AUD": 1.53, "SGD": 1.34, "JPY": 149.0,
    "BRL": 4.97, "ZAR": 18.6, "KES": 129.0, "NGN": 1540.0,
}
```

### Parser: `_parse_scoring_weights(v)` — Line 38

**Input:** JSON string from env var
**Logic:**
1. If empty → return defaults
2. Try `json.loads(v)` → if dict with exactly 6 keys → return parsed
3. On `JSONDecodeError` or `TypeError` or wrong length → return defaults

**Edge cases:** Non-JSON string, array instead of dict, dict with 5 or 7 keys → all fall back to defaults.

### Parser: `_parse_exchange_rates(v)` — Line 51

**Input:** JSON string from env var
**Logic:**
1. If empty → return defaults
2. Try `json.loads(v)` → if dict and all values are `int` or `float` → return parsed
3. On parse error or non-numeric values → return defaults

### `class Settings(BaseSettings)` — Line 64

**Config:** `env_file=".env"`, `extra="ignore"` (unknown env vars are silently ignored)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `mongodb_uri` | `str` | `"mongodb://localhost:27017"` | `MONGODB_URI` | MongoDB connection string |
| `ai_gateway_url` | `str` | `"https://ai-gateway.vercel.sh/v1"` | `AI_GATEWAY_URL` | AI Gateway endpoint |
| `ai_gateway_api_key` | `str` | `""` | `AI_GATEWAY_API_KEY` | Gateway API key |
| `anthropic_api_key` | `str` | `""` | `ANTHROPIC_API_KEY` | Direct Anthropic fallback |
| `openai_api_key` | `str` | `""` | `OPENAI_API_KEY` | Legacy, unused |
| `notion_token` | `str` | `""` | `NOTION_TOKEN` | Notion API token |
| `notion_knowledge_base_page_id` | `str` | `""` | `NOTION_KNOWLEDGE_BASE_PAGE_ID` | Scope sync to page |
| `notion_webhook_secret` | `str` | `""` | `NOTION_WEBHOOK_SECRET` | HMAC validation |
| `google_client_id` | `str` | `""` | `GOOGLE_CLIENT_ID` | OAuth |
| `google_client_secret` | `str` | `""` | `GOOGLE_CLIENT_SECRET` | OAuth |
| `google_refresh_token` | `str` | `""` | `GOOGLE_REFRESH_TOKEN` | Drive access |
| `pinecone_api_key` | `str` | `""` | `PINECONE_API_KEY` | Vector DB |
| `pinecone_index_name` | `str` | `"grants-engine"` | `PINECONE_INDEX_NAME` | Index name |
| `cloudflare_account_id` | `str` | `""` | `CLOUDFLARE_ACCOUNT_ID` | Browser rendering |
| `cloudflare_browser_token` | `str` | `""` | `CLOUDFLARE_BROWSER_TOKEN` | Browser rendering |
| `slack_bot_token` | `str` | `""` | `SLACK_BOT_TOKEN` | Slack MCP |
| `slack_team_id` | `str` | `""` | `SLACK_TEAM_ID` | Slack MCP |
| `tavily_api_key` | `str` | `""` | `TAVILY_API_KEY` | Web search |
| `exa_api_key` | `str` | `""` | `EXA_API_KEY` | Semantic search |
| `perplexity_api_key` | `str` | `""` | `PERPLEXITY_API_KEY` | AI research |
| `jina_api_key` | `str` | `""` | `JINA_API_KEY` | Page fetching |
| `cron_secret` | `str` | `"dev-cron-secret"` | `CRON_SECRET` | Cron endpoint auth |
| `internal_secret` | `str` | `"dev-internal-secret"` | `INTERNAL_SECRET` | Internal API auth |
| `langchain_api_key` | `str` | `""` | `LANGCHAIN_API_KEY` | LangSmith |
| `langchain_tracing_v2` | `bool` | `False` | `LANGCHAIN_TRACING_V2` | Enable tracing |
| `langchain_project` | `str` | `"altcarbon-grants"` | `LANGCHAIN_PROJECT` | Project name |
| `scout_frequency_hours` | `int` | `48` | `SCOUT_FREQUENCY_HOURS` | Discovery interval |
| `pursue_threshold` | `float` | `6.5` | `PURSUE_THRESHOLD` | Min score to pursue |
| `watch_threshold` | `float` | `5.0` | `WATCH_THRESHOLD` | Min score to watch |
| `min_grant_funding` | `int` | `3000` | `MIN_GRANT_FUNDING` | Min USD to consider |
| `themes` | `List[str]` | `["climatetech", "agritech", "ai_for_sciences", "applied_earth_sciences", "social_impact", "deeptech"]` | `THEMES` | Company themes |
| `scoring_weights` | `str` | `""` | `SCORING_WEIGHTS` | JSON string |
| `score_floor` | `float` | `4.0` | `SCORE_FLOOR` | Pre-triage min score |
| `theme_alignment_floor` | `int` | `2` | `THEME_ALIGNMENT_FLOOR` | Pre-triage min theme |
| `chunk_size` | `int` | `400` | `CHUNK_SIZE` | Words per chunk |
| `chunk_overlap` | `int` | `80` | `CHUNK_OVERLAP` | Word overlap |
| `min_chunk_words` | `int` | `40` | `MIN_CHUNK_WORDS` | Min words per chunk |
| `company_name` | `str` | `"AltCarbon"` | `COMPANY_NAME` | Company identity |
| `company_domain` | `str` | `"altcarbon.com"` | `COMPANY_DOMAIN` | Domain identity |
| `scout_model` | `str` | `""` | `SCOUT_MODEL` | Override scout model |
| `analyst_heavy_model` | `str` | `""` | `ANALYST_HEAVY_MODEL` | Override analyst model |
| `drafter_model` | `str` | `""` | `DRAFTER_MODEL` | Override drafter model |
| `deadline_urgent_days` | `int` | `30` | `DEADLINE_URGENT_DAYS` | Days threshold |
| `red_flag_penalty` | `float` | `0.5` | `RED_FLAG_PENALTY` | Per-flag deduction |
| `red_flag_max_penalty` | `float` | `2.0` | `RED_FLAG_MAX_PENALTY` | Max cumulative |
| `min_funding_inr` | `float` | `150000` | `MIN_FUNDING_INR` | INR minimum |
| `exchange_rates` | `str` | `""` | `EXCHANGE_RATES` | JSON string |
| `reviewer_revision_threshold` | `float` | `6.0` | `REVIEWER_REVISION_THRESHOLD` | Below = revise |
| `reviewer_export_threshold` | `float` | `6.5` | `REVIEWER_EXPORT_THRESHOLD` | Above = export-ready |
| `default_section_word_limit` | `int` | `500` | `DEFAULT_SECTION_WORD_LIMIT` | Fallback word limit |
| `max_revision_attempts` | `int` | `3` | `MAX_REVISION_ATTEMPTS` | Max per section |
| `scout_enrichment_timeout` | `int` | `45` | `SCOUT_ENRICHMENT_TIMEOUT` | Seconds per item |
| `scout_enrichment_concurrency` | `int` | `4` | `SCOUT_ENRICHMENT_CONCURRENCY` | Parallel enrichments |
| `scout_crawl_timeout` | `int` | `180` | `SCOUT_CRAWL_TIMEOUT` | Total crawl seconds |
| `jina_concurrency` | `int` | `3` | `JINA_CONCURRENCY` | Jina parallel reqs |
| `jina_delay` | `float` | `1.0` | `JINA_DELAY` | Jina rate limit delay |

### Methods

#### `get_scoring_weights()` — Line 176
Returns parsed dict of 6 weights summing to 1.0.

#### `get_exchange_rates()` — Line 180
Returns parsed dict of currency conversion rates.

### Singleton: `get_settings()` — Line 186
Uses `@lru_cache` — settings are loaded once and cached for the process lifetime. To reload, restart the process.

---

## Part 6: LLM Utilities — Models, Fallbacks, Error Detection

**File:** `backend/utils/llm.py` (350 lines)

### Model Constants

| Constant | Value | Agent | Purpose |
|----------|-------|-------|---------|
| `SCOUT_MODEL` | `"openai/gpt-5.4"` (or env override) | Scout | Extraction/scraping |
| `ANALYST_HEAVY` | `"anthropic/claude-opus-4-6"` (or env override) | Analyst | 6D scoring, deep research |
| `ANALYST_LIGHT` | `"openai/gpt-5.4"` | Analyst | Currency, winners, extraction |
| `ANALYST_FUNDER` | `"perplexity/sonar"` | Analyst | Funder enrichment |
| `BRAIN_MODEL` | `"openai/gpt-5.4"` | Company Brain | Chunk tagging |
| `DRAFTER_DEFAULT` | `"openai/gpt-5.4"` (or env override) | Drafter | Section writing |
| `SONNET` | alias for `ANALYST_HEAVY` | Legacy | Backward compat |
| `HAIKU` | alias for `ANALYST_LIGHT` | Legacy | Backward compat |

### Drafter Model Selection (Line 64)

```python
DRAFTER_MODELS = {
    "gpt-5.4": "openai/gpt-5.4",
    "opus-4.6": "anthropic/claude-opus-4-6",
}
```

Users select model via UI key (e.g., `"gpt-5.4"`), resolved to gateway ID via `resolve_drafter_model()`.

### Fallback Chains (Line 75)

```python
_FALLBACK_CHAINS = {
    "anthropic/claude-opus-4-6": ["openai/gpt-5.4", "anthropic/claude-sonnet-4-6"],
    "openai/gpt-5.4": ["anthropic/claude-opus-4-6", "anthropic/claude-sonnet-4-6"],
    "anthropic/claude-sonnet-4-6": ["openai/gpt-5.4", "anthropic/claude-opus-4-6"],
    "google/gemini-2.5-flash-lite": ["openai/gpt-5.4", "anthropic/claude-opus-4-6"],
    "openai/gpt-5-nano": ["openai/gpt-5.4", "anthropic/claude-opus-4-6"],
}
```

### Exhaustion Tracking (Line 101)

```python
_exhausted_models: Dict[str, float] = {}  # model → expiry timestamp
_EXHAUSTION_COOLDOWN_SECS = 300            # 5 minutes
```

#### `_is_exhausted(model)` — Line 108
Returns `True` if model is within cooldown window. Auto-clears expired entries.

#### `_mark_exhausted(model)` — Line 119
Sets `expiry = time.time() + 300`.

#### `_is_credit_error(exc)` — Line 125
**Credit signals detected in exception message (case-insensitive):**
```python
("429", "rate limit", "rate_limit", "402", "payment required",
 "insufficient", "quota", "exceeded", "billing", "credits",
 "resource_exhausted", "too many requests", "limit reached", "spending limit")
```
**HTTP status codes:** `429`, `402`, `403`
Checks `exc.status_code`, `exc.http_status`, or falls back to string matching.

### `get_client()` — Line 183

```python
def get_client() -> AsyncOpenAI:
```

**Logic:**
1. If `ai_gateway_api_key` is set → use AI Gateway (`base_url = ai_gateway_url`)
2. Otherwise → use direct Anthropic API (`base_url = "https://api.anthropic.com/v1"`) with `anthropic-version: 2023-06-01` header

### `chat()` — Line 218

```python
async def chat(
    prompt: str,
    model: str = SONNET,
    max_tokens: int = 1024,
    system: str = "",
    temperature: Optional[float] = None,
) -> str:
```

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `str` | required | User message content |
| `model` | `str` | `SONNET` | Gateway model ID |
| `max_tokens` | `int` | `1024` | Max response tokens |
| `system` | `str` | `""` | System message (prepended if non-empty) |
| `temperature` | `Optional[float]` | `None` | Sampling temperature (omitted from API call if None) |

**Complete logic flow:**
1. Build messages: `[{system}, {user: prompt}]`
2. Build model chain: `[primary] + fallback_chain`
3. For each candidate model:
   a. Skip if `_is_exhausted(candidate)` — log as `"(skipped-exhausted)"`
   b. Call `_call_model(client, candidate, messages, max_tokens, temperature)`
   c. On success: if fallback was used, log info message. Return result.
   d. On exception:
      - If `_is_credit_error(exc)`: mark exhausted, log warning, fire-and-forget `_log_fallback_to_notion()`, continue to next model
      - If NOT credit error: **re-raise immediately** (don't try fallbacks for network/malformed errors)
4. If ALL models exhausted: log critical, fire-and-forget `_log_all_models_failed()`, raise `RuntimeError`

**Error messages logged to Notion Mission Control:**
- Fallback event: `"Credit exhaustion fallback: {primary} → {fallback}"`
- All failed: `"ALL models exhausted: {models_tried}"` with severity `"Critical"`

### `chat_stream()` — Line 290

Same logic as `chat()` but yields string chunks via `async for`:

```python
async def chat_stream(prompt, model, max_tokens, system, temperature):
    # ... yields content deltas as strings
```

### `resolve_drafter_model(model_key)` — Line 343

```python
def resolve_drafter_model(model_key: str) -> str:
```
Maps user-facing key to gateway ID. Falls back to the key itself if not found in `DRAFTER_MODELS`.

---

## Part 7: JSON Parsing & Retry — Every Edge Case

**File:** `backend/utils/parsing.py` (293 lines)

### `parse_json_safe(text)` — Line 163

```python
def parse_json_safe(text: str) -> dict:
```

**Returns:** Parsed dict, or `{}` on any failure. **Never raises.**

**Strategy (ordered):**

1. **Empty input** → `{}`
2. **Code fences** — if text contains ` ``` `:
   - Split by ` ``` `, take odd-indexed segments (inside fences)
   - Strip leading `json` label
   - Try `_try_load(block)` on each
3. **Direct parse** — `_try_load(full_text)`
4. **Balanced-brace extraction** — find first `{`, track brace depth, extract `{...}` when depth returns to 0
   - Try `_try_load(candidate)`
   - If fails, try removing trailing commas: `re.sub(r",\s*([}\]])", r"\1", candidate)`
5. **Log failure** — debug log with first 120 chars

#### `_try_load(text)` — Line 221

```python
def _try_load(text: str) -> Optional[dict]:
```

- `json.loads(text)` → if `dict`, return it
- If `list` with at least one `dict` element → return `obj[0]` (unwrap single-element array)
- On `JSONDecodeError` or `ValueError` → return `None`

**Edge cases handled by parse_json_safe:**
- ` ```json\n{...}\n``` ` — code fences with json label
- ` ```\n{...}\n``` ` — code fences without label
- `"Here is the result: {...}"` — prose before JSON
- `[{"key": "value"}]` — array wrapping single object
- `{"key": "value",}` — trailing comma
- Nested braces within strings
- Multiple code fence blocks (tries each)
- Empty string → `{}`

---

### `CreditExhaustedError` — Line 235

```python
class CreditExhaustedError(Exception):
    def __init__(self, service: str, original: Exception):
        self.service = service
        self.original = original
        super().__init__(f"{service} credit/quota exhausted: {original}")
```

Raised by `retry_async()` when a credit error is detected AND a `service` name is provided.

---

### `retry_async()` — Line 244

```python
async def retry_async(
    coro_factory: Callable[[], Any],
    retries: int = 3,
    base_delay: float = 1.5,
    label: str = "",
    exceptions: Tuple[type, ...] = (Exception,),
    service: str = "",
) -> Optional[Any]:
```

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `coro_factory` | `Callable[[], Any]` | required | Zero-arg callable returning a new coroutine |
| `retries` | `int` | `3` | Total attempts (including first) |
| `base_delay` | `float` | `1.5` | Initial backoff delay in seconds |
| `label` | `str` | `""` | Human-readable tag for logs |
| `exceptions` | `Tuple[type, ...]` | `(Exception,)` | Exception types to catch |
| `service` | `str` | `""` | Service name for credit detection |

**Backoff formula:** `delay = base_delay * (2 ** attempt)`
- Attempt 0: 1.5s
- Attempt 1: 3.0s
- Attempt 2: 6.0s

**Logic:**
1. For each attempt (0 to `retries-1`):
   a. Call `coro_factory()` and await
   b. On success → return result
   c. On exception:
      - If `service` is set AND `_is_api_credit_error(exc)`:
        - Call `api_health.record_error(service, exc)`
        - Raise `CreditExhaustedError` immediately (no retry)
      - Otherwise: sleep `base_delay * 2^attempt`, then retry
2. After all attempts fail → log warning, return `None`

**Critical design:** `coro_factory` must return a NEW coroutine each call. Passing a pre-created coroutine will fail on retry since coroutines can only be awaited once.

---

## Part 8: API Health Tracker — Credit Exhaustion System

**File:** `backend/utils/parsing.py` (Lines 24-160)

### Credit Signal Detection (Line 27)

```python
_CREDIT_SIGNALS = (
    "429", "rate limit", "rate_limit", "402", "payment required",
    "insufficient", "quota", "exceeded", "billing", "credits",
    "resource_exhausted", "too many requests", "limit reached",
    "spending limit", "usage limit", "plan limit", "subscription", "free tier",
)
_CREDIT_STATUS_CODES = {429, 402, 403}
```

### `_is_api_credit_error(exc)` — Line 39

Checks:
1. String match: any `_CREDIT_SIGNALS` substring in `str(exc).lower()`
2. Status code: `exc.status_code`, `exc.http_status`, or `exc.response.status_code` in `{429, 402, 403}`

### Class: `APIHealthTracker` — Line 55

```python
class APIHealthTracker:
    def __init__(self, cooldown_secs: int = 600):  # 10 minutes
```

**State:**
- `_cooldown`: seconds before retrying (600)
- `_exhausted`: `{service: expiry_timestamp}`
- `_last_errors`: `{service: error_message}`
- `_exhausted_at`: `{service: ISO_timestamp}`
- `_success_counts`: `{service: count}`

### Methods

#### `is_exhausted(service)` — Line 79
Returns `True` if service is within cooldown. Auto-clears expired entries and logs `"re-enabling"`.

#### `record_error(service, exc)` — Line 92
If credit error detected:
1. Set cooldown expiry
2. Store error message (truncated to 300 chars)
3. Store ISO timestamp
4. Log warning
5. Fire-and-forget Notion log (catches `RuntimeError` for tests without event loop)
Returns `True` if marked exhausted, `False` if not a credit error.

#### `record_success(service)` — Line 110
Increments success counter. If service was marked exhausted but just worked, **clears exhaustion** (false positive recovery).

#### `get_status()` — Line 120
Returns health status for all tracked services:
```python
{
    "tavily": {"status": "ok"} | {"status": "exhausted", "exhausted_at": "...", "cooldown_remaining_secs": 123, "last_error": "..."},
    "exa": ...,
    "perplexity": ...,
    "jina": ...,
}
```
Always includes these 4 services. Cleans expired entries before returning.

### Singleton (Line 160)

```python
api_health = APIHealthTracker(cooldown_secs=600)
```

---

## Part 9: Pre-Triage Guardrail — Every Check

**File:** `backend/agents/pre_triage_guardrail.py` (187 lines)

**Purpose:** Deterministic filter (NO LLM calls). Runs after analyst, before human triage.

### Thresholds (Line 26)

```python
SCORE_FLOOR = settings.score_floor              # default: 4.0
THEME_ALIGNMENT_FLOOR = settings.theme_alignment_floor  # default: 2
```

### `_check_grant(grant)` — Line 30

**Input:** Single scored grant dict
**Returns:** Rejection reason dict or `None` (passed)

**Check 1: Low overall score**
```python
if weighted_total < SCORE_FLOOR:  # default: 4.0
    return {"reason": "low_score", "detail": f"weighted_total {wt:.2f} < {SCORE_FLOOR}"}
```

**Check 2: Theme alignment too low**
```python
if theme_alignment <= THEME_ALIGNMENT_FLOOR:  # default: 2
    return {"reason": "low_theme_alignment", "detail": f"theme_alignment {ta} <= {THEME_ALIGNMENT_FLOOR}"}
```

**Check 3: Deadline expired or unparseable**
```python
if deadline_dt is None:
    return {"reason": "deadline_unparseable", "detail": f"Could not parse deadline '{deadline_str}'"}
if deadline_dt < datetime.now(timezone.utc):
    return {"reason": "deadline_expired", "detail": f"deadline {deadline_str} is in the past"}
```

**Edge cases:**
- `scores` key missing → `{}` → `theme_alignment = 0` → rejected
- `deadline` key missing/empty → deadline check skipped (passes)
- Unparseable deadline string → flagged as `"deadline_unparseable"` (NOT silently passed)
- Non-triage status grants (`auto_pass`, `hold`, etc.) → skipped entirely, pass through

### `pre_triage_guardrail_node(state)` — Line 70

**Full flow:**
1. Get `scored_grants` from state. If empty → return with `passed=0, rejected=0`
2. For each grant:
   - If `status != "triage"` → pass through (don't filter non-triage grants)
   - Run `_check_grant()` → rejection or pass
3. Update MongoDB: rejected grants get `status: "guardrail_rejected"`
4. Write to `audit_logs` collection
5. Send batch notification via `notify()` (event_type: `"pre_triage_guardrail"`, priority: `"low"`)
6. Log to Notion Agent Runs

**Labels/statuses used:**
- `"triage"` — grants that need filtering
- `"guardrail_rejected"` — status set on rejected grants
- `"low_score"`, `"low_theme_alignment"`, `"deadline_unparseable"`, `"deadline_expired"` — rejection reasons

**Error handling:**
- MongoDB update failure → log warning, continue
- Notification failure → log debug, continue
- Notion sync failure → log debug, continue
- All error handling is non-blocking (guardrail results always returned)

---

## Part 10: MCP Hub — Connection Lifecycle

**File:** `backend/integrations/mcp_hub.py` (387 lines)

### `MCPServerConfig` — Line 46

```python
class MCPServerConfig:
    def __init__(self, name: str, raw: Dict):
        self.name = name
        self.description: str = raw.get("description", name)
        self.command: str = raw.get("command", "")
        self.npm_package: str = raw.get("npm_package", "")
        self.args: List[str] = raw.get("args", [])
        self.env_map: Dict[str, str] = raw.get("env_map", {})
        self.required_env: List[str] = raw.get("required_env", [])
        self.enabled: bool = raw.get("enabled", True)
        self.tags: List[str] = raw.get("tags", [])
```

### `MCPServerConnection` — Line 63

**State:**
- `_session: Optional[ClientSession]`
- `_exit_stack: Optional[AsyncExitStack]`
- `_connected: bool`
- `_lock: asyncio.Lock()` — prevents concurrent connect/disconnect
- `_tools: List[str]` — cached tool names

#### `connect()` — Line 82
1. Acquire lock (prevents race conditions)
2. If already connected → return `True`
3. If disabled → skip
4. Check required env vars → skip if missing (log warning with var names)
5. Resolve command: prefer `shutil.which(cmd)`, fallback to `npx -y {npm_package}`
6. Build env: inherit `os.environ` + mapped env vars
7. Create `StdioServerParameters(command, args, env)`
8. Spawn subprocess via `stdio_client(server_params)`
9. Initialize `ClientSession`
10. Cache tool names from `list_tools()`
11. Log connected with tool count

**Error handling:** On connection failure → cleanup, return `False`

#### `call_tool(tool_name, arguments)` — Line 170
1. If not connected → try `connect()`. If fails → raise `RuntimeError`
2. Call `_call_tool_raw()`
3. **On failure: auto-reconnect once**, then retry
4. If reconnect fails → re-raise original error

#### `_call_tool_raw()` — Line 185
1. Call `self._session.call_tool(tool_name, arguments)`
2. Extract `result.content[0].text`
3. Try `json.loads(text)` → return parsed
4. If not JSON → return raw text string
5. If no content → return `None`

### `MCPHub` — Line 237

#### `connect_all()` — Line 260
Iterates all configs, connects enabled servers sequentially. Returns `{name: bool}`.

#### `call_tool(server, tool_name, arguments)` — Line 326
Delegates to `MCPServerConnection.call_tool()`. Raises `RuntimeError` if server not registered.

#### `find_servers_by_tag(tag)` — Line 348
Returns server names where `tag in config.tags AND server.connected`. Used to find which MCP servers are available for a given agent.

---

## Part 11: Notification Hub — Every Event Type

**File:** `backend/notifications/hub.py` (242 lines)

### Event Types (all possible values for `event_type`)

| Event Type | Description | Priority | Action URL |
|-----------|-------------|----------|------------|
| `scout_complete` | Scout finished discovery | high (if high scores) / normal | `/triage` or `/pipeline` |
| `analyst_complete` | Analyst finished scoring | high (if triage items) / normal | `/triage` or `/pipeline` |
| `high_score_grant` | Grant scored above 7.0 | high | `/grants/{id}` |
| `triage_needed` | Grants awaiting triage | high | `/triage` |
| `draft_section_ready` | Section ready for review | normal | `/drafter` |
| `draft_complete` | All sections approved | high | `/drafter` |
| `agent_error` | Critical agent failure | high | `/monitoring` |
| `deadline_warning` | Urgent deadline approaching | high | — |
| `knowledge_sync` | Knowledge sync completed | normal | — |
| `pre_triage_guardrail` | Grants filtered by guardrail | low | — |

### `notify()` — Line 52

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `event_type` | `str` | required | Event type (see table above) |
| `title` | `str` | required | Short headline |
| `body` | `str` | required | Detail text |
| `action_url` | `str` | `"/dashboard"` | Frontend deep link |
| `priority` | `str` | `"normal"` | `"high"` / `"normal"` / `"low"` |
| `metadata` | `Optional[dict]` | `None` | Event-specific data |
| `user_email` | `str` | `"all"` | Target user or broadcast |

**Dual delivery:**
1. **MongoDB** → `notifications` collection (persisted for bell icon)
2. **Pusher** → `"notifications"` channel, event `"notification:new"`

**Additional Pusher channel for agent events:**
If `event_type` in `("scout_complete", "analyst_complete", "draft_section_ready", "draft_complete")`:
- Also triggers on `"agent-status"` channel with `event_type` as event name

**MongoDB document shape:**
```python
{
    "user_email": str,
    "type": str,
    "priority": str,
    "title": str,
    "body": str,
    "action_url": str,
    "metadata": dict,
    "read": False,
    "read_at": None,
    "created_at": ISO_timestamp,
}
```

**Error handling:** Both MongoDB and Pusher failures are caught and logged (warning/debug). Never raises.

### Convenience Functions

| Function | Event Type | Parameters |
|----------|-----------|------------|
| `notify_scout_complete()` | `scout_complete` | `new_grants, total_found, high_score_count=0, triage_count=0` |
| `notify_analyst_complete()` | `analyst_complete` | `scored_count, triage_count=0, pursue_count=0` |
| `notify_high_score_grant()` | `high_score_grant` | `grant_name, grant_id, score, funder=""` |
| `notify_agent_error()` | `agent_error` | `agent, error_message` |
| `notify_triage_needed()` | `triage_needed` | `count` |
| `notify_draft_complete()` | `draft_complete` | `grant_name, grant_id, pipeline_id` |

---

## Part 12: Theme Profiles — Every Theme

**File:** `backend/agents/drafter/theme_profiles.py` (396 lines)

### Articulation Sections (12 total)

```python
ARTICULATION_SECTIONS = [
    "Problem Statement", "Literature", "Solution", "Why Best Suited",
    "Collaborators", "Outputs", "Outcomes", "Project Plan",
    "Cobenefits", "Unit Economics", "Pricing", "Budget",
]
```

### Section → Articulation Mapping (34 patterns)

Maps grant section names to which articulation documents to retrieve:

| Grant Section Pattern | Articulation Sections Retrieved |
|----------------------|-------------------------------|
| `"project overview"` | Problem Statement, Solution, Outcomes |
| `"executive summary"` | Problem Statement, Solution, Outcomes |
| `"abstract"` | Problem Statement, Solution |
| `"introduction"` | Problem Statement, Literature |
| `"background"` | Problem Statement, Literature |
| `"problem statement"` | Problem Statement, Literature |
| `"literature review"` | Literature |
| `"technical approach"` | Solution, Why Best Suited, Project Plan |
| `"methodology"` | Solution, Project Plan |
| `"research plan"` | Solution, Project Plan, Outputs |
| `"innovation"` | Solution, Why Best Suited |
| `"team"` | Why Best Suited, Collaborators |
| `"team & capabilities"` | Why Best Suited, Collaborators |
| `"partnerships"` | Collaborators |
| `"budget"` | Budget, Unit Economics, Pricing |
| `"budget justification"` | Budget, Unit Economics |
| `"financial plan"` | Budget, Unit Economics, Pricing |
| `"impact"` | Outcomes, Cobenefits |
| `"expected outcomes"` | Outcomes, Outputs |
| `"deliverables"` | Outputs, Project Plan |
| `"milestones"` | Project Plan, Outputs |
| `"timeline"` | Project Plan |
| `"sustainability"` | Cobenefits, Unit Economics |
| `"scalability"` | Unit Economics, Pricing, Outcomes |
| `"commercialization"` | Unit Economics, Pricing |
| `"mrv"` | Solution, Outputs, Why Best Suited |

**Fallback (line 99):** If no pattern matches → `["Problem Statement", "Solution"]`

### 6 Theme Profiles

Each profile contains:

| Field | Type | Description |
|-------|------|-------------|
| `display_name` | `str` | Human-readable theme name |
| `domain_terms` | `List[str]` | 16-18 technical vocabulary terms |
| `tone` | `str` | Writing guidance (2-4 sentences) |
| `strengths` | `List[str]` | 5 company-specific strengths to highlight |
| `evidence_queries` | `Dict[str, str]` | 5 Pinecone search queries: default, technical, impact, team, market |
| `default_sections` | `List[Dict]` | 6 default sections: name, description, word_limit, required, order |

#### Theme: `climatetech` (Line 108)
- **Display:** "Climate Tech / CDR"
- **Tone:** Scientific rigor, quantified climate impact, MRV advantage
- **Strengths:** Plot-level MRV, field data, carbon buyers, founder background, dual pathway
- **Sections:** Executive Summary, Problem & Opportunity, Technical Approach, Team & Track Record, Impact & Scalability, Budget & Timeline

#### Theme: `agritech` (Line 148)
- **Display:** "AgriTech"
- **Tone:** Agricultural impact, farmer livelihoods, accessible language
- **Strengths:** Tea planter expertise, field operations, soil amendments, farmer relationships
- **Sections:** Executive Summary, Agricultural Context, Technical Approach, Team & Field Experience, Impact on Farmers & Soil, Budget & Work Plan

#### Theme: `ai_for_sciences` (Line 188)
- **Display:** "AI for Sciences"
- **Tone:** ML innovation, novel contributions, data advantage
- **Strengths:** Proprietary MRV, real ground-truth data, sensor fusion, scalable inference
- **Sections:** Executive Summary, Scientific Background, Technical Innovation, Data & Infrastructure, Team & Research Capacity, Expected Outcomes & Timeline

#### Theme: `applied_earth_sciences` (Line 228)
- **Display:** "Applied Earth Sciences"
- **Tone:** Deeply technical, peer-review precision, mineral systems
- **Strengths:** Field geochemistry, dissolution rates, geochemical+AI integration, IISc collaboration
- **Sections:** Research Summary, Geological & Geochemical Background, Methodology, Research Team & Facilities, Expected Results & Significance, Budget & Timeline

#### Theme: `social_impact` (Line 268)
- **Display:** "Social Impact"
- **Tone:** Human impact, community outcomes, SDG language, storytelling
- **Strengths:** Farmer partnerships, rural employment, local founders, co-benefits, just transition
- **Sections:** Executive Summary, Community Context, Approach & Activities, Team & Community Relationships, Impact Measurement, Sustainability & Budget

#### Theme: `deeptech` (Line 306)
- **Display:** "Deep Tech"
- **Tone:** Technology moat, TRL language, data flywheel, science to product
- **Strengths:** Proprietary MRV stack, hardware-software integration, data moat, venture-scale market, multiple revenue streams
- **Sections:** Executive Summary, Technology Overview, Technical Development Plan, Team & Technical Capacity, Market & Commercialization, Budget & Milestones

### Theme Resolution Functions

#### `resolve_theme(themes: List[str])` — Line 351
**Input:** List of detected theme strings
**Logic:**
1. If empty → return `"climatetech"` (DEFAULT_THEME)
2. For each theme string:
   - Exact match (lowercased, spaces→underscores) → return
   - Fuzzy match: `"climate"/"cdr"/"carbon"` → climatetech, `"agri"/"farm"` → agritech, etc.
3. If no match → `"climatetech"`

#### `get_theme_profile(theme_key)` — Line 375
Returns profile dict. Falls back to `THEME_PROFILES["climatetech"]` if key not found.

#### `get_evidence_query(theme_key, section_name)` — Line 380
Maps section name to query category:
- `"technical"/"method"/"approach"` → `queries["technical"]`
- `"impact"/"outcome"/"result"` → `queries["impact"]`
- `"team"/"qualif"/"capab"` → `queries["team"]`
- `"budget"/"cost"/"market"` → `queries["market"]`
- Default → `queries["default"]`

---

## Part 13: Notion Config — Every Label & Mapping

**File:** `backend/integrations/notion_config.py` (106 lines)

### Page/Database IDs

| Constant | Env Var | Default Value | Purpose |
|----------|---------|---------------|---------|
| `NOTION_KNOWLEDGE_BASE_PAGE_ID` | `NOTION_KNOWLEDGE_BASE_PAGE_ID` | `""` | Scope knowledge sync |
| `MISSION_CONTROL_PAGE_ID` | `NOTION_MISSION_CONTROL_PAGE_ID` | `30b50d0e-c20e-8057-aee5-f775b9902c95` | Parent page |
| `GRANT_PIPELINE_DS` | `NOTION_GRANT_PIPELINE_DS` | `8e9cd5d9-0239-4072-8233-6006aa184e48` | Grant pipeline DB |
| `AGENT_RUNS_DS` | `NOTION_AGENT_RUNS_DS` | `6848a08a-a5ab-4627-989b-22dac3195f42` | Agent runs log |
| `ERROR_LOGS_DS` | `NOTION_ERROR_LOGS_DS` | `2149b3a1-aa9c-456d-8daf-fce6858807be` | Error logs |
| `TRIAGE_DECISIONS_DS` | `NOTION_TRIAGE_DECISIONS_DS` | `3fc6834d-18b2-4e95-91dc-06ccca42b679` | Triage decisions |
| `DRAFT_SECTIONS_DS` | `NOTION_DRAFT_SECTIONS_DS` | `c244df69-d74e-4703-ac88-d506c85aabe2` | Draft sections |
| `KNOWLEDGE_CONNECTIONS_DS` | `NOTION_KNOWLEDGE_CONNECTIONS_DS` | `1ce5cd69-d174-40bc-9c6a-8277e7a692a4` | Knowledge sync status |
| `DOCUMENTS_LIST_DS` | `NOTION_DOCUMENTS_LIST_DS` | `30d50d0e-c20e-8062-bdb6-000b82620d34` | Articulation docs |
| `TABLE_OF_CONTENT_DS` | `NOTION_TABLE_OF_CONTENT_DS` | `31f50d0e-c20e-80d1-b22a-e7124bd9103e` | Knowledge registry |

### Theme Mappings

#### `TOC_THEME_MAP` — Notion "Content info" → internal key
```python
{
    "theme - Climate tech": "climatetech",
    "theme - Agritech": "agritech",
    "theme - AI for sciences": "ai_for_sciences",
    "theme - Advanced earth sciences": "applied_earth_sciences",
    "theme - Deeptech": "deeptech",
    "theme - general": "general",
}
```

#### `THEME_DISPLAY` — internal key → Notion display name
```python
{
    "climatetech": "Climate Tech",
    "agritech": "Agri Tech",
    "ai_for_sciences": "AI for Sciences",
    "applied_earth_sciences": "Earth Sciences",
    "social_impact": "Social Impact",
    "deeptech": "Deep Tech",
}
```

### Status Mapping

#### `STATUS_MAP` — MongoDB status → Notion select
```python
{
    "triage": "Triage",
    "pursue": "Pursue",
    "pursuing": "Pursue",        # alias
    "watch": "Watch",
    "passed": "Pass",
    "human_passed": "Pass",      # alias
    "auto_pass": "Auto Pass",
    "drafting": "Drafting",
    "draft_complete": "Submitted",
    "submitted": "Submitted",
    "won": "Won",
}
```

### Priority Function

```python
def get_priority_label(score: float) -> str:
    if score >= 6.5: return "High"
    if score >= 5.0: return "Medium"
    return "Low"
```

### Agent Display Names

```python
AGENT_DISPLAY = {
    "scout": "Scout",
    "analyst": "Analyst",
    "drafter": "Drafter",
    "knowledge_sync": "Knowledge Sync",
    "company_brain": "Knowledge Sync",
    "company_brain_load": "Company Brain Load",
    "draft_guardrail": "Draft Guardrail",
    "pre_triage_guardrail": "Pre-Triage Guardrail",
}
```

---

## Part 14: MongoDB Collections — Every Index

**File:** `backend/db/mongo.py` (204 lines)

### Database: `altcarbon_grants`

### Collection Accessors (18 functions)

| Function | Collection Name | Purpose |
|----------|----------------|---------|
| `graph_checkpoints()` | `graph_checkpoints` | LangGraph state |
| `grants_raw()` | `grants_raw` | Scout output |
| `grants_scored()` | `grants_scored` | Analyst output |
| `grants_pipeline()` | `grants_pipeline` | Pipeline tracking |
| `grant_drafts()` | `grant_drafts` | Draft documents |
| `draft_reviews()` | `draft_reviews` | Review output |
| `grant_outcomes()` | `grant_outcomes` | Submission results |
| `golden_examples()` | `golden_examples` | Few-shot examples |
| `knowledge_chunks()` | `knowledge_chunks` | Indexed knowledge |
| `knowledge_sync_logs()` | `knowledge_sync_logs` | Sync history |
| `agent_config()` | `agent_config` | Agent settings |
| `audit_logs()` | `audit_logs` | Event log |
| `scout_runs()` | `scout_runs` | Run tracking |
| `funder_context_cache()` | `funder_context_cache` | Perplexity cache |
| `drafter_chat_history()` | `drafter_chat_history` | Chat messages |
| `notion_page_cache()` | `notion_page_cache` | Page cache |
| `draft_preferences()` | `draft_preferences` | User preferences |
| `chat_snapshots()` | `chat_snapshots` | Conversation state |

### `ensure_indexes()` — Line 89

Creates all MongoDB indexes at startup. Uses `_idx()` helper that catches `OperationFailure` for pre-existing indexes.

#### `grants_raw` Indexes
| Index | Options | Purpose |
|-------|---------|---------|
| `url_hash` | `unique=True` | Primary dedup key |
| `scraped_at` | — | Time-based queries |
| `processed` | — | Filter unprocessed |
| `normalized_url_hash` | `sparse=True` | Layer 2 dedup |
| `content_hash` | `sparse=True` | Layer 3 dedup |
| `grant_type` | `sparse=True` | Filter by type |

#### `grants_scored` Indexes
| Index | Options | Purpose |
|-------|---------|---------|
| `url_hash` | `unique=True, sparse=True` | Dedup |
| `raw_grant_id` | — | Link to raw |
| `status` | — | Pipeline filtering |
| `[("weighted_total", -1)]` | — | Sort by score desc |
| `deadline` | — | Deadline queries |
| `content_hash` | `sparse=True` | Layer 3 dedup |
| `grant_type` | `sparse=True` | Type filter |
| `[("funder", 1), ("title", 1)]` | `sparse=True` | Funder+title compound |
| `scored_at` | — | Time-based |
| `[("deadline_urgent", 1), ("status", 1)]` | — | Urgent + status compound |

#### `grants_pipeline` Indexes
| Index | Options |
|-------|---------|
| `grant_id` | — |
| `thread_id` | `unique=True` |
| `status` | — |
| `[("status", 1), ("started_at", -1)]` | — |

#### TTL Indexes (auto-delete)
| Collection | TTL Field | Duration | Purpose |
|-----------|-----------|----------|---------|
| `funder_context_cache` | `cached_at` | 7 days | Stale funder data |
| `deep_research_cache` | `cached_at` | 7 days | Stale research |
| `notion_page_cache` | `cached_at` | 24 hours | Stale page content |
| `notifications` | `created_at` | 30 days | Old notifications |
| `chat_snapshots` | `snapshot_at` | 90 days | Old snapshots |

---

## Part 15: Scout Agent — Complete Logic

**File:** `backend/agents/scout.py` (~1800 lines)

### Search Sources & Query Templates

| Source | # Templates | API | Model |
|--------|------------|-----|-------|
| Tavily | 8 | `tavily-python` | — |
| Exa | 10 | `exa-py` | — |
| Perplexity | variable | OpenAI-compat | `perplexity/sonar` |
| Direct crawl | ~12 sites | HTTP/Jina | — |

### 3-Layer Deduplication

| Layer | Field | Scope | Description |
|-------|-------|-------|-------------|
| 1 | `url_hash` | In-memory + DB | SHA256 of raw URL |
| 2 | `normalized_url_hash` | DB | SHA256 of URL after stripping query params, fragments, trailing slashes |
| 3 | `content_hash` | DB | SHA256 of `title.lower() + funder.lower()` |

### Hub Expansion

For listing pages (BIRAC, DST, ANRF hubs), the scout extracts individual grant URLs from the hub page content via `_extract_hub_subgrants()`. Each sub-URL becomes a separate discovery item with `source: "hub_expansion"`.

### Enrichment Pipeline

For each grant:
1. **Content fetch** (if `raw_content < 400 chars`): Jina → plain HTTP → Cloudflare
2. **Theme detection**: keyword matching against content + title (no LLM)
3. **LLM field extraction**: Claude extracts structured fields
4. **Field merging**: LLM output merged with raw values as fallback
5. **Deadline regex fallback**: if LLM returns null deadline, try `_extract_deadline_regex()`

### Extracted Fields

| Field | Source | Fallback |
|-------|--------|----------|
| `grant_name` / `title` | LLM | Raw title |
| `funder` | LLM | URL-based extraction |
| `grant_type` | LLM | `"grant"` |
| `geography` | LLM | `""` |
| `amount` / `max_funding_usd` | LLM | `""` / `None` |
| `currency` | LLM | `"USD"` |
| `deadline` | LLM | Regex fallback |
| `eligibility` | LLM | `""` |
| `application_url` | LLM | Grant URL |
| `about_opportunity` | LLM | `""` |
| `past_winners_url` | LLM | `None` |

### Quality Filter

`_is_quality_grant(title, url, content)` rejects:
- Pages without actual grant content
- News articles about grants (not the grant itself)
- Job postings, events, general org pages

### Heartbeat Updates

On success/failure, updates agent heartbeat via `update_heartbeat("scout", {...})`.

### Notion Logging

On failure: logs to `Error Logs` (severity: `"Critical"`) and `Agent Runs` (status: `"Failed"`).

---

## Part 16: Analyst Agent — Scoring Formula

**File:** `backend/agents/analyst.py` (~600 lines)

### Hard Rules (auto_pass immediately)

| Rule | Condition | Result |
|------|-----------|--------|
| Deadline too close | `days_to_deadline < deadline_urgent_days (30)` | `status: "auto_pass"` |
| Funding too low (USD) | `max_funding_usd < min_grant_funding (3000)` | `status: "auto_pass"` |
| Funding too low (INR) | `max_funding_inr < min_funding_inr (150000)` | `status: "auto_pass"` |
| Geography mismatch | Not UK/India applicable | `status: "auto_pass"` |
| Theme mismatch | No theme overlap with any of 6 themes | `status: "auto_pass"` |

### Scoring Dimensions (6)

Each dimension scored 1-10 by Claude Opus:

| Dimension | Weight | What evaluator considers |
|-----------|--------|------------------------|
| `theme_alignment` | 0.25 | Match to 6 AltCarbon themes |
| `eligibility_confidence` | 0.20 | How well AltCarbon fits eligibility criteria |
| `funding_amount` | 0.20 | Attractiveness of funding size |
| `deadline_urgency` | 0.15 | Time remaining to apply |
| `geography_fit` | 0.10 | UK/India geographic match |
| `competition_level` | 0.10 | Expected competition intensity |

### Weighted Total Formula

```
weighted_total = Σ(score_i × weight_i)  for all 6 dimensions
```

### Red Flag System

```python
penalty = min(num_red_flags × red_flag_penalty, red_flag_max_penalty)
# Default: min(n × 0.5, 2.0)
adjusted_total = weighted_total - penalty
```

### Action Thresholds

```
adjusted_total >= 6.5 → "pursue" (status: "triage")
adjusted_total >= 5.0 → "watch"  (status: "watch")
adjusted_total <  5.0 → "pass"   (status: "auto_pass")
```

### Funder Enrichment

Uses Perplexity via AI Gateway (`perplexity/sonar`) to research funder background. Cached in `funder_context_cache` with 7-day TTL.

---

## Part 17: Drafter Agent — Section Loop

**Files:** `backend/agents/drafter/` (6 files)

### Per-Section Loop (drafter_node.py)

```
For section_index 0 to len(sections_required)-1:
  1. Load theme profile (resolve_theme)
  2. Get articulation sections (SECTION_TO_ARTICULATION mapping)
  3. Build criteria map from evaluation criteria
  4. Generate section via section_writer
  5. Self-critique (score 1-10 on coherence, evidence, clarity)
  6. If critique_score < revision_threshold (6.0):
     → Generate revision instructions
     → Increment section_revision_counts
     → If revision_count < max_revision_attempts (3): loop back to step 4
     → If max reached: use best version
  7. Set pending_interrupt with section content + critique
  8. Graph interrupts (interrupt_before=["drafter"])
  9. On resume, check section_review_decision:
     → "approve": store in approved_sections, advance index
     → "revise": incorporate section_edited_content, re-critique
  10. After all sections: route_after_drafter → "export"
```

### Section Writer (section_writer.py)

Takes as input:
- Section name and description
- Company context (from Company Brain)
- Theme profile (domain terms, tone, strengths)
- Grant requirements (from grant reader)
- Criteria map (what evaluators look for)
- Previously approved sections (for coherence)
- Style examples (from golden examples)

### Grant Reader (grant_reader.py)

Parses grant document into structured format:
```python
{
    "sections_required": [{"name": str, "description": str, "word_limit": int}],
    "evaluation_criteria": [{"criterion": str, "weight": str}],
    "budget_info": {"total": str, "categories": [...]},
    "eligibility": str,
    "funder_terms": str,  # language to mirror
}
```

### Draft Guardrail (draft_guardrail.py)

Validates draftability:
- Has valid content (not empty/error page)
- Has extractable sections
- Has enough information to draft

Returns: `{passed: bool, checks: [...], reason: str}`

### Exporter (exporter.py)

Saves completed draft:
1. Assemble all `approved_sections` into markdown
2. Store in `grant_drafts` collection
3. Update `grants_pipeline` status

---

## Part 18: Reviewer Agent — Dual Review

**Files:** `backend/agents/reviewer.py`, `backend/agents/dual_reviewer.py`

### Three Review Perspectives

| Perspective | Model | What it evaluates |
|------------|-------|-------------------|
| Funder-centric | Sonnet | Does draft match funder priorities? |
| Scientific credibility | Sonnet | Is evidence rigorous? |
| Coherence | Sonnet | Do sections tell consistent story? |

### Output Structure

```python
{
    "funder_score": float,      # 1-10
    "funder_notes": str,
    "credibility_score": float,  # 1-10
    "credibility_notes": str,
    "coherence_score": float,    # 1-10
    "coherence_notes": str,
    "overall_score": float,      # average or weighted
    "ready_for_export": bool,    # overall >= 6.5
    "summary": str,
    "suggested_revisions": [
        {"section": str, "suggestion": str, "priority": str}
    ],
}
```

### Thresholds

| Threshold | Value | Effect |
|-----------|-------|--------|
| `reviewer_revision_threshold` | 6.0 | Any dimension below → flag for revision |
| `reviewer_export_threshold` | 6.5 | Overall below → not ready for export |

---

## Part 19: Company Brain — Knowledge Retrieval

**File:** `backend/agents/company_brain.py` (~400 lines)

### Two Modes

| Mode | Node | When | Purpose |
|------|------|------|---------|
| Load | `company_brain_load_node` | Before analyst | Load static profile |
| Retrieve | `company_brain_node` | After triage (pursue only) | Grant-specific context |

### Knowledge Sources (Priority Order)

1. **Pinecone vector search** — semantic search of indexed chunks
2. **Notion MCP search** — live search of workspace pages
3. **MongoDB knowledge_chunks** — fallback text search
4. **Static profile** — `backend/knowledge/altcarbon_profile.md` (always available)

### Chunking Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `chunk_size` | 400 words | Words per chunk |
| `chunk_overlap` | 80 words | Overlap between chunks |
| `min_chunk_words` | 40 | Minimum words to keep |

---

## Part 20: FastAPI Routes — Every Endpoint

**File:** `backend/main.py` (~161KB)

See DEVELOPER_GUIDE.md Section 5.1 for full route table. Key details:

### Pydantic Request Models

#### `TriageResumeRequest`
```python
class TriageResumeRequest(BaseModel):
    thread_id: str           # LangGraph thread ID
    grant_id: str            # MongoDB _id
    decision: str            # "pursue" | "pass" | "watch"
    notes: Optional[str] = None
```

#### `StartDraftRequest`
```python
class StartDraftRequest(BaseModel):
    grant_id: str
    thread_id: Optional[str] = None  # Auto-generated if not provided
```

#### `DrafterChatRequest`
```python
class DrafterChatRequest(BaseModel):
    pipeline_id: str
    section_name: str
    message: str
    model: Optional[str] = None  # User-selected model key
```

#### `ManualGrantRequest`
```python
class ManualGrantRequest(BaseModel):
    title: str
    funder: str
    url: str
    funding_amount: Optional[str] = None
    deadline: Optional[str] = None
    description: Optional[str] = None
```

#### `RunReviewRequest`
```python
class RunReviewRequest(BaseModel):
    grant_id: str
    thread_id: Optional[str] = None
```

#### `ApplySuggestionsRequest`
```python
class ApplySuggestionsRequest(BaseModel):
    grant_id: str
    accepted_suggestions: list[str]
    rejected_suggestions: list[str]
```

#### `RecordOutcomeRequest`
```python
class RecordOutcomeRequest(BaseModel):
    grant_id: str
    outcome: str            # "won" | "lost" | "pending"
    amount_received: Optional[float] = None
    notes: Optional[str] = None
```

---

## Part 21: Frontend — Every Component

See DEVELOPER_GUIDE.md Section 6.2 for component inventory. Key details:

### Color System (from `lib/utils.ts`)

```typescript
function getPriority(score: number) {
    if (score >= 6.5) return { label: "High", color: "text-green-600", bg: "bg-green-50" }
    if (score >= 5.0) return { label: "Medium", color: "text-amber-600", bg: "bg-amber-50" }
    return { label: "Low", color: "text-red-600", bg: "bg-red-50" }
}
```

### Theme Labels

```typescript
const THEME_LABELS = {
    climatetech: { label: "Climate Tech", color: "bg-teal-100 text-teal-800" },
    agritech: { label: "Agri Tech", color: "bg-green-100 text-green-800" },
    ai_for_sciences: { label: "AI for Sciences", color: "bg-purple-100 text-purple-800" },
    applied_earth_sciences: { label: "Earth Sciences", color: "bg-blue-100 text-blue-800" },
    social_impact: { label: "Social Impact", color: "bg-orange-100 text-orange-800" },
    deeptech: { label: "Deep Tech", color: "bg-pink-100 text-pink-800" },
}
```

### Status Labels

```typescript
const STATUS_LABELS = {
    triage: "Shortlisted",
    pursue: "Pursue",
    watch: "Watch",
    passed: "Pass",
    auto_pass: "Auto Pass",
    drafting: "Drafting",
    draft_complete: "Draft Complete",
    submitted: "Submitted",
    won: "Won",
    guardrail_rejected: "Filtered",
}
```

---

## Part 22: Frontend API Routes — Every Proxy

All frontend API routes follow this pattern:

```typescript
export async function POST(request: NextRequest) {
    const body = await request.json()
    const res = await fetch(`${FASTAPI_URL}/path`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "x-internal-secret": INTERNAL_SECRET,
            "x-user-email": session?.user?.email || "",
        },
        body: JSON.stringify(body),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
}
```

**Headers sent to backend:**
- `Content-Type: application/json`
- `x-internal-secret`: from env `INTERNAL_SECRET`
- `x-user-email`: from NextAuth session (or empty)

**Error handling:** If backend returns non-OK status, the status code is forwarded to the frontend client.

---

## Part 23: Configuration Files — Every Setting

See agent output from config reader. Key highlights:

### Backend Dockerfile
- **Base:** `python:3.11-slim-bookworm`
- **Node.js 20:** for MCP servers
- **Playwright Chromium:** for page rendering
- **Non-root user:** `appuser:appgroup` (UID/GID 1001)
- **Port:** `${PORT:-8000}`
- **Healthcheck:** `curl -f http://localhost:${PORT:-8000}/health` every 30s

### Frontend Dockerfile
- **Multi-stage:** deps → builder → runner
- **Base:** `node:20-alpine`
- **Output:** standalone
- **Non-root user:** `nextjs:nodejs` (UID/GID 1001)

### Cron Schedule (Vercel)
| Job | Schedule | Description |
|-----|----------|-------------|
| Scout | `0 2 */2 * *` | Every 2 days at 2am UTC |
| Analyst | `0 4 */2 * *` | Every 2 days at 4am UTC |
| Knowledge Sync | `0 6 * * *` | Daily at 6am UTC |

---

## Part 24: Skills Registry — Every Skill

**File:** `backend/config/skills.yaml`

### 20 Skills Across 6 Categories

| Category | Skill | Providers (in fallback order) |
|----------|-------|-------------------------------|
| **Discovery** | `web_search` | Tavily → Exa → Perplexity |
| | `fetch_page` | Fetch MCP → Jina → Plain HTTP |
| | `extract_fields` | Internal LLM |
| **Research** | `enrich_funder` | Perplexity direct → Perplexity gateway |
| | `score_grant` | Internal LLM |
| | `deep_research` | Internal LLM |
| **Knowledge** | `search_workspace` | Notion MCP → Notion REST |
| | `fetch_document` | Notion MCP → GDrive MCP → Notion REST → GDrive API |
| | `vector_search` | Pinecone API |
| | `vector_upsert` | Pinecone API |
| | `load_company_profile` | Vector store → Static profile |
| **Writing** | `fetch_grant_doc` | Fetch MCP → Jina → Firecrawl |
| | `parse_grant_doc` | Internal LLM |
| | `write_section` | Internal LLM |
| | `review_draft` | Internal LLM |
| | `export_draft` | Filesystem MCP → Internal local |
| **Communication** | `send_notification` | Internal Pusher |
| | `send_slack_message` | Slack MCP (disabled) |
| | `alert_triage` | Internal notify → Slack MCP |
| **Sync** | `sync_grant` | Notion SDK |
| | `log_agent_run` | Notion SDK |
| | `log_error` | Notion SDK |
| | `sync_draft` | Notion SDK |

---

## Part 25: MCP Servers Config — Every Server

**File:** `backend/config/mcp_servers.yaml`

| Server | Command | Enabled | Required Env | Tags |
|--------|---------|---------|-------------|------|
| `notion` | `notion-mcp-server` | **true** | `NOTION_TOKEN` | knowledge, sync |
| `slack` | `slack-mcp-server` | false | `SLACK_BOT_TOKEN`, `SLACK_TEAM_ID` | communication |
| `google_drive` | `google-drive-mcp-server` | false | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | knowledge |
| `filesystem` | `filesystem-mcp-server` | false | — | drafter, exports |
| `fetch` | `fetch-mcp-server` | false | — | scout, content_fetcher |

**Only `notion` is currently enabled.** All others are configured but disabled.

---

*This document covers every parameter, edge case, error handler, label, and logic flow in the Grants Intelligence Engine codebase. Updated 2026-03-20.*
