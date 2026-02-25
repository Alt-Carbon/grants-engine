"use client";

import { useState, useMemo } from "react";
import { StatusBadge } from "./StatusBadge";
import { DeadlineChip } from "./DeadlineChip";
import { GrantDetailSheet } from "./GrantDetailSheet";
import type { Grant } from "@/lib/queries";
import {
  ChevronDown,
  ChevronUp,
  Globe,
  DollarSign,
  Tag,
  ExternalLink,
  MoveRight,
} from "lucide-react";

interface PipelineListProps {
  initialGrants: Record<string, Grant[]>;
}

const STATUS_TABS = [
  { id: "all",      label: "All" },
  { id: "triage",   label: "Triage" },
  { id: "pursue",   label: "Pursue" },
  { id: "watch",    label: "Watch" },
  { id: "drafting", label: "Drafting" },
  { id: "complete", label: "Complete" },
  { id: "passed",   label: "Auto-passed" },
] as const;

const MOVE_OPTIONS = [
  { value: "triage",         label: "Triage" },
  { value: "pursue",         label: "Pursue" },
  { value: "watch",          label: "Watch" },
  { value: "passed",         label: "Pass" },
  { value: "drafting",       label: "Drafting" },
  { value: "draft_complete", label: "Draft Complete" },
  { value: "submitted",      label: "Submitted" },
];

async function moveGrant(grantId: string, status: string) {
  await fetch("/api/grants/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grant_id: grantId, status }),
  });
}

function ScorePill({ score }: { score: number }) {
  const color =
    score >= 6.5
      ? "bg-green-100 text-green-800"
      : score >= 5.0
      ? "bg-amber-100 text-amber-800"
      : "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ${color}`}>
      {score.toFixed(1)}
    </span>
  );
}

function GrantListCard({
  grant,
  onClick,
}: {
  grant: Grant;
  onClick: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [moving, setMoving] = useState(false);

  const name = grant.grant_name || grant.title || "Unnamed";
  const funding = grant.max_funding_usd || grant.max_funding;

  async function handleMove(e: React.ChangeEvent<HTMLSelectElement>) {
    const newStatus = e.target.value;
    if (!newStatus) return;
    setMoving(true);
    await moveGrant(grant._id, newStatus);
    // Optimistic: page will revalidate on next visit
    setMoving(false);
    e.target.value = "";
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm transition hover:border-indigo-200 hover:shadow-md">
      {/* Main row */}
      <div
        className="flex cursor-pointer items-start gap-3 px-4 py-3"
        onClick={onClick}
      >
        {/* Score */}
        <div className="shrink-0 pt-0.5">
          <ScorePill score={grant.weighted_total ?? 0} />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-gray-900 leading-snug line-clamp-1">
              {name}
            </span>
            <StatusBadge status={grant.status} />
            {grant.deadline_urgent && (
              <DeadlineChip
                deadline={grant.deadline}
                daysLeft={grant.days_to_deadline}
              />
            )}
          </div>

          {/* Meta row */}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
            {grant.funder && (
              <span className="font-medium text-gray-600">{grant.funder}</span>
            )}
            {grant.geography && (
              <span className="flex items-center gap-0.5">
                <Globe className="h-3 w-3" />
                {grant.geography}
              </span>
            )}
            {funding && (
              <span className="flex items-center gap-0.5">
                <DollarSign className="h-3 w-3" />
                {`$${(funding / 1000).toFixed(0)}K`}
              </span>
            )}
            {grant.grant_type && (
              <span className="flex items-center gap-0.5">
                <Tag className="h-3 w-3" />
                {grant.grant_type}
              </span>
            )}
            {!grant.deadline_urgent && grant.deadline && (
              <span className="text-gray-400">{grant.deadline.slice(0, 10)}</span>
            )}
          </div>
        </div>

        {/* Chevron */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((o) => !o);
          }}
          className="shrink-0 rounded p-1 text-gray-300 hover:text-gray-500"
        >
          {expanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          className="border-t border-gray-100 px-4 pb-3 pt-2"
          onClick={(e) => e.stopPropagation()}
        >
          {grant.rationale && (
            <p className="mb-2 text-xs leading-relaxed text-gray-600 line-clamp-4">
              {grant.rationale}
            </p>
          )}
          {grant.themes_detected && grant.themes_detected.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {grant.themes_detected.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                >
                  {t.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            {grant.url && (
              <a
                href={grant.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                Open grant page
              </a>
            )}
            {/* Move to */}
            <div className="ml-auto flex items-center gap-1.5">
              <MoveRight className="h-3.5 w-3.5 text-gray-400" />
              <select
                defaultValue=""
                disabled={moving}
                onChange={handleMove}
                className="rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 shadow-sm focus:border-indigo-400 focus:outline-none"
              >
                <option value="" disabled>
                  Move to…
                </option>
                {MOVE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function PipelineList({ initialGrants }: PipelineListProps) {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedGrantId, setSelectedGrantId] = useState<string | null>(null);

  const allGrants = useMemo(() => {
    const flat: Grant[] = [];
    for (const col of Object.values(initialGrants)) flat.push(...col);
    return flat;
  }, [initialGrants]);

  const filtered = useMemo(() => {
    if (statusFilter === "all") return allGrants;
    if (statusFilter === "pursue")
      return allGrants.filter((g) => g.status === "pursue" || g.status === "pursuing");
    if (statusFilter === "complete")
      return allGrants.filter((g) =>
        ["draft_complete", "submitted", "won"].includes(g.status)
      );
    if (statusFilter === "passed")
      return allGrants.filter((g) =>
        ["passed", "auto_pass", "reported"].includes(g.status)
      );
    return allGrants.filter((g) => g.status === statusFilter);
  }, [allGrants, statusFilter]);

  // Sort by score descending
  const sorted = useMemo(
    () => [...filtered].sort((a, b) => (b.weighted_total ?? 0) - (a.weighted_total ?? 0)),
    [filtered]
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: allGrants.length };
    for (const g of allGrants) {
      const key =
        g.status === "pursuing"
          ? "pursue"
          : ["draft_complete", "submitted", "won"].includes(g.status)
          ? "complete"
          : ["passed", "auto_pass", "reported"].includes(g.status)
          ? "passed"
          : g.status;
      c[key] = (c[key] ?? 0) + 1;
    }
    return c;
  }, [allGrants]);

  return (
    <div className="flex flex-col gap-4">
      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setStatusFilter(tab.id)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              statusFilter === tab.id
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {tab.label}
            {counts[tab.id] !== undefined && (
              <span className="ml-1.5 opacity-70">{counts[tab.id]}</span>
            )}
          </button>
        ))}
      </div>

      {/* List */}
      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No grants in this view
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sorted.map((grant) => (
            <GrantListCard
              key={grant._id}
              grant={grant}
              onClick={() => setSelectedGrantId(grant._id)}
            />
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400">
        {sorted.length} grant{sorted.length !== 1 ? "s" : ""}
        {statusFilter !== "all" && ` · ${counts.all ?? 0} total discovered`}
        {" · "}click a card to view full details
      </p>

      <GrantDetailSheet
        grantId={selectedGrantId}
        onClose={() => setSelectedGrantId(null)}
      />
    </div>
  );
}
