"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AgentConfig } from "@/lib/queries";
import { Save, CheckCircle, AlertCircle } from "lucide-react";

interface ConfigEditorProps {
  initialConfigs: Record<string, AgentConfig>;
}

const AGENTS = ["scout", "analyst", "drafter"] as const;
type AgentName = (typeof AGENTS)[number];

export function ConfigEditor({ initialConfigs }: ConfigEditorProps) {
  const [activeAgent, setActiveAgent] = useState<AgentName>("scout");
  const [drafts, setDrafts] = useState<Record<AgentName, string>>(() => {
    const result = {} as Record<AgentName, string>;
    for (const a of AGENTS) {
      const cfg = initialConfigs[a] || { agent: a };
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { _id, ...rest } = cfg as AgentConfig & { _id?: string };
      result[a] = JSON.stringify(rest, null, 2);
    }
    return result;
  });
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"ok" | "error" | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  function handleChange(value: string) {
    setDrafts((p) => ({ ...p, [activeAgent]: value }));
    setSaveResult(null);
    setParseError(null);
    try {
      JSON.parse(value);
    } catch {
      setParseError("Invalid JSON");
    }
  }

  async function handleSave() {
    if (parseError) return;
    setSaving(true);
    setSaveResult(null);

    try {
      const config = JSON.parse(drafts[activeAgent]);
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: activeAgent, config }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaveResult("ok");
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Agent tabs */}
      <div className="flex gap-2">
        {AGENTS.map((a) => (
          <button
            key={a}
            onClick={() => {
              setActiveAgent(a);
              setSaveResult(null);
              setParseError(null);
            }}
            className={`rounded-lg border px-4 py-2 text-sm font-medium capitalize transition-colors ${
              activeAgent === a
                ? "border-blue-600 bg-blue-600 text-white"
                : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
            }`}
          >
            {a}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="capitalize">{activeAgent} Configuration</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Textarea
            value={drafts[activeAgent]}
            onChange={(e) => handleChange(e.target.value)}
            rows={28}
            className="font-mono text-sm"
            spellCheck={false}
          />

          {parseError && (
            <div className="flex items-center gap-2 text-sm text-red-600">
              <AlertCircle className="h-4 w-4" />
              {parseError}
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button
              onClick={handleSave}
              loading={saving}
              disabled={!!parseError}
            >
              <Save className="h-4 w-4" />
              Save {activeAgent} config
            </Button>

            {saveResult === "ok" && (
              <span className="flex items-center gap-1 text-sm text-green-600">
                <CheckCircle className="h-4 w-4" />
                Saved
              </span>
            )}
            {saveResult === "error" && (
              <span className="text-sm text-red-600">Save failed — check console</span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
