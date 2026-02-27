"use client";

import { useState } from "react";
import { LayoutGrid, Table2, Search, X } from "lucide-react";
import { PipelineBoard } from "./PipelineBoard";
import { PipelineTable } from "./PipelineTable";
import { ManualGrantEntry } from "./ManualGrantEntry";
import type { Grant } from "@/lib/queries";

interface PipelineViewProps {
  initialGrants: Record<string, Grant[]>;
}

/** Filter a grouped grant map by search query (name, funder, geography) */
function filterGrants(
  grouped: Record<string, Grant[]>,
  query: string
): Record<string, Grant[]> {
  if (!query.trim()) return grouped;
  const q = query.toLowerCase();
  const result: Record<string, Grant[]> = {};
  for (const [key, grants] of Object.entries(grouped)) {
    result[key] = grants.filter((g) => {
      const name = (g.grant_name || g.title || "").toLowerCase();
      const funder = (g.funder || "").toLowerCase();
      const geo = (g.geography || "").toLowerCase();
      const type = (g.grant_type || "").toLowerCase();
      return (
        name.includes(q) ||
        funder.includes(q) ||
        geo.includes(q) ||
        type.includes(q)
      );
    });
  }
  return result;
}

export function PipelineView({ initialGrants }: PipelineViewProps) {
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [search, setSearch] = useState("");

  const filteredGrants = filterGrants(initialGrants, search);

  const totalFiltered = Object.values(filteredGrants).reduce(
    (sum, arr) => sum + arr.length,
    0
  );
  const totalAll = Object.values(initialGrants).reduce(
    (sum, arr) => sum + arr.length,
    0
  );

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Top bar */}
      <div className="flex flex-wrap items-start gap-3">
        {/* Manual grant entry */}
        <div className="min-w-[240px] max-w-xl flex-1">
          <ManualGrantEntry />
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search grants..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-8 text-sm shadow-sm outline-none placeholder:text-gray-400 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-600"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* View toggle */}
        <div className="flex shrink-0 items-center gap-1 rounded-lg border border-gray-200 bg-white p-1 shadow-sm">
          <button
            onClick={() => setView("kanban")}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === "kanban"
                ? "bg-gray-900 text-white shadow-sm"
                : "text-gray-500 hover:text-gray-800"
            }`}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
            Kanban
          </button>
          <button
            onClick={() => setView("table")}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === "table"
                ? "bg-gray-900 text-white shadow-sm"
                : "text-gray-500 hover:text-gray-800"
            }`}
          >
            <Table2 className="h-3.5 w-3.5" />
            Table
          </button>
        </div>
      </div>

      {/* Search indicator */}
      {search && (
        <p className="text-xs text-gray-500">
          Showing {totalFiltered} of {totalAll} grants matching &ldquo;
          {search}&rdquo;
        </p>
      )}

      {/* Active view */}
      <div className="flex-1 overflow-auto">
        {view === "kanban" ? (
          <PipelineBoard initialGrants={filteredGrants} />
        ) : (
          <PipelineTable initialGrants={filteredGrants} />
        )}
      </div>
    </div>
  );
}
