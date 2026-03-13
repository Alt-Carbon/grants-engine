"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { isHybridMode, NOTION_WORKSPACE_URL } from "@/lib/deployment";
import {
  Play,
  Search,
  BarChart3,
  Zap,
  RefreshCw,
  Loader2,
  CheckCircle,
  AlertCircle,
  Clock,
  ArrowRight,
  ExternalLink,
  Radio,
  Terminal,
  TrendingUp,
  AlertTriangle,
  Inbox,
  FileText,
  Trophy,
  ChevronRight,
  ChevronDown,
  Cpu,
  CircleDot,
  Activity,
  Sparkles,
  Shield,
  Hash,
  ArrowUpRight,
  Layers,
  Timer,
  Wifi,
  WifiOff,
  Globe,
  Database,
  BookOpen,
  Upload,
  Pause,
  RotateCcw,
  Link2,
  Server,
  Wrench,
  Calendar,
  Plug,
  Trash2,
  FolderSync,
  Brain,
  PlusCircle,
  ScrollText,
  Settings,
  Save,
  Filter,
  Bot,
  ChevronUp,
  Rocket,
  CheckCircle2,
} from "lucide-react";

/* ═══════════════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════════════ */

interface AgentStatus {
  running: boolean;
  started_at: string | null;
  last_run_at?: string | null;
  last_run_new_grants?: number;
  last_run_total_found?: number;
  last_run_scored?: number;
  pending_unprocessed?: number;
  total_runs?: number;
}

interface ActivityEvent {
  _id: string;
  agent: string;
  action: string;
  details: string;
  created_at: string;
  type: "success" | "error" | "info" | "warning";
}

interface Discovery {
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

interface PipelineSummary {
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

interface ScoutRun {
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

interface ServiceHealth {
  status: "ok" | "exhausted" | "unknown";
  exhausted_at?: string;
  cooldown_remaining_secs?: number;
  last_error?: string;
}

interface APIHealthData {
  tavily: ServiceHealth;
  exa: ServiceHealth;
  perplexity: ServiceHealth;
  cloudflare: ServiceHealth;
}

interface NotionMcpStatus {
  status: "connected" | "disconnected" | "error" | string;
  tools?: number;
}

interface SchedulerJob {
  id: string;
  name: string;
  next_run: string | null;
  trigger: string;
}

interface MCPServer {
  name: string;
  connected: boolean;
  tools_count?: number;
  error?: string;
}

interface MissionControlProps {
  initialActivity: ActivityEvent[];
  initialDiscoveries: Discovery[];
  initialPipeline: PipelineSummary;
  initialScoutRuns: ScoutRun[];
}

/* ═══════════════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════════════ */

function elapsed(startedAt: string | null): string {
  if (!startedAt) return "";
  const sec = Math.floor(
    (Date.now() - new Date(startedAt).getTime()) / 1000
  );
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return (
    d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
    " " +
    d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  );
}

function formatMoney(n: number | null): string {
  if (!n) return "--";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Global Progress Bar
   ═══════════════════════════════════════════════════════════════════════════ */

function GlobalProgress({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="fixed left-0 right-0 top-0 z-[120] h-1">
      <div
        className="h-full w-full bg-blue-600/20"
        style={{ position: "relative", overflow: "hidden" }}
      >
        <div
          className="absolute inset-0 h-full bg-gradient-to-r from-transparent via-blue-500 to-transparent"
          style={{
            animation: "progress-shimmer 1.5s ease-in-out infinite",
            width: "40%",
          }}
        />
      </div>
      <style>{`
        @keyframes progress-shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(350%); }
        }
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(400%); }
        }
      `}</style>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Status Dot
   ═══════════════════════════════════════════════════════════════════════════ */

function StatusDot({
  status,
  pulse,
  size = "sm",
}: {
  status: "online" | "busy" | "idle" | "error";
  pulse?: boolean;
  size?: "sm" | "md";
}) {
  const colors = {
    online: "bg-emerald-500",
    busy: "bg-amber-500",
    idle: "bg-slate-400",
    error: "bg-rose-500",
  };
  const dim = size === "md" ? "h-3 w-3" : "h-2.5 w-2.5";
  return (
    <span className={`relative flex ${dim}`}>
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full ${colors[status]} opacity-75`}
        />
      )}
      <span
        className={`relative inline-flex ${dim} rounded-full ${colors[status]}`}
      />
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Command Header
   ═══════════════════════════════════════════════════════════════════════════ */

function CommandHeader({
  lastRefresh,
  onRefresh,
  scoutRunning,
  analystRunning,
  apiExhaustedCount,
}: {
  lastRefresh: number;
  onRefresh: () => void;
  scoutRunning: boolean;
  analystRunning: boolean;
  apiExhaustedCount: number;
}) {
  const anyRunning = scoutRunning || analystRunning;
  const systemStatus = apiExhaustedCount > 0 ? "error" : anyRunning ? "busy" : "online";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 shadow-sm">
            <Shield className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-slate-900">
                Mission Control
              </h1>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                v4
              </span>
            </div>
            <p className="text-[11px] text-slate-400">
              AltCarbon Grants Intelligence Engine
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="hidden items-center gap-2 lg:flex">
            <Link
              href="/drafter"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 hover:bg-slate-50"
            >
              <FileText className="h-3.5 w-3.5" />
              Drafter
            </Link>
          </div>

          {/* System status pill */}
          <div className="hidden items-center gap-2.5 rounded-full border border-slate-200 px-3.5 py-2 sm:flex">
            <StatusDot status={systemStatus} pulse={anyRunning} />
            <span className="text-[11px] font-semibold text-slate-600">
              {apiExhaustedCount > 0
                ? `${apiExhaustedCount} API${apiExhaustedCount > 1 ? "s" : ""} exhausted`
                : anyRunning
                ? scoutRunning && analystRunning
                  ? "Scout + Analyst active"
                  : scoutRunning
                  ? "Scout active"
                  : "Analyst active"
                : "All systems operational"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden text-[10px] tabular-nums text-slate-400 sm:block">
              {timeAgo(new Date(lastRefresh).toISOString())}
            </span>
            <button
              onClick={onRefresh}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-400 transition-all hover:-translate-y-0.5 hover:border-slate-300 hover:text-slate-600 hover:shadow-sm"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Notion Pipeline Banner (hybrid mode only)
   ═══════════════════════════════════════════════════════════════════════════ */

function NotionPipelineBanner({
  pipeline,
  notionMcp,
}: {
  pipeline: PipelineSummary;
  notionMcp: NotionMcpStatus | null;
}) {
  if (!isHybridMode) return null;

  const notionConnected = notionMcp?.status === "connected";

  return (
    <a
      href={NOTION_WORKSPACE_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="group relative overflow-hidden rounded-2xl border border-slate-200 p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-lg"
      style={{ background: "linear-gradient(to right, #0f172a, #1e293b, #0f172a)" }}
    >
      {/* Subtle gradient shimmer */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.03] to-transparent opacity-0 transition-opacity group-hover:opacity-100" />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 backdrop-blur-sm">
            <BookOpen className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white">
              Grant Pipeline in Notion
            </h2>
            <p className="mt-0.5 text-[11px] text-slate-300">
              {pipeline.total_discovered} grants discovered · {pipeline.pursuing} pursuing · {pipeline.drafting} drafting
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Notion MCP status */}
          <div className="flex items-center gap-2 rounded-full bg-white/[0.15] px-3 py-1.5">
            {notionConnected ? (
              <>
                <Wifi className="h-3 w-3 text-emerald-400" />
                <span className="text-[10px] font-semibold text-emerald-400">
                  Notion Synced
                </span>
              </>
            ) : (
              <>
                <WifiOff className="h-3 w-3 text-amber-400" />
                <span className="text-[10px] font-semibold text-amber-400">
                  Notion Offline
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-1.5 text-slate-300 transition-colors group-hover:text-white">
            <span className="text-xs font-semibold">Open in Notion</span>
            <ArrowUpRight className="h-4 w-4" />
          </div>
        </div>
      </div>

      {/* Mini pipeline stages */}
      <div className="mt-4 flex gap-2">
        {[
          { label: "Triage", count: pipeline.in_triage, color: "bg-blue-400" },
          { label: "Pursuing", count: pipeline.pursuing, color: "bg-emerald-400" },
          { label: "Drafting", count: pipeline.drafting, color: "bg-purple-400" },
          { label: "Submitted", count: pipeline.submitted, color: "bg-cyan-400" },
        ].map((stage) => (
          <div
            key={stage.label}
            className="flex items-center gap-2 rounded-lg bg-white/[0.12] px-3 py-1.5"
          >
            <div className={`h-1.5 w-1.5 rounded-full ${stage.color}`} />
            <span className="text-[10px] font-semibold text-slate-200">
              {stage.count} {stage.label}
            </span>
          </div>
        ))}
      </div>
    </a>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Pipeline Metrics
   ═══════════════════════════════════════════════════════════════════════════ */

function PipelineMetrics({ data }: { data: PipelineSummary }) {
  const stages = [
    { label: "Discovered", value: data.total_discovered, icon: Search, accent: "from-blue-500 to-blue-600", iconColor: "text-blue-600", iconBg: "bg-blue-50" },
    { label: "In Triage", value: data.in_triage, icon: Inbox, accent: "from-indigo-500 to-indigo-600", iconColor: "text-indigo-600", iconBg: "bg-indigo-50" },
    { label: "Pursuing", value: data.pursuing, icon: TrendingUp, accent: "from-emerald-500 to-emerald-600", iconColor: "text-emerald-600", iconBg: "bg-emerald-50" },
    { label: "Drafting", value: data.drafting, icon: FileText, accent: "from-purple-500 to-purple-600", iconColor: "text-purple-600", iconBg: "bg-purple-50" },
    { label: "Submitted", value: data.submitted, icon: Trophy, accent: "from-cyan-500 to-cyan-600", iconColor: "text-cyan-600", iconBg: "bg-cyan-50" },
  ];

  const maxVal = Math.max(...stages.map((s) => s.value), 1);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {stages.map((stage) => {
        const Icon = stage.icon;
        const ratio = stage.value / maxVal;
        return (
          <div key={stage.label} className="group relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">{stage.label}</p>
              <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${stage.iconBg}`}>
                <Icon className={`h-4 w-4 ${stage.iconColor}`} />
              </div>
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums text-slate-900">{stage.value}</p>
            <div className="mt-3 h-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full bg-gradient-to-r ${stage.accent} transition-all duration-700 ease-out`}
                style={{ width: `${Math.max(ratio * 100, 4)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Alert Badges
   ═══════════════════════════════════════════════════════════════════════════ */

function AlertBadges({ data }: { data: PipelineSummary }) {
  if (data.urgent === 0 && data.unprocessed === 0 && data.rejected === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {data.urgent > 0 && (
        isHybridMode ? (
          <a
            href={NOTION_WORKSPACE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-[11px] font-semibold text-rose-700 transition-colors hover:bg-rose-100"
          >
            <AlertTriangle className="h-3 w-3" />
            {data.urgent} urgent deadline{data.urgent !== 1 ? "s" : ""}
            <ArrowUpRight className="h-3 w-3" />
          </a>
        ) : (
          <Link
            href="/triage"
            className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-[11px] font-semibold text-rose-700 transition-colors hover:bg-rose-100"
          >
            <AlertTriangle className="h-3 w-3" />
            {data.urgent} urgent deadline{data.urgent !== 1 ? "s" : ""}
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        )
      )}
      {data.unprocessed > 0 && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-semibold text-amber-700">
          <Clock className="h-3 w-3" />
          {data.unprocessed} queued for scoring
        </span>
      )}
      {data.rejected > 0 && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-500">
          {data.rejected} rejected
        </span>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Agent Panel
   ═══════════════════════════════════════════════════════════════════════════ */

const AGENT_CONFIG = {
  scout: {
    label: "Scout Agent",
    icon: Search,
    accentGradient: "from-blue-500 to-blue-600",
    iconBg: "bg-blue-50",
    iconColor: "text-blue-600",
    pillBg: "bg-blue-50",
    pillText: "text-blue-700",
    pillBorder: "border-blue-200",
    desc: "Searches the web for new grant opportunities via Tavily, Exa & Perplexity",
    runLabel: "Run Scout",
    runningLabel: "Scouting the web...",
  },
  analyst: {
    label: "Analyst Agent",
    icon: BarChart3,
    accentGradient: "from-violet-500 to-violet-600",
    iconBg: "bg-violet-50",
    iconColor: "text-violet-600",
    pillBg: "bg-violet-50",
    pillText: "text-violet-700",
    pillBorder: "border-violet-200",
    desc: "Scores, ranks & triages grants using multi-criteria AI evaluation",
    runLabel: "Run Analyst",
    runningLabel: "Scoring grants...",
  },
} as const;

type AgentKey = keyof typeof AGENT_CONFIG;

function AgentPanel({
  agentKey,
  status,
  triggerLoading,
  onTrigger,
}: {
  agentKey: AgentKey;
  status: AgentStatus | null;
  triggerLoading: string | null;
  onTrigger: (agent: AgentKey) => void;
}) {
  const cfg = AGENT_CONFIG[agentKey];
  const Icon = cfg.icon;
  const isRunning = status?.running ?? false;

  return (
    <div className="group relative flex overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md">
      <div className={`w-1 shrink-0 bg-gradient-to-b ${cfg.accentGradient} ${isRunning ? "animate-pulse" : ""}`} />
      <div className="flex-1 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${cfg.iconBg}`}>
              <Icon className={`h-5 w-5 ${cfg.iconColor}`} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">{cfg.label}</h3>
              <p className="mt-0.5 max-w-[240px] text-[11px] leading-relaxed text-slate-400">{cfg.desc}</p>
            </div>
          </div>
          {isRunning ? (
            <div className={`flex shrink-0 items-center gap-2 rounded-full border ${cfg.pillBorder} ${cfg.pillBg} px-3 py-1.5`}>
              <StatusDot status="busy" pulse />
              <span className={`text-[11px] font-semibold uppercase tracking-[0.12em] ${cfg.pillText}`}>Active</span>
            </div>
          ) : (
            <div className="flex shrink-0 items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5">
              <StatusDot status="idle" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Idle</span>
            </div>
          )}
        </div>

        {isRunning && status?.started_at && (
          <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Loader2 className={`h-3.5 w-3.5 animate-spin ${cfg.iconColor}`} />
                <span className="text-[11px] font-semibold text-slate-600">{cfg.runningLabel}</span>
              </div>
              <span className="rounded-md bg-white px-2 py-0.5 font-mono text-[11px] font-bold tabular-nums text-slate-500 shadow-sm">
                {elapsed(status.started_at)}
              </span>
            </div>
            <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full w-1/3 rounded-full bg-gradient-to-r ${cfg.accentGradient}`}
                style={{ animation: "shimmer 1.5s ease-in-out infinite" }}
              />
            </div>
          </div>
        )}

        {!isRunning && status && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
              <Timer className="h-3 w-3" />
              <span>Last run: <span className="font-semibold text-slate-600">{status.last_run_at ? timeAgo(status.last_run_at) : "Never"}</span></span>
            </div>
            {agentKey === "scout" && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { value: (status.last_run_total_found ?? 0).toLocaleString(), label: "Scanned", bg: "bg-slate-50", ring: "ring-slate-100", valueColor: "text-slate-900" },
                  { value: status.last_run_new_grants ?? 0, label: "New Found", bg: "bg-emerald-50", ring: "ring-emerald-100", valueColor: "text-emerald-700" },
                  { value: status.total_runs ?? 0, label: "Total Runs", bg: "bg-slate-50", ring: "ring-slate-100", valueColor: "text-slate-900" },
                ].map((stat) => (
                  <div key={stat.label} className={`rounded-xl ${stat.bg} p-3 text-center ring-1 ${stat.ring}`}>
                    <p className={`text-xl font-black tabular-nums ${stat.valueColor}`}>{stat.value}</p>
                    <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{stat.label}</p>
                  </div>
                ))}
              </div>
            )}
            {agentKey === "analyst" && (
              <div className="grid grid-cols-3 gap-2">
                {[
                  { value: status.last_run_scored ?? 0, label: "Scored", bg: "bg-slate-50", ring: "ring-slate-100", valueColor: "text-slate-900" },
                  { value: status.pending_unprocessed ?? 0, label: "In Queue", bg: "bg-amber-50", ring: "ring-amber-100", valueColor: "text-amber-700" },
                  { value: status.last_run_at ? new Date(status.last_run_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "--", label: "Last Run", bg: "bg-slate-50", ring: "ring-slate-100", valueColor: "text-slate-700" },
                ].map((stat) => (
                  <div key={stat.label} className={`rounded-xl ${stat.bg} p-3 text-center ring-1 ${stat.ring}`}>
                    <p className={`text-sm font-black tabular-nums ${stat.valueColor}`}>{stat.value}</p>
                    <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{stat.label}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="mt-4">
          <button
            disabled={isRunning || triggerLoading === agentKey}
            onClick={() => onTrigger(agentKey)}
            className={`inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all ${
              isRunning
                ? "cursor-not-allowed bg-slate-100 text-slate-400"
                : triggerLoading === agentKey
                ? "cursor-wait bg-slate-100 text-slate-500"
                : "bg-slate-900 text-white shadow-sm hover:bg-slate-800"
            }`}
          >
            {triggerLoading === agentKey ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {isRunning ? "Running..." : triggerLoading === agentKey ? "Starting..." : cfg.runLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Toolkit — Quick Actions Grid
   ═══════════════════════════════════════════════════════════════════════════ */

interface ToolkitAction {
  id: string;
  label: string;
  desc: string;
  icon: typeof Database;
  iconColor: string;
  iconBg: string;
  endpoint: string;
  method: "run" | "admin";
  confirm?: string;
}

const TOOLKIT_ACTIONS: ToolkitAction[] = [
  {
    id: "knowledge-sync",
    label: "Sync Knowledge",
    desc: "Re-sync Notion pages to vector DB",
    icon: FolderSync,
    iconColor: "text-blue-600",
    iconBg: "bg-blue-50",
    endpoint: "knowledge-sync",
    method: "run",
  },
  {
    id: "sync-profile",
    label: "Rebuild Profile",
    desc: "Re-sync AltCarbon static profile from Notion",
    icon: Brain,
    iconColor: "text-violet-600",
    iconBg: "bg-violet-50",
    endpoint: "sync-profile",
    method: "run",
  },
  {
    id: "sync-past-grants",
    label: "Ingest Past Grants",
    desc: "Re-extract and sync past grant PDFs",
    icon: BookOpen,
    iconColor: "text-emerald-600",
    iconBg: "bg-emerald-50",
    endpoint: "sync-past-grants",
    method: "run",
  },
  {
    id: "backfill",
    label: "Backfill Fields",
    desc: "Fill missing grant_type, geography, eligibility",
    icon: Database,
    iconColor: "text-amber-600",
    iconBg: "bg-amber-50",
    endpoint: "backfill",
    method: "admin",
  },
  {
    id: "deduplicate",
    label: "Deduplicate",
    desc: "Remove duplicate grants from DB",
    icon: Trash2,
    iconColor: "text-rose-600",
    iconBg: "bg-rose-50",
    endpoint: "deduplicate",
    method: "admin",
    confirm: "Remove duplicate grants? This cannot be undone.",
  },
  {
    id: "notion-backfill",
    label: "Notion Backfill",
    desc: "Sync all scored grants to Notion",
    icon: Upload,
    iconColor: "text-cyan-600",
    iconBg: "bg-cyan-50",
    endpoint: "notion-backfill",
    method: "admin",
  },
];

function ToolkitPanel() {
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; msg: string }>>({});

  const runAction = useCallback(async (action: ToolkitAction) => {
    if (action.confirm && !window.confirm(action.confirm)) return;
    setRunning(action.id);
    setResults((p) => { const n = { ...p }; delete n[action.id]; return n; });

    try {
      const url = action.method === "run" ? `/api/run/${action.endpoint}` : "/api/admin";
      const body = action.method === "admin" ? { action: action.endpoint } : {};
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
      const msg = data.status || data.message || "Done";
      setResults((p) => ({ ...p, [action.id]: { ok: true, msg: typeof msg === "string" ? msg : JSON.stringify(msg) } }));
    } catch (e) {
      setResults((p) => ({ ...p, [action.id]: { ok: false, msg: e instanceof Error ? e.message : "Failed" } }));
    } finally {
      setRunning(null);
    }
  }, []);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2.5">
        <Wrench className="h-4 w-4 text-slate-400" />
        <h2 className="text-sm font-bold text-slate-900">Toolkit</h2>
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Quick Actions</span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {TOOLKIT_ACTIONS.map((action) => {
          const Icon = action.icon;
          const isRunning = running === action.id;
          const result = results[action.id];

          return (
            <button
              key={action.id}
              onClick={() => runAction(action)}
              disabled={running !== null}
              className={`group relative flex flex-col items-center gap-2.5 rounded-xl border p-4 text-center transition-all ${
                isRunning
                  ? "border-blue-200 bg-blue-50/50"
                  : result?.ok === true
                  ? "border-emerald-200 bg-emerald-50/30"
                  : result?.ok === false
                  ? "border-rose-200 bg-rose-50/30"
                  : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
              } ${running !== null && !isRunning ? "opacity-50" : ""}`}
            >
              <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${action.iconBg} transition-transform group-hover:scale-110`}>
                {isRunning ? (
                  <Loader2 className={`h-5 w-5 animate-spin ${action.iconColor}`} />
                ) : result?.ok === true ? (
                  <CheckCircle className="h-5 w-5 text-emerald-600" />
                ) : result?.ok === false ? (
                  <AlertCircle className="h-5 w-5 text-rose-600" />
                ) : (
                  <Icon className={`h-5 w-5 ${action.iconColor}`} />
                )}
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-900">{action.label}</p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-slate-400">
                  {result ? result.msg.slice(0, 40) : action.desc}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Integrations Panel — MCP + Scheduler
   ═══════════════════════════════════════════════════════════════════════════ */

function IntegrationsPanel() {
  const [scheduler, setScheduler] = useState<{ jobs: SchedulerJob[]; paused: boolean } | null>(null);
  const [mcp, setMcp] = useState<{ servers: MCPServer[] } | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [sched, mcpData] = await Promise.all([
        fetch("/api/status/scheduler").then((r) => r.json()).catch(() => null),
        fetch("/api/status/mcp").then((r) => r.json()).catch(() => null),
      ]);
      if (sched) setScheduler(sched);
      if (mcpData) setMcp(mcpData);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSchedulerAction = useCallback(async (action: "pause" | "resume") => {
    setActionLoading(action);
    try {
      await fetch("/api/scheduler", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      await load();
    } finally {
      setActionLoading(null);
    }
  }, [load]);

  const handleReconnect = useCallback(async (target: string) => {
    setActionLoading(`reconnect-${target}`);
    try {
      await fetch("/api/admin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: target === "all" ? "reconnect-mcp" : "reconnect-notion" }),
      });
      await load();
    } finally {
      setActionLoading(null);
    }
  }, [load]);

  const jobs = scheduler?.jobs ?? [];
  const servers = mcp?.servers ?? [];
  const connectedCount = servers.filter((s) => s.connected).length;

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-50/50"
      >
        <div className="flex items-center gap-2.5">
          <Plug className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">Integrations & Scheduler</h2>
          {servers.length > 0 && (
            <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em] ${
              connectedCount === servers.length ? "bg-emerald-50 text-emerald-600" : connectedCount > 0 ? "bg-amber-50 text-amber-600" : "bg-rose-50 text-rose-600"
            }`}>
              {connectedCount}/{servers.length} MCP
            </span>
          )}
          {jobs.length > 0 && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[9px] font-bold text-blue-600">
              {jobs.length} jobs
            </span>
          )}
        </div>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="border-t border-slate-100 px-5 pb-5 pt-4">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {/* Scheduler */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Calendar className="h-3.5 w-3.5 text-blue-500" />
                  <h3 className="text-xs font-bold text-slate-700">Scheduled Jobs</h3>
                </div>
                <div className="flex items-center gap-1.5">
                  {scheduler?.paused ? (
                    <button
                      onClick={() => handleSchedulerAction("resume")}
                      disabled={actionLoading !== null}
                      className="flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-700 transition-colors hover:bg-emerald-100"
                    >
                      {actionLoading === "resume" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                      Resume
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSchedulerAction("pause")}
                      disabled={actionLoading !== null}
                      className="flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-[10px] font-semibold text-amber-700 transition-colors hover:bg-amber-100"
                    >
                      {actionLoading === "pause" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Pause className="h-3 w-3" />}
                      Pause All
                    </button>
                  )}
                </div>
              </div>

              {jobs.length === 0 ? (
                <p className="text-[11px] text-slate-400">No scheduled jobs found</p>
              ) : (
                <div className="space-y-2">
                  {jobs.map((job) => (
                    <div key={job.id} className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2.5">
                      <div>
                        <p className="text-[11px] font-semibold text-slate-700">{job.name}</p>
                        <p className="text-[10px] text-slate-400">{job.trigger}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] font-medium text-slate-500">Next run</p>
                        <p className="text-[10px] font-semibold tabular-nums text-blue-600">
                          {job.next_run ? timeAgo(job.next_run).replace(" ago", "") : "--"}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* MCP Servers */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Server className="h-3.5 w-3.5 text-violet-500" />
                  <h3 className="text-xs font-bold text-slate-700">MCP Servers</h3>
                </div>
                <button
                  onClick={() => handleReconnect("all")}
                  disabled={actionLoading !== null}
                  className="flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600 transition-colors hover:bg-slate-200"
                >
                  {actionLoading === "reconnect-all" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                  Reconnect All
                </button>
              </div>

              {servers.length === 0 ? (
                <p className="text-[11px] text-slate-400">No MCP servers configured</p>
              ) : (
                <div className="space-y-2">
                  {servers.map((srv) => (
                    <div key={srv.name} className={`flex items-center justify-between rounded-lg border px-3 py-2.5 ${
                      srv.connected ? "border-emerald-100 bg-emerald-50/30" : "border-rose-100 bg-rose-50/30"
                    }`}>
                      <div className="flex items-center gap-2.5">
                        <StatusDot status={srv.connected ? "online" : "error"} />
                        <div>
                          <p className="text-[11px] font-semibold capitalize text-slate-700">{srv.name}</p>
                          {srv.tools_count != null && (
                            <p className="text-[10px] text-slate-400">{srv.tools_count} tools</p>
                          )}
                        </div>
                      </div>
                      {!srv.connected && (
                        <button
                          onClick={() => handleReconnect(srv.name === "notion" ? "notion" : "all")}
                          disabled={actionLoading !== null}
                          className="flex items-center gap-1 rounded-md bg-rose-100 px-2 py-1 text-[10px] font-semibold text-rose-700 transition-colors hover:bg-rose-200"
                        >
                          <RotateCcw className="h-3 w-3" />
                          Retry
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Activity Feed
   ═══════════════════════════════════════════════════════════════════════════ */

const AGENT_COLORS: Record<string, { dot: string; bg: string; text: string; border: string }> = {
  scout: { dot: "bg-blue-500", bg: "bg-blue-50", text: "text-blue-700", border: "border-l-blue-400" },
  analyst: { dot: "bg-violet-500", bg: "bg-violet-50", text: "text-violet-700", border: "border-l-violet-400" },
  drafter: { dot: "bg-emerald-500", bg: "bg-emerald-50", text: "text-emerald-700", border: "border-l-emerald-400" },
  notify_triage: { dot: "bg-amber-500", bg: "bg-amber-50", text: "text-amber-700", border: "border-l-amber-400" },
};

const TYPE_STYLES: Record<string, { dot: string; icon: typeof CheckCircle }> = {
  success: { dot: "bg-emerald-500", icon: CheckCircle },
  error: { dot: "bg-rose-500", icon: AlertCircle },
  warning: { dot: "bg-amber-500", icon: AlertTriangle },
  info: { dot: "bg-slate-400", icon: Activity },
};

function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  const [filter, setFilter] = useState<string>("all");

  const filtered = filter === "all" ? events : events.filter((e) => e.agent === filter);
  const agents = Array.from(new Set(events.map((e) => e.agent)));

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <Activity className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">Activity Feed</h2>
          <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em] text-emerald-600">
            <Radio className="h-2 w-2" />
            Live
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setFilter("all")}
            className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors ${
              filter === "all" ? "bg-slate-900 text-white" : "text-slate-400 hover:bg-slate-50 hover:text-slate-600"
            }`}
          >
            All
          </button>
          {agents.map((agent) => {
            const colors = AGENT_COLORS[agent] || { bg: "bg-slate-50", text: "text-slate-600" };
            return (
              <button
                key={agent}
                onClick={() => setFilter(agent)}
                className={`rounded-md px-2.5 py-1 text-[11px] font-semibold capitalize transition-colors ${
                  filter === agent ? `${colors.bg} ${colors.text}` : "text-slate-400 hover:bg-slate-50 hover:text-slate-600"
                }`}
              >
                {agent}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" style={{ maxHeight: "420px" }}>
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <Activity className="mb-2 h-5 w-5" />
            <span className="text-xs">Waiting for agent activity...</span>
          </div>
        ) : (
          <div className="divide-y divide-slate-50">
            {filtered.map((event) => {
              const typeStyle = TYPE_STYLES[event.type] || TYPE_STYLES.info;
              const agentColor = AGENT_COLORS[event.agent] || { dot: "bg-slate-400", bg: "bg-slate-50", text: "text-slate-600", border: "border-l-slate-300" };
              return (
                <div key={event._id} className={`group flex items-start gap-3 border-l-2 px-5 py-3 transition-colors hover:bg-slate-50/50 ${agentColor.border}`}>
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${typeStyle.dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] ${agentColor.bg} ${agentColor.text}`}>{event.agent}</span>
                      <span className="text-xs font-medium text-slate-700">{event.action}</span>
                    </div>
                    {event.details && <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{event.details}</p>}
                  </div>
                  <span className="shrink-0 text-[10px] tabular-nums text-slate-300 transition-colors group-hover:text-slate-500">
                    {event.created_at ? new Date(event.created_at).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" }) : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   API Health Panel
   ═══════════════════════════════════════════════════════════════════════════ */

const SERVICE_META: Record<string, { label: string; desc: string; iconColor: string; iconBg: string }> = {
  tavily: { label: "Tavily", desc: "Keyword search", iconColor: "text-blue-600", iconBg: "bg-blue-50" },
  exa: { label: "Exa", desc: "Semantic search", iconColor: "text-violet-600", iconBg: "bg-violet-50" },
  perplexity: { label: "Perplexity", desc: "Sonar research", iconColor: "text-cyan-600", iconBg: "bg-cyan-50" },
  jina: { label: "Jina", desc: "Page fetcher", iconColor: "text-amber-600", iconBg: "bg-amber-50" },
};

function formatCooldown(secs: number): string {
  if (secs <= 0) return "Recovering...";
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function APIHealthPanel({ data }: { data: APIHealthData | null }) {
  if (!data) return null;
  const services = Object.entries(data) as [string, ServiceHealth][];
  const exhaustedCount = services.filter(([, v]) => v.status === "exhausted").length;
  const allOk = exhaustedCount === 0;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Globe className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">API Health</h2>
          {allOk ? (
            <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em] text-emerald-600">
              <Wifi className="h-2.5 w-2.5" />All OK
            </span>
          ) : (
            <span className="flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.15em] text-rose-600">
              <WifiOff className="h-2.5 w-2.5" />{exhaustedCount} exhausted
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {services.map(([key, svc]) => {
          const meta = SERVICE_META[key] || { label: key, desc: "", iconColor: "text-slate-600", iconBg: "bg-slate-50" };
          const isExhausted = svc.status === "exhausted";
          const isUnknown = svc.status === "unknown";
          return (
            <div key={key} className={`group relative overflow-hidden rounded-xl border p-3.5 transition-all hover:-translate-y-0.5 hover:shadow-md ${
              isExhausted ? "border-rose-200 bg-rose-50/30" : isUnknown ? "border-slate-200 bg-slate-50/50" : "border-slate-200 bg-white"
            }`}>
              <div className={`absolute left-0 right-0 top-0 h-0.5 ${isExhausted ? "bg-rose-400" : isUnknown ? "bg-slate-300" : "bg-emerald-400"}`} />
              <div className="flex items-center gap-2.5">
                <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${isExhausted ? "bg-rose-100" : meta.iconBg}`}>
                  {isExhausted ? <WifiOff className="h-4 w-4 text-rose-500" /> : <Wifi className={`h-4 w-4 ${isUnknown ? "text-slate-400" : meta.iconColor}`} />}
                </div>
                <div>
                  <p className="text-xs font-bold text-slate-900">{meta.label}</p>
                  <p className="text-[10px] text-slate-400">{meta.desc}</p>
                </div>
              </div>
              <div className="mt-3">
                {isExhausted ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <StatusDot status="error" pulse />
                      <span className="text-[11px] font-semibold text-rose-600">Quota Exhausted</span>
                    </div>
                    {svc.cooldown_remaining_secs != null && (
                      <div className="flex items-center gap-1 text-[10px] text-rose-500">
                        <Timer className="h-2.5 w-2.5" />Retry in {formatCooldown(svc.cooldown_remaining_secs)}
                      </div>
                    )}
                  </div>
                ) : isUnknown ? (
                  <div className="flex items-center gap-1.5">
                    <StatusDot status="idle" />
                    <span className="text-[11px] font-medium text-slate-400">Unknown</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <StatusDot status="online" />
                    <span className="text-[11px] font-semibold text-emerald-600">Operational</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Recent Discoveries
   ═══════════════════════════════════════════════════════════════════════════ */

const THEME_COLORS: Record<string, { bg: string; text: string }> = {
  climatetech: { bg: "bg-teal-50", text: "text-teal-700" },
  agritech: { bg: "bg-lime-50", text: "text-lime-700" },
  ai_for_sciences: { bg: "bg-purple-50", text: "text-purple-700" },
  applied_earth_sciences: { bg: "bg-orange-50", text: "text-orange-700" },
  social_impact: { bg: "bg-pink-50", text: "text-pink-700" },
  deep_tech: { bg: "bg-indigo-50", text: "text-indigo-700" },
  deeptech: { bg: "bg-indigo-50", text: "text-indigo-700" },
};

const STATUS_BADGE: Record<string, { bg: string; text: string; border: string; label: string }> = {
  triage: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", label: "Triage" },
  pursue: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", label: "Pursue" },
  pursuing: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", label: "Pursuing" },
  hold: { bg: "bg-slate-50", text: "text-slate-600", border: "border-slate-200", label: "Hold" },
  passed: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", label: "Passed" },
  auto_pass: { bg: "bg-rose-50", text: "text-rose-500", border: "border-rose-200", label: "Auto-Pass" },
  drafting: { bg: "bg-purple-50", text: "text-purple-700", border: "border-purple-200", label: "Drafting" },
};

function DiscoveryCard({ grant }: { grant: Discovery }) {
  const badge = STATUS_BADGE[grant.status] || { bg: "bg-slate-50", text: "text-slate-500", border: "border-slate-200", label: grant.status };
  const score = grant.weighted_total;
  return (
    <div className="group relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md">
      {score != null && (
        <div className={`absolute left-0 right-0 top-0 h-0.5 ${score >= 7 ? "bg-emerald-500" : score >= 5 ? "bg-amber-500" : "bg-rose-400"}`} />
      )}
      <div className="flex items-start justify-between gap-2">
        <h4 className="line-clamp-2 text-xs font-semibold leading-relaxed text-slate-900">{grant.grant_name}</h4>
        <div className="flex shrink-0 items-center gap-1.5">
          {score != null && (
            <span className={`rounded-lg px-2 py-0.5 text-xs font-black tabular-nums ${score >= 7 ? "bg-emerald-50 text-emerald-700" : score >= 5 ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-700"}`}>
              {score.toFixed(1)}
            </span>
          )}
          {grant.url && (
            <a href={grant.url} target="_blank" rel="noopener noreferrer" className="opacity-0 transition-opacity group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
              <ExternalLink className="h-3 w-3 text-slate-400 hover:text-blue-500" />
            </a>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {grant.funder && <span className="text-[11px] font-medium text-slate-500">{grant.funder}</span>}
        {grant.funder && <span className="text-slate-200">·</span>}
        <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${badge.bg} ${badge.text} ${badge.border}`}>{badge.label}</span>
        {grant.max_funding_usd != null && grant.max_funding_usd > 0 && (
          <>
            <span className="text-slate-200">·</span>
            <span className="text-[10px] font-semibold text-slate-500">{formatMoney(grant.max_funding_usd)}</span>
          </>
        )}
      </div>
      <div className="mt-2.5 flex items-end justify-between">
        <div className="flex flex-wrap gap-1">
          {grant.themes_detected.slice(0, 2).map((t) => {
            const themeColor = THEME_COLORS[t] || { bg: "bg-slate-50", text: "text-slate-500" };
            return <span key={t} className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold ${themeColor.bg} ${themeColor.text}`}>{t.replace(/_/g, " ")}</span>;
          })}
        </div>
        <span className="text-[10px] tabular-nums text-slate-300">{timeAgo(grant.scored_at || grant.scraped_at)}</span>
      </div>
    </div>
  );
}

function RecentDiscoveries({ grants }: { grants: Discovery[] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-blue-500" />
          <h2 className="text-sm font-bold text-slate-900">Recent Discoveries</h2>
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-bold tabular-nums text-blue-700">{grants.length}</span>
        </div>
        {isHybridMode ? (
          <a
            href={NOTION_WORKSPACE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-[11px] font-semibold text-blue-600 transition-colors hover:text-blue-800"
          >
            View in Notion
            <ArrowRight className="h-3 w-3" />
          </a>
        ) : (
          <Link
            href="/pipeline?view=table&sort=scored_at"
            className="flex items-center gap-1 text-[11px] font-semibold text-blue-600 transition-colors hover:text-blue-800"
          >
            View all
            <ArrowRight className="h-3 w-3" />
          </Link>
        )}
      </div>
      {grants.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-400">
          <Search className="mb-2 h-5 w-5" />
          <span className="text-xs">No grants discovered yet. Run the Scout agent to start.</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {grants.slice(0, 8).map((g) => <DiscoveryCard key={g._id} grant={g} />)}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Scout Run History
   ═══════════════════════════════════════════════════════════════════════════ */

function ScoutHistory({ runs }: { runs: ScoutRun[] }) {
  const [expanded, setExpanded] = useState(false);
  if (runs.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between border-b border-slate-100 px-5 py-3.5 text-left transition-colors hover:bg-slate-50/50"
      >
        <div className="flex items-center gap-2.5">
          <Layers className="h-4 w-4 text-blue-500" />
          <h2 className="text-sm font-bold text-slate-900">Scout Run History</h2>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Last {runs.length} runs</span>
        </div>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80">
                {["When", "Tavily", "Exa", "Perplexity", "Direct", "Total Found", "New", "Rejected", "Dupes"].map((h, i) => (
                  <th key={h} className={`whitespace-nowrap py-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400 ${i === 0 ? "px-5 text-left" : "px-3 text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {runs.map((run) => (
                <tr key={run._id} className="transition-colors hover:bg-slate-50">
                  <td className="whitespace-nowrap px-5 py-3 font-medium text-slate-700">{formatDate(run.run_at)}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-600">{run.tavily_queries}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-600">{run.exa_queries}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-600">{run.perplexity_queries}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-600">{run.direct_sources_crawled}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums font-bold text-slate-900">{run.total_found.toLocaleString()}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right">
                    <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-black tabular-nums ${run.new_grants > 0 ? "bg-emerald-50 text-emerald-700" : "text-slate-400"}`}>{run.new_grants}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-amber-600">{run.quality_rejected}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-400">{run.content_dupes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Audit Log Panel (embedded)
   ═══════════════════════════════════════════════════════════════════════════ */

interface AuditEntry {
  _id: string;
  node?: string;
  event?: string;
  action?: string;
  created_at: string;
  [key: string]: unknown;
}

const AUDIT_AGENTS = [
  { value: "", label: "All Agents" },
  { value: "scout", label: "Scout" },
  { value: "analyst", label: "Analyst" },
  { value: "drafter", label: "Drafter" },
  { value: "knowledge_sync", label: "Knowledge Sync" },
  { value: "company_brain", label: "Company Brain" },
  { value: "grant_reader", label: "Grant Reader" },
] as const;

const AUDIT_AGENT_COLORS: Record<string, { dot: string; badge: string }> = {
  scout: { dot: "bg-blue-500", badge: "bg-blue-50 text-blue-700 ring-1 ring-blue-200" },
  analyst: { dot: "bg-purple-500", badge: "bg-purple-50 text-purple-700 ring-1 ring-purple-200" },
  drafter: { dot: "bg-green-500", badge: "bg-green-50 text-green-700 ring-1 ring-green-200" },
  knowledge_sync: { dot: "bg-amber-500", badge: "bg-amber-50 text-amber-700 ring-1 ring-amber-200" },
  company_brain: { dot: "bg-cyan-500", badge: "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200" },
  grant_reader: { dot: "bg-rose-500", badge: "bg-rose-50 text-rose-700 ring-1 ring-rose-200" },
};

const SKIP_KEYS = new Set(["_id", "node", "event", "action", "created_at", "__v"]);

function getAuditDetails(entry: AuditEntry): Record<string, unknown> | null {
  const details: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entry)) {
    if (SKIP_KEYS.has(k) || v === undefined || v === null) continue;
    details[k] = v;
  }
  return Object.keys(details).length > 0 ? details : null;
}

function AuditLogPanel() {
  const [expanded, setExpanded] = useState(false);
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [agentFilter, setAgentFilter] = useState("");
  const [timeRange, setTimeRange] = useState(7);
  const [search, setSearch] = useState("");
  const [sortAsc, setSortAsc] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (agentFilter) params.set("agent", agentFilter);
      if (timeRange > 0) params.set("days", String(timeRange));
      params.set("limit", "200");
      const res = await fetch(`/api/audit?${params}`);
      const data = await res.json();
      if (Array.isArray(data)) setLogs(data);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [agentFilter, timeRange]);

  useEffect(() => {
    if (expanded && !loaded.current) {
      loaded.current = true;
      load();
    }
  }, [expanded, load]);

  useEffect(() => {
    if (loaded.current) load();
  }, [agentFilter, timeRange, load]);

  const filtered = (() => {
    let result = logs;
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((e) =>
        [e.node, e.event, e.action, JSON.stringify(e)].filter(Boolean).join(" ").toLowerCase().includes(q)
      );
    }
    return [...result].sort((a, b) => {
      const ta = new Date(a.created_at).getTime();
      const tb = new Date(b.created_at).getTime();
      return sortAsc ? ta - tb : tb - ta;
    });
  })();

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-50/50"
      >
        <div className="flex items-center gap-2.5">
          <ScrollText className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">Audit Log</h2>
          {logs.length > 0 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold tabular-nums text-slate-500">
              {logs.length}
            </span>
          )}
        </div>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="border-t border-slate-100 px-5 pb-5 pt-4">
          {/* Filter bar */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
            <div className="flex items-center gap-2">
              <Bot className="h-3.5 w-3.5 text-slate-400" />
              <select
                value={agentFilter}
                onChange={(e) => setAgentFilter(e.target.value)}
                className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
              >
                {AUDIT_AGENTS.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              {[
                { value: 7, label: "7d" },
                { value: 30, label: "30d" },
                { value: 0, label: "All" },
              ].map((t) => (
                <button
                  key={t.value}
                  onClick={() => setTimeRange(t.value)}
                  className={`rounded-lg px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                    timeRange === t.value
                      ? "bg-slate-900 text-white"
                      : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="relative flex-1 sm:max-w-[200px]">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search logs..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-[11px] text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />
            </div>

            <div className="flex items-center gap-1.5 text-[10px] text-slate-400 sm:ml-auto">
              <Filter className="h-3 w-3" />
              {filtered.length} result{filtered.length !== 1 ? "s" : ""}
              {loading && <Loader2 className="ml-1 h-3 w-3 animate-spin" />}
            </div>
          </div>

          {/* Table */}
          {filtered.length === 0 ? (
            <div className="py-8 text-center text-[11px] text-slate-400">
              {loading ? "Loading audit logs..." : "No audit entries found"}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-100">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/80">
                    <th
                      className="cursor-pointer select-none whitespace-nowrap px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400 hover:text-slate-700"
                      onClick={() => setSortAsc((p) => !p)}
                    >
                      <span className="inline-flex items-center gap-1">
                        Timestamp
                        {sortAsc ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      </span>
                    </th>
                    <th className="whitespace-nowrap px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">Agent</th>
                    <th className="whitespace-nowrap px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">Action</th>
                    <th className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {filtered.slice(0, 50).map((entry, i) => {
                    const colors = AUDIT_AGENT_COLORS[entry.node ?? ""] || { dot: "bg-slate-400", badge: "bg-slate-50 text-slate-600 ring-1 ring-slate-200" };
                    const details = getAuditDetails(entry);
                    return (
                      <tr key={entry._id} className={`transition-colors hover:bg-blue-50/40 ${i % 2 === 1 ? "bg-slate-50/50" : ""}`}>
                        <td className="whitespace-nowrap px-4 py-2.5">
                          <div className="flex flex-col">
                            <span className="text-[11px] font-medium text-slate-700">{timeAgo(entry.created_at)}</span>
                            <span className="text-[10px] text-slate-400">{formatDate(entry.created_at)}</span>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5">
                          {entry.node ? (
                            <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${colors.badge}`}>
                              <span className={`inline-block h-1.5 w-1.5 rounded-full ${colors.dot}`} />
                              {(entry.node ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                            </span>
                          ) : (
                            <span className="text-[10px] text-slate-400">--</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          <span className="text-[11px] text-slate-700">{(entry.action as string) || (entry.event as string) || "log"}</span>
                        </td>
                        <td className="max-w-[300px] truncate px-4 py-2.5 text-[10px] text-slate-500">
                          {details
                            ? Object.entries(details).length <= 2
                              ? Object.entries(details).map(([k, v]) => `${k}: ${String(v)}`).join(" | ")
                              : `${Object.keys(details).length} fields`
                            : "--"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length > 50 && (
                <div className="border-t border-slate-100 px-4 py-2.5 text-center text-[10px] text-slate-400">
                  Showing 50 of {filtered.length} entries
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Agent Config Panel (embedded)
   ═══════════════════════════════════════════════════════════════════════════ */

const CONFIG_AGENTS = ["scout", "analyst", "drafter"] as const;
type ConfigAgentName = (typeof CONFIG_AGENTS)[number];

function ConfigPanel() {
  const [expanded, setExpanded] = useState(false);
  const [activeAgent, setActiveAgent] = useState<ConfigAgentName>("scout");
  const [drafts, setDrafts] = useState<Record<ConfigAgentName, string>>({
    scout: "",
    analyst: "",
    drafter: "",
  });
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"ok" | "error" | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/config");
      const configs = await res.json();
      const result = {} as Record<ConfigAgentName, string>;
      for (const a of CONFIG_AGENTS) {
        const cfg = configs[a] || { agent: a };
        const { _id, ...rest } = cfg as Record<string, unknown>;
        result[a] = JSON.stringify(rest, null, 2);
      }
      setDrafts(result);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (expanded && !loaded.current) {
      loaded.current = true;
      load();
    }
  }, [expanded, load]);

  function handleChange(value: string) {
    setDrafts((p) => ({ ...p, [activeAgent]: value }));
    setSaveResult(null);
    setParseError(null);
    try { JSON.parse(value); } catch { setParseError("Invalid JSON"); }
  }

  async function handleSave() {
    if (parseError) return;
    setSaving(true);
    setSaveResult(null);
    try {
      const config = JSON.parse(drafts[activeAgent]);
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: activeAgent, config }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaveResult("ok");
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-50/50"
      >
        <div className="flex items-center gap-2.5">
          <Settings className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">Agent Config</h2>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            Search themes, scoring weights, behaviour
          </span>
        </div>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="border-t border-slate-100 px-5 pb-5 pt-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          ) : (
            <>
              {/* Agent tabs */}
              <div className="mb-4 flex gap-2">
                {CONFIG_AGENTS.map((a) => (
                  <button
                    key={a}
                    onClick={() => { setActiveAgent(a); setSaveResult(null); setParseError(null); }}
                    className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold capitalize transition-colors ${
                      activeAgent === a
                        ? "border-blue-600 bg-blue-600 text-white"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {a}
                  </button>
                ))}
              </div>

              {/* Editor */}
              <textarea
                value={drafts[activeAgent]}
                onChange={(e) => handleChange(e.target.value)}
                rows={16}
                spellCheck={false}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
              />

              {parseError && (
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-rose-600">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {parseError}
                </div>
              )}

              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={handleSave}
                  disabled={!!parseError || saving}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-[11px] font-semibold transition-all ${
                    parseError
                      ? "cursor-not-allowed bg-slate-100 text-slate-400"
                      : "bg-slate-900 text-white shadow-sm hover:bg-slate-800"
                  }`}
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  Save {activeAgent} config
                </button>

                {saveResult === "ok" && (
                  <span className="flex items-center gap-1 text-[11px] text-emerald-600">
                    <CheckCircle className="h-3.5 w-3.5" /> Saved
                  </span>
                )}
                {saveResult === "error" && (
                  <span className="text-[11px] text-rose-600">Save failed</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Operations Panel (merged Toolkit — backfill, sync, reconnect, force-analyze)
   ═══════════════════════════════════════════════════════════════════════════ */

type OpsActionKey =
  | "force_analyst"
  | "sync_profile"
  | "notion_backfill"
  | "notion_backfill_views"
  | "reconnect_notion"
  | "notion_reverse_sync";

function OperationsPanel({
  notionMcp,
  onRefresh,
}: {
  notionMcp: NotionMcpStatus | null;
  onRefresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [actionLoading, setActionLoading] = useState<Record<OpsActionKey, boolean>>({
    force_analyst: false,
    sync_profile: false,
    notion_backfill: false,
    notion_backfill_views: false,
    reconnect_notion: false,
    notion_reverse_sync: false,
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runOp = useCallback(
    async (key: OpsActionKey, req: () => Promise<Response>, successMsg: string) => {
      setActionLoading((prev) => ({ ...prev, [key]: true }));
      setMessage(null);
      setError(null);
      try {
        const res = await req();
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || data?.detail || `Failed (${res.status})`);
        setMessage(successMsg);
        onRefresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActionLoading((prev) => ({ ...prev, [key]: false }));
      }
    },
    [onRefresh]
  );

  const notionConnected = notionMcp?.status === "connected";

  const OPS_ACTIONS: {
    key: OpsActionKey;
    title: string;
    subtitle: string;
    icon: React.ElementType;
    iconColor: string;
    run: () => void;
    accent?: string;
  }[] = [
    {
      key: "notion_reverse_sync",
      title: "Sync from Notion",
      subtitle: "Pull status & priority changes from Notion into dashboard",
      icon: RefreshCw,
      iconColor: "text-emerald-600",
      run: () =>
        runOp("notion_reverse_sync", () => fetch("/api/notion/reverse-sync", { method: "POST" }), "Reverse sync started — pulling changes from Notion."),
    },
    {
      key: "force_analyst",
      title: "Force Re-Analyze All",
      subtitle: "Re-score every grant regardless of state",
      icon: Zap,
      iconColor: "text-amber-600",
      run: () =>
        runOp("force_analyst", () => fetch("/api/run/analyst?force=true", { method: "POST" }), "Force analyst started."),
      accent: "border-amber-200",
    },
    {
      key: "sync_profile",
      title: "Sync Company Profile",
      subtitle: "Refresh AltCarbon profile from Notion",
      icon: Database,
      iconColor: "text-violet-600",
      run: () =>
        runOp("sync_profile", () => fetch("/api/run/sync-profile", { method: "POST" }), "Profile sync started."),
    },
    {
      key: "notion_backfill",
      title: "Backfill to Notion",
      subtitle: "Sync all scored grants to Notion pipeline",
      icon: ArrowUpRight,
      iconColor: "text-blue-600",
      run: () =>
        runOp(
          "notion_backfill",
          () =>
            fetch("/api/notion/backfill", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ setup_views: false }),
            }),
          "Notion backfill started."
        ),
    },
    {
      key: "notion_backfill_views",
      title: "Backfill + Setup Views",
      subtitle: "Backfill and create Notion board/table views",
      icon: Layers,
      iconColor: "text-indigo-600",
      run: () =>
        runOp(
          "notion_backfill_views",
          () =>
            fetch("/api/notion/backfill", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ setup_views: true }),
            }),
          "Backfill + views started."
        ),
    },
    {
      key: "reconnect_notion",
      title: "Reconnect Notion MCP",
      subtitle: notionConnected ? "MCP connected — reconnect if needed" : "MCP disconnected — reconnect now",
      icon: notionConnected ? Wifi : WifiOff,
      iconColor: notionConnected ? "text-emerald-600" : "text-rose-600",
      run: () =>
        runOp("reconnect_notion", () => fetch("/api/run/notion-mcp/reconnect", { method: "POST" }), "Notion MCP reconnected."),
      accent: notionConnected ? undefined : "border-rose-200",
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Toggle header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-50"
      >
        <div className="flex items-center gap-2.5">
          <Wrench className="h-4 w-4 text-slate-400" />
          <h2 className="text-sm font-bold text-slate-900">Operations</h2>
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            {OPS_ACTIONS.length} actions
          </span>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-slate-100 px-5 py-4">
          {/* Status messages */}
          {(message || error) && (
            <div
              className={`mb-4 rounded-lg border px-3 py-2 text-xs ${
                error
                  ? "border-rose-200 bg-rose-50 text-rose-700"
                  : "border-emerald-200 bg-emerald-50 text-emerald-700"
              }`}
            >
              <div className="flex items-center gap-2">
                {error ? <AlertTriangle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                <span>{error || message}</span>
              </div>
            </div>
          )}

          {/* Action grid */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {OPS_ACTIONS.map((action) => {
              const Icon = action.icon;
              const loading = actionLoading[action.key];
              return (
                <button
                  key={action.key}
                  onClick={action.run}
                  disabled={loading}
                  className={`rounded-xl border bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 ${
                    action.accent || "border-slate-200"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Icon className={`h-4 w-4 shrink-0 ${action.iconColor}`} />
                        <p className="text-xs font-semibold text-slate-900">{action.title}</p>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-400">{action.subtitle}</p>
                    </div>
                    {loading ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-slate-400" />
                    ) : (
                      <Rocket className="h-4 w-4 shrink-0 text-slate-300" />
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════════════ */

export default function MissionControl({
  initialActivity,
  initialDiscoveries,
  initialPipeline,
  initialScoutRuns,
}: MissionControlProps) {
  const [scout, setScout] = useState<AgentStatus | null>(null);
  const [analyst, setAnalyst] = useState<AgentStatus | null>(null);
  const [apiHealth, setApiHealth] = useState<APIHealthData | null>(null);
  const [notionMcp, setNotionMcp] = useState<NotionMcpStatus | null>(null);
  const [triggerLoading, setTriggerLoading] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>(initialActivity);
  const [discoveries, setDiscoveries] = useState<Discovery[]>(initialDiscoveries);
  const [pipeline, setPipeline] = useState<PipelineSummary>(initialPipeline);
  const [lastRefresh, setLastRefresh] = useState(Date.now());

  const poll = useCallback(async () => {
    try {
      const [s, a, act, disc, pipe, health, notion] = await Promise.all([
        fetch("/api/run/scout").then((r) => r.json()),
        fetch("/api/run/analyst").then((r) => r.json()),
        fetch("/api/activity").then((r) => r.json()),
        fetch("/api/discoveries").then((r) => r.json()),
        fetch("/api/pipeline-summary").then((r) => r.json()),
        fetch("/api/status/api-health").then((r) => r.json()).catch(() => null),
        fetch("/api/status/notion-mcp").then((r) => r.json()).catch(() => null),
      ]);
      setScout(s);
      setAnalyst(a);
      if (Array.isArray(act)) setActivity(act);
      if (Array.isArray(disc)) setDiscoveries(disc);
      if (pipe && typeof pipe.total_discovered === "number") setPipeline(pipe);
      if (health?.services) setApiHealth(health.services);
      if (notion) setNotionMcp(notion);
      setLastRefresh(Date.now());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [poll]);

  async function trigger(agent: AgentKey) {
    setTriggerLoading(agent);
    try {
      await fetch(`/api/run/${agent}`, { method: "POST" });
      await new Promise((r) => setTimeout(r, 1500));
      poll();
    } finally {
      setTriggerLoading(null);
    }
  }

  const anyAgentRunning = (scout?.running ?? false) || (analyst?.running ?? false);
  const apiExhaustedCount = apiHealth
    ? Object.values(apiHealth).filter((s) => s.status === "exhausted").length
    : 0;

  return (
    <div className="flex flex-col gap-5">
      <GlobalProgress active={anyAgentRunning} />

      <CommandHeader
        lastRefresh={lastRefresh}
        onRefresh={poll}
        scoutRunning={scout?.running ?? false}
        analystRunning={analyst?.running ?? false}
        apiExhaustedCount={apiExhaustedCount}
      />

      {/* Notion Pipeline Banner (hybrid mode) */}
      <NotionPipelineBanner pipeline={pipeline} notionMcp={notionMcp} />

      {/* KPI metrics */}
      <PipelineMetrics data={pipeline} />
      <AlertBadges data={pipeline} />

      {/* Operations panel (backfill, sync, force-analyze, reconnect) */}
      <OperationsPanel notionMcp={notionMcp} onRefresh={poll} />

      {/* Agent panels + Activity feed */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="flex flex-col gap-4 lg:col-span-5">
          <AgentPanel agentKey="scout" status={scout} triggerLoading={triggerLoading} onTrigger={trigger} />
          <AgentPanel agentKey="analyst" status={analyst} triggerLoading={triggerLoading} onTrigger={trigger} />
        </div>
        <div className="lg:col-span-7">
          <ActivityFeed events={activity} />
        </div>
      </div>

      {/* API Health */}
      <APIHealthPanel data={apiHealth} />

      {/* Toolkit — Quick Actions */}
      <ToolkitPanel />

      {/* Integrations & Scheduler (collapsible) */}
      <IntegrationsPanel />

      {/* Recent discoveries */}
      <RecentDiscoveries grants={discoveries} />

      {/* Scout run history (collapsible) */}
      <ScoutHistory runs={initialScoutRuns} />

      {/* Audit Log (collapsible) */}
      <AuditLogPanel />

      {/* Agent Config (collapsible) */}
      <ConfigPanel />
    </div>
  );
}
