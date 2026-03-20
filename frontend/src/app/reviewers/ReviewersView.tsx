"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type {
  Grant, DraftReview, SectionReview,
  CoherenceReview, CoherenceIssue,
  ComplianceReview, ComplianceIssue,
  WritingQualityReview,
} from "@/lib/queries";
import {
  PlayCircle,
  Loader2,
  AlertTriangle,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  Banknote,
  FlaskConical,
  Trophy,
  Ban,
  Save,
  BookOpen,
  Settings,
  Download,
  FileText,
  Globe,
  ExternalLink,
  Wand2,
  Square,
  CheckSquare,
  Link2,
  Pencil,
  RotateCcw,
  ShieldCheck,
  Type,
} from "lucide-react";
import { ReviewerSettingsPanel } from "@/components/ReviewerSettingsPanel";
import { fetchDraftContent, generateDraftPdf, downloadDraftMarkdown } from "@/lib/generateDraftPdf";

// ── Helpers ──────────────────────────────────────────────────────────────────

function scoreColor(score: number) {
  if (score >= 8) return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (score >= 6) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-red-700 bg-red-50 border-red-200";
}

function scoreBg(score: number) {
  if (score >= 8) return "bg-emerald-500";
  if (score >= 6) return "bg-amber-500";
  return "bg-red-500";
}

const VERDICT_LABELS: Record<string, { label: string; color: string }> = {
  strong_submit: { label: "Strong Submit", color: "bg-emerald-100 text-emerald-800" },
  submit_with_revisions: { label: "Submit with Revisions", color: "bg-amber-100 text-amber-800" },
  major_revisions: { label: "Major Revisions", color: "bg-orange-100 text-orange-800" },
  reconsider: { label: "Reconsider", color: "bg-red-100 text-red-800" },
};

const COHERENCE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  contradiction: { label: "Contradiction", color: "text-red-700 bg-red-50" },
  budget_mismatch: { label: "Budget Mismatch", color: "text-orange-700 bg-orange-50" },
  unsupported_claim: { label: "Unsupported Claim", color: "text-amber-700 bg-amber-50" },
  repetition: { label: "Repetition", color: "text-blue-700 bg-blue-50" },
  missing_thread: { label: "Missing Thread", color: "text-purple-700 bg-purple-50" },
};

/** Build the canonical key for a suggestion in the accepted set */
function suggKey(perspective: string, section: string, suggestion: string) {
  return `${perspective}::${section}::${suggestion}`;
}

// ── Editable Suggestion Item ─────────────────────────────────────────────────

function EditableSuggestion({
  text,
  isAccepted,
  onToggle,
  onEdit,
}: {
  text: string;
  isAccepted: boolean;
  onToggle: () => void;
  onEdit: (oldText: string, newText: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(text);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commitEdit = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== text) {
      onEdit(text, trimmed);
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="rounded-md border border-purple-300 bg-purple-50 p-2">
        <textarea
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitEdit(); }
            if (e.key === "Escape") { setEditValue(text); setEditing(false); }
          }}
          rows={2}
          className="w-full rounded border border-purple-200 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-purple-400 resize-none"
        />
        <p className="mt-1 text-[10px] text-purple-500">Enter to save, Esc to cancel</p>
      </div>
    );
  }

  return (
    <div className="group flex w-full items-start gap-1">
      <button
        type="button"
        onClick={onToggle}
        className={`flex flex-1 items-start gap-2 text-sm text-left rounded-md px-2 py-1.5 transition-colors ${
          isAccepted
            ? "bg-purple-50 text-purple-800 border border-purple-200"
            : "text-gray-700 hover:bg-gray-50"
        }`}
      >
        {isAccepted ? (
          <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-purple-600" />
        ) : (
          <Square className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
        )}
        <span className="flex-1">{text}</span>
      </button>
      <button
        type="button"
        onClick={() => { setEditValue(text); setEditing(true); }}
        className="mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity rounded p-1 text-gray-400 hover:text-purple-600 hover:bg-purple-50"
        title="Edit suggestion before applying"
      >
        <Pencil className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── Section Review Card ──────────────────────────────────────────────────────

function SectionCard({
  name,
  review,
  perspective,
  acceptedSuggestions,
  onToggleSuggestion,
  onEditSuggestion,
  onSelectAllSection,
}: {
  name: string;
  review: SectionReview;
  perspective: string;
  acceptedSuggestions: Set<string>;
  onToggleSuggestion: (perspective: string, section: string, suggestion: string) => void;
  onEditSuggestion: (perspective: string, section: string, oldText: string, newText: string) => void;
  onSelectAllSection: (perspective: string, section: string, suggestions: string[], select: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const sectionSuggestions = review.suggestions ?? [];
  const acceptedCount = sectionSuggestions.filter((s) => acceptedSuggestions.has(suggKey(perspective, name, s))).length;
  const allSelected = sectionSuggestions.length > 0 && acceptedCount === sectionSuggestions.length;

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold text-white ${scoreBg(
            review.score
          )}`}
        >
          {review.score}
        </span>
        <span className="flex-1 text-sm font-medium text-gray-800 truncate">
          {name.replace(/_/g, " ")}
        </span>
        {acceptedCount > 0 && (
          <span className="rounded-full bg-purple-100 text-purple-700 px-2 py-0.5 text-[10px] font-semibold">
            {acceptedCount} accepted
          </span>
        )}
        {open ? (
          <ChevronUp className="h-4 w-4 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400" />
        )}
      </button>
      {open && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-3">
          {review.strengths?.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-600 mb-1">
                Strengths
              </p>
              <ul className="space-y-1">
                {review.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                    <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {review.issues?.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-red-600 mb-1">
                Issues
              </p>
              <ul className="space-y-1">
                {review.issues.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {sectionSuggestions.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-600">
                  Suggestions — click to accept
                </p>
                <button
                  type="button"
                  onClick={() => onSelectAllSection(perspective, name, sectionSuggestions, !allSelected)}
                  className="text-[10px] font-medium text-purple-600 hover:text-purple-800 transition-colors"
                >
                  {allSelected ? "Deselect All" : "Select All"}
                </button>
              </div>
              <ul className="space-y-1">
                {sectionSuggestions.map((s, i) => (
                  <li key={i}>
                    <EditableSuggestion
                      text={s}
                      isAccepted={acceptedSuggestions.has(suggKey(perspective, name, s))}
                      onToggle={() => onToggleSuggestion(perspective, name, s)}
                      onEdit={(oldText, newText) => onEditSuggestion(perspective, name, oldText, newText)}
                    />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Review Panel (one perspective) ───────────────────────────────────────────

function ReviewPanel({
  review,
  icon: Icon,
  label,
  acceptedSuggestions,
  onToggleSuggestion,
  onEditSuggestion,
  onSelectAllSection,
  onSelectAllPerspective,
}: {
  review: DraftReview;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  acceptedSuggestions: Set<string>;
  onToggleSuggestion: (perspective: string, section: string, suggestion: string) => void;
  onEditSuggestion: (perspective: string, section: string, oldText: string, newText: string) => void;
  onSelectAllSection: (perspective: string, section: string, suggestions: string[], select: boolean) => void;
  onSelectAllPerspective: (perspective: string, review: DraftReview, select: boolean) => void;
}) {
  const verdict = VERDICT_LABELS[review.verdict] || {
    label: review.verdict,
    color: "bg-gray-100 text-gray-700",
  };

  // Count total suggestions and accepted in this perspective
  const allSuggestions: string[] = [];
  for (const [secName, sr] of Object.entries(review.section_reviews || {})) {
    for (const s of sr.suggestions ?? []) {
      allSuggestions.push(suggKey(review.perspective, secName, s));
    }
  }
  const perspAccepted = allSuggestions.filter((k) => acceptedSuggestions.has(k)).length;
  const allPerspSelected = allSuggestions.length > 0 && perspAccepted === allSuggestions.length;

  return (
    <div className="flex-1 min-w-0 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100">
          <Icon className="h-5 w-5 text-gray-600" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-gray-900">{label}</h3>
          <p className="text-[11px] text-gray-400">
            v{review.draft_version} &middot;{" "}
            {new Date(review.created_at).toLocaleDateString()}
          </p>
        </div>
        {allSuggestions.length > 0 && (
          <button
            onClick={() => onSelectAllPerspective(review.perspective, review, !allPerspSelected)}
            className="text-[10px] font-semibold text-purple-600 hover:text-purple-800 border border-purple-200 rounded-md px-2 py-1 hover:bg-purple-50 transition-colors"
          >
            {allPerspSelected ? "Deselect All" : `Accept All (${allSuggestions.length})`}
          </button>
        )}
      </div>

      {/* Score + Verdict */}
      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center rounded-xl border px-3 py-1.5 text-lg font-bold ${scoreColor(
            review.overall_score
          )}`}
        >
          {review.overall_score.toFixed(1)}
          <span className="ml-1 text-xs font-medium opacity-60">/ 10</span>
        </span>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${verdict.color}`}
        >
          {verdict.label}
        </span>
      </div>

      {/* Summary */}
      <p className="text-sm leading-relaxed text-gray-700">{review.summary}</p>

      {/* Strengths */}
      {review.strengths?.length > 0 && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700 mb-2">
            Key Strengths
          </p>
          <ul className="space-y-1.5">
            {review.strengths.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-emerald-900">
                <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Top Issues */}
      {review.top_issues?.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-red-700 mb-2">
            Critical Issues
          </p>
          <ul className="space-y-1.5">
            {review.top_issues.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-red-900">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Research Insights */}
      {(review as any).research_insights?.length > 0 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700 mb-2 flex items-center gap-1.5">
            <Globe className="h-3 w-3" />
            Web Research Insights
          </p>
          <ul className="space-y-1.5">
            {(review as any).research_insights.map((s: string, i: number) => (
              <li key={i} className="flex items-start gap-2 text-sm text-blue-900">
                <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-500" />
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Section Breakdown */}
      {Object.keys(review.section_reviews || {}).length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Section Breakdown
          </p>
          <div className="space-y-2">
            {Object.entries(review.section_reviews).map(([name, sr]) => (
              <SectionCard
                key={name}
                name={name}
                review={sr}
                perspective={review.perspective}
                acceptedSuggestions={acceptedSuggestions}
                onToggleSuggestion={onToggleSuggestion}
                onEditSuggestion={onEditSuggestion}
                onSelectAllSection={onSelectAllSection}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Coherence Panel ─────────────────────────────────────────────────────────

function CoherencePanel({
  review,
  acceptedSuggestions,
  onToggleSuggestion,
  onEditSuggestion,
}: {
  review: CoherenceReview;
  acceptedSuggestions: Set<string>;
  onToggleSuggestion: (perspective: string, section: string, suggestion: string) => void;
  onEditSuggestion: (perspective: string, section: string, oldText: string, newText: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const issues = review.issues ?? [];
  const fixableIssues = issues.filter((i) => i.fix);

  return (
    <div className="mt-6 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100">
          <Link2 className="h-5 w-5 text-gray-600" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-gray-900">Coherence Review</h3>
          <p className="text-[11px] text-gray-400">
            Cross-section consistency &middot;{" "}
            {new Date(review.created_at).toLocaleDateString()}
          </p>
        </div>
        <span
          className={`inline-flex items-center rounded-xl border px-3 py-1 text-base font-bold ${scoreColor(
            review.coherence_score
          )}`}
        >
          {review.coherence_score.toFixed(1)}
          <span className="ml-1 text-xs font-medium opacity-60">/ 10</span>
        </span>
        {open ? (
          <ChevronUp className="h-4 w-4 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400" />
        )}
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4">
          {/* Assessment */}
          <p className="text-sm leading-relaxed text-gray-700">{review.overall_assessment}</p>

          {/* Narrative consistency badge */}
          <div className="flex items-center gap-2">
            {review.narrative_consistent ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                <CheckCircle className="h-3.5 w-3.5" />
                Narrative Consistent
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 text-xs font-semibold text-red-700">
                <XCircle className="h-3.5 w-3.5" />
                Narrative Inconsistent
              </span>
            )}
          </div>

          {/* Issues */}
          {issues.length > 0 && (
            <div className="space-y-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                Issues Found ({issues.length})
              </p>
              {issues.map((issue, i) => {
                const typeInfo = COHERENCE_TYPE_LABELS[issue.type] || {
                  label: issue.type,
                  color: "text-gray-700 bg-gray-50",
                };
                const fixKey = issue.fix ? suggKey("coherence", issue.sections_involved.join("+"), issue.fix) : "";
                const isAccepted = fixKey ? acceptedSuggestions.has(fixKey) : false;

                return (
                  <div key={i} className="rounded-lg border border-gray-200 p-3 space-y-2">
                    <div className="flex items-start gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                      {issue.sections_involved.length > 0 && (
                        <span className="text-[10px] text-gray-400">
                          {issue.sections_involved.map((s) => s.replace(/_/g, " ")).join(" / ")}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-700">{issue.description}</p>
                    {issue.fix && (
                      <div className="group flex items-start gap-1">
                        <button
                          type="button"
                          onClick={() => onToggleSuggestion("coherence", issue.sections_involved.join("+"), issue.fix)}
                          className={`flex flex-1 items-start gap-2 text-sm text-left rounded-md px-2 py-1.5 transition-colors ${
                            isAccepted
                              ? "bg-purple-50 text-purple-800 border border-purple-200"
                              : "text-gray-600 hover:bg-gray-50"
                          }`}
                        >
                          {isAccepted ? (
                            <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-purple-600" />
                          ) : (
                            <Square className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                          )}
                          <span className="flex-1">
                            <span className="font-medium text-purple-700">Fix: </span>
                            {issue.fix}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const newFix = prompt("Edit fix suggestion:", issue.fix);
                            if (newFix && newFix.trim() !== issue.fix) {
                              onEditSuggestion("coherence", issue.sections_involved.join("+"), issue.fix, newFix.trim());
                            }
                          }}
                          className="mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity rounded p-1 text-gray-400 hover:text-purple-600 hover:bg-purple-50"
                          title="Edit fix before applying"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {issues.length === 0 && (
            <p className="text-sm text-gray-400 italic">No coherence issues detected.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Compliance Panel ─────────────────────────────────────────────────────────

const COMPLIANCE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  missing_section: { label: "Missing Section", color: "text-red-700 bg-red-50" },
  word_limit: { label: "Word Limit", color: "text-orange-700 bg-orange-50" },
  eligibility: { label: "Eligibility", color: "text-amber-700 bg-amber-50" },
  placeholder: { label: "Placeholder", color: "text-purple-700 bg-purple-50" },
  budget: { label: "Budget", color: "text-blue-700 bg-blue-50" },
  timeline: { label: "Timeline", color: "text-gray-700 bg-gray-100" },
};

function CompliancePanel({
  review,
  acceptedSuggestions,
  onToggleSuggestion,
}: {
  review: ComplianceReview;
  acceptedSuggestions: Set<string>;
  onToggleSuggestion: (perspective: string, section: string, suggestion: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const issues = review.issues ?? [];

  return (
    <div className="mt-4 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100">
          <ShieldCheck className="h-5 w-5 text-gray-600" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-gray-900">Compliance Check</h3>
          <p className="text-[11px] text-gray-400">
            Word limits, required sections, eligibility, placeholders
          </p>
        </div>
        <div className="flex items-center gap-2">
          {review.all_sections_present ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
              All sections present
            </span>
          ) : (
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700">
              Missing sections
            </span>
          )}
          <span
            className={`inline-flex items-center rounded-xl border px-3 py-1 text-base font-bold ${scoreColor(
              review.compliance_score
            )}`}
          >
            {review.compliance_score.toFixed(1)}
            <span className="ml-1 text-xs font-medium opacity-60">/ 10</span>
          </span>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4">
          <p className="text-sm leading-relaxed text-gray-700">{review.overall_assessment}</p>

          {/* Quick status badges */}
          <div className="flex flex-wrap gap-2">
            {review.budget_in_range ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700">
                <CheckCircle className="h-3 w-3" /> Budget in range
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-[10px] font-semibold text-red-700">
                <XCircle className="h-3 w-3" /> Budget out of range
              </span>
            )}
            {(review.placeholder_markers?.length ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2.5 py-1 text-[10px] font-semibold text-purple-700">
                <AlertTriangle className="h-3 w-3" /> {review.placeholder_markers.length} placeholder(s) remaining
              </span>
            )}
            {(review.word_limit_violations?.length ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2.5 py-1 text-[10px] font-semibold text-orange-700">
                <AlertTriangle className="h-3 w-3" /> {review.word_limit_violations.length} word limit violation(s)
              </span>
            )}
          </div>

          {/* Issues with fixable suggestions */}
          {issues.length > 0 && (
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                Issues ({issues.length})
              </p>
              {issues.map((issue, i) => {
                const typeInfo = COMPLIANCE_TYPE_LABELS[issue.type] || { label: issue.type, color: "text-gray-700 bg-gray-50" };
                const fixKey = issue.fix ? suggKey("compliance", issue.type, issue.fix) : "";
                const isAccepted = fixKey ? acceptedSuggestions.has(fixKey) : false;

                return (
                  <div key={i} className="rounded-lg border border-gray-200 p-3 space-y-2">
                    <div className="flex items-start gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700">{issue.description}</p>
                    {issue.fix && (
                      <button
                        type="button"
                        onClick={() => onToggleSuggestion("compliance", issue.type, issue.fix)}
                        className={`flex w-full items-start gap-2 text-sm text-left rounded-md px-2 py-1.5 transition-colors ${
                          isAccepted
                            ? "bg-purple-50 text-purple-800 border border-purple-200"
                            : "text-gray-600 hover:bg-gray-50"
                        }`}
                      >
                        {isAccepted ? (
                          <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-purple-600" />
                        ) : (
                          <Square className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                        )}
                        <span className="flex-1">
                          <span className="font-medium text-purple-700">Fix: </span>
                          {issue.fix}
                        </span>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Writing Quality Panel ────────────────────────────────────────────────────

function WritingQualityPanel({
  review,
  acceptedSuggestions,
  onToggleSuggestion,
}: {
  review: WritingQualityReview;
  acceptedSuggestions: Set<string>;
  onToggleSuggestion: (perspective: string, section: string, suggestion: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const sectionEntries = Object.entries(review.section_reviews || {});

  return (
    <div className="mt-4 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100">
          <Type className="h-5 w-5 text-gray-600" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-bold text-gray-900">Writing Quality</h3>
          <p className="text-[11px] text-gray-400">
            Style rules, evidence density, voice consistency
          </p>
        </div>
        <div className="flex items-center gap-2">
          {review.total_violations === 0 ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
              All checks passed
            </span>
          ) : (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
              {review.total_violations} violation{review.total_violations !== 1 ? "s" : ""}
            </span>
          )}
          <span
            className={`inline-flex items-center rounded-xl border px-3 py-1 text-base font-bold ${scoreColor(
              review.writing_score
            )}`}
          >
            {review.writing_score.toFixed(1)}
            <span className="ml-1 text-xs font-medium opacity-60">/ 10</span>
          </span>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4">
          <p className="text-sm leading-relaxed text-gray-700">{review.overall_assessment}</p>

          {sectionEntries.length > 0 && (
            <div className="space-y-3">
              {sectionEntries.map(([secName, sr]) => (
                <div key={secName} className="rounded-lg border border-gray-200 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-800">{secName.replace(/_/g, " ")}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold text-white ${scoreBg(sr.score)}`}>
                      {sr.score}/10
                    </span>
                  </div>
                  {sr.issues.map((issue, i) => (
                    <p key={i} className="flex items-start gap-2 text-sm text-red-700">
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {issue}
                    </p>
                  ))}
                  {sr.suggestions.map((sug, i) => {
                    const key = suggKey("writing_quality", secName, sug);
                    const isAccepted = acceptedSuggestions.has(key);
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => onToggleSuggestion("writing_quality", secName, sug)}
                        className={`flex w-full items-start gap-2 text-sm text-left rounded-md px-2 py-1.5 transition-colors ${
                          isAccepted
                            ? "bg-purple-50 text-purple-800 border border-purple-200"
                            : "text-gray-600 hover:bg-gray-50"
                        }`}
                      >
                        {isAccepted ? (
                          <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-purple-600" />
                        ) : (
                          <Square className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                        )}
                        <span className="flex-1">{sug}</span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          {sectionEntries.length === 0 && (
            <p className="text-sm text-emerald-600 italic">No writing quality issues detected.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Apply Progress ──────────────────────────────────────────────────────────

function ApplyProgress({ sections }: { sections: string[] }) {
  return (
    <div className="space-y-1.5 mt-3">
      {sections.map((sec) => (
        <div key={sec} className="flex items-center gap-2 text-sm">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-purple-500" />
          <span className="text-gray-600">Revising {sec.replace(/_/g, " ")}...</span>
        </div>
      ))}
    </div>
  );
}

// ── Main View ────────────────────────────────────────────────────────────────

export function ReviewersView({ grants }: { grants: Grant[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(
    grants[0]?._id ?? null
  );
  const [reviews, setReviews] = useState<{
    funder: DraftReview | null;
    scientific: DraftReview | null;
    coherence: CoherenceReview | null;
    compliance: ComplianceReview | null;
    writing_quality: WritingQualityReview | null;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileListOpen, setMobileListOpen] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [acceptedSuggestions, setAcceptedSuggestions] = useState<Set<string>>(new Set());
  const [applyLoading, setApplyLoading] = useState(false);
  const [applyResult, setApplyResult] = useState<{ version: number; sections: string[] } | null>(null);
  const [applySections, setApplySections] = useState<string[]>([]);

  // Track user edits to suggestion text: maps original key -> edited text
  const [editedSuggestions, setEditedSuggestions] = useState<Map<string, string>>(new Map());

  const fetchReviews = useCallback(async (grantId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/review/${grantId}`);
      if (!res.ok) throw new Error("Failed to fetch reviews");
      const data = await res.json();
      setReviews(data);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) fetchReviews(selectedId);
  }, [selectedId, fetchReviews]);

  // Poll for results after triggering a review (max 60 attempts = 5 minutes)
  const [pollCount, setPollCount] = useState(0);
  useEffect(() => {
    if (!polling || !selectedId) return;
    const MAX_POLL_ATTEMPTS = 60;
    const interval = setInterval(async () => {
      setPollCount((c) => {
        const next = c + 1;
        if (next >= MAX_POLL_ATTEMPTS) {
          setPolling(false);
          setRunLoading(false);
          setError("Review timed out after 5 minutes. Please check back later or re-run.");
          return 0;
        }
        return next;
      });
      const data = await fetchReviews(selectedId);
      if (data?.funder && data?.scientific) {
        setPolling(false);
        setRunLoading(false);
        setPollCount(0);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [polling, selectedId, fetchReviews]);

  const runReview = useCallback(async () => {
    if (!selectedId) return;
    setRunLoading(true);
    setError(null);
    setApplyResult(null);
    try {
      const res = await fetch("/api/review/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: selectedId }),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(data?.detail || "Failed to start review");
        setRunLoading(false);
        return;
      }
      setPollCount(0);
      setPolling(true);
    } catch {
      setError("Network error");
      setRunLoading(false);
    }
  }, [selectedId]);

  const handleExport = useCallback(async (format: "pdf" | "md", mode: "submission" | "review") => {
    if (!selectedId) return;
    setPdfLoading(true);
    setExportMenuOpen(false);
    try {
      const data = await fetchDraftContent(selectedId);
      if (!data) {
        setError("Could not load draft content for export");
        return;
      }
      if (format === "pdf") {
        await generateDraftPdf(data, mode);
      } else {
        downloadDraftMarkdown(data, mode);
      }
    } catch {
      setError("Export failed");
    } finally {
      setPdfLoading(false);
    }
  }, [selectedId]);

  // ── Suggestion handlers ──────────────────────────────────────────────────

  const toggleSuggestion = useCallback((perspective: string, section: string, suggestion: string) => {
    const key = suggKey(perspective, section, suggestion);
    setAcceptedSuggestions((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setApplyResult(null);
  }, []);

  const editSuggestion = useCallback((perspective: string, section: string, oldText: string, newText: string) => {
    const oldKey = suggKey(perspective, section, oldText);
    const newKey = suggKey(perspective, section, newText);
    setAcceptedSuggestions((prev) => {
      const next = new Set(prev);
      if (next.has(oldKey)) {
        next.delete(oldKey);
        next.add(newKey);
      }
      return next;
    });
    setEditedSuggestions((prev) => {
      const next = new Map(prev);
      next.set(oldKey, newText);
      return next;
    });
    setApplyResult(null);
  }, []);

  const selectAllSection = useCallback((perspective: string, section: string, suggestions: string[], select: boolean) => {
    setAcceptedSuggestions((prev) => {
      const next = new Set(prev);
      for (const s of suggestions) {
        const key = suggKey(perspective, section, s);
        if (select) next.add(key);
        else next.delete(key);
      }
      return next;
    });
    setApplyResult(null);
  }, []);

  const selectAllPerspective = useCallback((perspective: string, review: DraftReview, select: boolean) => {
    setAcceptedSuggestions((prev) => {
      const next = new Set(prev);
      for (const [secName, sr] of Object.entries(review.section_reviews || {})) {
        for (const s of sr.suggestions ?? []) {
          const key = suggKey(perspective, secName, s);
          if (select) next.add(key);
          else next.delete(key);
        }
      }
      return next;
    });
    setApplyResult(null);
  }, []);

  const applySuggestions = useCallback(async () => {
    if (!selectedId || acceptedSuggestions.size === 0) return;
    setApplyLoading(true);
    setApplyResult(null);
    setError(null);

    // Build accepted map, applying any user edits
    const accepted: Record<string, Record<string, string[]>> = {};
    const sectionsInvolved: string[] = [];

    for (const key of acceptedSuggestions) {
      const [perspective, section, ...rest] = key.split("::");
      const originalText = rest.join("::");
      // Use edited text if the user modified this suggestion
      const finalText = editedSuggestions.get(suggKey(perspective, section, originalText)) || originalText;
      if (!accepted[perspective]) accepted[perspective] = {};
      if (!accepted[perspective][section]) {
        accepted[perspective][section] = [];
        sectionsInvolved.push(section);
      }
      accepted[perspective][section].push(finalText);
    }

    setApplySections(sectionsInvolved);

    try {
      const res = await fetch("/api/review/apply-suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: selectedId, accepted }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail || "Failed to apply suggestions");
        return;
      }
      setApplyResult({ version: data.new_version, sections: data.revised_sections });
      setAcceptedSuggestions(new Set());
      setEditedSuggestions(new Map());
    } catch {
      setError("Network error applying suggestions");
    } finally {
      setApplyLoading(false);
      setApplySections([]);
    }
  }, [selectedId, acceptedSuggestions, editedSuggestions]);

  // Reset state when switching grants
  useEffect(() => {
    setAcceptedSuggestions(new Set());
    setEditedSuggestions(new Map());
    setApplyResult(null);
    setApplySections([]);
  }, [selectedId]);

  const selectedGrant = grants.find((g) => g._id === selectedId);
  const hasReviews = reviews?.funder || reviews?.scientific;

  const grantListContent = (
    <>
      <div className="px-4 py-3 border-b border-gray-200">
        <h2 className="text-sm font-bold text-gray-900">Completed Drafts</h2>
        <p className="text-[11px] text-gray-500 mt-0.5">
          {grants.length} grant{grants.length !== 1 ? "s" : ""} ready for review
        </p>
      </div>
      {grants.map((g) => (
        <button
          key={g._id}
          onClick={() => {
            setSelectedId(g._id);
            setMobileListOpen(false);
          }}
          className={`flex w-full flex-col gap-1 border-b border-gray-100 px-4 py-3 text-left transition-colors ${
            selectedId === g._id
              ? "bg-white border-l-2 border-l-purple-600"
              : "hover:bg-white"
          }`}
        >
          <span className="text-sm font-medium text-gray-900 truncate">
            {g.grant_name || g.title || "Untitled"}
          </span>
          <span className="text-[11px] text-gray-500 truncate">
            {g.funder || "Unknown funder"}
          </span>
          {g.weighted_total != null && (
            <span
              className={`self-start rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                g.weighted_total >= 6.5
                  ? "bg-green-100 text-green-800"
                  : g.weighted_total >= 5
                  ? "bg-amber-100 text-amber-800"
                  : "bg-red-100 text-red-800"
              }`}
            >
              Score: {g.weighted_total.toFixed(1)}
            </span>
          )}
        </button>
      ))}
    </>
  );

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Mobile grant picker button */}
      <button
        onClick={() => setMobileListOpen(true)}
        className="fixed bottom-4 left-4 z-30 flex items-center gap-2 rounded-full bg-purple-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg lg:hidden"
      >
        <PlayCircle className="h-4 w-4" />
        {grants.find((g) => g._id === selectedId)?.grant_name?.slice(0, 20) || "Select Grant"}
      </button>

      {/* Mobile overlay */}
      {mobileListOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setMobileListOpen(false)}
        />
      )}

      {/* Left — Grant list (desktop: static, mobile: slide-over) */}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-72 border-r border-gray-200 bg-gray-50 overflow-y-auto transition-transform duration-200 lg:static lg:shrink-0 lg:translate-x-0 ${
          mobileListOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {grantListContent}
      </div>

      {/* Right — Review content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {!selectedGrant ? (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            Select a grant to view reviews
          </div>
        ) : (
          <div className="max-w-5xl mx-auto">
            {/* Header */}
            <div className="flex flex-col gap-3 mb-6 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <h1 className="text-lg font-bold text-gray-900 sm:text-xl truncate">
                  {selectedGrant.grant_name || selectedGrant.title}
                </h1>
                <p className="mt-1 text-sm text-gray-500 truncate">
                  {selectedGrant.funder}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {/* Export dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setExportMenuOpen((o) => !o)}
                    disabled={pdfLoading}
                    className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors disabled:opacity-50"
                    title="Download draft as PDF or Markdown"
                  >
                    {pdfLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    <span className="text-xs font-medium hidden sm:inline">Export</span>
                    <ChevronDown className="h-3 w-3" />
                  </button>
                  {exportMenuOpen && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setExportMenuOpen(false)} />
                      <div className="absolute right-0 top-full mt-1 z-50 w-56 rounded-lg border border-gray-200 bg-white shadow-lg py-1">
                        <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
                          Submission-ready (clean)
                        </p>
                        <button
                          onClick={() => handleExport("pdf", "submission")}
                          className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          <FileText className="h-4 w-4 text-red-500" />
                          Download PDF
                        </button>
                        <button
                          onClick={() => handleExport("md", "submission")}
                          className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          <FileText className="h-4 w-4 text-gray-500" />
                          Download Markdown
                        </button>
                        <div className="my-1 border-t border-gray-100" />
                        <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
                          Internal review copy
                        </p>
                        <button
                          onClick={() => handleExport("pdf", "review")}
                          className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          <FileText className="h-4 w-4 text-purple-500" />
                          PDF with word counts
                        </button>
                        <button
                          onClick={() => handleExport("md", "review")}
                          className="flex w-full items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                        >
                          <FileText className="h-4 w-4 text-gray-400" />
                          Markdown with word counts
                        </button>
                      </div>
                    </>
                  )}
                </div>

                <button
                  onClick={() => setSettingsOpen(true)}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
                  title="Review settings for this grant"
                >
                  <Settings className="h-4 w-4" />
                </button>
                <button
                  onClick={runReview}
                  disabled={runLoading}
                  className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-purple-700 disabled:opacity-50"
                >
                  {runLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <PlayCircle className="h-4 w-4" />
                  )}
                  {runLoading ? "Reviewing..." : hasReviews ? "Re-run Review" : "Run Review"}
                </button>
              </div>
            </div>

            {error && (
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
                <AlertTriangle className="h-4 w-4 shrink-0 text-red-500" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {/* Grant Details Bar */}
            <div className="mb-4 rounded-lg border border-gray-200 bg-white px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              {selectedGrant.funder && (
                <span className="text-gray-500">
                  <strong className="text-gray-700">Funder:</strong> {selectedGrant.funder}
                </span>
              )}
              {selectedGrant.deadline && (
                <span className="text-gray-500">
                  <strong className="text-gray-700">Deadline:</strong>{" "}
                  {new Date(selectedGrant.deadline).toLocaleDateString()}
                </span>
              )}
              {(selectedGrant.max_funding_usd || selectedGrant.max_funding) && (
                <span className="text-gray-500">
                  <strong className="text-gray-700">Funding:</strong>{" "}
                  ${Number(selectedGrant.max_funding_usd || selectedGrant.max_funding || 0).toLocaleString()}
                </span>
              )}
              {selectedGrant.url && (
                <a
                  href={selectedGrant.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-purple-600 hover:text-purple-800 font-medium"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Grant Page
                </a>
              )}
              {(reviews?.funder as any)?.web_research_used && (
                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                  <Globe className="h-3 w-3" />
                  Web Research Applied
                </span>
              )}
            </div>

            {loading && !hasReviews ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
              </div>
            ) : !hasReviews ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-purple-50">
                  <FlaskConical className="h-7 w-7 text-purple-400" />
                </div>
                <p className="text-base font-semibold text-gray-700">
                  No reviews yet
                </p>
                <p className="mt-1.5 text-sm text-gray-400">
                  Run a review to get funder and scientific perspectives
                </p>
              </div>
            ) : (
              <>
                {/* Funder + Scientific panels */}
                <div className="flex flex-col gap-6 lg:flex-row">
                  {reviews?.funder && (
                    <ReviewPanel
                      review={reviews.funder}
                      icon={Banknote}
                      label="Funder Perspective"
                      acceptedSuggestions={acceptedSuggestions}
                      onToggleSuggestion={toggleSuggestion}
                      onEditSuggestion={editSuggestion}
                      onSelectAllSection={selectAllSection}
                      onSelectAllPerspective={selectAllPerspective}
                    />
                  )}
                  {reviews?.scientific && (
                    <ReviewPanel
                      review={reviews.scientific}
                      icon={FlaskConical}
                      label="Scientific Perspective"
                      acceptedSuggestions={acceptedSuggestions}
                      onToggleSuggestion={toggleSuggestion}
                      onEditSuggestion={editSuggestion}
                      onSelectAllSection={selectAllSection}
                      onSelectAllPerspective={selectAllPerspective}
                    />
                  )}
                </div>

                {/* Coherence Panel */}
                {reviews?.coherence && (
                  <CoherencePanel
                    review={reviews.coherence}
                    acceptedSuggestions={acceptedSuggestions}
                    onToggleSuggestion={toggleSuggestion}
                    onEditSuggestion={editSuggestion}
                  />
                )}

                {/* Compliance Panel */}
                {reviews?.compliance && (
                  <CompliancePanel
                    review={reviews.compliance}
                    acceptedSuggestions={acceptedSuggestions}
                    onToggleSuggestion={toggleSuggestion}
                  />
                )}

                {/* Writing Quality Panel */}
                {reviews?.writing_quality && (
                  <WritingQualityPanel
                    review={reviews.writing_quality}
                    acceptedSuggestions={acceptedSuggestions}
                    onToggleSuggestion={toggleSuggestion}
                  />
                )}

                {/* Apply Suggestions Bar */}
                {(acceptedSuggestions.size > 0 || applyResult) && (
                  <div className="mt-4 rounded-xl border border-purple-200 bg-purple-50 px-5 py-4">
                    {applyResult ? (
                      <div className="space-y-3">
                        <div className="flex items-center gap-3">
                          <CheckCircle className="h-5 w-5 text-emerald-600 shrink-0" />
                          <div className="flex-1">
                            <p className="text-sm font-semibold text-gray-900">
                              Draft revised to v{applyResult.version}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5">
                              Sections updated: {applyResult.sections.map((s) => s.replace(/_/g, " ")).join(", ")}
                            </p>
                          </div>
                        </div>
                        {/* Re-review prompt */}
                        <div className="flex items-center gap-3 pt-2 border-t border-purple-200">
                          <p className="flex-1 text-xs text-purple-700">
                            Re-run the review to validate improvements on the revised draft.
                          </p>
                          <button
                            onClick={runReview}
                            disabled={runLoading}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-50 transition-colors"
                          >
                            {runLoading ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <RotateCcw className="h-3.5 w-3.5" />
                            )}
                            Re-run Review
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        <div className="flex items-center justify-between gap-4">
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-purple-900">
                              {acceptedSuggestions.size} suggestion{acceptedSuggestions.size !== 1 ? "s" : ""} selected
                            </p>
                            <p className="text-xs text-purple-600 mt-0.5">
                              Click &ldquo;Apply&rdquo; to revise the draft with accepted suggestions
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              onClick={() => { setAcceptedSuggestions(new Set()); setEditedSuggestions(new Map()); }}
                              className="rounded-lg border border-purple-200 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100 transition-colors"
                            >
                              Clear All
                            </button>
                            <button
                              onClick={applySuggestions}
                              disabled={applyLoading}
                              className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-purple-700 disabled:opacity-50"
                            >
                              {applyLoading ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Wand2 className="h-4 w-4" />
                              )}
                              {applyLoading ? "Applying..." : "Apply & Revise Draft"}
                            </button>
                          </div>
                        </div>
                        {/* Per-section progress during apply */}
                        {applyLoading && applySections.length > 0 && (
                          <ApplyProgress sections={applySections} />
                        )}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Outcome Recorder */}
            {selectedId && (
              <OutcomeRecorder grantId={selectedId} />
            )}
          </div>
        )}
      </div>

      {/* Per-grant reviewer settings panel */}
      <ReviewerSettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        grantId={selectedId}
      />
    </div>
  );
}

// ── Outcome Recorder ─────────────────────────────────────────────────────────

const OUTCOMES = [
  { value: "won", label: "Won", icon: Trophy, color: "emerald" },
  { value: "rejected", label: "Rejected", icon: Ban, color: "red" },
  { value: "shortlisted", label: "Shortlisted", icon: BookOpen, color: "amber" },
];

function OutcomeRecorder({ grantId }: { grantId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [outcome, setOutcome] = useState<string>("");
  const [feedback, setFeedback] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [existing, setExisting] = useState<string | null>(null);

  // Load existing outcome
  useEffect(() => {
    setOutcome("");
    setFeedback("");
    setSaved(false);
    setExisting(null);
    fetch(`/api/outcomes/${grantId}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.outcome) {
          setExisting(data.outcome);
          setOutcome(data.outcome);
          setFeedback(data.feedback || "");
        }
      })
      .catch(() => {});
  }, [grantId]);

  const handleSave = async () => {
    if (!outcome) return;
    setSaving(true);
    try {
      const res = await fetch("/api/outcomes/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grant_id: grantId,
          outcome,
          feedback,
        }),
      });
      if (res.ok) {
        setSaved(true);
        setExisting(outcome);
      }
    } catch {
      // silent
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-6 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setExpanded((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <BookOpen className="h-5 w-5 text-gray-400" />
        <span className="flex-1 text-sm font-semibold text-gray-800">
          Record Outcome
          {existing && (
            <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              existing === "won" ? "bg-emerald-100 text-emerald-700" :
              existing === "rejected" ? "bg-red-100 text-red-700" :
              "bg-amber-100 text-amber-700"
            }`}>
              {existing}
            </span>
          )}
        </span>
        <span className="text-[10px] text-gray-400">Feedback helps the drafter learn</span>
        {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-5 py-5 space-y-4">
          {/* Outcome selection */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2 block">
              What happened?
            </label>
            <div className="flex gap-2">
              {OUTCOMES.map((o) => {
                const selected = outcome === o.value;
                const Icon = o.icon;
                return (
                  <button
                    key={o.value}
                    onClick={() => setOutcome(o.value)}
                    className={`flex items-center gap-2 rounded-lg border-2 px-4 py-2 text-sm font-semibold transition-all ${
                      selected
                        ? o.color === "emerald"
                          ? "border-emerald-600 bg-emerald-50 text-emerald-700"
                          : o.color === "red"
                          ? "border-red-600 bg-red-50 text-red-700"
                          : "border-amber-600 bg-amber-50 text-amber-700"
                        : "border-gray-200 text-gray-600 hover:border-gray-300"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    {o.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Feedback */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5 block">
              Funder Feedback
            </label>
            <p className="text-[10px] text-gray-400 mb-2">
              Paste the funder&apos;s rejection/acceptance feedback. The system will extract lessons automatically.
            </p>
            <textarea
              value={feedback}
              onChange={(e) => { setFeedback(e.target.value); setSaved(false); }}
              rows={5}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder={
                outcome === "rejected"
                  ? "e.g., MRV section lacked specificity. Budget was not justified for the proposed scope. Team section did not demonstrate relevant experience in tropical deployments..."
                  : outcome === "won"
                  ? "e.g., Strong technical approach. MRV methodology was particularly compelling. Budget was well-justified..."
                  : "Paste any feedback from the funder..."
              }
            />
          </div>

          {/* Save */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={!outcome || saving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? "Saving..." : "Save & Extract Lessons"}
            </button>
            {saved && (
              <span className="flex items-center gap-1.5 text-sm font-medium text-green-600">
                <CheckCircle className="h-4 w-4" />
                Saved — lessons will be used in future drafts
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
