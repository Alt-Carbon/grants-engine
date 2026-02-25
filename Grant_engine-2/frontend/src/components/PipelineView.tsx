"use client";

import { useState } from "react";
import { LayoutGrid, Table2, List } from "lucide-react";
import { PipelineBoard } from "./PipelineBoard";
import { PipelineTable } from "./PipelineTable";
import { PipelineList } from "./PipelineList";
import { ManualGrantEntry } from "./ManualGrantEntry";
import type { Grant } from "@/lib/queries";

interface PipelineViewProps {
  initialGrants: Record<string, Grant[]>;
}

export function PipelineView({ initialGrants }: PipelineViewProps) {
  const [view, setView] = useState<"kanban" | "table" | "list">("kanban");

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Top bar: manual entry + view toggle */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        {/* Manual grant entry — expands inline */}
        <div className="flex-1 min-w-[280px] max-w-xl">
          <ManualGrantEntry />
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
          <button
            onClick={() => setView("list")}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === "list"
                ? "bg-gray-900 text-white shadow-sm"
                : "text-gray-500 hover:text-gray-800"
            }`}
          >
            <List className="h-3.5 w-3.5" />
            List
          </button>
        </div>
      </div>

      {/* Active view */}
      <div className="flex-1 overflow-auto">
        {view === "kanban" ? (
          <PipelineBoard initialGrants={initialGrants} />
        ) : view === "table" ? (
          <PipelineTable initialGrants={initialGrants} />
        ) : (
          <PipelineList initialGrants={initialGrants} />
        )}
      </div>
    </div>
  );
}
