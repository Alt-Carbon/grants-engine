"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import type { PipelineRecord, DraftSection } from "@/lib/queries";
import { CheckCircle, RotateCcw, ChevronRight, FileText } from "lucide-react";

interface DrafterViewProps {
  pipelines: PipelineRecord[];
}

const SECTION_ORDER = [
  "Executive Summary",
  "Problem Statement",
  "Solution Overview",
  "Impact & Theory of Change",
  "Team & Credentials",
  "Budget",
  "Conclusion",
];

export function DrafterView({ pipelines }: DrafterViewProps) {
  const [selectedId, setSelectedId] = useState<string>(pipelines[0]?._id ?? "");
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [instructions, setInstructions] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, "approved" | "revision">>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const selectedPipeline = pipelines.find((p) => p._id === selectedId);
  const sections: Record<string, DraftSection> =
    selectedPipeline?.latest_draft?.sections ?? {};

  const orderedSections = [
    ...SECTION_ORDER.filter((s) => s in sections),
    ...Object.keys(sections).filter((s) => !SECTION_ORDER.includes(s)),
  ];

  async function submitAction(
    sectionName: string,
    action: "approve" | "revise"
  ) {
    if (!selectedPipeline) return;
    const key = `${selectedId}-${sectionName}`;
    setSubmitting(key);
    setErrors((p) => ({ ...p, [key]: "" }));

    try {
      const res = await fetch("/api/drafter/section-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: selectedPipeline.thread_id,
          section_name: sectionName,
          action,
          edited_content: action === "approve" ? edits[key] || sections[sectionName]?.content : undefined,
          instructions: action === "revise" ? instructions[key] : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResults((p) => ({ ...p, [key]: action === "approve" ? "approved" : "revision" }));
    } catch (e) {
      setErrors((p) => ({
        ...p,
        [key]: e instanceof Error ? e.message : "Action failed",
      }));
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="flex h-full gap-4 overflow-hidden">
      {/* Left: grant list */}
      <div className="w-64 shrink-0 overflow-y-auto rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-100 px-3 py-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Active Drafts
          </p>
        </div>
        {pipelines.map((p) => (
          <button
            key={p._id}
            onClick={() => {
              setSelectedId(p._id);
              setActiveSection(null);
            }}
            className={`w-full px-3 py-3 text-left transition-colors hover:bg-gray-50 ${
              selectedId === p._id ? "bg-blue-50 border-r-2 border-r-blue-600" : ""
            }`}
          >
            <div className="flex items-start gap-2">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-purple-500" />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-900">
                  {p.grant_title || "Untitled"}
                </p>
                {p.grant_funder && (
                  <p className="truncate text-xs text-gray-500">{p.grant_funder}</p>
                )}
                <div className="mt-1">
                  <StatusBadge status={p.status} />
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Right: sections */}
      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Section tabs */}
        <div className="w-52 shrink-0 overflow-y-auto rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-100 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Sections
            </p>
          </div>
          {orderedSections.length === 0 && (
            <p className="px-3 py-4 text-xs text-gray-400">No sections yet</p>
          )}
          {orderedSections.map((name) => {
            const key = `${selectedId}-${name}`;
            const result = results[key];
            return (
              <button
                key={name}
                onClick={() => setActiveSection(name)}
                className={`flex w-full items-center justify-between px-3 py-2.5 text-left text-sm transition-colors hover:bg-gray-50 ${
                  activeSection === name ? "bg-blue-50 font-medium text-blue-700" : "text-gray-700"
                }`}
              >
                <span className="truncate">{name}</span>
                <div className="flex items-center gap-1 shrink-0">
                  {result === "approved" && (
                    <CheckCircle className="h-3.5 w-3.5 text-green-500" />
                  )}
                  {result === "revision" && (
                    <RotateCcw className="h-3.5 w-3.5 text-amber-500" />
                  )}
                  <ChevronRight className="h-3.5 w-3.5 text-gray-300" />
                </div>
              </button>
            );
          })}
        </div>

        {/* Section content */}
        <div className="flex-1 overflow-y-auto rounded-xl border border-gray-200 bg-white p-5">
          {!activeSection ? (
            <div className="flex h-full items-center justify-center text-gray-400">
              <div className="text-center">
                <FileText className="mx-auto mb-2 h-8 w-8 opacity-30" />
                <p>Select a section to review</p>
              </div>
            </div>
          ) : (
            <SectionEditor
              pipelineId={selectedId}
              sectionName={activeSection}
              section={sections[activeSection]}
              editValue={edits[`${selectedId}-${activeSection}`]}
              instructionValue={instructions[`${selectedId}-${activeSection}`]}
              onEditChange={(v) =>
                setEdits((p) => ({ ...p, [`${selectedId}-${activeSection}`]: v }))
              }
              onInstructionChange={(v) =>
                setInstructions((p) => ({ ...p, [`${selectedId}-${activeSection}`]: v }))
              }
              submitting={submitting === `${selectedId}-${activeSection}`}
              result={results[`${selectedId}-${activeSection}`]}
              error={errors[`${selectedId}-${activeSection}`]}
              onApprove={() => submitAction(activeSection, "approve")}
              onRevise={() => submitAction(activeSection, "revise")}
            />
          )}
        </div>
      </div>
    </div>
  );
}

interface SectionEditorProps {
  pipelineId: string;
  sectionName: string;
  section?: DraftSection;
  editValue?: string;
  instructionValue?: string;
  onEditChange: (v: string) => void;
  onInstructionChange: (v: string) => void;
  submitting: boolean;
  result?: "approved" | "revision";
  error?: string;
  onApprove: () => void;
  onRevise: () => void;
}

function SectionEditor({
  sectionName,
  section,
  editValue,
  instructionValue,
  onEditChange,
  onInstructionChange,
  submitting,
  result,
  error,
  onApprove,
  onRevise,
}: SectionEditorProps) {
  const [mode, setMode] = useState<"view" | "edit" | "revise">("view");
  const content = editValue ?? section?.content ?? "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">{sectionName}</h2>
        <div className="flex gap-2">
          {section?.word_count && (
            <span className="text-xs text-gray-400">{section.word_count} words</span>
          )}
          {result && (
            <span
              className={`text-xs font-medium ${
                result === "approved" ? "text-green-600" : "text-amber-600"
              }`}
            >
              {result === "approved" ? "✓ Approved" : "⟳ Revision requested"}
            </span>
          )}
        </div>
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 w-fit">
        {(["view", "edit", "revise"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1 text-xs font-medium capitalize transition-colors ${
              mode === m
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Content */}
      {mode === "view" && (
        <div className="prose prose-sm max-w-none rounded-lg bg-gray-50 p-4 text-gray-800">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
            {section?.content || "No content yet"}
          </pre>
        </div>
      )}

      {mode === "edit" && (
        <Textarea
          value={content}
          onChange={(e) => onEditChange(e.target.value)}
          rows={16}
          className="font-mono text-sm"
          placeholder="Edit the section content…"
        />
      )}

      {mode === "revise" && (
        <div className="space-y-3">
          <div className="rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
            <pre className="whitespace-pre-wrap font-sans leading-relaxed">
              {section?.content || "No content yet"}
            </pre>
          </div>
          <Textarea
            value={instructionValue || ""}
            onChange={(e) => onInstructionChange(e.target.value)}
            rows={4}
            placeholder="Instructions for revision (e.g., 'Shorten to 150 words', 'Emphasize SDG alignment')…"
          />
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}

      {/* Actions */}
      <div className="flex gap-3">
        <Button
          variant="success"
          size="sm"
          onClick={onApprove}
          loading={submitting}
          disabled={!!result}
        >
          <CheckCircle className="h-4 w-4" />
          Approve
        </Button>
        <Button
          variant="warning"
          size="sm"
          onClick={onRevise}
          loading={submitting}
          disabled={mode !== "revise" || !!result}
        >
          <RotateCcw className="h-4 w-4" />
          Request Revision
        </Button>
      </div>
    </div>
  );
}
