"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  X,
  Settings,
  Loader2,
  RotateCcw,
  Save,
  Info,
  ShieldCheck,
  Scale,
  Flame,
  Plus,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReviewerSettingsData {
  funder_strictness?: string;
  scientific_strictness?: string;
  funder_focus_areas?: string[];
  scientific_focus_areas?: string[];
  custom_criteria?: string[];
  custom_instructions?: string;
  is_default?: boolean;
}

interface ReviewerSettingsPanelProps {
  open: boolean;
  onClose: () => void;
  grantId: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STRICTNESS_OPTIONS = [
  {
    value: "lenient",
    label: "Lenient",
    icon: ShieldCheck,
    description: "Encouraging. Scores generously, focuses on potential.",
    colorClass: "border-emerald-600 bg-emerald-50 text-emerald-700",
    iconColor: "text-emerald-600",
  },
  {
    value: "balanced",
    label: "Balanced",
    icon: Scale,
    description: "Fair and constructive. Realistic scoring.",
    colorClass: "border-blue-600 bg-blue-50 text-blue-700",
    iconColor: "text-blue-600",
  },
  {
    value: "strict",
    label: "Strict",
    icon: Flame,
    description: "Demanding. Every weakness matters.",
    colorClass: "border-red-600 bg-red-50 text-red-700",
    iconColor: "text-red-600",
  },
];

// ---------------------------------------------------------------------------
// Editable List (inline, compact)
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
    <div className="space-y-1.5">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input
            type="text"
            value={item}
            onChange={(e) => {
              const updated = [...items];
              updated[i] = e.target.value;
              onChange(updated);
            }}
            className="flex-1 rounded-md border border-gray-200 px-2.5 py-1 text-xs focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-200"
          />
          <button
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-1.5">
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
          className="flex-1 rounded-md border border-dashed border-gray-300 px-2.5 py-1 text-xs placeholder:text-gray-400 focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-200"
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
          className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-purple-50 hover:text-purple-600 transition-colors disabled:opacity-30"
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strictness Picker (compact horizontal)
// ---------------------------------------------------------------------------

function StrictnessPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {STRICTNESS_OPTIONS.map((opt) => {
        const selected = value === opt.value;
        const Icon = opt.icon;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`flex flex-col items-center gap-1 rounded-lg border-2 p-2 text-center transition-all ${
              selected ? opt.colorClass : "border-gray-200 text-gray-500 hover:border-gray-300"
            }`}
          >
            <Icon className={`h-4 w-4 ${selected ? opt.iconColor : "text-gray-400"}`} />
            <span className="text-[10px] font-bold">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ReviewerSettingsPanel({
  open,
  onClose,
  grantId,
}: ReviewerSettingsPanelProps) {
  const [config, setConfig] = useState<ReviewerSettingsData>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
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
        `/api/grants/${encodeURIComponent(grantId)}/reviewer-settings`
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
      const { is_default, ...rest } = config;
      void is_default; // unused
      await fetch(
        `/api/grants/${encodeURIComponent(grantId)}/reviewer-settings`,
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
        `/api/grants/${encodeURIComponent(grantId)}/reviewer-settings`,
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

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/10 backdrop-blur-[1px]"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="fixed right-0 top-0 bottom-0 z-40 flex w-[360px] flex-col border-l border-gray-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4 text-purple-500" />
            <span className="text-sm font-semibold text-gray-700">
              Review Settings
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
                : "bg-purple-50 text-purple-700"
            }`}
          >
            <Info className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
            <span>
              {isDefault
                ? "Using global defaults. Changes here apply only to this grant."
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
                Select a grant to configure review settings
              </p>
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-gray-300" />
              <p className="mt-2 text-sm text-gray-400">Loading settings...</p>
            </div>
          ) : (
            <div className="px-4 py-4 space-y-5">
              {/* -- Funder Strictness ---------------------------------------- */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-600 mb-2">
                  Funder Reviewer
                </p>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Scoring Strictness
                </label>
                <StrictnessPicker
                  value={config.funder_strictness || "balanced"}
                  onChange={(v) => updateField("funder_strictness", v)}
                />

                {/* Funder Focus Areas */}
                <label className="block text-xs font-medium text-gray-600 mt-3 mb-1">
                  Focus Areas
                </label>
                <EditableListCompact
                  items={config.funder_focus_areas || []}
                  onChange={(items) => updateField("funder_focus_areas", items)}
                  placeholder="Add funder focus area..."
                />
              </div>

              {/* -- Scientific Strictness ------------------------------------ */}
              <div className="border-t border-gray-100 pt-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600 mb-2">
                  Scientific Reviewer
                </p>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Scoring Strictness
                </label>
                <StrictnessPicker
                  value={config.scientific_strictness || "balanced"}
                  onChange={(v) => updateField("scientific_strictness", v)}
                />

                {/* Scientific Focus Areas */}
                <label className="block text-xs font-medium text-gray-600 mt-3 mb-1">
                  Focus Areas
                </label>
                <EditableListCompact
                  items={config.scientific_focus_areas || []}
                  onChange={(items) =>
                    updateField("scientific_focus_areas", items)
                  }
                  placeholder="Add scientific focus area..."
                />
              </div>

              {/* -- Shared Settings ----------------------------------------- */}
              <div className="border-t border-gray-100 pt-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Shared (Both Perspectives)
                </p>

                {/* Custom Criteria */}
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Additional Evaluation Criteria
                </label>
                <p className="text-[10px] text-gray-400 mb-1.5">
                  Extra criteria applied to both reviewer perspectives.
                </p>
                <EditableListCompact
                  items={config.custom_criteria || []}
                  onChange={(items) => updateField("custom_criteria", items)}
                  placeholder="e.g., Does the proposal address data sovereignty?"
                />

                {/* Custom Instructions */}
                <label className="block text-xs font-medium text-gray-600 mt-3 mb-1">
                  Custom Instructions
                </label>
                <Textarea
                  value={config.custom_instructions || ""}
                  onChange={(e) =>
                    updateField("custom_instructions", e.target.value)
                  }
                  placeholder="Add any custom instructions for both reviewer agents..."
                  rows={3}
                  className="text-sm"
                />
                <p className="mt-1 text-[10px] text-gray-400">
                  Injected into both funder and scientific review prompts.
                </p>
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
              Reset to defaults
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={handleSave}
              disabled={saving || !dirty}
              className="ml-auto gap-1.5 bg-purple-600 hover:bg-purple-700"
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
