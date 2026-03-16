"use client";

import { useState, useCallback } from "react";
import type { AgentConfig } from "@/lib/queries";
import {
  Save,
  CheckCircle,
  AlertTriangle,
  Loader2,
  Banknote,
  FlaskConical,
  Plus,
  X,
  ShieldCheck,
  Scale,
  Flame,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

interface PerspectiveSettings {
  strictness: "lenient" | "balanced" | "strict";
  temperature: number;
  focus_areas: string[];
  custom_criteria: string[];
  custom_instructions: string;
}

interface ReviewerConfig {
  agent: string;
  funder: PerspectiveSettings;
  scientific: PerspectiveSettings;
  [key: string]: unknown;
}

const EMPTY_PERSPECTIVE: PerspectiveSettings = {
  strictness: "balanced",
  temperature: 0.3,
  focus_areas: [],
  custom_criteria: [],
  custom_instructions: "",
};

const DEFAULT_FOCUS = {
  funder: [
    "Alignment with funder priorities",
    "Budget justification and value for money",
    "Measurable objectives and impact claims",
    "Team credibility for the proposed scope",
    "Competitiveness vs. typical winning applications",
    "Compliance with submission requirements",
  ],
  scientific: [
    "Methodology soundness and reproducibility",
    "MRV rigor and data quality",
    "Scientific novelty vs. incremental work",
    "Scalability evidence and pathway",
    "Uncertainties honestly acknowledged",
    "Claims supported by data or citations",
    "Technical feasibility of proposed approach",
  ],
};

const STRICTNESS_OPTIONS = [
  {
    value: "lenient" as const,
    label: "Lenient",
    icon: ShieldCheck,
    description: "Encouraging. Scores generously, focuses on potential. Flags only critical issues.",
    color: "emerald",
  },
  {
    value: "balanced" as const,
    label: "Balanced",
    icon: Scale,
    description: "Fair and constructive. Acknowledges strengths before issues. Realistic scoring.",
    color: "blue",
  },
  {
    value: "strict" as const,
    label: "Strict",
    icon: Flame,
    description: "Demanding. Skeptical reviewer with limited funding. Every weakness matters.",
    color: "red",
  },
];

const COLOR_MAP: Record<string, { border: string; bg: string; text: string }> = {
  emerald: { border: "border-emerald-600", bg: "bg-emerald-50", text: "text-emerald-700" },
  blue: { border: "border-blue-600", bg: "bg-blue-50", text: "text-blue-700" },
  red: { border: "border-red-600", bg: "bg-red-50", text: "text-red-700" },
};

// ── Editable List ────────────────────────────────────────────────────────────

function EditableList({
  items,
  onChange,
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder: string;
}) {
  const [newItem, setNewItem] = useState("");
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="text"
            value={item}
            onChange={(e) => {
              const updated = [...items];
              updated[i] = e.target.value;
              onChange(updated);
            }}
            className="flex-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className="shrink-0 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newItem.trim()) {
              onChange([...items, newItem.trim()]);
              setNewItem("");
            }
          }}
          className="flex-1 rounded-lg border border-dashed border-gray-300 px-3 py-1.5 text-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder={placeholder}
        />
        <button
          onClick={() => { if (newItem.trim()) { onChange([...items, newItem.trim()]); setNewItem(""); } }}
          disabled={!newItem.trim()}
          className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-600 transition-colors disabled:opacity-30"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Perspective Card ─────────────────────────────────────────────────────────

function PerspectiveCard({
  perspective,
  label,
  icon: Icon,
  accentColor,
  settings,
  onUpdate,
  defaultFocus,
}: {
  perspective: "funder" | "scientific";
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  accentColor: string;
  settings: PerspectiveSettings;
  onUpdate: (field: string, value: unknown) => void;
  defaultFocus: string[];
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className={`flex items-center gap-3 px-5 py-4 ${accentColor === "amber" ? "bg-amber-50" : "bg-indigo-50"}`}>
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${accentColor === "amber" ? "bg-amber-100" : "bg-indigo-100"}`}>
          <Icon className={`h-5 w-5 ${accentColor === "amber" ? "text-amber-700" : "text-indigo-700"}`} />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-900">{label}</h3>
          <p className="text-xs text-gray-500">
            {perspective === "funder"
              ? "Reviews as a grant program officer deciding whether to fund"
              : "Reviews as a peer scientist evaluating technical rigor"}
          </p>
        </div>
      </div>

      <div className="px-5 py-5 space-y-5">
        {/* Strictness */}
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-3 block">
            Scoring Strictness
          </label>
          <div className="grid grid-cols-3 gap-2">
            {STRICTNESS_OPTIONS.map((opt) => {
              const selected = settings.strictness === opt.value;
              const colors = COLOR_MAP[opt.color];
              const OptIcon = opt.icon;
              return (
                <button
                  key={opt.value}
                  onClick={() => onUpdate("strictness", opt.value)}
                  className={`flex flex-col items-center gap-1.5 rounded-xl border-2 p-3 text-center transition-all ${
                    selected
                      ? `${colors.border} ${colors.bg} ring-1 ring-${opt.color}-200`
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <OptIcon className={`h-5 w-5 ${selected ? colors.text : "text-gray-400"}`} />
                  <span className={`text-xs font-bold ${selected ? colors.text : "text-gray-600"}`}>
                    {opt.label}
                  </span>
                </button>
              );
            })}
          </div>
          <p className="text-[10px] text-gray-400 mt-2">
            {STRICTNESS_OPTIONS.find((o) => o.value === settings.strictness)?.description}
          </p>
        </div>

        {/* Temperature */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Review Temperature
            </label>
            <span className="text-xs font-bold text-gray-600">{settings.temperature.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={0.8}
            step={0.05}
            value={settings.temperature}
            onChange={(e) => onUpdate("temperature", parseFloat(e.target.value))}
            className="w-full accent-blue-600"
          />
          <div className="flex justify-between text-[10px] text-gray-400 mt-1">
            <span>Deterministic</span>
            <span>Varied</span>
          </div>
        </div>

        {/* Focus Areas */}
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
            Review Focus Areas
          </label>
          <p className="text-[10px] text-gray-400 mb-2">
            What the reviewer prioritizes. Edit or add to customize.
          </p>
          <EditableList
            items={settings.focus_areas.length ? settings.focus_areas : defaultFocus}
            onChange={(items) => onUpdate("focus_areas", items)}
            placeholder="Add a focus area..."
          />
        </div>

        {/* Custom Criteria */}
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
            Additional Evaluation Criteria
          </label>
          <p className="text-[10px] text-gray-400 mb-2">
            Extra criteria beyond the grant&apos;s own — applied to every review from this perspective.
          </p>
          <EditableList
            items={settings.custom_criteria}
            onChange={(items) => onUpdate("custom_criteria", items)}
            placeholder="e.g., Does the proposal address data sovereignty?"
          />
        </div>

        {/* Custom Instructions */}
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
            Custom Instructions
          </label>
          <textarea
            value={settings.custom_instructions}
            onChange={(e) => onUpdate("custom_instructions", e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder={
              perspective === "funder"
                ? "e.g., Compare against Frontier and Stripe CDR purchase criteria"
                : "e.g., Pay special attention to MRV methodology and permanence claims"
            }
          />
        </div>
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

export function ReviewerSettings({ initialConfig }: { initialConfig: AgentConfig }) {
  const [config, setConfig] = useState<ReviewerConfig>(() => {
    const c = initialConfig as unknown as ReviewerConfig;
    return {
      agent: "reviewer",
      funder: { ...EMPTY_PERSPECTIVE, ...c.funder },
      scientific: { ...EMPTY_PERSPECTIVE, ...{ temperature: 0.25 }, ...c.scientific },
    };
  });
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"ok" | "error" | null>(null);

  const updatePerspective = useCallback((perspective: "funder" | "scientific", field: string, value: unknown) => {
    setConfig((prev) => ({
      ...prev,
      [perspective]: { ...prev[perspective], [field]: value },
    }));
    setSaveResult(null);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: "reviewer", config }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaveResult("ok");
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  }, [config]);

  return (
    <div className="flex flex-col gap-5">
      <PerspectiveCard
        perspective="funder"
        label="Funder Reviewer Agent"
        icon={Banknote}
        accentColor="amber"
        settings={config.funder}
        onUpdate={(field, value) => updatePerspective("funder", field, value)}
        defaultFocus={DEFAULT_FOCUS.funder}
      />

      <PerspectiveCard
        perspective="scientific"
        label="Scientific Reviewer Agent"
        icon={FlaskConical}
        accentColor="indigo"
        settings={config.scientific}
        onUpdate={(field, value) => updatePerspective("scientific", field, value)}
        defaultFocus={DEFAULT_FOCUS.scientific}
      />

      {/* Save Bar */}
      <div className="sticky bottom-0 z-10 -mx-6 border-t border-gray-200 bg-white/95 backdrop-blur-sm px-6 py-4">
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? "Saving..." : "Save Reviewer Settings"}
          </button>
          {saveResult === "ok" && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-green-600">
              <CheckCircle className="h-4 w-4" />
              Saved — applies to next review run
            </span>
          )}
          {saveResult === "error" && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-red-600">
              <AlertTriangle className="h-4 w-4" />
              Save failed
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
