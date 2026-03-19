"use client";

import { useState, useCallback, useEffect } from "react";
import type { Grant, DraftReview, SectionReview } from "@/lib/queries";
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
} from "lucide-react";
import { ReviewerSettingsPanel } from "@/components/ReviewerSettingsPanel";

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

// ── Section Review Card ──────────────────────────────────────────────────────

function SectionCard({ name, review }: { name: string; review: SectionReview }) {
  const [open, setOpen] = useState(false);
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
          {review.suggestions?.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-600 mb-1">
                Suggestions
              </p>
              <ul className="space-y-1">
                {review.suggestions.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                    <span className="mt-0.5 shrink-0 text-blue-500 font-bold">&rarr;</span>
                    {s}
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
}: {
  review: DraftReview;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  const verdict = VERDICT_LABELS[review.verdict] || {
    label: review.verdict,
    color: "bg-gray-100 text-gray-700",
  };

  return (
    <div className="flex-1 min-w-0 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gray-100">
          <Icon className="h-5 w-5 text-gray-600" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-900">{label}</h3>
          <p className="text-[11px] text-gray-400">
            v{review.draft_version} &middot;{" "}
            {new Date(review.created_at).toLocaleDateString()}
          </p>
        </div>
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

      {/* Section Breakdown */}
      {Object.keys(review.section_reviews || {}).length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Section Breakdown
          </p>
          <div className="space-y-2">
            {Object.entries(review.section_reviews).map(([name, sr]) => (
              <SectionCard key={name} name={name} review={sr} />
            ))}
          </div>
        </div>
      )}
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
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  // Poll for results after triggering a review
  useEffect(() => {
    if (!polling || !selectedId) return;
    const interval = setInterval(async () => {
      const data = await fetchReviews(selectedId);
      if (data?.funder && data?.scientific) {
        setPolling(false);
        setRunLoading(false);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [polling, selectedId, fetchReviews]);

  const runReview = useCallback(async () => {
    if (!selectedId) return;
    setRunLoading(true);
    setError(null);
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
      // Start polling for results
      setPolling(true);
    } catch {
      setError("Network error");
      setRunLoading(false);
    }
  }, [selectedId]);

  const selectedGrant = grants.find((g) => g._id === selectedId);
  const hasReviews = reviews?.funder || reviews?.scientific;

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left — Grant list */}
      <div className="w-72 shrink-0 border-r border-gray-200 bg-gray-50 overflow-y-auto">
        <div className="px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-bold text-gray-900">Completed Drafts</h2>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {grants.length} grant{grants.length !== 1 ? "s" : ""} ready for review
          </p>
        </div>
        {grants.map((g) => (
          <button
            key={g._id}
            onClick={() => setSelectedId(g._id)}
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
      </div>

      {/* Right — Review content */}
      <div className="flex-1 overflow-y-auto p-6">
        {!selectedGrant ? (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            Select a grant to view reviews
          </div>
        ) : (
          <div className="max-w-5xl mx-auto">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 mb-6">
              <div>
                <h1 className="text-xl font-bold text-gray-900">
                  {selectedGrant.grant_name || selectedGrant.title}
                </h1>
                <p className="mt-1 text-sm text-gray-500">
                  {selectedGrant.funder}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
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
              <div className="flex gap-6">
                {reviews?.funder && (
                  <ReviewPanel
                    review={reviews.funder}
                    icon={Banknote}
                    label="Funder Perspective"
                  />
                )}
                {reviews?.scientific && (
                  <ReviewPanel
                    review={reviews.scientific}
                    icon={FlaskConical}
                    label="Scientific Perspective"
                  />
                )}
              </div>
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
