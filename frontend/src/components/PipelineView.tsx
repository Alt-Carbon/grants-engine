"use client";

import { useState, useMemo, useCallback } from "react";
import {
  LayoutGrid,
  Table2,
  Search,
  X,
  SlidersHorizontal,
  ChevronDown,
} from "lucide-react";
import { PipelineBoard } from "./PipelineBoard";
import { PipelineTable } from "./PipelineTable";
import { ManualGrantEntry } from "./ManualGrantEntry";
import { THEME_CONFIG } from "@/lib/utils";
import type { Grant } from "@/lib/queries";

/* ─── Filter types ──────────────────────────────────────────────────────── */

export interface PipelineFilters {
  search: string;
  themes: string[];
  scoreRange: "all" | "high" | "medium" | "low";
  deadline: "all" | "urgent" | "has_deadline" | "no_deadline";
  funding: "all" | "50k" | "100k" | "500k" | "1m";
  geography: string;
}

const DEFAULT_FILTERS: PipelineFilters = {
  search: "",
  themes: [],
  scoreRange: "all",
  deadline: "all",
  funding: "all",
  geography: "",
};

const SCORE_OPTIONS = [
  { id: "all", label: "All Scores" },
  { id: "high", label: "High (≥7)" },
  { id: "medium", label: "Medium (5–7)" },
  { id: "low", label: "Low (<5)" },
] as const;

const DEADLINE_OPTIONS = [
  { id: "all", label: "All" },
  { id: "urgent", label: "Urgent (≤30d)" },
  { id: "has_deadline", label: "Has Deadline" },
  { id: "no_deadline", label: "No Deadline" },
] as const;

const FUNDING_OPTIONS = [
  { id: "all", label: "Any Amount" },
  { id: "50k", label: "> $50K", min: 50_000 },
  { id: "100k", label: "> $100K", min: 100_000 },
  { id: "500k", label: "> $500K", min: 500_000 },
  { id: "1m", label: "> $1M", min: 1_000_000 },
] as const;

/* ─── Filter logic ──────────────────────────────────────────────────────── */

function applyFilters(
  grouped: Record<string, Grant[]>,
  filters: PipelineFilters
): Record<string, Grant[]> {
  const result: Record<string, Grant[]> = {};

  for (const [key, grants] of Object.entries(grouped)) {
    result[key] = grants.filter((g) => {
      // Text search
      if (filters.search.trim()) {
        const q = filters.search.toLowerCase();
        const name = (g.grant_name || g.title || "").toLowerCase();
        const funder = (g.funder || "").toLowerCase();
        const geo = (g.geography || "").toLowerCase();
        const type = (g.grant_type || "").toLowerCase();
        if (!name.includes(q) && !funder.includes(q) && !geo.includes(q) && !type.includes(q)) {
          return false;
        }
      }

      // Theme filter
      if (filters.themes.length > 0) {
        const grantThemes = g.themes_detected || [];
        if (!filters.themes.some((t) => grantThemes.includes(t))) {
          return false;
        }
      }

      // Score range
      if (filters.scoreRange !== "all") {
        const score = g.weighted_total ?? 0;
        if (filters.scoreRange === "high" && score < 7) return false;
        if (filters.scoreRange === "medium" && (score < 5 || score >= 7)) return false;
        if (filters.scoreRange === "low" && score >= 5) return false;
      }

      // Deadline
      if (filters.deadline !== "all") {
        if (filters.deadline === "urgent" && !g.deadline_urgent) return false;
        if (filters.deadline === "has_deadline" && !g.deadline) return false;
        if (filters.deadline === "no_deadline" && g.deadline) return false;
      }

      // Funding
      if (filters.funding !== "all") {
        const amount = g.max_funding_usd || g.max_funding || 0;
        const option = FUNDING_OPTIONS.find((o) => o.id === filters.funding);
        if (option && "min" in option && amount < option.min) return false;
      }

      // Geography
      if (filters.geography) {
        const geo = (g.geography || "").toLowerCase();
        if (!geo.includes(filters.geography.toLowerCase())) return false;
      }

      return true;
    });
  }

  return result;
}

function countActiveFilters(filters: PipelineFilters): number {
  let n = 0;
  if (filters.themes.length > 0) n++;
  if (filters.scoreRange !== "all") n++;
  if (filters.deadline !== "all") n++;
  if (filters.funding !== "all") n++;
  if (filters.geography) n++;
  return n;
}

/* ─── Extract unique values from data ───────────────────────────────────── */

function extractGeographies(grouped: Record<string, Grant[]>): string[] {
  const geoSet = new Set<string>();
  for (const grants of Object.values(grouped)) {
    for (const g of grants) {
      if (g.geography) geoSet.add(g.geography);
    }
  }
  return Array.from(geoSet).sort();
}

function extractThemes(grouped: Record<string, Grant[]>): string[] {
  const themeSet = new Set<string>();
  for (const grants of Object.values(grouped)) {
    for (const g of grants) {
      for (const t of g.themes_detected || []) themeSet.add(t);
    }
  }
  return Array.from(themeSet).sort();
}

/* ─── Component ─────────────────────────────────────────────────────────── */

interface PipelineViewProps {
  initialGrants: Record<string, Grant[]>;
}

export function PipelineView({ initialGrants }: PipelineViewProps) {
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [filters, setFilters] = useState<PipelineFilters>(DEFAULT_FILTERS);
  const [showFilters, setShowFilters] = useState(false);

  const activeCount = countActiveFilters(filters);
  const allThemes = useMemo(() => extractThemes(initialGrants), [initialGrants]);
  const allGeographies = useMemo(() => extractGeographies(initialGrants), [initialGrants]);

  const filteredGrants = useMemo(
    () => applyFilters(initialGrants, filters),
    [initialGrants, filters]
  );

  const totalFiltered = Object.values(filteredGrants).reduce((sum, arr) => sum + arr.length, 0);
  const totalAll = Object.values(initialGrants).reduce((sum, arr) => sum + arr.length, 0);

  // Stable key for PipelineBoard — forces remount when filter results change
  const boardKey = useMemo(
    () => `board-${totalFiltered}-${filters.search}-${filters.themes.join(",")}-${filters.scoreRange}-${filters.deadline}-${filters.funding}-${filters.geography}`,
    [totalFiltered, filters]
  );

  const updateFilter = useCallback(<K extends keyof PipelineFilters>(
    key: K,
    value: PipelineFilters[K]
  ) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const toggleTheme = useCallback((theme: string) => {
    setFilters((prev) => ({
      ...prev,
      themes: prev.themes.includes(theme)
        ? prev.themes.filter((t) => t !== theme)
        : [...prev.themes, theme],
    }));
  }, []);

  const clearFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
  }, []);

  const hasAnyFilter = filters.search.trim() !== "" || activeCount > 0;

  return (
    <div className="flex h-full flex-col gap-3">
      {/* ── Top bar ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start gap-3">
        {/* Manual grant entry */}
        <div className="min-w-[240px] max-w-xl flex-1">
          <ManualGrantEntry />
        </div>

        {/* Search */}
        <div className="relative min-w-[200px] max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search grants..."
            value={filters.search}
            onChange={(e) => updateFilter("search", e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-8 text-sm shadow-sm outline-none placeholder:text-gray-400 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
          />
          {filters.search && (
            <button
              onClick={() => updateFilter("search", "")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-600"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium shadow-sm transition-colors ${
            showFilters || activeCount > 0
              ? "border-indigo-300 bg-indigo-50 text-indigo-700"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Filters
          {activeCount > 0 && (
            <span className="rounded-full bg-indigo-600 px-1.5 py-0.5 text-[10px] font-bold text-white leading-none">
              {activeCount}
            </span>
          )}
          <ChevronDown
            className={`h-3 w-3 transition-transform ${showFilters ? "rotate-180" : ""}`}
          />
        </button>

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

      {/* ── Filter panel (collapsible) ──────────────────────────── */}
      {showFilters && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-4">
            {/* Row 1: Themes */}
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                Themes
              </label>
              <div className="flex flex-wrap gap-1.5">
                {allThemes.map((t) => {
                  const active = filters.themes.includes(t);
                  const cfg = THEME_CONFIG[t];
                  return (
                    <button
                      key={t}
                      onClick={() => toggleTheme(t)}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-all ${
                        active
                          ? "ring-2 ring-offset-1 ring-indigo-400 shadow-sm"
                          : "opacity-60 hover:opacity-100"
                      }`}
                      style={{
                        backgroundColor: cfg?.bg || "#f3f4f6",
                        color: cfg?.color || "#4b5563",
                      }}
                    >
                      {cfg?.label || t}
                    </button>
                  );
                })}
                {allThemes.length === 0 && (
                  <span className="text-xs text-gray-400">No themes found</span>
                )}
              </div>
            </div>

            {/* Row 2: Score, Deadline, Funding, Geography */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {/* Score */}
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                  Score
                </label>
                <div className="flex flex-wrap gap-1">
                  {SCORE_OPTIONS.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => updateFilter("scoreRange", opt.id)}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                        filters.scoreRange === opt.id
                          ? "bg-gray-900 text-white"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Deadline */}
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                  Deadline
                </label>
                <div className="flex flex-wrap gap-1">
                  {DEADLINE_OPTIONS.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => updateFilter("deadline", opt.id)}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                        filters.deadline === opt.id
                          ? "bg-gray-900 text-white"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Funding */}
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                  Min Funding
                </label>
                <div className="flex flex-wrap gap-1">
                  {FUNDING_OPTIONS.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => updateFilter("funding", opt.id)}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                        filters.funding === opt.id
                          ? "bg-gray-900 text-white"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Geography */}
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                  Geography
                </label>
                {allGeographies.length > 0 ? (
                  <select
                    value={filters.geography}
                    onChange={(e) => updateFilter("geography", e.target.value)}
                    className="w-full rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
                  >
                    <option value="">All Regions</option>
                    {allGeographies.map((geo) => (
                      <option key={geo} value={geo}>
                        {geo}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="text-xs text-gray-400">No geography data</span>
                )}
              </div>
            </div>

            {/* Clear all */}
            {activeCount > 0 && (
              <div className="flex items-center justify-between border-t border-gray-100 pt-3">
                <p className="text-xs text-gray-500">
                  {activeCount} filter{activeCount !== 1 ? "s" : ""} active
                </p>
                <button
                  onClick={clearFilters}
                  className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                >
                  Clear all filters
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Result count ────────────────────────────────────────── */}
      {hasAnyFilter && (
        <div className="flex items-center gap-2">
          <p className="text-xs text-gray-500">
            Showing {totalFiltered} of {totalAll} grants
            {filters.search && (
              <> matching &ldquo;{filters.search}&rdquo;</>
            )}
            {activeCount > 0 && (
              <> with {activeCount} filter{activeCount !== 1 ? "s" : ""}</>
            )}
          </p>
          {hasAnyFilter && (
            <button
              onClick={() => {
                clearFilters();
                updateFilter("search", "");
              }}
              className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
            >
              Reset
            </button>
          )}
        </div>
      )}

      {/* ── Active view ─────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {view === "kanban" ? (
          <PipelineBoard key={boardKey} initialGrants={filteredGrants} />
        ) : (
          <PipelineTable initialGrants={filteredGrants} />
        )}
      </div>
    </div>
  );
}
