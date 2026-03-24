"use client";

import { useState, useCallback } from "react";
import type { AgentConfig } from "@/lib/queries";
import {
  Save,
  CheckCircle,
  AlertTriangle,
  Loader2,
  FileText,
  FlaskConical,
  Settings2,
  ChevronDown,
  ChevronUp,
  Leaf,
  Sprout,
  Cpu,
  Globe2,
  Heart,
  Rocket,
  Plus,
  X,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

interface ThemeSettings {
  tone: string;
  voice: string;
  temperature: number;
  custom_instructions: string;
  strengths: string[];
  domain_terms: string[];
}

interface DrafterConfig {
  agent: string;
  writing_style: "professional" | "scientific" | "startup-founder";
  custom_instructions: string;
  temperature: number;
  theme_settings: Record<string, ThemeSettings>;
  [key: string]: unknown;
}

const EMPTY_THEME: ThemeSettings = {
  tone: "",
  voice: "",
  temperature: 0.4,
  custom_instructions: "",
  strengths: [],
  domain_terms: [],
};

// ── Theme definitions with defaults from theme_profiles.py ───────────────

const THEMES = [
  {
    key: "climatetech",
    label: "Climate Tech / CDR",
    icon: Leaf,
    color: "emerald",
    description: "Carbon removal, ERW, biochar, MRV. Lead with scientific rigor and quantified climate impact.",
    defaultTone: "Lead with scientific rigor and quantified climate impact. Frame ERW and Biochar as proven, scalable CDR pathways backed by peer-reviewed science.",
    defaultVoice: "Authoritative scientist-practitioner — precise but accessible to non-specialist reviewers",
    defaultStrengths: [
      "Only CDR company with plot-level AI-driven MRV across ERW and Biochar",
      "Operational in Darjeeling (ERW) and Eastern India (Biochar) — real field data",
      "Carbon credit buyers: Google/Frontier, Stripe, Shopify, UBS, BCG, Mitsubishi",
      "Founded by 4th-gen tea planters — deep agronomic knowledge + tech capability",
      "Dual-pathway approach: ERW for long-term + Biochar for near-term credits",
    ],
    defaultTerms: ["CDR", "ERW", "biochar", "MRV", "carbon credits", "permanence", "additionality", "net negativity", "soil carbon sequestration"],
  },
  {
    key: "agritech",
    label: "AgriTech",
    icon: Sprout,
    color: "lime",
    description: "Soil health, crop yields, farmer livelihoods. Frame technology through agricultural impact.",
    defaultTone: "Frame technology through agricultural impact — improved yields, soil health, farmer livelihoods. Lead with farmer outcomes, then the science.",
    defaultVoice: "Empathetic agronomist — practical, farmer-first language accessible to agri-policy reviewers",
    defaultStrengths: [
      "4th-generation tea planters — deep agronomic domain expertise",
      "Active field operations across Darjeeling tea estates and Eastern India farms",
      "Biochar and ERW as soil amendments with proven yield co-benefits",
      "Plot-level monitoring shows measurable soil health improvements",
      "Direct farmer relationships — not just lab research",
    ],
    defaultTerms: ["soil health", "crop yield", "precision agriculture", "regenerative agriculture", "smallholder farmers", "biochar application", "soil amendment"],
  },
  {
    key: "ai_for_sciences",
    label: "AI for Sciences",
    icon: Cpu,
    color: "blue",
    description: "ML, computer vision, remote sensing, AI-driven MRV. Lead with technical innovation.",
    defaultTone: "Lead with the AI/ML innovation and scientific methodology. Position as building foundational AI infrastructure for earth sciences.",
    defaultVoice: "ML researcher-engineer — precise technical language, cite novel contributions over off-the-shelf approaches",
    defaultStrengths: [
      "Proprietary AI-driven MRV system — not using third-party measurement",
      "Real ground-truth data from active CDR deployments (not simulated)",
      "ML models trained on actual field measurements from Darjeeling and Eastern India",
      "Sensor fusion: soil sensors + satellite imagery + spectral analysis",
      "Scalable inference pipeline — plot-level to regional monitoring",
    ],
    defaultTerms: ["machine learning", "computer vision", "remote sensing", "geospatial AI", "sensor fusion", "automated MRV", "AI-driven measurement"],
  },
  {
    key: "applied_earth_sciences",
    label: "Applied Earth Sciences",
    icon: Globe2,
    color: "amber",
    description: "Geochemistry, mineralogy, weathering. Deeply technical, peer-review-level precision.",
    defaultTone: "Deeply technical and scientifically rigorous. Reference specific mineral systems, analytical methods, and quantitative results.",
    defaultVoice: "Field geochemist — peer-review-level precision, specific mineral systems and analytical protocols",
    defaultStrengths: [
      "Field geochemistry data from real ERW deployments in tropical soils",
      "Mineral dissolution rate measurements under tropical conditions",
      "Integration of geochemical measurement with AI-driven MRV",
      "Collaboration potential with IISc and research institutions",
      "Applied science: translating lab geochemistry to field-scale CDR",
    ],
    defaultTerms: ["geochemistry", "mineralogy", "silicate weathering", "mineral dissolution kinetics", "basalt", "stable isotopes", "XRF analysis"],
  },
  {
    key: "social_impact",
    label: "Social Impact",
    icon: Heart,
    color: "pink",
    description: "Community development, farmer livelihoods, SDGs. Lead with human impact and storytelling.",
    defaultTone: "Lead with human impact and community outcomes. Frame CDR as a vehicle for rural development and equitable climate action.",
    defaultVoice: "Community advocate — impact-oriented storytelling, SDG/SROI language, centering farmer agency",
    defaultStrengths: [
      "Direct farmer partnerships in Darjeeling and Eastern India — not extractive",
      "CDR operations create rural employment (rock application, monitoring, logistics)",
      "Founded by local community members (4th-gen tea planters)",
      "Co-benefits: improved soil → better yields → higher farmer income",
      "Just transition: climate action that benefits the most vulnerable",
    ],
    defaultTerms: ["community development", "livelihood improvement", "SDGs", "just transition", "co-benefits", "participatory approach", "social return on investment"],
  },
  {
    key: "deeptech",
    label: "Deep Tech",
    icon: Rocket,
    color: "violet",
    description: "Technology moat, TRL, IP, commercialization. Position as venture-scale deep tech.",
    defaultTone: "Position as a deep-tech venture building novel infrastructure. Emphasize the technology moat and data flywheel. Frame in TRL language.",
    defaultVoice: "Tech entrepreneur-scientist — venture-scale ambition with deep technical substance",
    defaultStrengths: [
      "Proprietary MRV technology stack — not using third-party tools",
      "Hardware (sensors) + software (AI) + field operations integration",
      "Data moat: real field measurements that competitors don't have",
      "CDR market is venture-scale: $10B+ TAM by 2030",
      "Multiple revenue streams: carbon credits + technology licensing + data services",
    ],
    defaultTerms: ["TRL", "technology readiness", "IP", "scalable systems", "data infrastructure", "sensor technology", "commercialization pathway"],
  },
];

const COLOR_MAP: Record<string, { border: string; bg: string; text: string; accent: string }> = {
  emerald: { border: "border-emerald-200", bg: "bg-emerald-50", text: "text-emerald-700", accent: "accent-emerald-600" },
  lime: { border: "border-lime-200", bg: "bg-lime-50", text: "text-lime-700", accent: "accent-lime-600" },
  blue: { border: "border-blue-200", bg: "bg-blue-50", text: "text-blue-700", accent: "accent-blue-600" },
  amber: { border: "border-amber-200", bg: "bg-amber-50", text: "text-amber-700", accent: "accent-amber-600" },
  pink: { border: "border-pink-200", bg: "bg-pink-50", text: "text-pink-700", accent: "accent-pink-600" },
  violet: { border: "border-violet-200", bg: "bg-violet-50", text: "text-violet-700", accent: "accent-violet-600" },
};

// ── Collapsible Section ──────────────────────────────────────────────────────

function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-gray-50"
      >
        <Icon className="h-5 w-5 text-gray-400" />
        <span className="flex-1 text-sm font-semibold text-gray-800">{title}</span>
        {open ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>
      {open && <div className="border-t border-gray-100 px-5 py-5">{children}</div>}
    </div>
  );
}

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
          onClick={() => {
            if (newItem.trim()) {
              onChange([...items, newItem.trim()]);
              setNewItem("");
            }
          }}
          disabled={!newItem.trim()}
          className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-600 transition-colors disabled:opacity-30"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Theme Card ───────────────────────────────────────────────────────────────

function ThemeCard({
  theme,
  settings,
  onUpdate,
}: {
  theme: typeof THEMES[number];
  settings: ThemeSettings;
  onUpdate: (field: string, value: unknown) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const colors = COLOR_MAP[theme.color] || COLOR_MAP.blue;
  const Icon = theme.icon;

  const hasOverrides = settings.tone || settings.voice || settings.custom_instructions ||
    (settings.strengths?.length > 0) || (settings.domain_terms?.length > 0);

  return (
    <div className={`rounded-xl border-2 overflow-hidden transition-all ${expanded ? colors.border : "border-gray-200"}`}>
      {/* Header */}
      <button
        onClick={() => setExpanded((o) => !o)}
        className={`flex w-full items-center gap-3 px-5 py-4 text-left transition-colors ${expanded ? colors.bg : "hover:bg-gray-50"}`}
      >
        <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${colors.bg}`}>
          <Icon className={`h-5 w-5 ${colors.text}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-gray-900">{theme.label}</span>
            {hasOverrides && (
              <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${colors.bg} ${colors.text}`}>
                customized
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 truncate">{theme.description}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-gray-400 font-medium">
            temp: {(settings.temperature ?? 0.4).toFixed(2)}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
        </div>
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="border-t border-gray-100 px-5 py-5 space-y-5">
          {/* Tone */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Tone
            </label>
            <textarea
              value={settings.tone}
              onChange={(e) => onUpdate("tone", e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder={theme.defaultTone}
            />
            {!settings.tone && (
              <p className="text-[10px] text-gray-400 mt-1">Default: {theme.defaultTone.slice(0, 100)}...</p>
            )}
          </div>

          {/* Voice */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Voice
            </label>
            <input
              type="text"
              value={settings.voice}
              onChange={(e) => onUpdate("voice", e.target.value)}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder={theme.defaultVoice}
            />
          </div>

          {/* Temperature */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                Temperature
              </label>
              <span className="text-xs font-bold text-gray-600">{(settings.temperature ?? 0.4).toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.temperature ?? 0.4}
              onChange={(e) => onUpdate("temperature", parseFloat(e.target.value))}
              className={`w-full ${colors.accent}`}
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>Precise</span>
              <span>Creative</span>
            </div>
          </div>

          {/* Strengths */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Key Strengths to Highlight
            </label>
            <EditableList
              items={settings.strengths?.length ? settings.strengths : theme.defaultStrengths}
              onChange={(items) => onUpdate("strengths", items)}
              placeholder="Add a strength..."
            />
          </div>

          {/* Domain Terms */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Domain Terminology
            </label>
            <EditableList
              items={settings.domain_terms?.length ? settings.domain_terms : theme.defaultTerms}
              onChange={(items) => onUpdate("domain_terms", items)}
              placeholder="Add a term..."
            />
          </div>

          {/* Theme-specific instructions */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Theme-specific Instructions
            </label>
            <textarea
              value={settings.custom_instructions || ""}
              onChange={(e) => onUpdate("custom_instructions", e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder={`e.g., For ${theme.label} grants, always emphasize...`}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

export function DrafterSettings({ initialConfig }: { initialConfig: AgentConfig }) {
  const [config, setConfig] = useState<DrafterConfig>(() => {
    const c = initialConfig as unknown as DrafterConfig;
    return {
      agent: "drafter",
      writing_style: c.writing_style || "professional",
      custom_instructions: c.custom_instructions || "",
      temperature: c.temperature ?? 0.4,
      theme_settings: c.theme_settings || {},
    };
  });
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"ok" | "error" | null>(null);

  const updateField = useCallback((field: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setSaveResult(null);
  }, []);

  const updateTheme = useCallback((themeKey: string, field: string, value: unknown) => {
    setConfig((prev) => ({
      ...prev,
      theme_settings: {
        ...prev.theme_settings,
        [themeKey]: {
          ...EMPTY_THEME,
          ...(prev.theme_settings[themeKey] || {}),
          [field]: value,
        },
      },
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
        body: JSON.stringify({ agent: "drafter", config }),
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
      {/* ── Writing Style ──────────────────────────────────────────── */}
      <Section title="Writing Style" icon={FileText}>
        <div className="space-y-5">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3 block">
              Primary Style
            </label>
            <div className="grid grid-cols-3 gap-3">
              <button
                onClick={() => updateField("writing_style", "professional")}
                className={`flex flex-col gap-2 rounded-xl border-2 p-4 text-left transition-all ${
                  config.writing_style === "professional"
                    ? "border-blue-600 bg-blue-50 ring-1 ring-blue-200"
                    : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <div className="flex items-center gap-2">
                  <FileText className={`h-5 w-5 ${config.writing_style === "professional" ? "text-blue-600" : "text-gray-400"}`} />
                  <span className={`text-sm font-bold ${config.writing_style === "professional" ? "text-blue-900" : "text-gray-700"}`}>
                    Professional
                  </span>
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">
                  Corporate style — clear, formal, confident. Strong assertions,
                  structured arguments.
                </p>
              </button>
              <button
                onClick={() => updateField("writing_style", "scientific")}
                className={`flex flex-col gap-2 rounded-xl border-2 p-4 text-left transition-all ${
                  config.writing_style === "scientific"
                    ? "border-purple-600 bg-purple-50 ring-1 ring-purple-200"
                    : "border-gray-200 hover:border-gray-300"
                }`}
              >
                <div className="flex items-center gap-2">
                  <FlaskConical className={`h-5 w-5 ${config.writing_style === "scientific" ? "text-purple-600" : "text-gray-400"}`} />
                  <span className={`text-sm font-bold ${config.writing_style === "scientific" ? "text-purple-900" : "text-gray-700"}`}>
                    Scientific
                  </span>
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">
                  Academic — rigorous, evidence-driven. Finding → Evidence → Implication.
                </p>
              </button>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Default Creativity (Temperature)
              </label>
              <span className="text-sm font-bold text-gray-700">{config.temperature.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={config.temperature}
              onChange={(e) => updateField("temperature", parseFloat(e.target.value))}
              className="w-full accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>Precise &amp; Consistent</span>
              <span>Creative &amp; Varied</span>
            </div>
          </div>
        </div>
      </Section>

      {/* ── Custom Instructions ────────────────────────────────────── */}
      <Section title="Global Custom Instructions" icon={Settings2}>
        <div className="space-y-2">
          <p className="text-xs text-gray-500">
            Applied to every section across all themes. Use for company-wide rules.
          </p>
          <textarea
            value={config.custom_instructions}
            onChange={(e) => updateField("custom_instructions", e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-800 placeholder:text-gray-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder={`Example:\n- Always mention our IISc Bangalore research partnership\n- Use "carbon dioxide removal" not "carbon capture"\n- Include specific tonnage numbers when available`}
          />
        </div>
      </Section>

      {/* ── Theme Agents ──────────────────────────────────────────── */}
      <Section title="Theme Agents" icon={Settings2} defaultOpen={true}>
        <p className="text-xs text-gray-500 mb-4">
          Each theme agent controls how drafts are written for that domain — tone, voice, vocabulary, strengths to highlight,
          and theme-specific instructions. Click a theme to customize it.
        </p>
        <div className="space-y-3">
          {THEMES.map((theme) => (
            <ThemeCard
              key={theme.key}
              theme={theme}
              settings={config.theme_settings[theme.key] || EMPTY_THEME}
              onUpdate={(field, value) => updateTheme(theme.key, field, value)}
            />
          ))}
        </div>
      </Section>

      {/* ── Save Bar ──────────────────────────────────────────────── */}
      <div className="sticky bottom-0 z-10 -mx-6 border-t border-gray-200 bg-white/95 backdrop-blur-sm px-6 py-4">
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? "Saving..." : "Save Settings"}
          </button>

          {saveResult === "ok" && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-green-600">
              <CheckCircle className="h-4 w-4" />
              Settings saved — applies to all new drafts
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
