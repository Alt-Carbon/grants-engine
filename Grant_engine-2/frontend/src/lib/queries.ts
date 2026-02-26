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
  const [total, triage, pursuing, watching, onHold, drafting, complete, urgentCount] =
    await Promise.all([
      db.collection("grants_scored").countDocuments({}),
      db.collection("grants_scored").countDocuments({ status: "triage" }),
      db.collection("grants_scored").countDocuments({ status: { $in: ["pursue", "pursuing"] } }),
      db.collection("grants_scored").countDocuments({ status: "watch" }),
      db.collection("grants_scored").countDocuments({ status: "hold" }),
      db.collection("grants_pipeline").countDocuments({ status: "drafting" }),
      db.collection("grants_pipeline").countDocuments({ status: "draft_complete" }),
      db.collection("grants_scored").countDocuments({
        deadline_urgent: true,
        status: { $in: ["triage", "pursue", "watch"] },
      }),
    ]);

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
    watching,
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
    watch: [],
    drafting: [],
    submitted: [],
    passed: [],
  };

  for (const doc of docs) {
    const g = serializeId(doc as Record<string, unknown>) as unknown as Grant;
    if (!g.grant_name && g.title) g.grant_name = g.title;

    if (g.status === "triage") grouped.shortlisted.push(g);
    else if (g.status === "pursue" || g.status === "pursuing") grouped.pursue.push(g);
    else if (g.status === "watch") grouped.watch.push(g);
    else if (g.status === "drafting") grouped.drafting.push(g);
    else if (g.status === "draft_complete" || g.status === "submitted" || g.status === "won")
      grouped.submitted.push(g);
    else if (g.status === "passed" || g.status === "auto_pass" || g.status === "human_passed" || g.status === "reported")
      grouped.passed.push(g);
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
  const pipelines = await db
    .collection("grants_pipeline")
    .find({ status: { $in: ["drafting", "draft_complete"] } })
    .sort({ started_at: -1 })
    .toArray();

  const result: PipelineRecord[] = [];

  for (const p of pipelines) {
    const pid = serializeId(p as Record<string, unknown>) as unknown as PipelineRecord;

    // Enrich with grant title/funder
    if (p.grant_id) {
      const { ObjectId } = await import("mongodb");
      const grant = await db
        .collection("grants_scored")
        .findOne({ _id: new ObjectId(p.grant_id as string) });
      if (grant) {
        pid.grant_title = (grant.grant_name as string) || (grant.title as string) || "Unknown Grant";
        pid.grant_funder = (grant.funder as string) || "";
      }
    }

    // Attach latest draft
    const draft = await db
      .collection("grant_drafts")
      .findOne({ pipeline_id: pid._id }, { sort: { version: -1 } });
    if (draft) {
      pid.latest_draft = serializeId(draft as Record<string, unknown>) as unknown as DraftDoc;
    }

    result.push(pid);
  }

  return result;
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
