/**
 * TypeScript port of app/db/queries.py — all MongoDB read functions for the UI.
 * Import only in Server Components, Server Actions, and API routes.
 */
import { getDb } from "./mongodb";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface Grant {
  _id: string;
  grant_name?: string;
  title?: string;
  funder?: string;
  status: string;
  weighted_total?: number;
  deadline_urgent?: boolean;
  deadline?: string;
  geography?: string;
  eligibility?: string;
  max_funding_usd?: number;
  max_funding?: number;
  themes_detected?: string[];
  recommended_action?: string;
  rationale?: string;
  hold_reason?: string;
  scores?: Record<string, number>;
  human_override?: boolean;
  override_reason?: string;
  override_at?: string;
  days_to_deadline?: number;
  thread_id?: string;
  grant_type?: string;
  url?: string;
  application_url?: string;
  scored_at?: string;
  scraped_at?: string;
  notion_page_url?: string;
}

export interface PipelineRecord {
  _id: string;
  grant_id: string;
  thread_id: string;
  status: string;
  started_at?: string;
  draft_started_at?: string;
  current_draft_version?: number;
  final_draft_url?: string | null;
  grant_title?: string;
  grant_funder?: string;
  grant_themes?: string[];
  latest_draft?: DraftDoc | null;
}

export interface DraftSection {
  content: string;
  approved?: boolean;
  revision_count?: number;
  word_count?: number;
}

export interface DraftDoc {
  _id: string;
  pipeline_id: string;
  version: number;
  sections: Record<string, DraftSection>;
  created_at?: string;
}

export interface KnowledgeStatus {
  total_chunks: number;
  notion_chunks: number;
  drive_chunks: number;
  past_grant_chunks: number;
  by_type: Record<string, number>;
  by_theme: Record<string, number>;
  last_synced: string | null;
  status: "healthy" | "thin" | "critical";
}

export interface AgentConfig {
  agent: string;
  [key: string]: unknown;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function serializeId(doc: Record<string, unknown>): Record<string, unknown> {
  return { ...doc, _id: String(doc._id) };
}

// ── Dashboard ──────────────────────────────────────────────────────────────────

export async function getDashboardStats() {
  const db = await getDb();

  // Single $facet aggregation replaces 7 separate countDocuments round trips
  const facetResult = await db
    .collection("grants_scored")
    .aggregate([
      {
        $facet: {
          total: [{ $count: "n" }],
          triage: [{ $match: { status: "triage" } }, { $count: "n" }],
          pursuing: [
            { $match: { status: { $in: ["pursue", "pursuing"] } } },
            { $count: "n" },
          ],
          onHold: [{ $match: { status: "hold" } }, { $count: "n" }],
          drafting: [{ $match: { status: "drafting" } }, { $count: "n" }],
          complete: [
            {
              $match: {
                status: { $in: ["draft_complete", "reviewed", "submitted", "won"] },
              },
            },
            { $count: "n" },
          ],
          urgent: [
            {
              $match: {
                deadline_urgent: true,
                status: { $in: ["triage", "pursue", "pursuing"] },
              },
            },
            { $count: "n" },
          ],
        },
      },
    ])
    .toArray();

  const f = facetResult[0] ?? {};
  const total = f.total?.[0]?.n ?? 0;
  const triage = f.triage?.[0]?.n ?? 0;
  const pursuing = f.pursuing?.[0]?.n ?? 0;
  const onHold = f.onHold?.[0]?.n ?? 0;
  const drafting = f.drafting?.[0]?.n ?? 0;
  const complete = f.complete?.[0]?.n ?? 0;
  const urgentCount = f.urgent?.[0]?.n ?? 0;

  const warnings: string[] = [];
  if (total > 0 && triage === 0) {
    warnings.push(
      "Shortlist is empty — run a new scout to discover fresh opportunities."
    );
  }
  if (urgentCount > 0) {
    warnings.push(
      `${urgentCount} grant(s) with urgent deadlines (≤30 days) in your active queue — review now.`
    );
  }
  if (onHold > 0) {
    warnings.push(`${onHold} grant(s) on HOLD due to unresolved currency — manual review needed.`);
  }

  return {
    total_discovered: total,
    in_triage: triage,
    pursuing,
    on_hold: onHold,
    deadline_urgent_count: urgentCount,
    drafting,
    draft_complete: complete,
    warnings,
  };
}

export async function getGrantsActivity(
  days = 30
): Promise<{ date: string; count: number }[]> {
  const db = await getDb();
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const result = await db
    .collection("grants_raw")
    .aggregate([
      { $match: { scraped_at: { $gte: since } } },
      {
        $group: {
          _id: { $substr: ["$scraped_at", 0, 10] },
          count: { $sum: 1 },
        },
      },
      { $sort: { _id: 1 } },
    ])
    .toArray();

  return result.map((r) => ({ date: r._id as string, count: r.count as number }));
}

// ── Pipeline Kanban ────────────────────────────────────────────────────────────

export async function getPipelineGrants(): Promise<Record<string, Grant[]>> {
  const db = await getDb();
  // Fetch ALL scored grants — table view shows auto-passed too
  const docs = await db
    .collection("grants_scored")
    .find({})
    .sort({ weighted_total: -1 })
    .limit(1000)
    .toArray();

  const grouped: Record<string, Grant[]> = {
    shortlisted: [],
    pursue: [],
    hold: [],
    drafting: [],
    submitted: [],
    rejected: [],
  };

  for (const doc of docs) {
    const g = serializeId(doc as Record<string, unknown>) as unknown as Grant;
    if (!g.grant_name && g.title) g.grant_name = g.title;

    if (g.status === "triage" || g.status === "watch") grouped.shortlisted.push(g);
    else if (g.status === "pursue" || g.status === "pursuing") grouped.pursue.push(g);
    else if (g.status === "hold") grouped.hold.push(g);
    else if (g.status === "drafting") grouped.drafting.push(g);
    else if (g.status === "draft_complete" || g.status === "reviewed" || g.status === "submitted" || g.status === "won")
      grouped.submitted.push(g);
    else if (g.status === "passed" || g.status === "auto_pass" || g.status === "human_passed" || g.status === "reported" || g.status === "guardrail_rejected")
      grouped.rejected.push(g);
  }

  return grouped;
}

// ── Triage Queue ───────────────────────────────────────────────────────────────

export async function getTriageQueue(): Promise<Grant[]> {
  const db = await getDb();
  const docs = await db
    .collection("grants_scored")
    .find({ status: "triage" })
    .sort({ weighted_total: -1 })
    .toArray();

  return docs.map((doc) => {
    const g = serializeId(doc as Record<string, unknown>) as unknown as Grant;
    if (!g.grant_name && g.title) g.grant_name = g.title;
    return g;
  });
}

// ── Drafter ────────────────────────────────────────────────────────────────────

export async function getDraftGrants(): Promise<PipelineRecord[]> {
  const db = await getDb();

  // Use $lookup to avoid N+1 queries (was: sequential findOne per pipeline)
  const pipelines = await db
    .collection("grants_pipeline")
    .aggregate([
      { $match: { status: { $in: ["drafting", "draft_complete"] } } },
      { $sort: { started_at: -1 } },
      {
        $addFields: {
          _grant_oid: {
            $cond: {
              if: { $ne: ["$grant_id", null] },
              then: { $toObjectId: "$grant_id" },
              else: null,
            },
          },
        },
      },
      {
        $lookup: {
          from: "grants_scored",
          localField: "_grant_oid",
          foreignField: "_id",
          as: "_grant",
        },
      },
      {
        $lookup: {
          from: "grant_drafts",
          let: { pid: { $toString: "$_id" } },
          pipeline: [
            { $match: { $expr: { $eq: ["$pipeline_id", "$$pid"] } } },
            { $sort: { version: -1 } },
            { $limit: 1 },
          ],
          as: "_drafts",
        },
      },
      {
        $addFields: {
          grant_title: {
            $ifNull: [
              { $arrayElemAt: ["$_grant.grant_name", 0] },
              { $ifNull: [{ $arrayElemAt: ["$_grant.title", 0] }, "Unknown Grant"] },
            ],
          },
          grant_funder: { $ifNull: [{ $arrayElemAt: ["$_grant.funder", 0] }, ""] },
          grant_themes: { $ifNull: [{ $arrayElemAt: ["$_grant.themes_detected", 0] }, []] },
          latest_draft: { $arrayElemAt: ["$_drafts", 0] },
        },
      },
      {
        $project: { _grant: 0, _drafts: 0, _grant_oid: 0 },
      },
    ])
    .toArray();

  return pipelines.map((p) => {
    const rec = serializeId(p as Record<string, unknown>) as unknown as PipelineRecord;
    if (rec.latest_draft) {
      rec.latest_draft = serializeId(
        rec.latest_draft as unknown as Record<string, unknown>
      ) as unknown as DraftDoc;
    }
    return rec;
  });
}

export async function getSections(pipelineId: string): Promise<Record<string, DraftSection>> {
  const db = await getDb();
  const draft = await db
    .collection("grant_drafts")
    .findOne({ pipeline_id: pipelineId }, { sort: { version: -1 } });
  if (!draft) return {};
  return (draft.sections as Record<string, DraftSection>) || {};
}

// ── Knowledge Health ───────────────────────────────────────────────────────────

export async function getKnowledgeStatus(): Promise<KnowledgeStatus> {
  const db = await getDb();
  const [total, notion, drive, pastGrants] = await Promise.all([
    db.collection("knowledge_chunks").countDocuments({}),
    db.collection("knowledge_chunks").countDocuments({ source: "notion" }),
    db.collection("knowledge_chunks").countDocuments({ source: "drive" }),
    db.collection("knowledge_chunks").countDocuments({ doc_type: "past_grant_application" }),
  ]);

  const byTypeAgg = await db
    .collection("knowledge_chunks")
    .aggregate([{ $group: { _id: "$doc_type", count: { $sum: 1 } } }])
    .toArray();
  const byType: Record<string, number> = {};
  for (const r of byTypeAgg) byType[r._id as string] = r.count as number;

  const byThemeAgg = await db
    .collection("knowledge_chunks")
    .aggregate([
      { $unwind: "$themes" },
      { $group: { _id: "$themes", count: { $sum: 1 } } },
    ])
    .toArray();
  const byTheme: Record<string, number> = {};
  for (const r of byThemeAgg) byTheme[r._id as string] = r.count as number;

  const lastSync = await db
    .collection("knowledge_sync_logs")
    .findOne({}, { sort: { synced_at: -1 } });

  const status: KnowledgeStatus["status"] =
    total >= 200 ? "healthy" : total >= 50 ? "thin" : "critical";

  return {
    total_chunks: total,
    notion_chunks: notion,
    drive_chunks: drive,
    past_grant_chunks: pastGrants,
    by_type: byType,
    by_theme: byTheme,
    last_synced: lastSync ? (lastSync.synced_at as string) : null,
    status,
  };
}

export async function getSyncLogs(limit = 5) {
  const db = await getDb();
  const docs = await db
    .collection("knowledge_sync_logs")
    .find({})
    .sort({ synced_at: -1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => serializeId(d as Record<string, unknown>));
}

// ── Agent Config ───────────────────────────────────────────────────────────────

export async function getAgentConfig(agent?: string): Promise<AgentConfig | Record<string, AgentConfig>> {
  const db = await getDb();
  if (agent) {
    const doc = await db.collection("agent_config").findOne({ agent });
    if (!doc) return { agent };
    return serializeId(doc as Record<string, unknown>) as unknown as AgentConfig;
  }
  const docs = await db.collection("agent_config").find({}).toArray();
  const result: Record<string, AgentConfig> = {};
  for (const d of docs) {
    const cfg = serializeId(d as Record<string, unknown>) as unknown as AgentConfig;
    result[cfg.agent] = cfg;
  }
  return result;
}

export async function getGrantById(id: string): Promise<Grant | null> {
  const db = await getDb();
  const { ObjectId } = await import("mongodb");
  try {
    const doc = await db.collection("grants_scored").findOne({ _id: new ObjectId(id) });
    if (!doc) return null;
    const g = serializeId(doc as Record<string, unknown>) as unknown as Grant;
    if (!g.grant_name && g.title) g.grant_name = g.title;
    return g;
  } catch {
    return null;
  }
}

export async function saveAgentConfig(agent: string, config: Record<string, unknown>) {
  const db = await getDb();
  const update = { ...config, agent, updated_at: new Date().toISOString() };
  await db.collection("agent_config").updateOne({ agent }, { $set: update }, { upsert: true });
}

// ── Monitoring (B2) ─────────────────────────────────────────────────────────

export interface AgentRun {
  _id: string;
  node: string;
  action: string;
  created_at: string;
  grants_scored?: number;
  new_grants?: number;
  total_found?: number;
  pursue_count?: number;
  auto_pass_count?: number;
  hold_count?: number;
  top_score?: number;
  run_at?: string;
  quality_rejected?: number;
  content_dupes?: number;
  event?: string;
  [key: string]: unknown;
}

export interface AgentHealth {
  agent: string;
  lastRun: string | null;
  lastStatus: string;
  totalRuns: number;
  successfulRuns: number;
  failedRuns: number;
  uptimePct: number;
  lastGrantsProcessed: number;
}

export async function getAgentHealth(): Promise<AgentHealth[]> {
  const db = await getDb();

  // Single aggregation for node-based agents + parallel scout_runs count
  // knowledge_sync uses event regex, so it needs separate handling
  const [nodeRuns, knowledgeRuns, scoutRunCount] = await Promise.all([
    db
      .collection("audit_logs")
      .aggregate([
        { $match: { node: { $in: ["scout", "analyst", "drafter"] } } },
        { $sort: { created_at: -1 } },
        { $group: { _id: "$node", runs: { $push: "$$ROOT" } } },
        { $project: { _id: 1, runs: { $slice: ["$runs", 100] } } },
      ])
      .toArray(),
    db
      .collection("audit_logs")
      .find({ event: { $regex: /knowledge/i } })
      .sort({ created_at: -1 })
      .limit(100)
      .toArray(),
    db.collection("scout_runs").countDocuments({}),
  ]);

  // Build a map: agent -> runs array
  const runsByAgent: Record<string, Record<string, unknown>[]> = {
    scout: [],
    analyst: [],
    drafter: [],
    knowledge_sync: [],
  };
  for (const group of nodeRuns) {
    const agent = group._id as string;
    if (agent in runsByAgent) {
      runsByAgent[agent] = group.runs as Record<string, unknown>[];
    }
  }
  runsByAgent.knowledge_sync = knowledgeRuns as Record<string, unknown>[];

  const agents = ["scout", "analyst", "drafter", "knowledge_sync"];
  const results: AgentHealth[] = [];

  for (const agent of agents) {
    const allRuns = runsByAgent[agent];
    const lastRun = allRuns[0];
    const totalRuns = allRuns.length;

    const failedRuns = allRuns.filter(
      (r) => String(r.action || "").toLowerCase().includes("fail")
    ).length;

    results.push({
      agent,
      lastRun: (lastRun?.created_at as string) ?? (lastRun?.run_at as string) ?? null,
      lastStatus: lastRun ? "completed" : "never_run",
      totalRuns: agent === "scout" ? Math.max(totalRuns, scoutRunCount) : totalRuns,
      successfulRuns: totalRuns - failedRuns,
      failedRuns,
      uptimePct: totalRuns > 0 ? Math.round(((totalRuns - failedRuns) / totalRuns) * 100) : 0,
      lastGrantsProcessed: (lastRun?.grants_scored as number) ?? (lastRun?.new_grants as number) ?? 0,
    });
  }

  return results;
}

export async function getRunHistory(limit = 50): Promise<AgentRun[]> {
  const db = await getDb();
  const docs = await db.collection("audit_logs")
    .find({ node: { $in: ["scout", "analyst", "drafter", "company_brain", "grant_reader"] } })
    .sort({ created_at: -1 })
    .limit(limit)
    .toArray();

  return docs.map((d) => serializeId(d as Record<string, unknown>) as unknown as AgentRun);
}

export async function getErrorTimeline(days = 7): Promise<{ date: string; agent: string; message: string; created_at: string }[]> {
  const db = await getDb();
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const docs = await db.collection("audit_logs")
    .find({
      created_at: { $gte: since },
      $or: [
        { action: { $regex: /fail|error/i } },
        { event: { $regex: /fail|error/i } },
      ],
    })
    .sort({ created_at: -1 })
    .limit(50)
    .toArray();

  return docs.map((d) => ({
    date: (d.created_at as string || "").slice(0, 10),
    agent: (d.node as string) || "unknown",
    message: (d.action as string) || (d.event as string) || "Error",
    created_at: d.created_at as string || "",
  }));
}

// ── Audit Log (B5) ──────────────────────────────────────────────────────────

export interface AuditEntry {
  _id: string;
  node?: string;
  event?: string;
  action?: string;
  created_at: string;
  [key: string]: unknown;
}

export async function getAuditLogs(
  filters?: { agent?: string; days?: number },
  limit = 100
): Promise<AuditEntry[]> {
  const db = await getDb();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const query: Record<string, any> = {};

  if (filters?.agent) {
    query.node = filters.agent;
  }
  if (filters?.days) {
    const since = new Date(Date.now() - filters.days * 24 * 60 * 60 * 1000).toISOString();
    query.created_at = { $gte: since };
  }

  const docs = await db.collection("audit_logs")
    .find(query)
    .sort({ created_at: -1 })
    .limit(limit)
    .toArray();

  return docs.map((d) => serializeId(d as Record<string, unknown>) as unknown as AuditEntry);
}

// ── Grant Comments (B4) ─────────────────────────────────────────────────────

export interface GrantComment {
  _id: string;
  grant_id: string;
  user_name: string;
  user_email: string;
  message: string;
  created_at: string;
  parent_id?: string;
}

export async function getGrantComments(grantId: string): Promise<GrantComment[]> {
  const db = await getDb();
  const docs = await db.collection("grant_comments")
    .find({ grant_id: grantId })
    .sort({ created_at: 1 })
    .limit(100)
    .toArray();

  return docs.map((d) => serializeId(d as Record<string, unknown>) as unknown as GrantComment);
}

export interface ScoutRunDetail {
  _id: string;
  run_at: string;
  tavily_queries: number;
  exa_queries: number;
  perplexity_queries: number;
  direct_sources_crawled: number;
  total_found: number;
  new_grants: number;
  quality_rejected: number;
  content_dupes: number;
}

export async function getScoutRuns(limit = 10): Promise<ScoutRunDetail[]> {
  const db = await getDb();
  const docs = await db.collection("scout_runs")
    .find({})
    .sort({ run_at: -1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => serializeId(d as Record<string, unknown>) as unknown as ScoutRunDetail);
}

export async function addGrantComment(
  grantId: string,
  userName: string,
  userEmail: string,
  message: string
): Promise<GrantComment> {
  const db = await getDb();
  const doc = {
    grant_id: grantId,
    user_name: userName,
    user_email: userEmail,
    message,
    created_at: new Date().toISOString(),
  };
  const result = await db.collection("grant_comments").insertOne(doc);
  return { ...doc, _id: String(result.insertedId) };
}

// ── Recent Discoveries (Mission Control) ──────────────────────────────────

export interface RecentDiscovery {
  _id: string;
  grant_name: string;
  funder: string;
  source: string;
  scored_at: string | null;
  scraped_at: string | null;
  weighted_total: number | null;
  status: string;
  themes_detected: string[];
  max_funding_usd: number | null;
  url: string | null;
}

export async function getRecentDiscoveries(limit = 20): Promise<RecentDiscovery[]> {
  const db = await getDb();

  // Get recently scored grants (newest first)
  const scored = await db.collection("grants_scored")
    .find({})
    .sort({ scored_at: -1, _id: -1 })
    .limit(limit)
    .toArray();

  return scored.map((d) => ({
    _id: String(d._id),
    grant_name: (d.grant_name as string) || (d.title as string) || "Untitled",
    funder: (d.funder as string) || "Unknown",
    source: (d.source as string) || "scout",
    scored_at: (d.scored_at as string) || null,
    scraped_at: (d.scraped_at as string) || null,
    weighted_total: (d.weighted_total as number) ?? null,
    status: (d.status as string) || "triage",
    themes_detected: (d.themes_detected as string[]) || [],
    max_funding_usd: (d.max_funding_usd as number) ?? (d.max_funding as number) ?? null,
    url: (d.url as string) || null,
  }));
}

// ── Activity Feed (Mission Control) ────────────────────────────────────────

export interface ActivityEvent {
  _id: string;
  agent: string;
  action: string;
  details: string;
  created_at: string;
  type: "success" | "error" | "info" | "warning";
}

export async function getActivityFeed(limit = 50): Promise<ActivityEvent[]> {
  const db = await getDb();

  const docs = await db.collection("audit_logs")
    .find({})
    .sort({ created_at: -1 })
    .limit(limit)
    .toArray();

  return docs.map((d) => {
    const action = (d.action as string) || (d.event as string) || "";
    const isError = /fail|error/i.test(action);
    const isWarning = /warn|skip|reject/i.test(action);

    const details: string[] = [];
    if (d.grants_scored) details.push(`${d.grants_scored} scored`);
    if (d.new_grants) details.push(`${d.new_grants} new`);
    if (d.total_found) details.push(`${d.total_found} found`);
    if (d.pursue_count) details.push(`${d.pursue_count} pursue`);
    if (d.auto_pass_count) details.push(`${d.auto_pass_count} auto-pass`);
    if (d.scored_count) details.push(`${d.scored_count} scored`);
    if (d.input_count) details.push(`${d.input_count} input`);

    return {
      _id: String(d._id),
      agent: (d.node as string) || "system",
      action,
      details: details.join(" · ") || "",
      created_at: (d.created_at as string) || "",
      type: isError ? "error" : isWarning ? "warning" : "success",
    };
  });
}

// ── Pipeline Summary (Mission Control) ─────────────────────────────────────

export interface PipelineSummary {
  total_discovered: number;
  in_triage: number;
  pursuing: number;
  on_hold: number;
  drafting: number;
  submitted: number;
  rejected: number;
  urgent: number;
  unprocessed: number;
}

export async function getPipelineSummary(): Promise<PipelineSummary> {
  const db = await getDb();

  // Single $facet for grants_scored + parallel unprocessed count from grants_raw
  const [facetResult, unprocessed] = await Promise.all([
    db
      .collection("grants_scored")
      .aggregate([
        {
          $facet: {
            total: [{ $count: "n" }],
            triage: [{ $match: { status: "triage" } }, { $count: "n" }],
            pursuing: [
              { $match: { status: { $in: ["pursue", "pursuing"] } } },
              { $count: "n" },
            ],
            onHold: [{ $match: { status: "hold" } }, { $count: "n" }],
            drafting: [{ $match: { status: "drafting" } }, { $count: "n" }],
            submitted: [
              {
                $match: {
                  status: { $in: ["draft_complete", "reviewed", "submitted", "won"] },
                },
              },
              { $count: "n" },
            ],
            rejected: [
              {
                $match: {
                  status: { $in: ["passed", "auto_pass", "human_passed"] },
                },
              },
              { $count: "n" },
            ],
            urgent: [
              {
                $match: {
                  deadline_urgent: true,
                  status: { $in: ["triage", "pursue"] },
                },
              },
              { $count: "n" },
            ],
          },
        },
      ])
      .toArray(),
    db.collection("grants_raw").countDocuments({ processed: false }),
  ]);

  const f = facetResult[0] ?? {};

  return {
    total_discovered: f.total?.[0]?.n ?? 0,
    in_triage: f.triage?.[0]?.n ?? 0,
    pursuing: f.pursuing?.[0]?.n ?? 0,
    on_hold: f.onHold?.[0]?.n ?? 0,
    drafting: f.drafting?.[0]?.n ?? 0,
    submitted: f.submitted?.[0]?.n ?? 0,
    rejected: f.rejected?.[0]?.n ?? 0,
    urgent: f.urgent?.[0]?.n ?? 0,
    unprocessed,
  };
}

// ── What's New Digest (returning user) ──────────────────────────────────

export interface WhatsNewDigest {
  daysSinceVisit: number;
  scoutRuns: number;
  totalFound: number;
  newGrantsAdded: number;
  grantsScored: number;
  newInTriage: number;
  urgentDeadlines: number;
  errors: number;
  topNewGrants: {
    _id: string;
    grant_name: string;
    funder: string;
    weighted_total: number | null;
    themes_detected: string[];
    scored_at: string | null;
  }[];
  recentAgentRuns: {
    agent: string;
    action: string;
    created_at: string;
  }[];
}

export async function getWhatsNewDigest(since: string): Promise<WhatsNewDigest> {
  const db = await getDb();

  const daysSinceVisit = Math.max(
    1,
    Math.floor((Date.now() - new Date(since).getTime()) / 86_400_000)
  );

  const [
    scoutRunCount,
    newGrantsAdded,
    newInTriage,
    urgentDeadlines,
    errorCount,
  ] = await Promise.all([
    db.collection("scout_runs").countDocuments({ run_at: { $gte: since } }),
    db.collection("grants_scored").countDocuments({ scored_at: { $gte: since } }),
    db.collection("grants_scored").countDocuments({
      scored_at: { $gte: since },
      status: "triage",
    }),
    db.collection("grants_scored").countDocuments({
      deadline_urgent: true,
      status: { $in: ["triage", "pursue"] },
    }),
    db.collection("audit_logs").countDocuments({
      created_at: { $gte: since },
      $or: [
        { action: { $regex: /fail|error/i } },
        { event: { $regex: /fail|error/i } },
      ],
    }),
  ]);

  // Total found across scout runs since last visit
  const scoutAgg = await db.collection("scout_runs")
    .aggregate([
      { $match: { run_at: { $gte: since } } },
      { $group: { _id: null, total_found: { $sum: "$total_found" }, new_grants: { $sum: "$new_grants" } } },
    ])
    .toArray();
  const totalFound = scoutAgg[0]?.total_found ?? 0;

  // Analyst scoring count
  const analystAgg = await db.collection("audit_logs")
    .aggregate([
      { $match: { created_at: { $gte: since }, event: "analyst_run_complete" } },
      { $group: { _id: null, scored: { $sum: "$scored_count" } } },
    ])
    .toArray();
  const grantsScored = analystAgg[0]?.scored ?? 0;

  // Top new grants (highest score first)
  const topNewDocs = await db.collection("grants_scored")
    .find({ scored_at: { $gte: since } })
    .sort({ weighted_total: -1 })
    .limit(5)
    .toArray();

  const topNewGrants = topNewDocs.map((d) => ({
    _id: String(d._id),
    grant_name: (d.grant_name as string) || (d.title as string) || "Untitled",
    funder: (d.funder as string) || "Unknown",
    weighted_total: (d.weighted_total as number) ?? null,
    themes_detected: (d.themes_detected as string[]) || [],
    scored_at: (d.scored_at as string) || null,
  }));

  // Recent agent activity (latest 8)
  const recentActivity = await db.collection("audit_logs")
    .find({ created_at: { $gte: since } })
    .sort({ created_at: -1 })
    .limit(8)
    .toArray();

  const recentAgentRuns = recentActivity.map((d) => ({
    agent: (d.node as string) || "system",
    action: (d.action as string) || (d.event as string) || "",
    created_at: (d.created_at as string) || "",
  }));

  return {
    daysSinceVisit,
    scoutRuns: scoutRunCount,
    totalFound,
    newGrantsAdded,
    grantsScored,
    newInTriage,
    urgentDeadlines,
    errors: errorCount,
    topNewGrants,
    recentAgentRuns,
  };
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface Notification {
  _id: string;
  type: string;
  title: string;
  body: string;
  action_url: string;
  priority: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export async function getNotifications(
  limit = 30,
  unreadOnly = false,
): Promise<Notification[]> {
  const db = await getDb();
  const query: Record<string, unknown> = {};
  if (unreadOnly) query.read = false;

  const docs = await db
    .collection("notifications")
    .find(query)
    .sort({ created_at: -1 })
    .limit(limit)
    .toArray();

  return docs.map((d) => serializeId(d as Record<string, unknown>) as unknown as Notification);
}

export async function getUnreadNotificationCount(): Promise<number> {
  const db = await getDb();
  return db.collection("notifications").countDocuments({ read: false });
}

export async function markNotificationsRead(ids: string[]): Promise<void> {
  if (!ids.length) return;
  const { ObjectId } = await import("mongodb");
  const db = await getDb();
  await db.collection("notifications").updateMany(
    { _id: { $in: ids.map((id) => new ObjectId(id)) } },
    { $set: { read: true, read_at: new Date().toISOString() } },
  );
}

export async function markAllNotificationsRead(): Promise<void> {
  const db = await getDb();
  await db.collection("notifications").updateMany(
    { read: false },
    { $set: { read: true, read_at: new Date().toISOString() } },
  );
}

// ── Reviewers ─────────────────────────────────────────────────────────────────

export interface SectionReview {
  score: number;
  strengths: string[];
  issues: string[];
  suggestions: string[];
}

export interface DraftReview {
  _id: string;
  grant_id: string;
  draft_id: string;
  draft_version: number;
  perspective: "funder" | "scientific";
  overall_score: number;
  section_reviews: Record<string, SectionReview>;
  top_issues: string[];
  strengths: string[];
  verdict: string;
  summary: string;
  research_insights?: string[];
  web_research_used?: boolean;
  created_at: string;
}

export interface CoherenceIssue {
  type: "contradiction" | "budget_mismatch" | "unsupported_claim" | "repetition" | "missing_thread";
  sections_involved: string[];
  description: string;
  fix: string;
}

export interface CoherenceReview {
  _id: string;
  grant_id: string;
  draft_id: string;
  draft_version: number;
  perspective: "coherence";
  coherence_score: number;
  narrative_consistent: boolean;
  issues: CoherenceIssue[];
  overall_assessment: string;
  created_at: string;
}

export async function getReviewableGrants(): Promise<Grant[]> {
  const db = await getDb();
  const docs = await db
    .collection("grants_scored")
    .find({ status: { $in: ["draft_complete", "reviewed", "submitted", "won"] } })
    .sort({ scored_at: -1 })
    .limit(100)
    .toArray();

  return docs.map((doc) => {
    const g = serializeId(doc as Record<string, unknown>) as unknown as Grant;
    if (!g.grant_name && g.title) g.grant_name = g.title;
    return g;
  });
}

export async function getReviewsForGrant(grantId: string): Promise<{
  funder: DraftReview | null;
  scientific: DraftReview | null;
  coherence: CoherenceReview | null;
}> {
  const db = await getDb();
  const docs = await db
    .collection("draft_reviews")
    .find({ grant_id: grantId })
    .sort({ created_at: -1 })
    .limit(20)
    .toArray();

  const result: {
    funder: DraftReview | null;
    scientific: DraftReview | null;
    coherence: CoherenceReview | null;
  } = {
    funder: null,
    scientific: null,
    coherence: null,
  };
  for (const doc of docs) {
    const r = serializeId(doc as Record<string, unknown>) as any;
    if (r.perspective === "funder" && !result.funder) result.funder = r;
    if (r.perspective === "scientific" && !result.scientific) result.scientific = r;
    if (r.perspective === "coherence" && !result.coherence) result.coherence = r;
  }
  return result;
}
