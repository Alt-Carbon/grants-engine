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
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ThemeSetting {
  tone: string;
  voice: string;
  temperature: number;
}

interface DrafterConfig {
  agent?: string;
  writing_style?: string;
  custom_instructions?: string;
  theme_settings?: Record<string, ThemeSetting>;
  [key: string]: unknown;
}

interface DrafterSettingsProps {
  open: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WRITING_STYLES = [
  { value: "professional", label: "Professional" },
  { value: "academic", label: "Academic" },
  { value: "technical", label: "Technical" },
  { value: "conversational", label: "Conversational" },
];

const THEME_META: Record<string, { label: string; color: string; bg: string }> =
  {
    climatetech: {
      label: "ClimaTech",
      color: "text-emerald-700",
      bg: "bg-emerald-50",
    },
    agritech: {
      label: "AgriTech",
      color: "text-lime-700",
      bg: "bg-lime-50",
    },
    ai_for_sciences: {
      label: "AI for Sciences",
      color: "text-blue-700",
      bg: "bg-blue-50",
    },
    applied_earth_sciences: {
      label: "Earth Sciences",
      color: "text-amber-700",
      bg: "bg-amber-50",
    },
    social_impact: {
      label: "Social Impact",
      color: "text-pink-700",
      bg: "bg-pink-50",
    },
    deeptech: {
      label: "Deep Tech",
      color: "text-violet-700",
      bg: "bg-violet-50",
    },
  };

const THEME_ORDER = [
  "climatetech",
  "agritech",
  "ai_for_sciences",
  "applied_earth_sciences",
  "social_impact",
  "deeptech",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DrafterSettings({ open, onClose }: DrafterSettingsProps) {
  const [config, setConfig] = useState<DrafterConfig>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [expandedThemes, setExpandedThemes] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);

  // -- Load config -----------------------------------------------------------
  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/config?agent=drafter");
      if (res.ok) {
        const data = await res.json();
        setConfig(data);
      }
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      loadConfig();
      setDirty(false);
    }
  }, [open, loadConfig]);

  // -- Save ------------------------------------------------------------------
  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const { _id, agent, ...rest } = config;
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: "drafter", config: rest }),
      });
      setDirty(false);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  }, [config]);

  // -- Reset to defaults -----------------------------------------------------
  const handleReset = useCallback(async () => {
    setResetting(true);
    try {
      // Save with theme_settings removed so backend re-seeds defaults on next boot;
      // For immediate effect, re-fetch defaults by deleting theme_settings
      const { _id, agent, theme_settings, custom_instructions, writing_style, ...rest } = config;
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent: "drafter",
          config: {
            ...rest,
            writing_style: "professional",
            custom_instructions: "",
            theme_settings: null,
          },
        }),
      });
      await loadConfig();
      setDirty(false);
    } catch {
      // silently fail
    } finally {
      setResetting(false);
    }
  }, [config, loadConfig]);

  // -- Helpers ---------------------------------------------------------------
  const updateField = (field: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setDirty(true);
  };

  const updateThemeSetting = (
    theme: string,
    field: keyof ThemeSetting,
    value: string | number
  ) => {
    setConfig((prev) => {
      const ts = { ...(prev.theme_settings || {}) };
      ts[theme] = { ...(ts[theme] || { tone: "", voice: "", temperature: 0.4 }), [field]: value };
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
      {/* Panel */}
      <div className="absolute right-0 top-0 bottom-0 z-40 flex w-[340px] flex-col border-l border-gray-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4 text-gray-400" />
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

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
              <p className="mt-2 text-sm text-gray-400">Loading settings...</p>
            </div>
          ) : (
            <div className="px-4 py-4 space-y-5">
              {/* ── Global Section ──────────────────────────── */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Global
                </p>

                {/* Writing Style */}
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Writing Style
                </label>
                <select
                  value={config.writing_style || "professional"}
                  onChange={(e) => updateField("writing_style", e.target.value)}
                  className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800 focus:border-violet-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-violet-100"
                >
                  {WRITING_STYLES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>

                {/* Custom Instructions */}
                <label className="block text-xs font-medium text-gray-600 mt-3 mb-1">
                  Custom Instructions
                </label>
                <Textarea
                  value={config.custom_instructions || ""}
                  onChange={(e) =>
                    updateField("custom_instructions", e.target.value)
                  }
                  placeholder="Add any custom instructions for the drafter agent..."
                  rows={3}
                  className="text-sm"
                />
                <p className="mt-1 text-[10px] text-gray-400">
                  Injected into every drafter response as additional context.
                </p>
              </div>

              {/* ── Per-Theme Settings ──────────────────────── */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Theme Agents
                </p>

                <div className="space-y-1.5">
                  {THEME_ORDER.map((themeKey) => {
                    const meta = THEME_META[themeKey];
                    if (!meta) return null;
                    const ts = config.theme_settings?.[themeKey] || {
                      tone: "",
                      voice: "",
                      temperature: 0.4,
                    };
                    const isExpanded = expandedThemes.has(themeKey);

                    return (
                      <div
                        key={themeKey}
                        className="rounded-lg border border-gray-100 overflow-hidden"
                      >
                        {/* Collapse header */}
                        <button
                          onClick={() => toggleTheme(themeKey)}
                          className={`flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-gray-50 ${
                            isExpanded ? "bg-gray-50" : ""
                          }`}
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
                          )}
                          <span
                            className={`text-xs font-semibold ${meta.color}`}
                          >
                            {meta.label}
                          </span>
                          <span className="ml-auto text-[10px] text-gray-400">
                            temp: {ts.temperature}
                          </span>
                        </button>

                        {/* Expanded content */}
                        {isExpanded && (
                          <div className="border-t border-gray-100 px-3 py-3 space-y-3">
                            {/* Temperature slider */}
                            <div>
                              <div className="flex items-center justify-between mb-1">
                                <label className="text-[11px] font-medium text-gray-600">
                                  Temperature
                                </label>
                                <span className="text-[11px] font-mono text-gray-500">
                                  {Number(ts.temperature).toFixed(2)}
                                </span>
                              </div>
                              <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={ts.temperature}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    themeKey,
                                    "temperature",
                                    parseFloat(e.target.value)
                                  )
                                }
                                className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-violet-500"
                              />
                              <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
                                <span>Precise (0.0)</span>
                                <span>Creative (1.0)</span>
                              </div>
                            </div>

                            {/* Tone */}
                            <div>
                              <label className="block text-[11px] font-medium text-gray-600 mb-1">
                                Tone
                              </label>
                              <Textarea
                                value={ts.tone}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    themeKey,
                                    "tone",
                                    e.target.value
                                  )
                                }
                                rows={2}
                                className="text-xs min-h-[48px]"
                                placeholder="e.g. Authoritative and evidence-driven..."
                              />
                            </div>

                            {/* Voice */}
                            <div>
                              <label className="block text-[11px] font-medium text-gray-600 mb-1">
                                Voice
                              </label>
                              <Textarea
                                value={ts.voice}
                                onChange={(e) =>
                                  updateThemeSetting(
                                    themeKey,
                                    "voice",
                                    e.target.value
                                  )
                                }
                                rows={2}
                                className="text-xs min-h-[48px]"
                                placeholder="e.g. Technical expert who translates complex science..."
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
        {!loading && (
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
