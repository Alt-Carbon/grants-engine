"use client";

import { useState, useEffect, useCallback } from "react";
import { Telescope, Brain, Loader2, CheckCircle, AlertCircle } from "lucide-react";

interface ScoutStatus {
  running: boolean;
  started_at: string | null;
  last_run_at: string | null;
  last_run_new_grants: number;
  last_run_total_found: number;
  total_runs: number;
}

interface AnalystStatus {
  running: boolean;
  started_at: string | null;
  last_run_at: string | null;
  last_run_scored: number;
  pending_unprocessed: number;
}

type JobState = "idle" | "running" | "done" | "error";

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function AgentButton({
  label,
  icon: Icon,
  description,
  state,
  meta,
  badge,
  onClick,
}: {
  label: string;
  icon: React.ElementType;
  description: string;
  state: JobState;
  meta: string;
  badge?: string;
  onClick: () => void;
}) {
  const isRunning = state === "running";

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <Icon className="h-3.5 w-3.5 text-gray-400 shrink-0" />
            <span className="text-xs font-medium text-gray-200">{label}</span>
            {badge && (
              <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 leading-none">
                {badge}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[10px] text-gray-500 leading-snug">{description}</p>
          <p className="mt-1 text-[10px] text-gray-600">{meta}</p>
        </div>

        <button
          onClick={onClick}
          disabled={isRunning}
          className={`shrink-0 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
            isRunning
              ? "bg-gray-700 text-gray-500 cursor-not-allowed"
              : state === "done"
              ? "bg-green-700/50 text-green-300 hover:bg-green-700"
              : state === "error"
              ? "bg-red-700/50 text-red-300 hover:bg-red-700"
              : "bg-indigo-600 text-white hover:bg-indigo-500"
          }`}
        >
          {isRunning ? (
            <span className="flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              Running
            </span>
          ) : state === "done" ? (
            <span className="flex items-center gap-1">
              <CheckCircle className="h-3 w-3" />
              Done
            </span>
          ) : state === "error" ? (
            <span className="flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />
              Retry
            </span>
          ) : (
            "Run"
          )}
        </button>
      </div>

      {/* Running progress bar */}
      {isRunning && (
        <div className="mt-2 h-0.5 w-full overflow-hidden rounded-full bg-gray-700">
          <div className="h-full animate-[progress_2s_ease-in-out_infinite] bg-indigo-500 rounded-full" />
        </div>
      )}
    </div>
  );
}

export function AgentControls() {
  const [scoutState, setScoutState] = useState<JobState>("idle");
  const [analystState, setAnalystState] = useState<JobState>("idle");
  const [scoutStatus, setScoutStatus] = useState<ScoutStatus | null>(null);
  const [analystStatus, setAnalystStatus] = useState<AnalystStatus | null>(null);

  // Poll status every 5s while a job is running, else every 30s
  const pollInterval = scoutState === "running" || analystState === "running" ? 5_000 : 30_000;

  const fetchStatus = useCallback(async () => {
    try {
      const [sr, ar] = await Promise.all([
        fetch("/api/run/scout", { cache: "no-store" }),
        fetch("/api/run/analyst", { cache: "no-store" }),
      ]);
      if (sr.ok) {
        const s: ScoutStatus = await sr.json();
        setScoutStatus(s);
        if (s.running) setScoutState("running");
        else if (scoutState === "running") setScoutState("done");
      }
      if (ar.ok) {
        const a: AnalystStatus = await ar.json();
        setAnalystStatus(a);
        if (a.running) setAnalystState("running");
        else if (analystState === "running") setAnalystState("done");
      }
    } catch {
      // ignore poll errors
    }
  }, [scoutState, analystState]);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(id);
  }, [fetchStatus, pollInterval]);

  async function runScout() {
    setScoutState("running");
    try {
      const res = await fetch("/api/run/scout", { method: "POST", cache: "no-store" });
      if (!res.ok) {
        const d = await res.json();
        if (d.status === "scout_already_running") {
          setScoutState("running");
        } else {
          setScoutState("error");
        }
      }
    } catch {
      setScoutState("error");
    }
  }

  async function runAnalyst() {
    setAnalystState("running");
    try {
      const res = await fetch("/api/run/analyst", { method: "POST", cache: "no-store" });
      if (!res.ok) {
        const d = await res.json();
        if (d.status === "analyst_already_running") {
          setAnalystState("running");
        } else {
          setAnalystState("error");
        }
      }
    } catch {
      setAnalystState("error");
    }
  }

  const scoutMeta = scoutStatus
    ? `Last: ${timeAgo(scoutStatus.last_run_at)} · ${scoutStatus.last_run_new_grants} new`
    : "Not run yet";

  const analystMeta = analystStatus
    ? `Last: ${timeAgo(analystStatus.last_run_at)} · ${analystStatus.last_run_scored} scored`
    : "Not run yet";

  const pendingBadge =
    analystStatus?.pending_unprocessed && analystStatus.pending_unprocessed > 0
      ? String(analystStatus.pending_unprocessed)
      : undefined;

  return (
    <div className="flex flex-col gap-2 px-3 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-600">
        Run Agents
      </p>
      <AgentButton
        label="Scout"
        icon={Telescope}
        description="Discover new grants via Tavily, Exa & Perplexity"
        state={scoutState}
        meta={scoutMeta}
        onClick={runScout}
      />
      <AgentButton
        label="Analyst"
        icon={Brain}
        description="Score & triage unprocessed grants"
        state={analystState}
        meta={analystMeta}
        badge={pendingBadge}
        onClick={runAnalyst}
      />
    </div>
  );
}
