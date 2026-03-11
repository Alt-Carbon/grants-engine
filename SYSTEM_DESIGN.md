# Grants Intelligence Engine — System Design

> AltCarbon's AI-powered grant discovery, scoring, and drafting platform.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [System Context Diagram](#2-system-context-diagram)
3. [Component Architecture](#3-component-architecture)
4. [Data Flow — End-to-End Pipeline](#4-data-flow--end-to-end-pipeline)
5. [Agent Architecture](#5-agent-architecture)
6. [LangGraph State Machine](#6-langgraph-state-machine)
7. [Data Architecture](#7-data-architecture)
8. [Frontend Architecture](#8-frontend-architecture)
9. [Knowledge RAG Pipeline](#9-knowledge-rag-pipeline)
10. [Integration Layer](#10-integration-layer)
11. [Authentication & Security](#11-authentication--security)
12. [Real-Time Event System](#12-real-time-event-system)
13. [Error Handling & Resilience](#13-error-handling--resilience)
14. [Deployment Architecture](#14-deployment-architecture)
15. [API Contract Reference](#15-api-contract-reference)
16. [Areas of Improvement](#16-areas-of-improvement)
    - [16.1 Latency Optimization](#161-latency-optimization)
    - [16.2 Cron Scheduler (Railway-Native)](#162-cron-scheduler-railway-native)
    - [16.3 Notification System](#163-notification-system)
    - [16.4 Effort vs Impact Matrix](#164-improvement-summary--effort-vs-impact-matrix)

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GRANTS INTELLIGENCE ENGINE                   │
│                                                                     │
│  ┌──────────────────┐          ┌──────────────────────────────────┐ │
│  │   Next.js 16     │  HTTP    │       FastAPI + LangGraph        │ │
│  │   Frontend       │◄────────►│       Backend                    │ │
│  │                  │          │                                  │ │
│  │  • Dashboard     │          │  ┌──────┐ ┌────────┐ ┌────────┐ │ │
│  │  • Pipeline      │          │  │Scout │→│Analyst │→│Drafter │ │ │
│  │  • Triage        │          │  └──────┘ └────────┘ └────────┘ │ │
│  │  • Drafter UI    │          │       ▲                    │     │ │
│  │  • Monitoring    │          │       │   ┌─────────────┐  │     │ │
│  │  • Knowledge     │          │       └───│Company Brain│──┘     │ │
│  └────────┬─────────┘          │           └─────────────┘       │ │
│           │                    └──────────────┬──────────────────┘ │
│           │                                   │                    │
│  ┌────────▼───────────────────────────────────▼──────────────────┐ │
│  │                     DATA & SERVICES LAYER                     │ │
│  │                                                               │ │
│  │  MongoDB Atlas    Pinecone     Notion MCP    Pusher           │ │
│  │  (Primary DB)     (Vectors)    (Knowledge)   (Real-time)      │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 16, TypeScript, Tailwind CSS | Dashboard, pipeline management, drafter UI |
| Backend | FastAPI, Python 3.11+ | API server, agent orchestration |
| Orchestration | LangGraph | Multi-agent state machine with human-in-the-loop |
| Primary DB | MongoDB Atlas | Grants, pipelines, drafts, audit logs, comments |
| Vector DB | Pinecone (serverless) | Knowledge RAG embeddings |
| Knowledge | Notion MCP Server | Live workspace reads for company knowledge |
| Auth | NextAuth v5 (Google OAuth) | SSO restricted to @altcarbon.com |
| Real-time | Pusher | Live comment updates, event broadcasting |
| LLM | Claude Sonnet/Haiku via AI Gateway | Scoring, drafting, analysis, tagging |
| Embeddings | OpenAI text-embedding-3-small | 1536-dim vectors for RAG |
| Search | Tavily, Exa, Perplexity, Jina Reader | Grant discovery, funder enrichment, doc parsing |

---

## 2. System Context Diagram

```
                              ┌───────────────┐
                              │  Grants       │
                              │  Officer      │
                              │  (AltCarbon)  │
                              └───────┬───────┘
                                      │ Browser
                                      ▼
┌──────────────┐           ┌──────────────────┐           ┌──────────────┐
│  Google      │◄──OAuth──►│   Next.js        │──proxy───►│  FastAPI     │
│  Identity    │           │   Frontend       │           │  Backend     │
└──────────────┘           │                  │           │              │
                           │  Railway/Vercel  │           │  Railway     │
                           └────────┬─────────┘           └──────┬───────┘
                                    │                            │
                    ┌───────────────┼────────────┐    ┌──────────┼──────────┐
                    ▼               ▼            ▼    ▼          ▼          ▼
             ┌──────────┐  ┌──────────┐  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
             │ MongoDB  │  │ Pusher   │  │ Notion │ │Pinecone│ │Tavily  │ │OpenAI  │
             │ Atlas    │  │          │  │ MCP    │ │        │ │Exa     │ │Embeddings│
             └──────────┘  └──────────┘  └────────┘ └────────┘ │Perplexity│└────────┘
                                                               │Jina    │
                                                               └────────┘

Actors:
  • Grants Officer — Reviews triage queue, approves/revises draft sections
  • Cron Scheduler — Triggers Scout (48h) and Knowledge Sync (daily)
  • AI Agents — Autonomous grant discovery, scoring, drafting

External Services:
  • Tavily/Exa/Perplexity — Web search for grant discovery
  • Jina Reader — PDF/webpage content extraction
  • Notion MCP — AltCarbon workspace knowledge (read-only)
  • Notion Client SDK — Mission Control sync (write-only)
  • Pusher — WebSocket relay for real-time events
  • OpenAI — Embedding generation (text-embedding-3-small)
  • AI Gateway — LLM routing (Claude Sonnet/Haiku, GPT fallback)
```

---

## 3. Component Architecture

### Backend Components

```
backend/
├── main.py                          # FastAPI app — all endpoints, CORS, lifespan
├── config/
│   └── settings.py                  # Pydantic v2 settings from .env
├── graph/
│   ├── graph.py                     # LangGraph workflow definition
│   ├── state.py                     # GrantState TypedDict (shared state)
│   └── checkpointer.py             # MongoDB-backed state persistence
├── agents/
│   ├── scout.py                     # Grant discovery (Tavily, Exa, Perplexity, crawl)
│   ├── analyst.py                   # Scoring, hard rules, deep analysis
│   ├── company_brain.py             # Knowledge RAG — Notion MCP + vector search
│   ├── drafter/
│   │   ├── grant_reader.py          # Fetch & parse grant documents
│   │   ├── section_writer.py        # Write one application section
│   │   ├── drafter_node.py          # Section loop orchestration
│   │   └── exporter.py              # Assemble final Markdown draft
│   └── reviewer.py                  # Quality scoring against criteria
├── integrations/
│   ├── notion_mcp.py                # Persistent MCP subprocess (read-only)
│   ├── notion_sync.py               # Notion Client SDK (write-only, fire-and-forget)
│   └── notion_config.py             # DB IDs, property mappings, theme/status maps
├── knowledge/
│   ├── sync_profile.py              # Static profile rebuild from Notion pages
│   └── altcarbon_profile.md         # Fallback company knowledge (~22K chars)
├── db/
│   ├── mongo.py                     # Connection pool, collection accessors, indexes
│   └── pinecone_store.py            # Pinecone vector operations
├── jobs/
│   ├── scout_job.py                 # Scout + Analyst pipeline trigger
│   ├── knowledge_job.py             # Knowledge sync trigger
│   └── backfill_job.py              # One-time data maintenance
└── utils/
    ├── llm.py                       # LLM client with model fallback chains
    └── parsing.py                   # JSON extraction, retry, API health tracking
```

### Frontend Components

```
frontend/src/
├── app/
│   ├── layout.tsx                   # Root layout — auth gate, sidebar
│   ├── page.tsx                     # Redirect → /dashboard
│   ├── dashboard/page.tsx           # KPIs, activity chart, grants table
│   ├── pipeline/page.tsx            # Kanban + table with filters
│   ├── triage/
│   │   ├── page.tsx                 # Server: fetch triage queue
│   │   └── TriageQueue.tsx          # Client: pursue/pass with override
│   ├── drafter/page.tsx             # Section editor + AI chat
│   ├── monitoring/page.tsx          # Agent health, API quotas
│   ├── audit/page.tsx               # Full audit log viewer
│   ├── config/page.tsx              # Agent config editor
│   ├── knowledge/page.tsx           # Vector index health, Notion sources
│   ├── grants/[id]/
│   │   ├── page.tsx                 # Server: fetch single grant
│   │   └── GrantDetailPage.tsx      # Full-page detail view
│   ├── login/page.tsx               # OAuth login screen
│   └── api/                         # 27 API routes (proxy + DB ops)
├── components/
│   ├── Sidebar.tsx                  # Navigation, agent controls, profile
│   ├── PipelineView.tsx             # Filter container, view toggle
│   ├── PipelineBoard.tsx            # Kanban drag-drop (@hello-pangea/dnd)
│   ├── PipelineTable.tsx            # Sortable table view
│   ├── GrantCard.tsx                # Compact grant summary
│   ├── GrantDetailSheet.tsx         # Right slide-over detail panel
│   ├── CommentThread.tsx            # Nested comments + reactions + Pusher
│   ├── ScoreRadar.tsx               # Recharts radar chart
│   ├── ActivityChart.tsx            # 30-day discovery trend line
│   ├── MissionControl.tsx           # Agent health dashboard
│   ├── DrafterView.tsx              # Section-by-section editor + AI chat
│   ├── StatusPicker.tsx             # Inline status dropdown
│   ├── DeadlineChip.tsx             # Days remaining indicator
│   ├── AgentControls.tsx            # Run/poll buttons in sidebar
│   ├── WhatsNewDigest.tsx           # Returning user summary
│   └── ui/                          # Button, Card, Input, Textarea, Badge
├── hooks/
│   ├── useGrantUrl.ts               # URL-synced grant selection + deep-links
│   ├── usePusher.ts                 # Real-time event subscriptions
│   └── useLastSeen.ts              # localStorage visit tracking
├── lib/
│   ├── auth.ts                      # NextAuth config (Google, domain check)
│   ├── mongodb.ts                   # Singleton DB connection
│   ├── queries.ts                   # All MongoDB queries (~3.5K lines)
│   ├── api.ts                       # FastAPI HTTP client
│   ├── pusher.ts                    # Server-side Pusher singleton
│   └── utils.ts                     # cn(), theme config, priority helpers
└── middleware.ts                    # NextAuth route protection
```

---

## 4. Data Flow — End-to-End Pipeline

The system operates as a **multi-stage pipeline** with two human-in-the-loop gates:

```
PHASE 1: DISCOVERY (Automated — every 48h)
═══════════════════════════════════════════

  ┌────────┐     16 Tavily      ┌──────────────┐     Deduplicate
  │  Cron  │──►  8 Exa          │              │     Content-fetch
  │ Trigger│     6 Perplexity   │    SCOUT     │     Field extract
  │  (48h) │     Direct crawl   │              │     Quality filter
  └────────┘                    └──────┬───────┘
                                       │ raw_grants[]
                                       ▼
PHASE 2: ANALYSIS (Automated)
═════════════════════════════

  ┌──────────────────────────────────────────────┐
  │                  ANALYST                      │
  │                                              │
  │  For each raw grant:                         │
  │  1. Hard eligibility rules (auto-pass/fail)  │
  │  2. Perplexity funder enrichment (cached)    │
  │  3. Claude 6-dimension scoring               │
  │  4. Weighted total → action routing          │
  │  5. Deep analysis (pursue/watch only)        │
  │                                              │
  │  Output: scored_grants[] ranked by score     │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
PHASE 3: TRIAGE (Human Gate #1)
═══════════════════════════════

  ┌──────────────────────────────────────────┐
  │           TRIAGE QUEUE (UI)              │
  │                                          │
  │  Officer reviews shortlisted grants:     │
  │  • Score breakdown (radar chart)         │
  │  • AI recommendation + rationale         │
  │  • Eligibility analysis                  │
  │                                          │
  │  Decision: [Pursue] [Pass]               │
  │  Override? → requires written reason     │
  └──────────────────┬───────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      "pursue"             "watch/pass"
          │                     │
          ▼                     ▼
PHASE 4: KNOWLEDGE          Pipeline
RETRIEVAL                   updated,
(Automated)                 END
═══════════

  ┌─────────────────────────────────────────┐
  │            COMPANY BRAIN                 │
  │                                         │
  │  1. Vector search (Pinecone/MongoDB)    │
  │  2. Theme-filtered chunk retrieval      │
  │  3. Style examples from past apps       │
  │  4. Fallback: static profile (22K chars)│
  │                                         │
  │  Output: company_context, style_examples│
  └──────────────────┬──────────────────────┘
                     │
                     ▼
  ┌─────────────────────────────────────────┐
  │            GRANT READER                  │
  │                                         │
  │  1. Jina Reader fetches grant doc       │
  │  2. Claude extracts:                    │
  │     • Required sections + word limits   │
  │     • Evaluation criteria + weights     │
  │     • Budget constraints                │
  │     • Submission details                │
  │                                         │
  │  Output: grant_requirements             │
  └──────────────────┬──────────────────────┘
                     │
                     ▼
PHASE 5: DRAFTING (Human Gate #2 — per section)
═══════════════════════════════════════════════

  ┌──────────────────────────────────────────────────┐
  │                DRAFTER LOOP                       │
  │                                                  │
  │  For each section (e.g., 5 sections):            │
  │  ┌────────────────────────────────────────────┐  │
  │  │ 1. Section Writer generates draft          │  │
  │  │    (grounded in company context +          │  │
  │  │     grant criteria + style examples)       │  │
  │  │                                            │  │
  │  │ 2. INTERRUPT → Officer reviews:            │  │
  │  │    • [Approve] → save, next section        │  │
  │  │    • [Revise] → instructions → rewrite     │  │
  │  │    • Chat with AI for adjustments          │  │
  │  └────────────────────────────────────────────┘  │
  │  Repeat until all sections approved              │
  └──────────────────┬───────────────────────────────┘
                     │
                     ▼
PHASE 6: REVIEW & EXPORT (Automated)
═════════════════════════════════════

  ┌─────────────────┐     ┌─────────────────┐
  │    REVIEWER      │────►│    EXPORTER      │
  │                 │     │                 │
  │  Score draft vs │     │  Assemble MD    │
  │  eval criteria  │     │  Version in DB  │
  │  Section grades │     │  Ready for      │
  │  Top 3 fixes   │     │  download       │
  └─────────────────┘     └─────────────────┘
```

---

## 5. Agent Architecture

### 5.1 Scout Agent

**Purpose:** Discover grant opportunities from the open web.

```
                    ┌─────────────────────────────┐
                    │         SCOUT AGENT          │
                    │                              │
  ┌──────────┐     │  ┌────────────────────────┐  │     ┌──────────────┐
  │ Tavily   │────►│  │  Multi-source search   │  │────►│ grants_raw   │
  │ (16 q)   │     │  │  (30 queries total)    │  │     │ collection   │
  ├──────────┤     │  └──────────┬─────────────┘  │     └──────────────┘
  │ Exa      │────►│             │                │
  │ (8 q)    │     │  ┌──────────▼─────────────┐  │
  ├──────────┤     │  │  3-layer deduplication  │  │
  │Perplexity│────►│  │  url → normalized → hash│  │
  │ (6 q)    │     │  └──────────┬─────────────┘  │
  ├──────────┤     │             │                │
  │ Direct   │────►│  ┌──────────▼─────────────┐  │
  │ Crawl    │     │  │  Content fetch (Jina)   │  │
  └──────────┘     │  │  + quality filter       │  │
                   │  └──────────┬─────────────┘  │
                   │             │                │
                   │  ┌──────────▼─────────────┐  │
                   │  │  LLM field extraction   │  │
                   │  │  (Claude Haiku)         │  │
                   │  └────────────────────────┘  │
                   └─────────────────────────────┘

Search categories:
  • CDR/Carbon removal grants
  • Agritech/regenerative agriculture
  • AI for environmental sciences
  • India government (BIRAC, ANRF, DST, DBT, AIM, MeitY, TDB, Startup India)
  • Climate tech / deep tech
  • Foundation & DFI grants
```

### 5.2 Analyst Agent

**Purpose:** Score and rank grants against AltCarbon's profile.

```
  Input: raw_grants[]
         │
         ▼
  ┌──────────────────────────────────────────────────┐
  │                 ANALYST AGENT                     │
  │                                                  │
  │  ┌────────────────────────────────┐              │
  │  │ HARD RULES (instant fail)     │              │
  │  │ • Min funding < $3K           │              │
  │  │ • Max funding exceeded        │  auto_pass   │
  │  │ • Deadline expired            │──────────►   │
  │  │ • Excluded geography          │              │
  │  │ • No theme match              │              │
  │  └──────────────┬────────────────┘              │
  │                 │ passes                         │
  │                 ▼                                │
  │  ┌────────────────────────────────┐              │
  │  │ FUNDER ENRICHMENT             │              │
  │  │ Perplexity Sonar (cached 3d)  │              │
  │  └──────────────┬────────────────┘              │
  │                 │                                │
  │                 ▼                                │
  │  ┌────────────────────────────────┐              │
  │  │ 6-DIMENSION SCORING           │              │
  │  │ Claude Sonnet (3 retries)     │              │
  │  │                               │              │
  │  │  theme_alignment     × 0.25   │              │
  │  │  eligibility_conf    × 0.20   │              │
  │  │  funding_amount      × 0.20   │              │
  │  │  deadline_urgency    × 0.15   │              │
  │  │  geography_fit       × 0.10   │              │
  │  │  competition_level   × 0.10   │              │
  │  │  ─────────────────────────    │              │
  │  │  weighted_total       /10     │              │
  │  └──────────────┬────────────────┘              │
  │                 │                                │
  │                 ▼                                │
  │  ┌────────────────────────────────┐              │
  │  │ ACTION ROUTING                │              │
  │  │ ≥ 6.5 → "pursue" (triage)    │              │
  │  │ 5.0–6.4 → "watch"            │              │
  │  │ < 5.0 → "pass"               │              │
  │  └──────────────┬────────────────┘              │
  │                 │                                │
  │                 ▼ (pursue/watch only)            │
  │  ┌────────────────────────────────┐              │
  │  │ DEEP ANALYSIS                 │              │
  │  │ • Strategic angle             │              │
  │  │ • Eligibility checklist       │              │
  │  │ • Past winners analysis       │              │
  │  │ • Evaluation criteria         │              │
  │  │ • Red flags & tips            │              │
  │  └────────────────────────────────┘              │
  └──────────────────────────────────────────────────┘
         │
         ▼
  Output: scored_grants[] (sorted by weighted_total DESC)
          → upserted to grants_scored collection
          → synced to Notion Grant Pipeline DB
```

### 5.3 Company Brain Agent

**Purpose:** AltCarbon's institutional memory — retrieves relevant company knowledge for grounding drafts.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    COMPANY BRAIN                             │
  │                                                             │
  │  SYNC MODE (daily cron):                                    │
  │  ┌─────────────┐    ┌──────────┐    ┌────────┐   ┌──────┐ │
  │  │ Notion MCP  │───►│ Chunking │───►│Tagging │──►│Embed │ │
  │  │ (9+ pages)  │    │ 400w/80  │    │Haiku   │   │OpenAI│ │
  │  └─────────────┘    │ overlap  │    │doc_type│   │1536d │ │
  │                     └──────────┘    │themes  │   └──┬───┘ │
  │                                     └────────┘      │     │
  │                                                     ▼     │
  │                                              ┌──────────┐ │
  │                                              │ Pinecone │ │
  │                                              │ /MongoDB │ │
  │                                              └──────────┘ │
  │                                                            │
  │  QUERY MODE (per draft):                                   │
  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
  │  │ Grant themes │───►│ Vector search│───►│ Top-K chunks │ │
  │  │ + requirements│    │ + theme filter│   │ + style      │ │
  │  └──────────────┘    └──────────────┘    │ examples     │ │
  │                                          └──────────────┘ │
  │                                                            │
  │  4-LEVEL FALLBACK:                                         │
  │  Pinecone → MongoDB Atlas Vector → MongoDB text → Static  │
  └─────────────────────────────────────────────────────────────┘
```

### 5.4 Drafter Subsystem

```
  ┌───────────────────────────────────────────────────────────┐
  │                    DRAFTER SUBSYSTEM                       │
  │                                                           │
  │  ┌─────────────┐                                         │
  │  │Grant Reader │  Jina Reader → Claude Sonnet extract    │
  │  │             │  Outputs: sections[], criteria[], budget│
  │  └──────┬──────┘                                         │
  │         │                                                │
  │         ▼                                                │
  │  ┌─────────────────────────────────────────────────────┐ │
  │  │              SECTION LOOP                           │ │
  │  │                                                     │ │
  │  │  ┌──────────────┐    ┌─────────────┐               │ │
  │  │  │Section Writer│───►│   INTERRUPT  │──► Officer    │ │
  │  │  │              │    │   (review)   │    reviews    │ │
  │  │  │ Grounded in: │    └──────┬──────┘               │ │
  │  │  │ • RAG chunks │           │                      │ │
  │  │  │ • Style      │    ┌──────┴──────┐               │ │
  │  │  │ • Criteria   │    │             │               │ │
  │  │  │ • Word limit │  Approve      Revise             │ │
  │  │  └──────────────┘    │        (instructions)       │ │
  │  │                      │             │               │ │
  │  │                      ▼             │               │ │
  │  │               Next section    ◄────┘               │ │
  │  │               or done                              │ │
  │  └────────────────────────┬────────────────────────────┘ │
  │                           │                              │
  │                           ▼                              │
  │  ┌──────────┐     ┌──────────────┐                      │
  │  │ Reviewer │────►│   Exporter    │                      │
  │  │ Score vs │     │ Markdown +    │                      │
  │  │ criteria │     │ version in DB │                      │
  │  └──────────┘     └──────────────┘                      │
  └───────────────────────────────────────────────────────────┘
```

### 5.5 Theme-Specific Sub-Agents

Each theme has a specialized LLM persona for domain-grounded scoring and drafting:

| Theme | Agent Persona | Expertise Focus |
|-------|--------------|-----------------|
| Climate Tech | CDR/MRV specialist | tCO2e, permanence, Verra/Gold Standard, IPCC AR6 |
| Agri Tech | Regenerative ag expert | Soil carbon, FAO guidelines, VM0042 |
| AI for Sciences | ML researcher | Environmental monitoring, responsible AI, benchmarks |
| Earth Sciences | Geospatial scientist | Remote sensing, Sentinel/Landsat, SAR |
| Social Impact | Development specialist | SDGs, gender equity, just transition |
| Deep Tech | Innovation strategist | TRL levels, IP strategy, commercialization |

---

## 6. LangGraph State Machine

### 6.1 Graph Topology

```
                    ┌───────┐
                    │ START │
                    └───┬───┘
                        │
                        ▼
                   ┌─────────┐
                   │  SCOUT  │  Discover grants
                   └────┬────┘
                        │
                        ▼
                   ┌──────────┐
                   │ ANALYST  │  Score & rank
                   └────┬─────┘
                        │
                        ▼
                ┌───────────────┐
                │ NOTIFY_TRIAGE │  Prepare for human
                └───────┬───────┘
                        │
                ════════╪════════  INTERRUPT #1
                        │
                        ▼
                ┌───────────────┐
                │ HUMAN_TRIAGE  │  Human decides
                └───────┬───────┘
                        │
              ┌─────────┼─────────┐
              ▼         │         ▼
          "pursue"      │    "watch/pass"
              │         │         │
              ▼         │         ▼
       ┌──────────────┐ │  ┌───────────────┐
       │COMPANY_BRAIN │ │  │PIPELINE_UPDATE│──► END
       └──────┬───────┘ │  └───────────────┘
              │         │
              ▼         │
       ┌──────────────┐ │
       │ GRANT_READER │ │
       └──────┬───────┘ │
              │         │
       ═══════╪═════════╪═══  INTERRUPT #2 (per section)
              │         │
              ▼         │
       ┌──────────────┐ │
       │   DRAFTER    │◄┘  Section loop
       │   (loop)     │
       └──────┬───────┘
              │ all sections approved
              ▼
       ┌──────────────┐
       │   REVIEWER   │
       └──────┬───────┘
              │
              ▼
       ┌──────────────┐
       │   EXPORTER   │──► END
       └──────────────┘
```

### 6.2 State Schema (GrantState)

```python
class GrantState(TypedDict):
    # ─── Discovery ───
    raw_grants: List[Dict]                  # Scout output
    scored_grants: List[Dict]               # Analyst output

    # ─── Human Gate 1: Triage ───
    human_triage_decision: str              # "pursue" | "pass" | "watch"
    selected_grant_id: str                  # MongoDB _id of chosen grant
    triage_notes: str                       # Officer notes

    # ─── Grant Reading ───
    grant_requirements: Dict                # Sections, criteria, budget
    grant_raw_doc: str                      # Fetched document content

    # ─── Company Brain ───
    company_context: str                    # RAG-retrieved knowledge chunks
    style_examples: str                     # Past application excerpts
    style_examples_loaded: bool             # Cache flag

    # ─── Drafter Section Loop ───
    current_section_index: int              # Progress tracker
    approved_sections: Dict[str, Dict]      # {section_name: {content, word_count, ...}}
    section_critiques: Dict[str, str]       # Reviewer notes per section
    section_revision_instructions: Dict     # Human feedback per section
    pending_interrupt: Dict                 # Current section awaiting review
    section_review_decision: str            # "approve" | "revise"
    section_edited_content: str             # Human edits

    # ─── Review & Export ───
    reviewer_output: Dict                   # {overall_score, critiques, ready}
    draft_version: int                      # Version counter
    draft_filepath: str                     # /tmp/drafts/...
    markdown_content: str                   # Final assembled draft

    # ─── Meta ───
    pipeline_id: str
    thread_id: str
    run_id: str
    errors: List[str]
    audit_log: List[Dict]
```

### 6.3 State Persistence

```
┌──────────────┐     ┌────────────────────────────────────────┐
│  LangGraph   │────►│  MongoCheckpointSaver                  │
│  Runtime     │     │                                        │
│              │◄────│  Collection: graph_checkpoints          │
└──────────────┘     │  Index: (thread_id, checkpoint_id) DESC│
                     │                                        │
                     │  Document:                             │
                     │  {                                     │
                     │    thread_id: "abc-123",               │
                     │    checkpoint_id: "cp_45",             │
                     │    parent_checkpoint_id: "cp_44",      │
                     │    checkpoint: { ...serialized state }, │
                     │    metadata: { step, node, ... },      │
                     │    pending_writes: { ... },            │
                     │    saved_at: "2026-03-10T..."          │
                     │  }                                     │
                     └────────────────────────────────────────┘

Enables:
  • Multi-day pipelines (state persists across restarts)
  • Human interrupts (graph pauses, resumes on officer action)
  • Audit trail (every state transition recorded)
  • Crash recovery (resume from last checkpoint)
```

---

## 7. Data Architecture

### 7.1 MongoDB Collections

```
altcarbon_grants (database)
│
├── grants_raw                    # Discovered grants (pre-analysis)
│   Indexes: url_hash(unique), scraped_at, normalized_url_hash, content_hash
│   TTL: None (permanent record)
│   Write: Scout
│   Read: Analyst
│
├── grants_scored                 # Analyzed & scored grants
│   Indexes: url_hash(unique), status, weighted_total(desc), deadline,
│            (funder,title), content_hash, scored_at
│   Write: Analyst
│   Read: Frontend (all pages), Triage, Drafter
│
├── grants_pipeline               # Active drafting pipelines
│   Indexes: grant_id, thread_id(unique), status
│   Write: Triage resume, Drafter
│   Read: Frontend (drafter page)
│
├── grant_drafts                  # Versioned draft documents
│   Indexes: pipeline_id, grant_id, (pipeline_id, version desc)
│   Write: Exporter
│   Read: Frontend (drafter page)
│
├── grant_comments                # Collaborative discussion per grant
│   Indexes: grant_id, created_at
│   Fields: user_name, message, parent_id (replies), pinned,
│           reactions {emoji: [users]}, edited_at
│   Write: Frontend API
│   Read: Frontend (GrantDetailSheet, GrantDetailPage)
│
├── knowledge_chunks              # RAG vector index
│   Indexes: source_id, doc_type, themes, last_synced
│   Fields: content, embedding(1536d), source, doc_type,
│           themes[], metadata, confidence
│   Write: Company Brain (sync)
│   Read: Company Brain (query)
│
├── knowledge_sync_logs           # Sync job history
│   Write: Knowledge job
│   Read: Frontend (knowledge page)
│
├── graph_checkpoints             # LangGraph state persistence
│   Indexes: (thread_id, checkpoint_id desc)
│   Write: LangGraph runtime
│   Read: LangGraph runtime (resume)
│
├── audit_logs                    # All agent activity
│   Indexes: created_at(desc), node
│   Write: All agents
│   Read: Frontend (audit page, monitoring)
│
├── scout_runs                    # Scout execution metadata
│   Write: Scout job
│   Read: Frontend (monitoring)
│
├── agent_config                  # Agent behavior configuration
│   Indexes: agent(unique)
│   Write: Frontend (config page)
│   Read: All agents at startup
│
├── funder_context_cache          # Perplexity enrichment cache
│   Indexes: funder(unique), cached_at (7d TTL)
│   Write: Analyst
│   Read: Analyst
│
├── deep_research_cache           # Deep analysis cache
│   Indexes: url_hash(unique), cached_at (7d TTL)
│   Write: Analyst
│   Read: Analyst
│
└── drafter_chat_history          # Interactive drafter conversations
    Indexes: pipeline_id(unique)
    Write: Frontend (drafter chat API)
    Read: Frontend (drafter chat API)
```

### 7.2 Pinecone Vector Index

```
Index: grants-engine
├── Dimensions: 1536 (OpenAI text-embedding-3-small)
├── Metric: cosine
├── Cloud: AWS us-east-1 (serverless)
│
├── Vector Metadata Schema:
│   {
│     source_id: string,           # Notion page ID or Drive file ID
│     source: "notion" | "drive",
│     doc_type: string,            # company_overview, technical_methodology, etc.
│     themes: string[],            # climatetech, agritech, ...
│     title: string,               # Source document title
│     chunk_index: number,         # Position within source
│     word_count: number,
│     contains_data: boolean,      # Has quantitative data
│     is_useful_for_grants: boolean,
│     confidence: float            # Haiku tagging confidence
│   }
│
└── Query Pattern:
    Input: grant themes + section requirements
    Filter: themes IN grant.themes_detected
    Top-K: 10 chunks
    Output: concatenated text for grounding
```

### 7.3 Collection Relationships

```
grants_raw ──(url_hash)──► grants_scored ──(grant_id)──► grants_pipeline
                                │                              │
                                │                              ├──► grant_drafts
                                │                              │
                                ├──► grant_comments            ├──► drafter_chat_history
                                │                              │
                                └──► audit_logs                └──► graph_checkpoints

knowledge_chunks ◄──(sync)── Notion pages (via MCP)
                 ◄──(sync)── Google Drive (optional)

funder_context_cache ◄──(enrichment)── Perplexity API
```

---

## 8. Frontend Architecture

### 8.1 Page Rendering Strategy

```
┌──────────────────────────────────────────────────────────────────┐
│                    NEXT.JS APP ROUTER                             │
│                                                                  │
│  Server Components (data fetching at edge):                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ /dashboard    → getDashboardStats() + getPipelineGrants()│    │
│  │ /pipeline     → getPipelineGrants()                      │    │
│  │ /triage       → getTriageQueue()                         │    │
│  │ /drafter      → getDraftGrants()                         │    │
│  │ /monitoring   → getActivityFeed() + getPipelineSummary() │    │
│  │ /audit        → getAuditLogs()                           │    │
│  │ /knowledge    → getKnowledgeStatus() + getSyncLogs()     │    │
│  │ /grants/[id]  → getGrantById()                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          ↓ props                                │
│  Client Components (interactivity):                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ PipelineBoard  — drag-drop, filters, sheet              │    │
│  │ PipelineTable  — sort, select, sheet                    │    │
│  │ TriageQueue    — pursue/pass buttons, override flow     │    │
│  │ DrafterView    — section editor, AI chat, approval      │    │
│  │ MissionControl — polling, live status, activity feed    │    │
│  │ CommentThread  — real-time via Pusher                   │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 8.2 Grant Detail — Dual Access Pattern

```
  ┌────────────────────────────┐
  │   Pipeline / Triage Page   │
  │                            │
  │   Click row/card           │
  │        │                   │
  │        ▼                   │
  │   ┌─────────────────────┐  │
  │   │ GrantDetailSheet    │  │     ┌─────────────────────┐
  │   │ (slide-over panel)  │──────►│ /grants/[id]         │
  │   │                     │ ⤢     │ (full detail page)   │
  │   │ Quick preview       │expand │                      │
  │   │ Score + analysis    │button │ Complete view:        │
  │   │ Comments            │       │ • Hero header         │
  │   │                     │       │ • Score breakdown     │
  │   │ URL: ?grant={id}    │       │ • Eligibility cards   │
  │   └─────────────────────┘       │ • Evidence analysis   │
  │                                 │ • Strategy & tips     │
  │                                 │ • Comments + activity │
  │                                 │                       │
  │                                 │ URL: /grants/{id}     │
  │                                 │ (shareable, linkable)  │
  │                                 └───────────────────────┘
```

### 8.3 Filter & Data Flow

```
  Server Component (page.tsx)
  │
  │ Fetch all grants from MongoDB
  │
  └──► PipelineView (Client)
       │
       ├── State: PipelineFilters
       │   { search, themes[], scoreRange, deadline, funding, geography }
       │
       ├── useMemo: extractThemes(grants) → unique theme options
       ├── useMemo: extractGeographies(grants) → unique geo options
       ├── useMemo: applyFilters(grants, filters) → filteredGrants
       │
       ├──► PipelineBoard (Kanban)
       │    │ Groups by status column
       │    │ Drag-drop → PATCH status
       │    └── GrantCard per item
       │
       └──► PipelineTable (Table)
            │ Sort by column
            │ Click → open GrantDetailSheet
            └── Row per item
```

---

## 9. Knowledge RAG Pipeline

### 9.1 Sync Flow (Daily Cron)

```
  ┌─────────┐        ┌─────────────┐        ┌──────────┐
  │  Notion  │──MCP──►│ Company     │──chunk─►│  Tag     │
  │ Workspace│        │ Brain Sync  │  400w   │  (Haiku) │
  │ (332+    │        │             │  80w    │          │
  │  pages)  │        └─────────────┘ overlap │ doc_type │
  └─────────┘                                │ themes   │
                                             │ topics   │
  ┌─────────┐        ┌─────────────┐         └────┬─────┘
  │  Google  │──API──►│ Drive Sync  │              │
  │  Drive   │        │ (optional)  │              ▼
  └─────────┘        └─────────────┘        ┌──────────┐
                                            │  Embed   │
                                            │  OpenAI  │
                                            │  1536d   │
                                            └────┬─────┘
                                                 │
                                    ┌────────────┼────────────┐
                                    ▼                         ▼
                              ┌──────────┐            ┌──────────┐
                              │ Pinecone │            │ MongoDB  │
                              │ (primary)│            │ (Atlas   │
                              │          │            │  Vector) │
                              └──────────┘            └──────────┘
```

### 9.2 Query Flow (Per Draft)

```
  Grant Context                    Vector Search
  ┌──────────────┐                ┌──────────────────┐
  │ themes:      │   embed        │                  │
  │  [climatetech│───────────────►│  Pinecone query  │
  │   agritech]  │   query        │  filter: themes  │
  │              │                │  top_k: 10       │
  │ requirements:│                │                  │
  │  "methodology│                └────────┬─────────┘
  │   section"   │                         │
  └──────────────┘                         ▼
                                  ┌──────────────────┐
                                  │  Ranked chunks   │
                                  │  (cosine sim)    │
                                  └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │  company_context  │
                                  │  (concatenated    │
                                  │   relevant text)  │
                                  │                  │
                                  │  style_examples   │
                                  │  (past app tone) │
                                  └──────────────────┘
```

### 9.3 Graceful Degradation (4 Levels)

```
  Level 1: Pinecone (serverless, fastest, theme-filtered)
      │
      │ unavailable?
      ▼
  Level 2: MongoDB Atlas Vector Search (same embeddings, co-located)
      │
      │ unavailable?
      ▼
  Level 3: MongoDB text search ($text index, keyword matching)
      │
      │ unavailable?
      ▼
  Level 4: Static profile (altcarbon_profile.md, 22K chars, always available)
```

---

## 10. Integration Layer

### 10.1 Notion Integration (Bidirectional)

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    NOTION WORKSPACE                          │
  │                                                             │
  │  ┌──────────────────┐       ┌────────────────────────────┐ │
  │  │ Knowledge Pages  │       │ Mission Control            │ │
  │  │ (332+ pages)     │       │                            │ │
  │  │                  │       │ ┌────────────────────────┐  │ │
  │  │ Introducing AC   │       │ │ Grant Pipeline DB      │  │ │
  │  │ MRV Moat         │       │ │ Agent Runs DB          │  │ │
  │  │ DRP, BRP         │       │ │ Error Logs DB          │  │ │
  │  │ Vision & Comms   │       │ │ Triage Decisions DB    │  │ │
  │  │ ...              │       │ │ Draft Sections DB      │  │ │
  │  └────────┬─────────┘       │ │ Knowledge Connections  │  │ │
  │           │                 │ └────────────┬───────────┘  │ │
  │           │                 └──────────────┼──────────────┘ │
  └───────────┼────────────────────────────────┼────────────────┘
              │                                │
         READ (MCP)                       WRITE (SDK)
              │                                │
              ▼                                ▼
  ┌───────────────────┐           ┌───────────────────┐
  │ notion_mcp.py     │           │ notion_sync.py    │
  │                   │           │                   │
  │ MCP subprocess    │           │ notion-client SDK │
  │ @notionhq/notion  │           │ AsyncClient       │
  │ -mcp-server       │           │                   │
  │                   │           │ Fire-and-forget    │
  │ Persistent conn   │           │ All errors caught  │
  │ Auto-reconnect    │           │ Never blocks agents│
  └───────────────────┘           └───────────────────┘

  Reads (MCP): Knowledge sync, workspace search, page content
  Writes (SDK): Grant pipeline sync, agent run logs, error logs,
                triage decisions, draft sections
```

### 10.2 LLM Integration (Multi-Model Fallback)

```
  ┌─────────────────────────────────────────────────────┐
  │                  LLM CLIENT (utils/llm.py)           │
  │                                                     │
  │  ┌───────────────────────────────────────────┐      │
  │  │  Model Selection                          │      │
  │  │                                           │      │
  │  │  SONNET (heavy tasks):                    │      │
  │  │  Primary: AI Gateway model                │      │
  │  │  Chain: → GPT fallback → Claude Sonnet    │      │
  │  │                                           │      │
  │  │  HAIKU (light tasks):                     │      │
  │  │  Primary: AI Gateway model                │      │
  │  │  Chain: → GPT Nano → Claude Haiku         │      │
  │  └───────────────────────────────────────────┘      │
  │                                                     │
  │  ┌───────────────────────────────────────────┐      │
  │  │  Fallback Logic                           │      │
  │  │                                           │      │
  │  │  On 429/402 (credit exhausted):           │      │
  │  │  1. Mark model exhausted (5 min cooldown) │      │
  │  │  2. Try next model in fallback chain      │      │
  │  │  3. Log fallback to Notion (non-blocking) │      │
  │  └───────────────────────────────────────────┘      │
  │                                                     │
  │  Usage:                                             │
  │  • Scout: HAIKU for field extraction                │
  │  • Analyst: SONNET for scoring (3 retries)          │
  │  • Company Brain: HAIKU for chunk tagging           │
  │  • Drafter: SONNET for section writing              │
  │  • Reviewer: SONNET for quality scoring             │
  └─────────────────────────────────────────────────────┘
```

### 10.3 Search Integration (Grant Discovery)

```
  ┌──────────────────────────────────────────────────────┐
  │              SEARCH LAYER (Scout Agent)               │
  │                                                      │
  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐      │
  │  │ Tavily   │  │ Exa      │  │ Perplexity   │      │
  │  │ 16 query │  │ 8 query  │  │ 6 query      │      │
  │  │ batches  │  │ semantic │  │ Sonar model   │      │
  │  │          │  │ + highlights│ │ Direct API   │      │
  │  └────┬─────┘  └────┬─────┘  │ + gateway    │      │
  │       │              │        │ fallback     │      │
  │       │              │        └──────┬───────┘      │
  │       └──────────────┼───────────────┘              │
  │                      ▼                               │
  │           ┌──────────────────┐                      │
  │           │ Merge + Dedup    │                      │
  │           │ (3-layer hash)   │                      │
  │           └────────┬─────────┘                      │
  │                    ▼                                │
  │           ┌──────────────────┐   ┌──────────────┐  │
  │           │ Content Fetch    │──►│ Jina Reader   │  │
  │           │ (45s/grant,      │   │ (PDF/HTML)    │  │
  │           │  180s total)     │   │ 10 RPM limit  │  │
  │           └──────────────────┘   └──────────────┘  │
  │                                                     │
  │  APIHealthTracker:                                  │
  │  • Tracks credit exhaustion per service             │
  │  • 10-min cooldown on 429 errors                    │
  │  • Auto-skip exhausted services                     │
  └──────────────────────────────────────────────────────┘
```

---

## 11. Authentication & Security

### 11.1 Auth Flow

```
  Browser                    Next.js                     Google
  ┌──────┐                ┌──────────┐               ┌──────────┐
  │      │──/login────────►│          │──OAuth 2.0───►│          │
  │      │                │ NextAuth │               │ Identity │
  │      │◄───────────────│ v5 Beta  │◄──────────────│ Provider │
  │      │  session cookie│          │  id_token     │          │
  └──────┘                └──────────┘               └──────────┘

  Domain restriction: email must end with @altcarbon.com
  Session: JWT cookie (AUTH_SECRET signed)
```

### 11.2 API Security Layers

```
  ┌───────────────────────────────────────────────────────┐
  │                  SECURITY BOUNDARIES                   │
  │                                                       │
  │  Layer 1: NextAuth Middleware (all routes)             │
  │  ├── Requires valid session for /dashboard, /pipeline │
  │  ├── Allows /api/auth/* (login flow)                  │
  │  └── Allows /api/cron/* (cron jobs)                   │
  │                                                       │
  │  Layer 2: Next.js API → FastAPI (shared secret)       │
  │  ├── Header: x-internal-secret                        │
  │  └── Prevents direct access to FastAPI from browser   │
  │                                                       │
  │  Layer 3: Cron Endpoints (cron secret)                │
  │  ├── Header: X-Cron-Secret                            │
  │  └── Vercel/Railway cron scheduler only               │
  │                                                       │
  │  Layer 4: CORS (backend)                              │
  │  └── Currently open (allow_origins=["*"])             │
  │                                                       │
  │  Data boundaries:                                     │
  │  • MongoDB connection via URI (Atlas TLS)             │
  │  • Notion token scoped to workspace                   │
  │  • API keys in env vars (never client-exposed)        │
  └───────────────────────────────────────────────────────┘
```

---

## 12. Real-Time Event System

```
  ┌──────────────────────────────────────────────────────────────┐
  │                    REAL-TIME ARCHITECTURE                     │
  │                                                              │
  │  Channel Pattern: grant-{grantId}                            │
  │  Event: comment:new                                          │
  │                                                              │
  │  ┌─────────┐   POST /api/grants/{id}/comments  ┌─────────┐ │
  │  │ User A  │──────────────────────────────────►│ Next.js │ │
  │  │(browser)│                                   │  API    │ │
  │  └─────────┘                                   └────┬────┘ │
  │                                                     │      │
  │                               ┌─────────────────────┤      │
  │                               │                     │      │
  │                               ▼                     ▼      │
  │                        ┌──────────┐          ┌──────────┐  │
  │                        │ MongoDB  │          │ Pusher   │  │
  │                        │ Insert   │          │ Trigger  │  │
  │                        └──────────┘          └────┬─────┘  │
  │                                                   │        │
  │                              WebSocket broadcast  │        │
  │                         ┌─────────────────────────┘        │
  │                         │                                  │
  │                         ▼                                  │
  │  ┌─────────┐    usePusherEvent()                           │
  │  │ User B  │◄───────────────────                           │
  │  │(browser)│   Comment appears instantly                   │
  │  └─────────┘                                               │
  │                                                             │
  │  Polling (non-Pusher):                                     │
  │  • AgentControls polls /api/run/scout every ~2s            │
  │  • MissionControl polls /api/status/* periodically          │
  │                                                             │
  │  URL State Sync:                                            │
  │  • useGrantUrl() syncs ?grant={id}&comment={commentId}     │
  │  • Enables shareable deep-links to specific comments       │
  │  • Auto-scroll + highlight on load                         │
  └──────────────────────────────────────────────────────────────┘
```

---

## 13. Error Handling & Resilience

### 13.1 Multi-Level Error Strategy

```
  ┌────────────────────────────────────────────────────────────┐
  │               ERROR HANDLING STRATEGY                       │
  │                                                            │
  │  LEVEL 1: Retry with backoff                               │
  │  ├── retry_async() — 3 retries, exponential delay          │
  │  ├── Used by: LLM calls, API calls, content fetching      │
  │  └── Falls through to Level 2 on exhaustion               │
  │                                                            │
  │  LEVEL 2: Model/service fallback                           │
  │  ├── LLM: primary → fallback chain (3 models deep)        │
  │  ├── Content fetch: Jina → HTTP fallback                   │
  │  ├── Perplexity: Direct API → Gateway fallback             │
  │  └── Knowledge: Pinecone → MongoDB Vector → Text → Static │
  │                                                            │
  │  LEVEL 3: Circuit breaker (APIHealthTracker)               │
  │  ├── On credit error (429/402): cooldown for 10 min        │
  │  ├── Skip exhausted services in subsequent calls           │
  │  └── Auto-recovery after cooldown                          │
  │                                                            │
  │  LEVEL 4: Graceful degradation                             │
  │  ├── Analyst: scoring_error flag, skip grant               │
  │  ├── Drafter: continue with available context              │
  │  ├── Notion sync: fire-and-forget, never blocks agents     │
  │  └── Pusher: optional, app works without real-time         │
  │                                                            │
  │  LEVEL 5: Audit trail                                      │
  │  ├── All errors → audit_logs collection                    │
  │  ├── Critical errors → Notion Error Logs DB                │
  │  └── Visible on /monitoring and /audit pages               │
  └────────────────────────────────────────────────────────────┘
```

### 13.2 Agent-Specific Resilience

| Agent | Failure Mode | Handling |
|-------|-------------|----------|
| Scout | Search API exhausted | Skip service, continue with others. APIHealthTracker cooldown. |
| Scout | Content fetch timeout | 45s per-grant timeout, 180s overall. Skip grant, log warning. |
| Analyst | LLM scoring fails | 3 retries. On failure: `scoring_error: true`, skip grant. |
| Analyst | Perplexity enrichment fails | Continue without funder context. Cached results survive. |
| Company Brain | MCP unavailable | Fallback to static profile (always available). |
| Company Brain | Vector search empty | Fallback to static profile (22K chars). |
| Grant Reader | Jina fails | Try Firecrawl. On total failure: use default 5 sections. |
| Drafter | LLM timeout | Retry section. Human can revise or skip. |
| Reviewer | LLM fails | Default to `ready: true, score: 7.0`. |
| Notion Sync | API error | Log locally, never block agent pipeline. |

---

## 14. Deployment Architecture

```
  ┌────────────────────────────────────────────────────────────────┐
  │                     RAILWAY PLATFORM                            │
  │                                                                │
  │  ┌──────────────────────┐     ┌───────────────────────────┐   │
  │  │ Frontend Service     │     │ Backend Service            │   │
  │  │                      │     │                           │   │
  │  │ Next.js 16           │     │ FastAPI + Uvicorn         │   │
  │  │ Node.js 20           │────►│ Python 3.11+              │   │
  │  │ standalone output    │HTTP │ Node.js 20 (for MCP)      │   │
  │  │                      │     │                           │   │
  │  │ Port: $PORT          │     │ Port: $PORT               │   │
  │  │ RAM: ~512MB          │     │ RAM: ~1GB                 │   │
  │  └──────────────────────┘     └───────────────────────────┘   │
  │                                                                │
  │  Cron Jobs:                                                    │
  │  • Scout: every 48h → POST /cron/scout                        │
  │  • Knowledge: daily → POST /cron/knowledge-sync               │
  └────────────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────────────┐
  │                   EXTERNAL SERVICES                             │
  │                                                                │
  │  MongoDB Atlas (M10+)     │  Pinecone (Serverless)             │
  │  Region: us-east-1        │  Region: aws/us-east-1             │
  │  DB: altcarbon_grants     │  Index: grants-engine              │
  │  13 collections           │  Dims: 1536, cosine                │
  │                           │                                    │
  │  Pusher (ap2 cluster)     │  Notion Workspace                  │
  │  Channels: grant-{id}     │  MCP read + SDK write              │
  └────────────────────────────────────────────────────────────────┘

  Build pipeline:
  ┌──────┐    ┌──────┐    ┌───────┐    ┌────────┐
  │ Git  │───►│Build │───►│Deploy │───►│Health  │
  │ Push │    │(auto)│    │(auto) │    │Check   │
  └──────┘    └──────┘    └───────┘    └────────┘
```

---

## 15. API Contract Reference

### 15.1 FastAPI Backend Endpoints

**Health & Status:**
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | None | App health |
| GET | `/status/notion-mcp` | None | MCP connection health |
| GET | `/status/api-health` | None | External API credit status |
| GET | `/status/scout` | None | Scout job progress |
| GET | `/status/analyst` | None | Analyst job progress |
| GET | `/status/pipeline` | None | Pipeline summary counts |
| GET | `/status/knowledge-sources` | None | Notion workspace page listing |

**Agent Triggers:**
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/cron/scout` | X-Cron-Secret | Scheduled scout run (48h) |
| POST | `/cron/knowledge-sync` | X-Cron-Secret | Daily knowledge sync |
| POST | `/run/scout` | X-Internal-Secret | Manual scout trigger |
| POST | `/run/analyst` | X-Internal-Secret | Manual analyst trigger |
| POST | `/run/sync-profile` | X-Internal-Secret | Rebuild static profile |
| POST | `/run/notion-mcp/reconnect` | X-Internal-Secret | Force MCP reconnect |

**Human-in-the-Loop:**
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/resume/triage` | X-Internal-Secret | Submit triage decision |
| POST | `/resume/section-review` | X-Internal-Secret | Approve/revise draft section |
| POST | `/resume/start-draft` | X-Internal-Secret | Start new draft pipeline |

**Drafter:**
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/drafter/chat` | X-Internal-Secret | Interactive section chat |
| POST | `/drafter/chat/stream` | X-Internal-Secret | Streaming section chat (SSE) |
| POST | `/drafter/intelligence-brief` | X-Internal-Secret | Grant intelligence summary |
| GET | `/drafter/chat-history/{pipeline_id}` | X-Internal-Secret | Fetch chat history |
| PUT | `/drafter/chat-history` | X-Internal-Secret | Save chat history |
| DELETE | `/drafter/chat-history/{pid}/{section}` | X-Internal-Secret | Clear section history |

### 15.2 Next.js API Routes (Proxy + DB)

**Agent Control:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/run/scout` | Trigger scout → FastAPI |
| POST | `/api/run/analyst` | Trigger analyst → FastAPI |
| GET | `/api/run/scout` | Poll scout status |
| GET | `/api/run/analyst` | Poll analyst status |

**Grant Operations:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/grants/[id]` | Fetch single grant |
| GET | `/api/grants/[id]/comments` | List comments (pinned first) |
| POST | `/api/grants/[id]/comments` | Create comment + Pusher broadcast |
| PATCH | `/api/grants/[id]/comments/[cid]` | Update/pin comment |
| POST | `/api/grants/manual` | Manually add grant |

**Drafter:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/drafter/chat` | LLM chat → FastAPI |
| POST | `/api/drafter/chat-stream` | Streaming chat → FastAPI |
| POST | `/api/drafter/trigger` | Start draft → FastAPI |
| POST | `/api/drafter/intelligence-brief` | Grant analysis → FastAPI |
| POST | `/api/drafter/section-review` | Section decision → FastAPI |
| GET | `/api/drafter/chat-history` | Fetch chat history |

**Monitoring:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check |
| GET | `/api/status/api-health` | API credit status |
| GET | `/api/status/knowledge-sources` | Notion sources |
| GET | `/api/activity` | Activity feed |
| GET | `/api/discoveries` | Recent discoveries |
| GET | `/api/pipeline-summary` | Pipeline counts |
| GET | `/api/whats-new` | Returning user digest |

**Triage:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/triage/resume` | Submit triage decision → FastAPI |

**Knowledge:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/knowledge/sync` | Trigger sync → FastAPI |

---

## Appendix: Environment Variables

| Variable | Service | Required | Purpose |
|----------|---------|----------|---------|
| `MONGODB_URI` | MongoDB Atlas | Yes | Primary database connection |
| `AI_GATEWAY_URL` | AI Gateway | Yes | LLM API endpoint |
| `AI_GATEWAY_API_KEY` | AI Gateway | Yes | LLM authentication |
| `ANTHROPIC_API_KEY` | Anthropic | Fallback | Direct Claude access |
| `OPENAI_API_KEY` | OpenAI | Yes | Embedding generation |
| `NOTION_TOKEN` | Notion | Yes | Workspace access (MCP + SDK) |
| `NOTION_KNOWLEDGE_BASE_PAGE_ID` | Notion | Optional | Scope knowledge sync |
| `PINECONE_API_KEY` | Pinecone | Optional | Vector DB (falls back to MongoDB) |
| `PINECONE_INDEX_NAME` | Pinecone | Optional | Default: "grants-engine" |
| `TAVILY_API_KEY` | Tavily | Yes | Web search (Scout) |
| `EXA_API_KEY` | Exa | Yes | Semantic search (Scout) |
| `PERPLEXITY_API_KEY` | Perplexity | Yes | Sonar enrichment (Scout + Analyst) |
| `JINA_API_KEY` | Jina | Yes | Content extraction |
| `CRON_SECRET` | Internal | Yes | Cron endpoint auth |
| `INTERNAL_SECRET` | Internal | Yes | Frontend → Backend auth |
| `AUTH_SECRET` | NextAuth | Yes | Session signing |
| `GOOGLE_CLIENT_ID` | Google | Yes | OAuth login |
| `GOOGLE_CLIENT_SECRET` | Google | Yes | OAuth login |
| `PUSHER_APP_ID` | Pusher | Optional | Real-time events |
| `NEXT_PUBLIC_PUSHER_KEY` | Pusher | Optional | Client-side Pusher |
| `PUSHER_SECRET` | Pusher | Optional | Server-side Pusher |
| `NEXT_PUBLIC_PUSHER_CLUSTER` | Pusher | Optional | Pusher region |
| `LANGCHAIN_API_KEY` | LangSmith | Optional | Tracing & observability |

---

## 16. Areas of Improvement

### 16.1 Latency Optimization

#### Current Bottlenecks

```
  ┌────────────────────────────────────────────────────────────────────┐
  │                   LATENCY HOTSPOT MAP                              │
  │                                                                    │
  │  ❶ Frontend → Backend Proxy Hop                                   │
  │  ┌──────────┐    ┌──────────┐    ┌──────────┐                    │
  │  │ Browser  │───►│ Next.js  │───►│ FastAPI  │  +50-150ms per hop │
  │  │          │    │ API route│    │ endpoint │  (Railway internal) │
  │  └──────────┘    └──────────┘    └──────────┘                    │
  │                                                                    │
  │  ❷ MongoDB N+1 Queries (getPipelineGrants)                        │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ Fetch 1000 grants from grants_scored     │  1 query           │
  │  │   └─► For each pipeline grant:           │                    │
  │  │        └─► Lookup grant_scored by _id    │  +N queries        │
  │  │        └─► Lookup latest draft           │  +N queries        │
  │  │                                          │                    │
  │  │  1000 grants = 1 + 2000 queries ≈ 3-8s  │                    │
  │  └──────────────────────────────────────────┘                    │
  │                                                                    │
  │  ❸ Dashboard Activity Full Table Scan                             │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ getGrantsActivity(30):                   │                    │
  │  │ $match + $substr on ALL grants_raw docs  │  No date index     │
  │  │ then filter last 30 days                 │  = full scan       │
  │  └──────────────────────────────────────────┘                    │
  │                                                                    │
  │  ❹ Scout Content Enrichment                                       │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ 200 new grants × (Jina 5s + LLM 3s)     │                    │
  │  │ Jina concurrency: 3 (10 RPM free tier)   │                    │
  │  │ = ~15-20 minutes enrichment phase         │                    │
  │  └──────────────────────────────────────────┘                    │
  │                                                                    │
  │  ❺ Analyst Sequential Scoring                                     │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ 50 grants × 1 LLM call each (sequential)│                    │
  │  │ = ~2.5 minutes (no parallelism)           │                    │
  │  └──────────────────────────────────────────┘                    │
  │                                                                    │
  │  ❻ Monitoring Page Polling Storm                                  │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ 3 endpoints polled every 3-5s            │                    │
  │  │ = 12-20 requests/min per open tab         │                    │
  │  │ Each triggers fresh MongoDB queries       │                    │
  │  └──────────────────────────────────────────┘                    │
  │                                                                    │
  │  ❼ No Server-Side Caching                                        │
  │  ┌──────────────────────────────────────────┐                    │
  │  │ revalidate=0 on ALL pages                │                    │
  │  │ force-dynamic on dashboard + knowledge   │                    │
  │  │ Every page load = fresh MongoDB round trip│                    │
  │  └──────────────────────────────────────────┘                    │
  └────────────────────────────────────────────────────────────────────┘
```

#### Proposed Fixes

**Fix ❶ — Reduce proxy hops (quick win):**
```
  CURRENT (2 hops):
  Browser → Next.js API route → FastAPI → MongoDB

  OPTION A: Direct MongoDB from Next.js (already done for reads):
  Browser → Next.js Server Component → MongoDB (0 hops for reads)
  ✅ Already implemented for page loads via queries.ts

  OPTION B: Expose FastAPI directly for write-heavy paths:
  Browser → FastAPI (drafter chat, triage resume)
  Saves ~100ms per request on streaming endpoints
```

**Fix ❷ — Eliminate N+1 with MongoDB $lookup (high impact):**
```javascript
  // BEFORE: N+1 pattern in getPipelineGrants()
  const grants = await grants_scored.find().limit(1000).toArray();
  for (const pipeline of pipelines) {
    const grant = await grants_scored.findOne({ _id: pipeline.grant_id });  // N queries
    const draft = await grant_drafts.findOne({ pipeline_id: pipeline._id }); // N queries
  }

  // AFTER: Single aggregation with $lookup
  const results = await grants_scored.aggregate([
    { $match: { status: { $in: [...] } } },
    { $lookup: {
        from: "grants_pipeline",
        localField: "_id",
        foreignField: "grant_id",
        as: "pipeline"
    }},
    { $lookup: {
        from: "grant_drafts",
        let: { pid: "$pipeline._id" },
        pipeline: [
          { $match: { $expr: { $eq: ["$pipeline_id", "$$pid"] } } },
          { $sort: { version: -1 } },
          { $limit: 1 }
        ],
        as: "latest_draft"
    }},
    { $limit: 1000 }
  ]).toArray();
  // 1 query instead of 2001
```

**Fix ❸ — Add compound index on grants_raw (quick win):**
```javascript
  // Add index for activity aggregation
  db.grants_raw.createIndex({ scraped_at: -1 });
  // Turns full table scan into index scan for 30-day window
```

**Fix ❹ — Increase Jina concurrency with semaphore (medium):**
```python
  # BEFORE: asyncio.Semaphore(3) for free-tier Jina (10 RPM)
  # AFTER: If on paid Jina tier, increase to Semaphore(10)
  # Or: batch LLM extraction calls (group 5 grants per prompt)
```

**Fix ❺ — Parallel analyst scoring with semaphore (high impact):**
```python
  # BEFORE: Sequential loop
  for grant in raw_grants:
      score = await score_grant(grant)

  # AFTER: Parallel with concurrency limit
  sem = asyncio.Semaphore(5)  # 5 concurrent LLM calls
  async def score_with_limit(grant):
      async with sem:
          return await score_grant(grant)
  results = await asyncio.gather(*[score_with_limit(g) for g in raw_grants])
  # 50 grants: 10 batches × 3s = 30s instead of 150s
```

**Fix ❻ — Replace polling with Pusher events (medium):**
```
  BEFORE: Client polls /api/run/scout every 3s

  AFTER: Backend pushes status via Pusher
  Channel: agent-status
  Events: scout:started, scout:progress, scout:complete, analyst:complete
  Client subscribes once, no polling needed
```

**Fix ❼ — Add ISR/cache for stable data (quick win):**
```typescript
  // Pages with data that changes infrequently:
  // /audit → revalidate = 30 (30 seconds)
  // /config → revalidate = 60
  // /knowledge → revalidate = 60
  // /dashboard → revalidate = 10 (10 seconds, near-real-time)
```

#### Latency Budget (Target)

| Operation | Current | Target | Fix |
|-----------|---------|--------|-----|
| Dashboard page load | 800-1500ms | 200-400ms | ISR + $lookup |
| Pipeline page load | 1000-3000ms | 300-600ms | $lookup aggregation |
| Grant detail sheet | 200-500ms | 100-200ms | Already fast (single query) |
| Scout full run | 15-20 min | 8-12 min | Parallel enrichment |
| Analyst scoring (50) | 2.5 min | 30-45s | Parallel with semaphore |
| Monitoring refresh | 3s polling | 0ms (push) | Pusher events |

---

### 16.2 Cron Scheduler (Railway-Native)

#### Current Problem

```
  ┌────────────────────────────────────────────────────────────────┐
  │                    CRON — CURRENT STATE                        │
  │                                                                │
  │  Code references "Vercel cron" but app deploys on Railway.     │
  │  APScheduler is in requirements.txt but UNUSED.                │
  │                                                                │
  │  Current trigger options:                                      │
  │  1. Manual button click (sidebar → Run Scout)                  │
  │  2. External cron service hitting POST /cron/scout             │
  │  3. Railway cron job (if configured in dashboard)              │
  │                                                                │
  │  Problem: No AUTOMATED scheduling exists in code.              │
  │  If nobody clicks "Run Scout", no grants are discovered.       │
  └────────────────────────────────────────────────────────────────┘
```

#### Proposed Solution: APScheduler (Already a Dependency)

```
  ┌────────────────────────────────────────────────────────────────┐
  │               CRON — PROPOSED: APScheduler In-Process          │
  │                                                                │
  │  APScheduler runs inside the FastAPI process.                  │
  │  No external service needed. Survives Railway deploys.         │
  │                                                                │
  │  ┌──────────────────────────────────────────────────────────┐ │
  │  │  FastAPI Lifespan (startup)                              │ │
  │  │                                                          │ │
  │  │  scheduler = AsyncIOScheduler()                          │ │
  │  │                                                          │ │
  │  │  scheduler.add_job(                                      │ │
  │  │    run_scout_pipeline,                                   │ │
  │  │    trigger=IntervalTrigger(hours=48),                    │ │
  │  │    id="scout_cron",                                      │ │
  │  │    name="Scout Discovery",                               │ │
  │  │    next_run_time=calculate_next_scout_time(),            │ │
  │  │    misfire_grace_time=3600,  # 1h grace for missed runs  │ │
  │  │  )                                                       │ │
  │  │                                                          │ │
  │  │  scheduler.add_job(                                      │ │
  │  │    run_knowledge_sync,                                   │ │
  │  │    trigger=CronTrigger(hour=3, minute=0),  # 3 AM daily  │ │
  │  │    id="knowledge_cron",                                  │ │
  │  │    name="Knowledge Sync",                                │ │
  │  │    misfire_grace_time=3600,                              │ │
  │  │  )                                                       │ │
  │  │                                                          │ │
  │  │  scheduler.start()                                       │ │
  │  └──────────────────────────────────────────────────────────┘ │
  │                                                                │
  │  Benefits:                                                     │
  │  ✅ Zero external dependencies (no Vercel, no cron.org)       │
  │  ✅ APScheduler already in requirements.txt                   │
  │  ✅ Survives Railway auto-deploys (restarts with app)         │
  │  ✅ misfire_grace_time handles container restarts              │
  │  ✅ Manual triggers still work via /run/scout                 │
  │  ✅ Status visible: scheduler.get_job("scout_cron").next_run  │
  │                                                                │
  │  New endpoints:                                                │
  │  GET  /status/scheduler  → list all jobs + next run times     │
  │  POST /scheduler/pause   → pause all jobs                     │
  │  POST /scheduler/resume  → resume all jobs                    │
  └────────────────────────────────────────────────────────────────┘
```

#### Implementation Plan

```python
# backend/jobs/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

def setup_scheduler():
    """Called during FastAPI lifespan startup."""

    # Scout: every 48 hours
    scheduler.add_job(
        run_scout_pipeline,
        trigger=IntervalTrigger(hours=48),
        id="scout_cron",
        name="Scout Discovery (48h)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Knowledge sync: daily at 3 AM UTC
    scheduler.add_job(
        run_knowledge_sync,
        trigger=CronTrigger(hour=3, minute=0),
        id="knowledge_cron",
        name="Knowledge Sync (daily)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Profile rebuild: weekly Sunday 4 AM UTC
    scheduler.add_job(
        run_profile_sync,
        trigger=CronTrigger(day_of_week="sun", hour=4),
        id="profile_cron",
        name="Profile Rebuild (weekly)",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.start()


def teardown_scheduler():
    """Called during FastAPI lifespan shutdown."""
    scheduler.shutdown(wait=False)
```

```
  Schedule Overview:

  ┌──────────────────────┬───────────────┬──────────────────────────┐
  │ Job                  │ Frequency     │ Grace Period             │
  ├──────────────────────┼───────────────┼──────────────────────────┤
  │ Scout Discovery      │ Every 48h     │ 1 hour (misfire ok)      │
  │ Knowledge Sync       │ Daily 3 AM    │ 1 hour                   │
  │ Profile Rebuild      │ Weekly Sun 4AM│ 2 hours                  │
  │ Funder Cache Cleanup │ Daily 5 AM    │ 1 hour (optional)        │
  └──────────────────────┴───────────────┴──────────────────────────┘

  Note: APScheduler in-memory store means jobs reset on restart.
  This is fine because:
  - misfire_grace_time handles gaps
  - Scout/Sync are idempotent (dedup prevents duplicates)
  - Railway restarts are rare (only on deploy)
```

#### Alternative: Railway Cron Jobs

```
  Railway supports cron jobs natively (dashboard config):

  Service: backend-cron
  Command: curl -X POST $BACKEND_URL/cron/scout -H "X-Cron-Secret: $CRON_SECRET"
  Schedule: 0 */48 * * *

  Pros: Decoupled from app process, survives crashes
  Cons: Extra service cost, external dependency, harder to monitor

  Recommendation: APScheduler (simpler, already a dependency, good enough)
```

---

### 16.3 Notification System

#### Current State

```
  ┌────────────────────────────────────────────────────────────────┐
  │             NOTIFICATIONS — CURRENT STATE                      │
  │                                                                │
  │  What EXISTS:                                                  │
  │  ✅ Pusher real-time for comments (grant-{id}:comment:new)    │
  │  ✅ Polling for agent status (AgentControls, MissionControl)  │
  │                                                                │
  │  What's MISSING:                                               │
  │  ❌ No notification when Scout finds new high-score grants    │
  │  ❌ No notification when grants need triage                   │
  │  ❌ No notification when draft section is ready for review    │
  │  ❌ No notification when draft is complete                    │
  │  ❌ No notification when agent errors occur                   │
  │  ❌ No email alerts at all                                    │
  │  ❌ No in-app notification center / bell icon                 │
  │  ❌ No browser push notifications                             │
  │                                                                │
  │  Impact: Officers must check the dashboard manually.           │
  │  High-score grants can sit unreviewed for days.                │
  └────────────────────────────────────────────────────────────────┘
```

#### Proposed: Multi-Channel Notification System

```
  ┌────────────────────────────────────────────────────────────────────┐
  │              NOTIFICATION SYSTEM — PROPOSED DESIGN                  │
  │                                                                    │
  │                    ┌──────────────────┐                            │
  │                    │ NOTIFICATION HUB │                            │
  │                    │ (backend service) │                            │
  │                    └────────┬─────────┘                            │
  │                             │                                      │
  │          ┌──────────────────┼──────────────────┐                  │
  │          │                  │                  │                   │
  │          ▼                  ▼                  ▼                   │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
  │  │   IN-APP     │  │    EMAIL     │  │   PUSHER     │           │
  │  │  (MongoDB +  │  │  (Resend /   │  │  (real-time  │           │
  │  │   bell icon) │  │   SendGrid)  │  │   push)      │           │
  │  └──────────────┘  └──────────────┘  └──────────────┘           │
  │                                                                    │
  │  Events that trigger notifications:                                │
  │                                                                    │
  │  ┌────────────────────────────────────────────────────────────┐   │
  │  │ EVENT                        │ IN-APP │ EMAIL │ PUSHER     │   │
  │  ├────────────────────────────────────────────────────────────┤   │
  │  │ Scout complete (N new grants)│   ✅   │  ✅  │    ✅      │   │
  │  │ High-score grant (≥7.0)     │   ✅   │  ✅  │    ✅      │   │
  │  │ Triage queue has items      │   ✅   │  ✅  │    ✅      │   │
  │  │ Draft section ready         │   ✅   │  ❌  │    ✅      │   │
  │  │ Draft complete              │   ✅   │  ✅  │    ✅      │   │
  │  │ Agent error (critical)      │   ✅   │  ✅  │    ✅      │   │
  │  │ Deadline approaching (7d)   │   ✅   │  ✅  │    ❌      │   │
  │  │ New comment on my grant     │   ✅   │  ❌  │    ✅      │   │
  │  │ Knowledge sync complete     │   ✅   │  ❌  │    ❌      │   │
  │  └────────────────────────────────────────────────────────────┘   │
  └────────────────────────────────────────────────────────────────────┘
```

#### Architecture

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                    NOTIFICATION FLOW                             │
  │                                                                 │
  │  BACKEND (event source):                                        │
  │                                                                 │
  │  Scout completes                                                │
  │      │                                                          │
  │      ▼                                                          │
  │  notify_hub.emit("scout:complete", {                            │
  │    new_grants: 12,                                              │
  │    high_score_grants: [{ name, score, id }],                    │
  │    triage_count: 5,                                             │
  │  })                                                             │
  │      │                                                          │
  │      ├──► MongoDB: notifications collection                     │
  │      │    { user_id, type, title, body, read: false,            │
  │      │      action_url: "/triage", created_at, metadata }       │
  │      │                                                          │
  │      ├──► Pusher: channel "notifications"                       │
  │      │    event "notification:new"                               │
  │      │    → Frontend bell icon updates count instantly           │
  │      │                                                          │
  │      └──► Email (async, batched):                               │
  │           To: grants-team@altcarbon.com                          │
  │           Subject: "Scout found 5 high-score grants"            │
  │           Body: summary + link to /triage                       │
  │                                                                 │
  │  FRONTEND (notification UI):                                    │
  │                                                                 │
  │  ┌─────────────────────────────────────────────────────────┐   │
  │  │  Sidebar / Top Bar                                      │   │
  │  │  ┌──────┐                                               │   │
  │  │  │ 🔔 5 │ ◄── Bell icon with unread count              │   │
  │  │  └──┬───┘                                               │   │
  │  │     │ click                                              │   │
  │  │     ▼                                                    │   │
  │  │  ┌──────────────────────────────────────────────────┐   │   │
  │  │  │ Notification Dropdown                            │   │   │
  │  │  │                                                  │   │   │
  │  │  │ ● Scout found 5 high-score grants    2 min ago  │   │   │
  │  │  │   → Click to review in Triage                    │   │   │
  │  │  │                                                  │   │   │
  │  │  │ ● Draft "Climate CDR" ready          1 hour ago  │   │   │
  │  │  │   → Review Section 3: Methodology                │   │   │
  │  │  │                                                  │   │   │
  │  │  │ ○ Knowledge sync complete           3 hours ago  │   │   │
  │  │  │   → 42 chunks updated                            │   │   │
  │  │  │                                                  │   │   │
  │  │  │ [Mark all read]        [View all →]              │   │   │
  │  │  └──────────────────────────────────────────────────┘   │   │
  │  └─────────────────────────────────────────────────────────┘   │
  └─────────────────────────────────────────────────────────────────┘
```

#### Data Model

```
  NEW COLLECTION: notifications

  {
    _id: ObjectId,
    user_email: "officer@altcarbon.com",     // or "all" for broadcast
    type: "scout_complete" | "triage_needed" | "draft_ready" |
          "draft_complete" | "agent_error" | "deadline_warning" |
          "comment_new" | "knowledge_sync",
    priority: "high" | "normal" | "low",
    title: "Scout found 5 high-score grants",
    body: "3 grants scored above 7.0. Review in Triage queue.",
    action_url: "/triage",                   // deep link
    metadata: {                              // event-specific data
      grant_ids: ["abc", "def"],
      new_count: 12,
      high_score_count: 5,
    },
    read: false,
    read_at: null,
    emailed: false,
    emailed_at: null,
    created_at: ISODate("2026-03-10T..."),
  }

  Indexes:
    (user_email, read, created_at DESC)  — unread notifications
    (created_at)                         — TTL: 30 days auto-delete
    (type, created_at DESC)              — filter by type
```

#### Email Integration (Recommended: Resend)

```
  Why Resend:
  • Free tier: 100 emails/day (more than enough for alerts)
  • Simple API: single HTTP POST, no SMTP config
  • React Email templates (matches Next.js stack)
  • $0 until 3K emails/month

  Alternative: SendGrid (more complex, overkill for low volume)

  Email triggers:
  ┌────────────────────────────────┬──────────────────────────────┐
  │ Event                         │ Email Content                │
  ├────────────────────────────────┼──────────────────────────────┤
  │ Scout complete                │ Summary: N new, top 3 grants │
  │ High-score grant (≥7.0)      │ Grant name, score, deadline  │
  │ Triage queue > 5 items       │ "5 grants need your review"  │
  │ Draft complete               │ Grant name, score, download   │
  │ Agent error (critical)       │ Error type, agent, timestamp │
  │ Deadline in 7 days           │ Grant name, deadline, status │
  └────────────────────────────────┴──────────────────────────────┘

  Email batching:
  • Scout alerts: immediate (1 email per run, summarized)
  • Deadline warnings: daily digest at 9 AM
  • Draft ready: immediate
  • Errors: immediate (max 1 per hour per error type)
```

#### New API Endpoints

```
  GET    /api/notifications              → List unread + recent
  POST   /api/notifications/read         → Mark notification(s) as read
  POST   /api/notifications/read-all     → Mark all as read
  GET    /api/notifications/count        → Unread count (for bell badge)
  PUT    /api/notifications/preferences  → Email on/off per event type
```

#### New Pusher Channels

```
  CURRENT:
    grant-{grantId}:comment:new         → Comment posted

  PROPOSED ADDITIONS:
    notifications:notification:new       → New notification (bell update)
    agent-status:scout:started           → Scout began
    agent-status:scout:progress          → Scout progress (X/Y grants)
    agent-status:scout:complete          → Scout finished
    agent-status:analyst:complete        → Analyst finished
    agent-status:drafter:section-ready   → Section awaiting review
    agent-status:drafter:complete        → Full draft assembled
    agent-status:error                   → Critical agent failure
```

#### Implementation Priority

```
  PHASE 1 — In-App Notifications (1-2 days)
  ├── notifications MongoDB collection + indexes
  ├── Backend: notify_hub.emit() calls after Scout, Analyst, Drafter
  ├── Pusher: notifications channel events
  ├── Frontend: NotificationBell component (sidebar)
  ├── Frontend: NotificationDropdown (unread list)
  └── API: /api/notifications/* endpoints

  PHASE 2 — Pusher Agent Status (1 day)
  ├── Backend: emit Pusher events from Scout/Analyst/Drafter nodes
  ├── Frontend: replace polling with usePusherEvent() subscriptions
  └── Remove setInterval polling from AgentControls + MissionControl

  PHASE 3 — Email Alerts (1 day)
  ├── Add resend package (npm + pip)
  ├── Backend: email templates (scout summary, deadline warning, error)
  ├── Notification preferences collection
  └── Daily digest cron job (9 AM deadline warnings)

  PHASE 4 — Browser Push Notifications (optional, future)
  ├── Service worker registration
  ├── Web Push API (VAPID keys)
  └── Permission prompt UI
```

---

### 16.4 Improvement Summary — Effort vs Impact Matrix

```
  HIGH IMPACT
       │
       │  ┌─────────────────┐   ┌─────────────────────────┐
       │  │ APScheduler     │   │ In-App Notifications    │
       │  │ cron setup      │   │ + Pusher agent events   │
       │  │                 │   │                         │
       │  │ (1 day)         │   │ (2-3 days)              │
       │  └─────────────────┘   └─────────────────────────┘
       │
       │  ┌─────────────────┐   ┌─────────────────────────┐
       │  │ MongoDB $lookup │   │ Parallel Analyst        │
       │  │ for pipeline    │   │ scoring (semaphore)     │
       │  │ queries         │   │                         │
       │  │ (0.5 day)       │   │ (0.5 day)               │
       │  └─────────────────┘   └─────────────────────────┘
       │
       │  ┌─────────────────┐
       │  │ Email alerts    │
       │  │ via Resend      │
       │  │                 │
       │  │ (1 day)         │
       │  └─────────────────┘
       │
       │  ┌─────────────────┐   ┌─────────────────────────┐
       │  │ Activity query  │   │ ISR caching for         │
       │  │ index fix       │   │ stable pages            │
       │  │ (15 min)        │   │ (30 min)                │
       │  └─────────────────┘   └─────────────────────────┘
       │
  LOW IMPACT ───────────────────────────────────────────────►
                LOW EFFORT                        HIGH EFFORT
```
