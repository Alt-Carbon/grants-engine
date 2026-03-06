"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, Play, RefreshCw, Search, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";

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

export function LiveStatus() {
  const [scout, setScout] = useState<AgentStatus | null>(null);
  const [analyst, setAnalyst] = useState<AgentStatus | null>(null);
  const [triggerLoading, setTriggerLoading] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([
        fetch("/api/run/scout").then((r) => r.json()),
        fetch("/api/run/analyst").then((r) => r.json()),
      ]);
      setScout(s);
      setAnalyst(a);
    } catch {
      /* ignore polling errors */
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, [poll]);

  async function trigger(agent: "scout" | "analyst") {
    setTriggerLoading(agent);
    try {
      await fetch(`/api/run/${agent}`, { method: "POST" });
      await new Promise((r) => setTimeout(r, 1000));
      poll();
    } finally {
      setTriggerLoading(null);
    }
  }

  function elapsed(startedAt: string | null): string {
    if (!startedAt) return "";
    const sec = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {/* Scout Live */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 ring-1 ring-blue-200">
              <Search className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Scout Agent</h3>
              {scout?.running ? (
                <div className="mt-0.5 flex items-center gap-1.5">
                  <Loader2 className="h-3 w-3 animate-spin text-blue-600" />
                  <span className="text-xs font-medium text-blue-600">
                    Running{scout.started_at ? ` (${elapsed(scout.started_at)})` : ""}...
                  </span>
                </div>
              ) : (
                <p className="mt-0.5 text-xs text-gray-500">
                  {scout?.last_run_at
                    ? `Last: ${new Date(scout.last_run_at).toLocaleString()}`
                    : "Idle"}
                </p>
              )}
            </div>
          </div>
          <Button
            size="sm"
            variant={scout?.running ? "secondary" : "default"}
            disabled={scout?.running || triggerLoading === "scout"}
            onClick={() => trigger("scout")}
            loading={triggerLoading === "scout"}
          >
            <Play className="h-3.5 w-3.5" />
            {scout?.running ? "Running" : "Run Scout"}
          </Button>
        </div>
        {scout && !scout.running && (
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900">{scout.last_run_total_found ?? 0}</p>
              <p className="text-[10px] text-gray-500">Found</p>
            </div>
            <div className="rounded-lg bg-green-50 p-2">
              <p className="text-lg font-bold text-green-700">{scout.last_run_new_grants ?? 0}</p>
              <p className="text-[10px] text-gray-500">New</p>
            </div>
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900">{scout.total_runs ?? 0}</p>
              <p className="text-[10px] text-gray-500">Total Runs</p>
            </div>
          </div>
        )}
      </div>

      {/* Analyst Live */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50 ring-1 ring-violet-200">
              <BarChart3 className="h-5 w-5 text-violet-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Analyst Agent</h3>
              {analyst?.running ? (
                <div className="mt-0.5 flex items-center gap-1.5">
                  <Loader2 className="h-3 w-3 animate-spin text-violet-600" />
                  <span className="text-xs font-medium text-violet-600">
                    Scoring{analyst.started_at ? ` (${elapsed(analyst.started_at)})` : ""}...
                  </span>
                </div>
              ) : (
                <p className="mt-0.5 text-xs text-gray-500">
                  {analyst?.last_run_at
                    ? `Last: ${new Date(analyst.last_run_at).toLocaleString()}`
                    : "Idle"}
                </p>
              )}
            </div>
          </div>
          <Button
            size="sm"
            variant={analyst?.running ? "secondary" : "default"}
            disabled={analyst?.running || triggerLoading === "analyst"}
            onClick={() => trigger("analyst")}
            loading={triggerLoading === "analyst"}
          >
            <Play className="h-3.5 w-3.5" />
            {analyst?.running ? "Scoring" : "Run Analyst"}
          </Button>
        </div>
        {analyst && !analyst.running && (
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900">{analyst.last_run_scored ?? 0}</p>
              <p className="text-[10px] text-gray-500">Scored</p>
            </div>
            <div className="rounded-lg bg-amber-50 p-2">
              <p className="text-lg font-bold text-amber-700">{analyst.pending_unprocessed ?? 0}</p>
              <p className="text-[10px] text-gray-500">Pending</p>
            </div>
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900">
                {analyst.last_run_at ? new Date(analyst.last_run_at).toLocaleDateString() : "--"}
              </p>
              <p className="text-[10px] text-gray-500">Last Run</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function AutoRefresh() {
  const [countdown, setCountdown] = useState(30);

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          window.location.reload();
          return 30;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <button
      onClick={() => window.location.reload()}
      className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-500 shadow-sm hover:bg-gray-50"
    >
      <RefreshCw className="h-3 w-3" />
      Refreshing in {countdown}s
    </button>
  );
}
