"use client";

import { useState, useMemo } from "react";
import { StatusPicker } from "./StatusPicker";
import { DeadlineChip } from "./DeadlineChip";
import { GrantDetailSheet } from "./GrantDetailSheet";
import type { Grant } from "@/lib/queries";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  ExternalLink,
} from "lucide-react";

interface PipelineTableProps {
  initialGrants: Record<string, Grant[]>;
  defaultFilter?: string;
}

type SortField =
  | "grant_name"
  | "weighted_total"
  | "max_funding_usd"
  | "days_to_deadline"
  | "funder";
type SortDir = "asc" | "desc";

const STATUS_TABS = [
  { id: "all", label: "All" },
  { id: "shortlisted", label: "Shortlisted" },
  { id: "pursue", label: "Pursue" },
  { id: "watch", label: "Watch" },
  { id: "drafting", label: "Drafting" },
  { id: "submitted", label: "Submitted" },
  { id: "rejected", label: "Rejected" },
] as const;

function ScoreCell({ score }: { score: number }) {
  const color =
    score >= 6.5
      ? "bg-green-100 text-green-800"
      : score >= 5.0
      ? "bg-amber-100 text-amber-800"
      : "bg-red-100 text-red-800";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ${color}`}
    >
      {score.toFixed(1)}
    </span>
  );
}

function SortIcon({
  field,
  sortField,
  sortDir,
}: {
  field: SortField;
  sortField: SortField;
  sortDir: SortDir;
}) {
  if (field !== sortField)
    return <ChevronsUpDown className="h-3.5 w-3.5 text-gray-300" />;
  return sortDir === "asc" ? (
    <ChevronUp className="h-3.5 w-3.5 text-gray-600" />
  ) : (
    <ChevronDown className="h-3.5 w-3.5 text-gray-600" />
  );
}

export function PipelineTable({
  initialGrants,
  defaultFilter = "shortlisted",
}: PipelineTableProps) {
  const [statusFilter, setStatusFilter] = useState<string>(defaultFilter);
  const [sortField, setSortField] = useState<SortField>("weighted_total");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedGrantId, setSelectedGrantId] = useState<string | null>(null);

  // Mutable grant list — flattened from initial prop, updated optimistically
  const [allGrants, setAllGrants] = useState<Grant[]>(() => {
    const flat: Grant[] = [];
    for (const col of Object.values(initialGrants)) flat.push(...col);
    return flat;
  });

  async function handleStatusChange(grantId: string, newStatus: string) {
    // Optimistic: update local state immediately
    setAllGrants((prev) =>
      prev.map((g) => (g._id === grantId ? { ...g, status: newStatus } : g))
    );
    // Persist to backend
    try {
      const res = await fetch("/api/grants/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: grantId, status: newStatus }),
      });
      if (!res.ok) {
        // Revert on failure
        setAllGrants((prev) => {
          const flat: Grant[] = [];
          for (const col of Object.values(initialGrants)) flat.push(...col);
          return flat;
        });
      }
    } catch {
      // Revert on error
      setAllGrants((prev) => {
        const flat: Grant[] = [];
        for (const col of Object.values(initialGrants)) flat.push(...col);
        return flat;
      });
    }
  }

  const filtered = useMemo(() => {
    if (statusFilter === "all") return allGrants;
    if (statusFilter === "shortlisted")
      return allGrants.filter((g) => g.status === "triage");
    if (statusFilter === "pursue")
      return allGrants.filter(
        (g) => g.status === "pursue" || g.status === "pursuing"
      );
    if (statusFilter === "submitted")
      return allGrants.filter((g) =>
        ["draft_complete", "submitted", "won"].includes(g.status)
      );
    if (statusFilter === "rejected")
      return allGrants.filter((g) =>
        ["passed", "auto_pass", "human_passed", "reported"].includes(g.status)
      );
    return allGrants.filter((g) => g.status === statusFilter);
  }, [allGrants, statusFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      let av: string | number | undefined;
      let bv: string | number | undefined;

      switch (sortField) {
        case "grant_name":
          av = a.grant_name || a.title || "";
          bv = b.grant_name || b.title || "";
          break;
        case "funder":
          av = a.funder || "";
          bv = b.funder || "";
          break;
        case "weighted_total":
          av = a.weighted_total ?? 0;
          bv = b.weighted_total ?? 0;
          break;
        case "max_funding_usd":
          av = a.max_funding_usd || a.max_funding || 0;
          bv = b.max_funding_usd || b.max_funding || 0;
          break;
        case "days_to_deadline":
          av = a.days_to_deadline ?? 9999;
          bv = b.days_to_deadline ?? 9999;
          break;
      }

      if (av === undefined || bv === undefined) return 0;
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc"
          ? av.localeCompare(bv)
          : bv.localeCompare(av);
      }
      return sortDir === "asc"
        ? (av as number) - (bv as number)
        : (bv as number) - (av as number);
    });
    return copy;
  }, [filtered, sortField, sortDir]);

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: allGrants.length };
    for (const g of allGrants) {
      const key =
        g.status === "triage"
          ? "shortlisted"
          : g.status === "pursuing"
          ? "pursue"
          : ["draft_complete", "submitted", "won"].includes(g.status)
          ? "submitted"
          : ["passed", "auto_pass", "human_passed", "reported"].includes(
              g.status
            )
          ? "rejected"
          : g.status;
      c[key] = (c[key] ?? 0) + 1;
    }
    return c;
  }, [allGrants]);

  function ThCol({
    field,
    label,
    className = "",
  }: {
    field: SortField;
    label: string;
    className?: string;
  }) {
    return (
      <th
        className={`cursor-pointer select-none whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 hover:text-gray-800 ${className}`}
        onClick={() => toggleSort(field)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          <SortIcon field={field} sortField={sortField} sortDir={sortDir} />
        </span>
      </th>
    );
  }

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

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
        {sorted.length === 0 ? (
          <div className="py-16 text-center text-sm text-gray-400">
            No grants in this view
          </div>
        ) : (
          <table className="w-full min-w-[800px] border-collapse text-sm">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="w-6 px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-gray-400">
                  #
                </th>
                <ThCol
                  field="grant_name"
                  label="Grant"
                  className="min-w-[220px]"
                />
                <ThCol field="funder" label="Funder" />
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <ThCol field="weighted_total" label="Score" />
                <ThCol field="max_funding_usd" label="Funding" />
                <ThCol field="days_to_deadline" label="Deadline" />
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                  Geography
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map((grant, i) => {
                const name = grant.grant_name || grant.title || "Unnamed";
                const funding = grant.max_funding_usd || grant.max_funding;

                return (
                  <tr
                    key={grant._id}
                    className="cursor-pointer transition-colors hover:bg-indigo-50/40"
                    onClick={() => setSelectedGrantId(grant._id)}
                  >
                    <td className="px-4 py-3 text-center text-xs text-gray-400">
                      {i + 1}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium text-gray-900 line-clamp-2 leading-snug">
                          {name}
                        </span>
                        {grant.grant_type && (
                          <span className="text-xs text-gray-400">
                            {grant.grant_type}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 max-w-[160px] truncate">
                      {grant.funder || "\u2014"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPicker
                        status={grant.status}
                        grantId={grant._id}
                        onStatusChange={handleStatusChange}
                        size="md"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <ScoreCell score={grant.weighted_total ?? 0} />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-700">
                      {funding
                        ? `$${(funding / 1000).toFixed(0)}K`
                        : "\u2014"}
                    </td>
                    <td className="px-4 py-3">
                      {grant.deadline_urgent ? (
                        <DeadlineChip
                          deadline={grant.deadline}
                          daysLeft={grant.days_to_deadline}
                        />
                      ) : grant.deadline ? (
                        <span className="text-xs text-gray-500">
                          {grant.deadline.slice(0, 10)}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">
                          {"\u2014"}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {grant.geography || "\u2014"}
                    </td>
                    <td className="px-4 py-3">
                      {grant.url && (
                        <a
                          href={grant.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50"
                        >
                          <ExternalLink className="h-3 w-3" />
                          Link
                        </a>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <p className="text-xs text-gray-400">
        {sorted.length} grant{sorted.length !== 1 ? "s" : ""}
        {statusFilter !== "all" &&
          ` \u00b7 ${counts.all ?? 0} total discovered`}
        {" \u00b7 "}click a row to view full details
      </p>

      <GrantDetailSheet
        grantId={selectedGrantId}
        onClose={() => setSelectedGrantId(null)}
      />
    </div>
  );
}
