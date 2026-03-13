"use client";

import { useState, useEffect } from "react";
import { useLastSeen } from "@/hooks/useLastSeen";
import Link from "next/link";
import { isHybridMode, NOTION_WORKSPACE_URL } from "@/lib/deployment";
import {
  Sparkles,
  Search,
  BarChart3,
  AlertTriangle,
  ArrowRight,
  X,
  Clock,
  TrendingUp,
  Inbox,
  AlertCircle,
} from "lucide-react";

interface DigestData {
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

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const hrs = Math.floor(diff / 3_600_000);
  if (hrs < 1) return "just now";
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function agentColor(agent: string): string {
  if (agent === "scout") return "text-blue-600";
  if (agent === "analyst") return "text-violet-600";
  if (agent === "drafter") return "text-emerald-600";
  return "text-amber-600";
}

export function WhatsNewDigest() {
  const { lastSeenAt, isReturningUser, daysSince } = useLastSeen();
  const [digest, setDigest] = useState<DigestData | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!lastSeenAt || !isReturningUser) return;

    setLoading(true);
    fetch(`/api/whats-new?since=${encodeURIComponent(lastSeenAt)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data && typeof data.newGrantsAdded === "number") {
          setDigest(data);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [lastSeenAt, isReturningUser]);

  // Don't show for first-time visitors or if dismissed
  if (!isReturningUser || dismissed) return null;

  // Loading state
  if (loading) {
    return (
      <div className="animate-pulse rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50 p-5">
        <div className="h-5 w-48 rounded bg-blue-200/50" />
        <div className="mt-2 h-4 w-72 rounded bg-blue-200/30" />
      </div>
    );
  }

  // No data or nothing happened
  if (!digest || (digest.newGrantsAdded === 0 && digest.scoutRuns === 0 && digest.grantsScored === 0)) {
    return null;
  }

  const hasActivity = digest.scoutRuns > 0 || digest.grantsScored > 0 || digest.newGrantsAdded > 0;

  return (
    <div className="relative overflow-hidden rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 via-indigo-50 to-violet-50 shadow-sm">
      {/* Dismiss button */}
      <button
        onClick={() => setDismissed(true)}
        className="absolute right-3 top-3 rounded-full p-1 text-gray-400 hover:bg-white/60 hover:text-gray-600 transition-colors"
      >
        <X className="h-4 w-4" />
      </button>

      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
            <Sparkles className="h-4 w-4 text-blue-600" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-gray-900">
              Welcome back! Here&apos;s what happened
            </h2>
            <p className="text-xs text-gray-500">
              In the last {daysSince} day{daysSince !== 1 ? "s" : ""} while you were away
            </p>
          </div>
        </div>

        {/* Summary stats */}
        {hasActivity && (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {digest.scoutRuns > 0 && (
              <div className="rounded-lg bg-white/70 px-3 py-2.5 ring-1 ring-blue-100">
                <div className="flex items-center gap-1.5">
                  <Search className="h-3.5 w-3.5 text-blue-500" />
                  <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">Scout</span>
                </div>
                <p className="mt-1 text-lg font-bold text-gray-900">{digest.scoutRuns} run{digest.scoutRuns !== 1 ? "s" : ""}</p>
                <p className="text-[11px] text-gray-500">
                  {digest.totalFound.toLocaleString()} scanned, {digest.newGrantsAdded} new
                </p>
              </div>
            )}

            {digest.grantsScored > 0 && (
              <div className="rounded-lg bg-white/70 px-3 py-2.5 ring-1 ring-violet-100">
                <div className="flex items-center gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5 text-violet-500" />
                  <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">Analyst</span>
                </div>
                <p className="mt-1 text-lg font-bold text-gray-900">{digest.grantsScored} scored</p>
                <p className="text-[11px] text-gray-500">Evaluated & ranked</p>
              </div>
            )}

            {digest.newInTriage > 0 && (
              <div className="rounded-lg bg-white/70 px-3 py-2.5 ring-1 ring-amber-100">
                <div className="flex items-center gap-1.5">
                  <Inbox className="h-3.5 w-3.5 text-amber-500" />
                  <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">Triage</span>
                </div>
                <p className="mt-1 text-lg font-bold text-amber-700">{digest.newInTriage} new</p>
                <p className="text-[11px] text-gray-500">Waiting for your review</p>
              </div>
            )}

            {digest.urgentDeadlines > 0 && (
              <div className="rounded-lg bg-white/70 px-3 py-2.5 ring-1 ring-red-100">
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
                  <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">Urgent</span>
                </div>
                <p className="mt-1 text-lg font-bold text-red-700">{digest.urgentDeadlines}</p>
                <p className="text-[11px] text-gray-500">Deadline ≤30 days</p>
              </div>
            )}
          </div>
        )}

        {/* Top new grants */}
        {digest.topNewGrants.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Top new grants discovered
            </h3>
            <div className="space-y-1.5">
              {digest.topNewGrants.slice(0, 3).map((g) => (
                <div
                  key={g._id}
                  className="flex items-center justify-between rounded-lg bg-white/70 px-3 py-2 ring-1 ring-gray-100"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-gray-900">{g.grant_name}</p>
                    <p className="text-[10px] text-gray-500">{g.funder}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    {g.weighted_total != null && (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-bold ${
                          g.weighted_total >= 7
                            ? "bg-green-100 text-green-700"
                            : g.weighted_total >= 5
                            ? "bg-amber-100 text-amber-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {g.weighted_total.toFixed(1)}
                      </span>
                    )}
                    <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                      NEW
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent agent activity */}
        {digest.recentAgentRuns.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Recent agent activity
            </h3>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {digest.recentAgentRuns.slice(0, 5).map((r, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[11px]">
                  <Clock className="h-3 w-3 text-gray-400" />
                  <span className={`font-semibold ${agentColor(r.agent)}`}>{r.agent}</span>
                  <span className="text-gray-600 truncate max-w-[200px]">{r.action}</span>
                  <span className="text-gray-400">{timeAgo(r.created_at)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Errors warning */}
        {digest.errors > 0 && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 ring-1 ring-red-200">
            <AlertCircle className="h-4 w-4 text-red-500 shrink-0" />
            <span className="text-xs text-red-700">
              {digest.errors} error{digest.errors !== 1 ? "s" : ""} occurred — check{" "}
              <Link href="/monitoring" className="underline font-medium">Mission Control</Link>
            </span>
          </div>
        )}

        {/* CTAs */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {digest.newInTriage > 0 && (
            isHybridMode ? (
              <a
                href={NOTION_WORKSPACE_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-blue-700 transition-colors"
              >
                Review {digest.newInTriage} new grant{digest.newInTriage !== 1 ? "s" : ""}
                <ArrowRight className="h-3.5 w-3.5" />
              </a>
            ) : (
              <Link
                href="/triage"
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-blue-700 transition-colors"
              >
                Review {digest.newInTriage} new grant{digest.newInTriage !== 1 ? "s" : ""}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )
          )}
          {isHybridMode ? (
            <a
              href={NOTION_WORKSPACE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-4 py-2 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
            >
              <TrendingUp className="h-3.5 w-3.5" />
              View in Notion
            </a>
          ) : (
            <Link
              href="/pipeline?view=table&sort=scored_at&filter=new"
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-4 py-2 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
            >
              <TrendingUp className="h-3.5 w-3.5" />
              View all new in pipeline
            </Link>
          )}
          <button
            onClick={() => setDismissed(true)}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
