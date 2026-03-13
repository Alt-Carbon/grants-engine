/**
 * Frontend query layer — all reads go through the FastAPI backend v2 API.
 * Notion (grants) and SQLite (metadata) are the sources of truth.
 * No direct MongoDB access.
 */
import { apiGet, apiPost } from "./api";

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
  notion_page_url?: string;
  notion_page_id?: string;
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

// ── Dashboard ──────────────────────────────────────────────────────────────────

export async function getDashboardStats() {
  return apiGet<{
    total_discovered: number;
    in_triage: number;
    pursuing: number;
    on_hold: number;
    deadline_urgent_count: number;
    drafting: number;
    draft_complete: number;
    warnings: string[];
  }>("/api/v2/dashboard/stats");
}

export async function getGrantsActivity(
  days = 30
): Promise<{ date: string; count: number }[]> {
  return apiGet(`/api/v2/activity?days=${days}`);
}

// ── Pipeline Kanban ────────────────────────────────────────────────────────────

export async function getPipelineGrants(): Promise<Record<string, Grant[]>> {
  return apiGet("/api/v2/grants");
}

// ── Triage Queue ───────────────────────────────────────────────────────────────

export async function getTriageQueue(): Promise<Grant[]> {
  return apiGet("/api/v2/grants/status/triage");
}

// ── Drafter ────────────────────────────────────────────────────────────────────

export async function getDraftGrants(): Promise<PipelineRecord[]> {
  return apiGet("/api/v2/drafts");
}

export async function getSections(pipelineId: string): Promise<Record<string, DraftSection>> {
  return apiGet(`/api/v2/drafts/${pipelineId}/sections`);
}

// ── Knowledge Health ───────────────────────────────────────────────────────────

export async function getKnowledgeStatus(): Promise<KnowledgeStatus> {
  return apiGet("/api/v2/knowledge/status");
}

export async function getSyncLogs(limit = 5) {
  return apiGet<Record<string, unknown>[]>(`/api/v2/knowledge/sync-logs?limit=${limit}`);
}

// ── Agent Config ───────────────────────────────────────────────────────────────

export async function getAgentConfig(agent?: string): Promise<AgentConfig | Record<string, AgentConfig>> {
  const path = agent ? `/api/v2/agent-config?agent=${agent}` : "/api/v2/agent-config";
  return apiGet(path);
}

export async function getGrantById(id: string): Promise<Grant | null> {
  try {
    return await apiGet<Grant>(`/api/v2/grants/by-id/${id}`);
  } catch {
    return null;
  }
}

export async function saveAgentConfig(agent: string, config: Record<string, unknown>) {
  return apiPost("/api/v2/agent-config", { agent, ...config });
}

// ── Monitoring ─────────────────────────────────────────────────────────────────

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
  return apiGet("/api/v2/agent-health");
}

export async function getRunHistory(limit = 50): Promise<AgentRun[]> {
  return apiGet(`/api/v2/run-history?limit=${limit}`);
}

export async function getErrorTimeline(days = 7): Promise<{ date: string; agent: string; message: string; created_at: string }[]> {
  return apiGet(`/api/v2/error-timeline?days=${days}`);
}

// ── Audit Log ──────────────────────────────────────────────────────────────────

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
  const params = new URLSearchParams();
  if (filters?.agent) params.set("agent", filters.agent);
  if (filters?.days) params.set("days", String(filters.days));
  params.set("limit", String(limit));
  return apiGet(`/api/v2/audit-logs?${params}`);
}

// ── Grant Comments ─────────────────────────────────────────────────────────────

export interface GrantComment {
  _id: string;
  grant_id: string;
  user_name: string;
  user_email: string;
  message: string;
  created_at: string;
  parent_id?: string;
  pinned?: boolean;
  reactions?: Record<string, string[]>;
  edited_at?: string | null;
}

export async function getGrantComments(grantId: string): Promise<GrantComment[]> {
  return apiGet(`/api/v2/comments/${grantId}`);
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
  return apiGet(`/api/v2/scout-runs?limit=${limit}`);
}

export async function addGrantComment(
  grantId: string,
  userName: string,
  userEmail: string,
  message: string
): Promise<GrantComment> {
  return apiPost(`/api/v2/comments/${grantId}`, {
    user_name: userName,
    user_email: userEmail,
    message,
  });
}

// ── Recent Discoveries (Mission Control) ──────────────────────────────────────

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
  return apiGet(`/api/v2/discoveries?limit=${limit}`);
}

// ── Activity Feed (Mission Control) ────────────────────────────────────────────

export interface ActivityEvent {
  _id: string;
  agent: string;
  action: string;
  details: string;
  created_at: string;
  type: "success" | "error" | "info" | "warning";
}

export async function getActivityFeed(limit = 50): Promise<ActivityEvent[]> {
  return apiGet(`/api/v2/activity-feed?limit=${limit}`);
}

// ── Pipeline Summary (Mission Control) ─────────────────────────────────────────

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
  return apiGet("/api/v2/pipeline-summary");
}

// ── What's New Digest ──────────────────────────────────────────────────────────

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
  return apiGet(`/api/v2/whats-new?since=${encodeURIComponent(since)}`);
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
  return apiGet(`/api/v2/notifications?limit=${limit}&unread_only=${unreadOnly}`);
}

export async function getUnreadNotificationCount(): Promise<number> {
  const data = await apiGet<{ count: number }>("/api/v2/notifications/count");
  return data.count;
}

export async function markNotificationsRead(ids: string[]): Promise<void> {
  if (!ids.length) return;
  await apiPost("/api/v2/notifications/mark-read", { ids });
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiPost("/api/v2/notifications/mark-all-read", {});
}
