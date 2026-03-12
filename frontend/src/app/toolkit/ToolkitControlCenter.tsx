"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCw,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  Wrench,
  Wifi,
  WifiOff,
} from "lucide-react";

interface AgentStatus {
  running: boolean;
  started_at: string | null;
  last_run_at?: string | null;
  pending_unprocessed?: number;
  last_run_scored?: number;
  last_run_new_grants?: number;
}

interface ServiceHealth {
  status: "ok" | "exhausted" | "unknown";
}

interface APIHealthData {
  tavily: ServiceHealth;
  exa: ServiceHealth;
  perplexity: ServiceHealth;
  jina: ServiceHealth;
}

interface NotionMcpStatus {
  status: "connected" | "disconnected" | "error" | string;
  tools?: number;
  error?: string;
}

type ActionKey =
  | "run_scout"
  | "run_analyst"
  | "force_analyst"
  | "sync_profile"
  | "notion_backfill"
  | "notion_backfill_views"
  | "reconnect_notion";

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function ActionButton({
  title,
  subtitle,
  loading,
  onClick,
  className = "",
}: {
  title: string;
  subtitle: string;
  loading: boolean;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{title}</p>
          <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
        </div>
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
        ) : (
          <Rocket className="h-4 w-4 text-slate-400" />
        )}
      </div>
    </button>
  );
}

export default function ToolkitControlCenter() {
  const [scout, setScout] = useState<AgentStatus | null>(null);
  const [analyst, setAnalyst] = useState<AgentStatus | null>(null);
  const [apiHealth, setApiHealth] = useState<APIHealthData | null>(null);
  const [notionMcp, setNotionMcp] = useState<NotionMcpStatus | null>(null);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());
  const [actionLoading, setActionLoading] = useState<Record<ActionKey, boolean>>({
    run_scout: false,
    run_analyst: false,
    force_analyst: false,
    sync_profile: false,
    notion_backfill: false,
    notion_backfill_views: false,
    reconnect_notion: false,
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const [scoutRes, analystRes, healthRes, notionRes] = await Promise.all([
        fetch("/api/run/scout").then((r) => r.json()),
        fetch("/api/run/analyst").then((r) => r.json()),
        fetch("/api/status/api-health").then((r) => r.json()),
        fetch("/api/status/notion-mcp").then((r) => r.json()),
      ]);
      setScout(scoutRes);
      setAnalyst(analystRes);
      if (healthRes?.services) setApiHealth(healthRes.services);
      setNotionMcp(notionRes);
      setLastRefresh(Date.now());
    } catch {
      // Ignore transient polling issues.
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 6000);
    return () => clearInterval(id);
  }, [poll]);

  const runAction = useCallback(
    async (key: ActionKey, req: () => Promise<Response>, successMessage: string) => {
      setActionLoading((prev) => ({ ...prev, [key]: true }));
      setMessage(null);
      setError(null);
      try {
        const res = await req();
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data?.error || data?.detail || `Action failed (${res.status})`);
        }
        setMessage(successMessage);
        await poll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActionLoading((prev) => ({ ...prev, [key]: false }));
      }
    },
    [poll]
  );

  const exhaustedCount = useMemo(
    () =>
      apiHealth
        ? Object.values(apiHealth).filter((service) => service.status === "exhausted").length
        : 0,
    [apiHealth]
  );

  const notionConnected = notionMcp?.status === "connected";

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5">
      <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <div className="rounded-lg bg-blue-50 p-2 text-blue-700">
                <Wrench className="h-4 w-4" />
              </div>
              <h1 className="text-lg font-bold text-slate-900">
                Toolkit Control Center
              </h1>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Operations console for re-runs, Notion sync, and system recovery.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={poll}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <Link
              href="/monitoring"
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
            >
              Mission Control
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Scout</p>
          <p className="mt-2 text-xl font-bold text-slate-900">
            {scout?.running ? "Running" : "Idle"}
          </p>
          <p className="mt-1 text-xs text-slate-500">Last run: {timeAgo(scout?.last_run_at)}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Analyst</p>
          <p className="mt-2 text-xl font-bold text-slate-900">
            {analyst?.running ? "Running" : "Idle"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Queue: {analyst?.pending_unprocessed ?? 0} unprocessed
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">API Health</p>
          <p className="mt-2 text-xl font-bold text-slate-900">
            {exhaustedCount === 0 ? "Healthy" : `${exhaustedCount} Exhausted`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {exhaustedCount === 0 ? "All search providers operational" : "One or more providers at quota"}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Notion MCP</p>
          <p className="mt-2 flex items-center gap-2 text-xl font-bold text-slate-900">
            {notionConnected ? (
              <>
                <Wifi className="h-4 w-4 text-emerald-600" />
                Connected
              </>
            ) : (
              <>
                <WifiOff className="h-4 w-4 text-rose-600" />
                {notionMcp?.status || "Disconnected"}
              </>
            )}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Tools: {notionMcp?.tools ?? 0}
          </p>
        </div>
      </div>

      {(message || error) && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            error
              ? "border-rose-200 bg-rose-50 text-rose-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}
        >
          <div className="flex items-center gap-2">
            {error ? (
              <AlertTriangle className="h-4 w-4" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            <span>{error || message}</span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Search className="h-4 w-4 text-blue-600" />
            <h2 className="text-sm font-bold text-slate-900">Agent Operations</h2>
          </div>
          <div className="grid grid-cols-1 gap-3">
            <ActionButton
              title="Run Scout"
              subtitle="Start a standard scout cycle to discover new grants."
              loading={actionLoading.run_scout}
              onClick={() =>
                runAction(
                  "run_scout",
                  () => fetch("/api/run/scout", { method: "POST" }),
                  "Scout run started."
                )
              }
            />
            <ActionButton
              title="Run Analyst"
              subtitle="Score only pending/unprocessed grants."
              loading={actionLoading.run_analyst}
              onClick={() =>
                runAction(
                  "run_analyst",
                  () => fetch("/api/run/analyst", { method: "POST" }),
                  "Analyst run started."
                )
              }
            />
            <ActionButton
              title="Force Re-Analyze All Grants"
              subtitle="Re-score every grant regardless of processed state."
              loading={actionLoading.force_analyst}
              onClick={() =>
                runAction(
                  "force_analyst",
                  () => fetch("/api/run/analyst?force=true", { method: "POST" }),
                  "Force analyst run started."
                )
              }
              className="border-amber-200 bg-amber-50/40"
            />
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-600" />
            <h2 className="text-sm font-bold text-slate-900">Notion Operations</h2>
          </div>
          <div className="grid grid-cols-1 gap-3">
            <ActionButton
              title="Sync Company Profile from Notion"
              subtitle="Refresh static AltCarbon profile used by agents."
              loading={actionLoading.sync_profile}
              onClick={() =>
                runAction(
                  "sync_profile",
                  () => fetch("/api/run/sync-profile", { method: "POST" }),
                  "Profile sync started."
                )
              }
            />
            <ActionButton
              title="Backfill Grants to Notion"
              subtitle="Sync all scored grants to the Notion grant pipeline."
              loading={actionLoading.notion_backfill}
              onClick={() =>
                runAction(
                  "notion_backfill",
                  () =>
                    fetch("/api/notion/backfill", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ setup_views: false }),
                    }),
                  "Notion backfill started."
                )
              }
            />
            <ActionButton
              title="Backfill + Setup Views"
              subtitle="Run backfill and create/update Notion board/table views."
              loading={actionLoading.notion_backfill_views}
              onClick={() =>
                runAction(
                  "notion_backfill_views",
                  () =>
                    fetch("/api/notion/backfill", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ setup_views: true }),
                    }),
                  "Notion backfill + views setup started."
                )
              }
            />
            <ActionButton
              title="Reconnect Notion MCP"
              subtitle="Restart the Notion MCP connection if it is disconnected."
              loading={actionLoading.reconnect_notion}
              onClick={() =>
                runAction(
                  "reconnect_notion",
                  () => fetch("/api/run/notion-mcp/reconnect", { method: "POST" }),
                  "Notion MCP reconnect triggered."
                )
              }
              className="border-sky-200 bg-sky-50/40"
            />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500 shadow-sm">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          Internal operations only
        </div>
        <span>Last refresh: {timeAgo(new Date(lastRefresh).toISOString())}</span>
      </div>
    </div>
  );
}

