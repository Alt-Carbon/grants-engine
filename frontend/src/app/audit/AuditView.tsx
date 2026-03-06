"use client";

import { useMemo, useState } from "react";
import {
  FileText,
  Filter,
  Clock,
  Bot,
  Search,
  ChevronUp,
  ChevronDown,
} from "lucide-react";
import type { AuditEntry } from "@/lib/queries";

// ── Agent config ────────────────────────────────────────────────────────────

const AGENTS = [
  { value: "", label: "All Agents" },
  { value: "scout", label: "Scout" },
  { value: "analyst", label: "Analyst" },
  { value: "drafter", label: "Drafter" },
  { value: "knowledge_sync", label: "Knowledge Sync" },
] as const;

const TIME_RANGES = [
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: 0, label: "All" },
] as const;

const AGENT_COLORS: Record<string, { dot: string; badge: string }> = {
  scout: {
    dot: "bg-blue-500",
    badge: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  },
  analyst: {
    dot: "bg-purple-500",
    badge: "bg-purple-50 text-purple-700 ring-1 ring-purple-200",
  },
  drafter: {
    dot: "bg-green-500",
    badge: "bg-green-50 text-green-700 ring-1 ring-green-200",
  },
  knowledge_sync: {
    dot: "bg-amber-500",
    badge: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  },
  company_brain: {
    dot: "bg-cyan-500",
    badge: "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200",
  },
  grant_reader: {
    dot: "bg-rose-500",
    badge: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  },
};

const DEFAULT_AGENT_COLOR = {
  dot: "bg-gray-400",
  badge: "bg-gray-50 text-gray-600 ring-1 ring-gray-200",
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function agentColor(node: string) {
  return AGENT_COLORS[node] ?? DEFAULT_AGENT_COLOR;
}

function agentLabel(node: string) {
  return node.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function relativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (isNaN(then)) return iso;

  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;

  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: diffDay > 365 ? "numeric" : undefined,
  });
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** Extract a human-readable action string from an audit entry. */
function getAction(entry: AuditEntry): string {
  return (entry.action as string) || (entry.event as string) || "log";
}

/** Build a details object from extra fields, excluding known top-level keys. */
const SKIP_KEYS = new Set([
  "_id",
  "node",
  "event",
  "action",
  "created_at",
  "__v",
]);

function getDetails(entry: AuditEntry): Record<string, unknown> | null {
  const details: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entry)) {
    if (SKIP_KEYS.has(k)) continue;
    if (v === undefined || v === null) continue;
    details[k] = v;
  }
  return Object.keys(details).length > 0 ? details : null;
}

function DetailsCell({ details }: { details: Record<string, unknown> | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!details) {
    return <span className="text-gray-400">&mdash;</span>;
  }

  const entries = Object.entries(details);
  // If simple (1-2 scalar fields), render inline
  if (
    entries.length <= 2 &&
    entries.every(([, v]) => typeof v !== "object")
  ) {
    return (
      <span className="text-xs text-gray-600">
        {entries.map(([k, v]) => `${k}: ${String(v)}`).join(" | ")}
      </span>
    );
  }

  // Complex: render as collapsible JSON
  return (
    <div>
      <button
        onClick={() => setExpanded((e) => !e)}
        className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-200 transition-colors"
      >
        <FileText className="h-3 w-3" />
        {entries.length} field{entries.length !== 1 ? "s" : ""}
        {expanded ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
      </button>
      {expanded && (
        <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-gray-50 p-3 text-[11px] leading-relaxed text-gray-700 border border-gray-100">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export function AuditView({ logs }: { logs: AuditEntry[] }) {
  const [agentFilter, setAgentFilter] = useState("");
  const [timeRange, setTimeRange] = useState(0); // 0 = all
  const [search, setSearch] = useState("");
  const [sortAsc, setSortAsc] = useState(false);

  const filtered = useMemo(() => {
    let result = logs;

    // Agent filter
    if (agentFilter) {
      result = result.filter((e) => e.node === agentFilter);
    }

    // Time range filter
    if (timeRange > 0) {
      const since = Date.now() - timeRange * 24 * 60 * 60 * 1000;
      result = result.filter(
        (e) => new Date(e.created_at).getTime() >= since
      );
    }

    // Search
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((e) => {
        const haystack = [
          e.node,
          e.event,
          e.action,
          JSON.stringify(e),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      });
    }

    // Sort
    result = [...result].sort((a, b) => {
      const ta = new Date(a.created_at).getTime();
      const tb = new Date(b.created_at).getTime();
      return sortAsc ? ta - tb : tb - ta;
    });

    return result;
  }, [logs, agentFilter, timeRange, search, sortAsc]);

  return (
    <div className="flex flex-col gap-4 p-4 sm:gap-6 sm:p-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">
          Audit Log
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          {filtered.length} event{filtered.length !== 1 ? "s" : ""} recorded
          across all agents
        </p>
      </div>

      {/* Filter bar */}
      <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-sm sm:p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
          {/* Agent filter */}
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 shrink-0 text-gray-400" />
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-700 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
            >
              {AGENTS.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>

          {/* Time range pills */}
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 shrink-0 text-gray-400" />
            <div className="flex gap-1">
              {TIME_RANGES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setTimeRange(t.value)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    timeRange === t.value
                      ? "bg-gray-900 text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* Search */}
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search logs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 pl-9 pr-3 text-sm text-gray-700 placeholder:text-gray-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>

          {/* Result count */}
          <div className="flex items-center gap-1.5 text-xs text-gray-400 sm:ml-auto">
            <Filter className="h-3.5 w-3.5" />
            {filtered.length} result{filtered.length !== 1 ? "s" : ""}
          </div>
        </div>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-gray-400">
          <FileText className="mx-auto h-10 w-10 text-gray-300" />
          <p className="mt-3 text-lg font-medium">No audit entries found</p>
          <p className="mt-1 text-sm">
            Try adjusting your filters or time range
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  <th
                    className="cursor-pointer select-none whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500 hover:text-gray-900"
                    onClick={() => setSortAsc((p) => !p)}
                  >
                    <span className="inline-flex items-center gap-1">
                      Timestamp
                      {sortAsc ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </span>
                  </th>
                  <th className="whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Agent
                  </th>
                  <th className="whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Action
                  </th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((entry, i) => {
                  const colors = agentColor(entry.node ?? "unknown");
                  const details = getDetails(entry);
                  return (
                    <tr
                      key={entry._id}
                      className={`transition-colors hover:bg-blue-50/40 ${
                        i % 2 === 1 ? "bg-gray-50/50" : "bg-white"
                      }`}
                    >
                      {/* Timestamp */}
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex flex-col">
                          <span className="text-sm font-medium text-gray-900">
                            {relativeTime(entry.created_at)}
                          </span>
                          <span className="text-[11px] text-gray-400">
                            {formatTimestamp(entry.created_at)}
                          </span>
                        </div>
                      </td>
                      {/* Agent */}
                      <td className="whitespace-nowrap px-4 py-3">
                        {entry.node ? (
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${colors.badge}`}
                          >
                            <span
                              className={`inline-block h-1.5 w-1.5 rounded-full ${colors.dot}`}
                            />
                            {agentLabel(entry.node)}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">--</span>
                        )}
                      </td>
                      {/* Action */}
                      <td className="px-4 py-3">
                        <span className="text-sm text-gray-700">
                          {getAction(entry)}
                        </span>
                      </td>
                      {/* Details */}
                      <td className="px-4 py-3">
                        <DetailsCell details={details} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
