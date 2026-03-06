import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Priority Tags ───────────────────────────────────────────────────────────

export type PriorityLevel = "High" | "Medium" | "Low";

export function getPriority(score: number): {
  label: PriorityLevel;
  className: string;
} {
  if (score >= 6.5)
    return { label: "High", className: "bg-green-100 text-green-700 ring-green-300" };
  if (score >= 5.0)
    return { label: "Medium", className: "bg-amber-100 text-amber-700 ring-amber-300" };
  return { label: "Low", className: "bg-red-100 text-red-700 ring-red-300" };
}

// ── Theme Tags ──────────────────────────────────────────────────────────────

export const THEME_CONFIG: Record<string, { label: string; bg: string; color: string }> = {
  climatetech:            { label: "Climate Tech",    bg: "#ccfbf1", color: "#115e59" },
  agritech:               { label: "Agri Tech",       bg: "#d1fae5", color: "#065f46" },
  ai_for_sciences:        { label: "AI for Sciences", bg: "#e9d5ff", color: "#6b21a8" },
  applied_earth_sciences: { label: "Earth Sciences",  bg: "#bae6fd", color: "#075985" },
  social_impact:          { label: "Social Impact",   bg: "#fed7aa", color: "#9a3412" },
  deeptech:               { label: "Deep Tech",       bg: "#fecdd3", color: "#9f1239" },
};

const THEME_FALLBACK = { label: "", bg: "#f3f4f6", color: "#4b5563" };

export function getThemeLabel(key: string): { label: string; bg: string; color: string } {
  const cfg = THEME_CONFIG[key];
  if (cfg) return cfg;
  return { ...THEME_FALLBACK, label: key };
}
