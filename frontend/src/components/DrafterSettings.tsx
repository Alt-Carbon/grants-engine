"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  X,
  Settings,
  ChevronDown,
  ChevronRight,
  Loader2,
  RotateCcw,
  Save,
  Info,
  FileText,
  FlaskConical,
  Plus,
  Leaf,
  Sprout,
  Cpu,
  Globe2,
  Heart,
  Rocket,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ThemeSetting {
  tone: string;
  voice: string;
  temperature: number;
  custom_instructions: string;
  strengths: string[];
  domain_terms: string[];
}

interface DrafterConfig {
  agent?: string;
  writing_style?: string;
  custom_instructions?: string;
  temperature?: number;
  theme_settings?: Record<string, ThemeSetting>;
  is_default?: boolean;
  [key: string]: unknown;
}

interface DrafterSettingsProps {
  open: boolean;
  onClose: () => void;
  grantId: string | null;
}

// ---------------------------------------------------------------------------
// Constants — Writing Styles (trained on reference grants)
// ---------------------------------------------------------------------------

const WRITING_STYLES = [
  {
    value: "professional",
    label: "Professional",
    icon: FileText,
    description:
      "Corporate grant style — clear, formal, confident. Strong assertions, structured arguments, business-oriented language. Trained on corporate grants (Adyen, Frontier).",
    borderColor: "border-blue-600",
    bgColor: "bg-blue-50",
    ringColor: "ring-blue-200",
    textColor: "text-blue-900",
    iconColor: "text-blue-600",
  },
  {
    value: "scientific",
    label: "Scientific / Academic",
    icon: FlaskConical,
    description:
      "Academic grant style — rigorous, precise, evidence-driven. Finding → Evidence → Implication → Justification structure. Trained on SERB, ANRF, Cambridge proposals.",
    borderColor: "border-purple-600",
    bgColor: "bg-purple-50",
    ringColor: "ring-purple-200",
    textColor: "text-purple-900",
    iconColor: "text-purple-600",
  },
  {
    value: "startup-founder",
    label: "Startup Founder",
    icon: Rocket,
    description:
      "Operational honesty — lead with deployment scale, frame problems as bottlenecks, quantify the unlock, land on ecosystem impact. Strategy team approved structure for corporate grants.",
    borderColor: "border-amber-600",
    bgColor: "bg-amber-50",
    ringColor: "ring-amber-200",
    textColor: "text-amber-900",
    iconColor: "text-amber-600",
  },
];

// ---------------------------------------------------------------------------
// Theme definitions with defaults (from theme_profiles.py)
// ---------------------------------------------------------------------------

const THEMES: {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  textColor: string;
  bgColor: string;
  borderColor: string;
  accentColor: string;
  description: string;
  defaultTone: string;
  defaultVoice: string;
  defaultStrengths: string[];
  defaultTerms: string[];
}[] = [
  {
    key: "climatetech",
    label: "Climate Tech / CDR",
    icon: Leaf,
    color: "emerald",
    textColor: "text-emerald-700",
    bgColor: "bg-emerald-50",
    borderColor: "border-emerald-200",
    accentColor: "accent-emerald-600",
    description: "Carbon removal, ERW, biochar, MRV",
    defaultTone:
      "Lead with scientific rigor and quantified climate impact. Frame ERW and Biochar as proven, scalable CDR pathways backed by peer-reviewed science.",
    defaultVoice:
      "Authoritative scientist-practitioner — precise but accessible to non-specialist reviewers",
    defaultStrengths: [
      "Only CDR company with plot-level AI-driven MRV across ERW and Biochar",
      "Operational in Darjeeling (ERW) and Eastern India (Biochar) — real field data",
      "Carbon credit buyers: Google/Frontier, Stripe, Shopify, UBS, BCG, Mitsubishi",
      "Founded by 4th-gen tea planters — deep agronomic knowledge + tech capability",
      "Dual-pathway approach: ERW for long-term + Biochar for near-term credits",
    ],
    defaultTerms: [
      "CDR",
      "ERW",
      "biochar",
      "MRV",
      "carbon credits",
      "permanence",
      "additionality",
      "net negativity",
      "soil carbon sequestration",
    ],
  },
  {
    key: "agritech",
    label: "AgriTech",
    icon: Sprout,
    color: "lime",
    textColor: "text-lime-700",
    bgColor: "bg-lime-50",
    borderColor: "border-lime-200",
    accentColor: "accent-lime-600",
    description: "Soil health, crop yields, farmer livelihoods",
    defaultTone:
      "Frame technology through agricultural impact — improved yields, soil health, farmer livelihoods. Lead with farmer outcomes, then the science.",
    defaultVoice:
      "Empathetic agronomist — practical, farmer-first language accessible to agri-policy reviewers",
    defaultStrengths: [
      "4th-generation tea planters — deep agronomic domain expertise",
      "Active field operations across Darjeeling tea estates and Eastern India farms",
      "Biochar and ERW as soil amendments with proven yield co-benefits",
      "Plot-level monitoring shows measurable soil health improvements",
      "Direct farmer relationships — not just lab research",
    ],
    defaultTerms: [
      "soil health",
      "crop yield",
      "precision agriculture",
      "regenerative agriculture",
      "smallholder farmers",
      "biochar application",
      "soil amendment",
    ],
  },
  {
    key: "ai_for_sciences",
    label: "AI for Sciences",
    icon: Cpu,
    color: "blue",
    textColor: "text-blue-700",
    bgColor: "bg-blue-50",
    borderColor: "border-blue-200",
    accentColor: "accent-blue-600",
    description: "ML, computer vision, remote sensing, AI-driven MRV",
    defaultTone:
      "Lead with the AI/ML innovation and scientific methodology. Position as building foundational AI infrastructure for earth sciences.",
    defaultVoice:
      "ML researcher-engineer — precise technical language, cite novel contributions over off-the-shelf approaches",
    defaultStrengths: [
      "Proprietary AI-driven MRV system — not using third-party measurement",
      "Real ground-truth data from active CDR deployments (not simulated)",
      "ML models trained on actual field measurements from Darjeeling and Eastern India",
      "Sensor fusion: soil sensors + satellite imagery + spectral analysis",
      "Scalable inference pipeline — plot-level to regional monitoring",
    ],
    defaultTerms: [
      "machine learning",
      "computer vision",
      "remote sensing",
      "geospatial AI",
      "sensor fusion",
      "automated MRV",
      "AI-driven measurement",
    ],
  },
  {
    key: "applied_earth_sciences",
    label: "Applied Earth Sciences",
    icon: Globe2,
    color: "amber",
    textColor: "text-amber-700",
    bgColor: "bg-amber-50",
    borderColor: "border-amber-200",
    accentColor: "accent-amber-600",
    description: "Geochemistry, mineralogy, weathering",
    defaultTone:
      "Deeply technical and scientifically rigorous. Reference specific mineral systems, analytical methods, and quantitative results.",
    defaultVoice:
      "Field geochemist — peer-review-level precision, specific mineral systems and analytical protocols",
    defaultStrengths: [
      "Field geochemistry data from real ERW deployments in tropical soils",
      "Mineral dissolution rate measurements under tropical conditions",
      "Integration of geochemical measurement with AI-driven MRV",
      "Collaboration potential with IISc and research institutions",
      "Applied science: translating lab geochemistry to field-scale CDR",
    ],
    defaultTerms: [
      "geochemistry",
      "mineralogy",
      "silicate weathering",
      "mineral dissolution kinetics",
      "basalt",
      "stable isotopes",
      "XRF analysis",
    ],
  },
  {
    key: "social_impact",
    label: "Social Impact",
    icon: Heart,
    color: "pink",
    textColor: "text-pink-700",
    bgColor: "bg-pink-50",
    borderColor: "border-pink-200",
    accentColor: "accent-pink-600",
    description: "Community development, farmer livelihoods, SDGs",
    defaultTone:
      "Lead with human impact and community outcomes. Frame CDR as a vehicle for rural development and equitable climate action.",
    defaultVoice:
      "Community advocate — impact-oriented storytelling, SDG/SROI language, centering farmer agency",
    defaultStrengths: [
      "Direct farmer partnerships in Darjeeling and Eastern India — not extractive",
      "CDR operations create rural employment (rock application, monitoring, logistics)",
      "Founded by local community members (4th-gen tea planters)",
      "Co-benefits: improved soil → better yields → higher farmer income",
      "Just transition: climate action that benefits the most vulnerable",
    ],
    defaultTerms: [
      "community development",
      "livelihood improvement",
      "SDGs",
      "just transition",
      "co-benefits",
      "participatory approach",
      "social return on investment",
    ],
  },
  {
    key: "deeptech",
    label: "Deep Tech",
    icon: Rocket,
    color: "violet",
    textColor: "text-violet-700",
    bgColor: "bg-violet-50",
    borderColor: "border-violet-200",
    accentColor: "accent-violet-600",
    description: "Technology moat, TRL, IP, commercialization",
    defaultTone:
      "Position as a deep-tech venture building novel infrastructure. Emphasize the technology moat and data flywheel. Frame in TRL language.",
    defaultVoice:
      "Tech entrepreneur-scientist — venture-scale ambition with deep technical substance",
    defaultStrengths: [
      "Proprietary MRV technology stack — not using third-party tools",
      "Hardware (sensors) + software (AI) + field operations integration",
      "Data moat: real field measurements that competitors don't have",
      "CDR market is venture-scale: $10B+ TAM by 2030",
      "Multiple revenue streams: carbon credits + technology licensing + data services",
    ],
    defaultTerms: [
      "TRL",
      "technology readiness",
      "IP",
      "scalable systems",
      "data infrastructure",
      "sensor technology",
      "commercialization pathway",
    ],
  },
];

const EMPTY_THEME: ThemeSetting = {
  tone: "",
  voice: "",
  temperature: 0.4,
  custom_instructions: "",
  strengths: [],
  domain_terms: [],
};

// ---------------------------------------------------------------------------
// Inline Editable List (compact for panel)
// ---------------------------------------------------------------------------

function EditableListCompact({
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
    <div className="space-y-1">
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-1">
          <span className="flex-1 text-[11px] text-gray-600 leading-snug py-0.5">
            {item}
          </span>
          <button
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className="shrink-0 rounded p-0.5 text-gray-300 hover:bg-red-50 hover:text-red-500 transition-colors"
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-1">
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
          className="flex-1 rounded border border-dashed border-gray-300 px-2 py-0.5 text-[11px] placeholder:text-gray-400 focus:border-violet-400 focus:outline-none focus:ring-1 focus:ring-violet-200"
          placeholder={placeholder}
        />
        <button
          onClick={() => {
            if (newItem.trim()) {
              onChange([...items, newItem.trim()]);
              setNewItem("");
            }
          }}
          disabled={!newItem.trim()}
          className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-violet-50 hover:text-violet-600 transition-colors disabled:opacity-30"
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DrafterSettings({
  open,
  onClose,
  grantId,
}: DrafterSettingsProps) {
  const [config, setConfig] = useState<DrafterConfig>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [expandedThemes, setExpandedThemes] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);
  const [isDefault, setIsDefault] = useState(false);

  // -- Load config -----------------------------------------------------------
  const loadConfig = useCallback(async () => {
    if (!grantId) {
      setConfig({});
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(
        `/api/grants/${encodeURIComponent(grantId)}/drafter-settings`
      );
      if (res.ok) {
        const data = await res.json();
        setIsDefault(!!data.is_default);
        setConfig(data);
      }
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [grantId]);

  useEffect(() => {
    if (open) {
      loadConfig();
      setDirty(false);
    }
  }, [open, loadConfig]);

  // -- Save ------------------------------------------------------------------
  const handleSave = useCallback(async () => {
    if (!grantId) return;
    setSaving(true);
    try {
      const { _id, agent, is_default, ...rest } = config;
      await fetch(
        `/api/grants/${encodeURIComponent(grantId)}/drafter-settings`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(rest),
        }
      );
      setIsDefault(false);
      setDirty(false);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  }, [config, grantId]);

  // -- Reset to defaults -----------------------------------------------------
  const handleReset = useCallback(async () => {
    if (!grantId) return;
    setResetting(true);
    try {
      await fetch(
        `/api/grants/${encodeURIComponent(grantId)}/drafter-settings`,
        { method: "DELETE" }
      );
      await loadConfig();
      setDirty(false);
    } catch {
      // silently fail
    } finally {
      setResetting(false);
    }
  }, [grantId, loadConfig]);

  // -- Helpers ---------------------------------------------------------------
  const updateField = (field: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setDirty(true);
  };

  const updateThemeSetting = (
    theme: string,
    field: keyof ThemeSetting,
    value: string | number | string[]
  ) => {
    setConfig((prev) => {
      const ts = { ...(prev.theme_settings || {}) };
      ts[theme] = {
        ...EMPTY_THEME,
        ...(ts[theme] || {}),
        [field]: value,
      };
      return { ...prev, theme_settings: ts };
    });
    setDirty(true);
  };

  const toggleTheme = (theme: string) => {
    setExpandedThemes((prev) => {
      const next = new Set(prev);
      next.has(theme) ? next.delete(theme) : next.add(theme);
      return next;
    });
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="absolute inset-0 z-30 bg-black/10 backdrop-blur-[1px]"
        onClick={onClose}
      />
      {/* Panel — wider to accommodate rich settings */}
      <div className="absolute right-0 top-0 bottom-0 z-40 flex w-[380px] flex-col border-l border-gray-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4 text-violet-500" />
            <span className="text-sm font-semibold text-gray-700">
              Drafter Settings
            </span>
          </div>
          <button
            onClick={onClose}
            className="flex h-6 w-6 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Default banner */}
        {!loading && grantId && (
          <div
            className={`flex items-start gap-2 px-4 py-2.5 text-xs border-b border-gray-100 ${
              isDefault
                ? "bg-amber-50 text-amber-700"
                : "bg-violet-50 text-violet-700"
            }`}
          >
            <Info className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
            <span>
              {isDefault
                ? "Using defaults. Changes here apply only to this grant."
                : "Custom settings for this grant."}
            </span>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {!grantId ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Settings className="h-6 w-6 text-gray-300" />
              <p className="mt-2 text-sm text-gray-400">
                Select a grant to configure settings
              </p>
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
              <p className="mt-2 text-sm text-gray-400">Loading settings...</p>
            </div>
          ) : (
            <div className="px-4 py-4 space-y-5">
              {/* ── Writing Style ─────────────────────────────────── */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Writing Style
                </p>
                <div className="space-y-2">
                  {WRITING_STYLES.map((s) => {
                    const selected =
                      (config.writing_style || "professional") === s.value;
                    const Icon = s.icon;
                    return (
                      <button
                        key={s.value}
                        onClick={() => updateField("writing_style", s.value)}
                        className={`flex w-full items-start gap-3 rounded-xl border-2 p-3 text-left transition-all ${
                          selected
                            ? `${s.borderColor} ${s.bgColor} ring-1 ${s.ringColor}`
                            : "border-gray-200 hover:border-gray-300"
                        }`}
                      >
                        <Icon
                          className={`h-4 w-4 mt-0.5 shrink-0 ${
                            selected ? s.iconColor : "text-gray-400"
                          }`}
                        />
                        <div>
                          <span
                            className={`text-xs font-bold ${
                              selected ? s.textColor : "text-gray-700"
                            }`}
                          >
                            {s.label}
                          </span>
                          <p className="text-[10px] text-gray-500 leading-snug mt-0.5">
                            {s.description}
                          </p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* ── Temperature ────────────────────────────────────── */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                    Default Temperature
                  </label>
                  <span className="text-[11px] font-mono font-bold text-gray-600">
                    {(config.temperature ?? 0.4).toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={config.temperature ?? 0.4}
                  onChange={(e) =>
                    updateField("temperature", parseFloat(e.target.value))
                  }
                  className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-violet-500"
                />
                <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
                  <span>Precise</span>
                  <span>Creative</span>
                </div>
              </div>

              {/* ── Custom Instructions ────────────────────────────── */}
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Custom Instructions
                </label>
                <Textarea
                  value={config.custom_instructions || ""}
                  onChange={(e) =>
                    updateField("custom_instructions", e.target.value)
                  }
                  placeholder="e.g., Always mention IISc partnership, use 'carbon dioxide removal' not 'carbon capture'..."
                  rows={3}
                  className="text-xs"
                />
                <p className="mt-1 text-[10px] text-gray-400">
                  Applied to every section for this grant.
                </p>
              </div>

              {/* ── Theme Agents ───────────────────────────────────── */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Theme Agents
                </p>
                <p className="text-[10px] text-gray-400 mb-2">
                  Tone, voice, vocabulary, and strengths per domain. Click to
                  customize.
                </p>

                <div className="space-y-1.5">
                  {THEMES.map((theme) => {
                    const Icon = theme.icon;
                    const ts: ThemeSetting = config.theme_settings?.[
                      theme.key
                    ] || { ...EMPTY_THEME };
                    const isExpanded = expandedThemes.has(theme.key);

                    const hasOverrides =
                      ts.tone ||
                      ts.voice ||
                      ts.custom_instructions ||
                      (ts.strengths?.length > 0) ||
                      (ts.domain_terms?.length > 0);

                    return (
                      <div
                        key={theme.key}
                        className={`rounded-lg border overflow-hidden transition-all ${
                          isExpanded
                            ? `${theme.borderColor} border-2`
                            : "border-gray-100"
                        }`}
                      >
                        {/* Collapse header */}
                        <button
                          onClick={() => toggleTheme(theme.key)}
                          className={`flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors ${
                            isExpanded
                              ? theme.bgColor
                              : "hover:bg-gray-50"
                          }`}
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
                          )}
                          <div
                            className={`flex h-6 w-6 items-center justify-center rounded-md ${theme.bgColor}`}
                          >
                            <Icon
                              className={`h-3.5 w-3.5 ${theme.textColor}`}
                            />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span
                                className={`text-xs font-semibold ${theme.textColor}`}
                              >
                                {theme.label}
                              </span>
                              {hasOverrides && (
                                <span
                                  className={`rounded-full px-1 py-0.5 text-[8px] font-semibold ${theme.bgColor} ${theme.textColor}`}
                                >
                                  custom
                                </span>
                              )}
                            </div>
                          </div>
                          <span className="text-[10px] text-gray-400">
                            {(ts.temperature ?? 0.4).toFixed(1)}
                          </span>
                        </button>

                        {/* Expanded content */}
                        {isExpanded && (
                          <div className="border-t border-gray-100 px-3 py-3 space-y-3">
                            {/* Tone */}
                            <div>
                              <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                Tone
                              </label>
                              <Textarea
                                value={ts.tone}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    theme.key,
                                    "tone",
                                    e.target.value
                                  )
                                }
                                rows={2}
                                className="text-[11px] min-h-[40px]"
                                placeholder={theme.defaultTone}
                              />
                              {!ts.tone && (
                                <p className="text-[9px] text-gray-400 mt-0.5 line-clamp-2">
                                  Default: {theme.defaultTone}
                                </p>
                              )}
                            </div>

                            {/* Voice */}
                            <div>
                              <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                Voice
                              </label>
                              <input
                                type="text"
                                value={ts.voice}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    theme.key,
                                    "voice",
                                    e.target.value
                                  )
                                }
                                className="w-full rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-[11px] focus:border-violet-400 focus:bg-white focus:outline-none focus:ring-1 focus:ring-violet-200"
                                placeholder={theme.defaultVoice}
                              />
                            </div>

                            {/* Temperature */}
                            <div>
                              <div className="flex items-center justify-between mb-1">
                                <label className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                                  Temperature
                                </label>
                                <span className="text-[10px] font-mono text-gray-500">
                                  {(ts.temperature ?? 0.4).toFixed(2)}
                                </span>
                              </div>
                              <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={ts.temperature ?? 0.4}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    theme.key,
                                    "temperature",
                                    parseFloat(e.target.value)
                                  )
                                }
                                className={`w-full h-1 bg-gray-200 rounded-full appearance-none cursor-pointer ${theme.accentColor}`}
                              />
                            </div>

                            {/* Strengths */}
                            <div>
                              <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                Key Strengths
                              </label>
                              <EditableListCompact
                                items={
                                  ts.strengths?.length
                                    ? ts.strengths
                                    : theme.defaultStrengths
                                }
                                onChange={(items) =>
                                  updateThemeSetting(
                                    theme.key,
                                    "strengths",
                                    items
                                  )
                                }
                                placeholder="Add a strength..."
                              />
                            </div>

                            {/* Domain Terms */}
                            <div>
                              <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                Domain Terms
                              </label>
                              <div className="flex flex-wrap gap-1">
                                {(ts.domain_terms?.length
                                  ? ts.domain_terms
                                  : theme.defaultTerms
                                ).map((term, i) => (
                                  <span
                                    key={i}
                                    className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${theme.bgColor} ${theme.textColor}`}
                                  >
                                    {term}
                                    <button
                                      onClick={() => {
                                        const current =
                                          ts.domain_terms?.length
                                            ? [...ts.domain_terms]
                                            : [...theme.defaultTerms];
                                        current.splice(i, 1);
                                        updateThemeSetting(
                                          theme.key,
                                          "domain_terms",
                                          current
                                        );
                                      }}
                                      className="ml-0.5 hover:text-red-600"
                                    >
                                      <X className="h-2 w-2" />
                                    </button>
                                  </span>
                                ))}
                                <input
                                  type="text"
                                  className="rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-[10px] w-20 focus:border-violet-400 focus:outline-none"
                                  placeholder="+ add"
                                  onKeyDown={(e) => {
                                    if (
                                      e.key === "Enter" &&
                                      (e.target as HTMLInputElement).value.trim()
                                    ) {
                                      const val = (
                                        e.target as HTMLInputElement
                                      ).value.trim();
                                      const current =
                                        ts.domain_terms?.length
                                          ? [...ts.domain_terms]
                                          : [...theme.defaultTerms];
                                      current.push(val);
                                      updateThemeSetting(
                                        theme.key,
                                        "domain_terms",
                                        current
                                      );
                                      (e.target as HTMLInputElement).value = "";
                                    }
                                  }}
                                />
                              </div>
                            </div>

                            {/* Theme-specific Instructions */}
                            <div>
                              <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                Theme Instructions
                              </label>
                              <Textarea
                                value={ts.custom_instructions || ""}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    theme.key,
                                    "custom_instructions",
                                    e.target.value
                                  )
                                }
                                rows={2}
                                className="text-[11px] min-h-[36px]"
                                placeholder={`e.g., For ${theme.label} grants, always emphasize...`}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {!loading && grantId && (
          <div className="border-t border-gray-100 px-4 py-3 flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleReset}
              disabled={resetting}
              className="gap-1.5 text-gray-600"
            >
              {resetting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw className="h-3 w-3" />
              )}
              Reset
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={handleSave}
              disabled={saving || !dirty}
              className="ml-auto gap-1.5 bg-violet-600 hover:bg-violet-700"
            >
              {saving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              Save
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
