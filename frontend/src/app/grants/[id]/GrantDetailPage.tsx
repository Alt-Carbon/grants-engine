"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ScoreRadar } from "@/components/ScoreRadar";
import { StatusPicker } from "@/components/StatusPicker";
import { CommentThread } from "@/components/CommentThread";
import { GrantActivity } from "@/components/GrantActivity";
import { formatCurrency as formatCurrencyUtil } from "@/lib/utils";
import {
  ArrowLeft,
  ExternalLink,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Clock,
  DollarSign,
  Globe,
  FileText,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  History,
  Sparkles,
  Shield,
  Target,
  Users,
  Calendar,
  Tag,
  Copy,
  Check,
  Info,
  Banknote,
  ClipboardList,
  Link2,
  Loader2,
  PlayCircle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface EligibilityCheck {
  criterion: string;
  altcarbon_status: "met" | "likely_met" | "verify" | "not_met";
  note: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GrantFull = Record<string, any>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const STATUS_ICON: Record<string, string> = {
  met: "\u2705",
  likely_met: "\ud83d\udfe1",
  verify: "\ud83d\udd0d",
  not_met: "\u274c",
};

const STATUS_LABEL: Record<string, string> = {
  met: "Met",
  likely_met: "Likely Met",
  verify: "Needs Verification",
  not_met: "Not Met",
};

const STATUS_BG: Record<string, string> = {
  met: "bg-green-50 border-green-200",
  likely_met: "bg-amber-50 border-amber-200",
  verify: "bg-blue-50 border-blue-200",
  not_met: "bg-red-50 border-red-200",
};

function priorityColor(score: number) {
  if (score >= 6.5) return { bg: "bg-green-500", text: "text-green-700", label: "High Priority", ring: "ring-green-200" };
  if (score >= 5.0) return { bg: "bg-amber-500", text: "text-amber-700", label: "Medium Priority", ring: "ring-amber-200" };
  return { bg: "bg-red-500", text: "text-red-700", label: "Low Priority", ring: "ring-red-200" };
}

const formatCurrency = formatCurrencyUtil;

// ---------------------------------------------------------------------------
// Collapsible Section
// ---------------------------------------------------------------------------
function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = true,
  badge,
}: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-gray-50"
      >
        {Icon && <Icon className="h-5 w-5 text-gray-400" />}
        <span className="flex-1 text-sm font-semibold text-gray-800">{title}</span>
        {badge}
        {open ? (
          <ChevronUp className="h-4 w-4 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400" />
        )}
      </button>
      {open && <div className="border-t border-gray-100 px-5 py-4">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Score Bar
// ---------------------------------------------------------------------------
function ScoreBar({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const color =
    value >= 7 ? "bg-green-500" : value >= 5 ? "bg-amber-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 text-sm text-gray-600 shrink-0">{label}</span>
      <div className="flex-1 h-2.5 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 text-right text-sm font-semibold text-gray-800">{value}/{max}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
export function GrantDetailPage({ grant }: { grant: GrantFull }) {
  const router = useRouter();
  const [currentStatus, setCurrentStatus] = useState(grant.status);
  const [copied, setCopied] = useState(false);
  const [collabTab, setCollabTab] = useState<"discussion" | "activity">("discussion");
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const name = grant.grant_name || grant.title || "Grant Details";
  const score = grant.weighted_total ?? 0;
  const funding = grant.max_funding_usd || grant.max_funding;
  const priority = priorityColor(score);
  const da = grant.deep_analysis || {};
  const pw = (grant.past_winners?.winners?.length ? grant.past_winners : da.past_winners) || {};

  const handleStatusChange = useCallback(
    async (_grantId: string, newStatus: string) => {
      try {
        const res = await fetch("/api/grants/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ grantId: grant._id, status: newStatus }),
        });
        if (res.ok) setCurrentStatus(newStatus);
      } catch (e) {
        console.error("Failed to update grant status:", e);
      }
    },
    [grant._id]
  );

  const copyLink = useCallback(() => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  const startDraft = useCallback(async () => {
    setDraftLoading(true);
    setDraftError(null);
    try {
      const res = await fetch("/api/drafter/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: grant._id }),
      });
      const data = await res.json();
      if (!res.ok) {
        setDraftError(data?.detail?.reason || data?.detail || data?.error || "Failed to start draft");
        return;
      }
      setCurrentStatus("drafting");
      router.push("/drafter");
    } catch {
      setDraftError("Network error — could not reach the server");
    } finally {
      setDraftLoading(false);
    }
  }, [grant._id, router]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Top bar ──────────────────────────────────────────────── */}
      <div className="sticky top-0 z-30 border-b border-gray-200 bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3 sm:px-6">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <div className="flex-1" />
          <button
            onClick={copyLink}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
          >
            {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied!" : "Share"}
          </button>
          {grant.application_url && (
            <a
              href={grant.application_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-green-700"
            >
              <FileText className="h-4 w-4" />
              Apply Now
            </a>
          )}
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        {/* ── Hero header ──────────────────────────────────────── */}
        <div className="mb-6 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-gray-900 leading-tight sm:text-3xl">
                {name}
              </h1>
              {grant.funder && (
                <p className="mt-1.5 text-base text-gray-500">by {grant.funder}</p>
              )}
            </div>

            {/* Score circle */}
            <div className="flex flex-col items-center shrink-0">
              <div
                className={`flex h-20 w-20 items-center justify-center rounded-full ring-4 ${priority.ring} ${
                  score >= 6.5
                    ? "bg-green-50"
                    : score >= 5.0
                    ? "bg-amber-50"
                    : "bg-red-50"
                }`}
              >
                <div className="text-center">
                  <p className={`text-2xl font-bold ${priority.text}`}>
                    {score.toFixed(1)}
                  </p>
                  <p className="text-[10px] text-gray-400 font-medium">/ 10</p>
                </div>
              </div>
              <span className={`mt-1.5 text-xs font-semibold ${priority.text}`}>
                {priority.label}
              </span>
            </div>
          </div>

          {/* Status + meta tags */}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <StatusPicker
              status={currentStatus}
              grantId={grant._id}
              onStatusChange={handleStatusChange}
              size="md"
            />
            {grant.deadline_urgent && (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">
                <Clock className="h-3 w-3" />
                {grant.days_to_deadline !== undefined
                  ? `${grant.days_to_deadline} days left`
                  : "Urgent"}
              </span>
            )}
            {grant.recommended_action && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">
                <Sparkles className="h-3 w-3" />
                AI says: {grant.recommended_action}
              </span>
            )}
            {grant.human_override && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
                <Shield className="h-3 w-3" />
                Override applied
              </span>
            )}
            {(currentStatus === "pursue" || currentStatus === "pursuing") && (
              <button
                onClick={startDraft}
                disabled={draftLoading}
                className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-purple-700 disabled:opacity-50"
              >
                {draftLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <PlayCircle className="h-3.5 w-3.5" />
                )}
                {draftLoading ? "Starting..." : "Start Draft"}
              </button>
            )}
            {currentStatus === "drafting" && (
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-2.5 py-1 text-xs font-semibold text-purple-700">
                <FileText className="h-3 w-3" />
                Drafting in progress
              </span>
            )}
          </div>
          {draftError && (
            <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5">
              <AlertTriangle className="h-4 w-4 shrink-0 text-red-500" />
              <p className="text-sm text-red-700">{draftError}</p>
            </div>
          )}

          {/* Quick facts grid */}
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              {
                icon: DollarSign,
                label: "Funding",
                value: formatCurrency(funding) || grant.amount || "Not specified",
                sub: grant.currency && grant.currency !== "USD" ? `(${grant.currency})` : "",
              },
              {
                icon: Calendar,
                label: "Deadline",
                value: grant.deadline
                  ? (() => {
                      try {
                        const d = new Date(grant.deadline);
                        return isNaN(d.getTime()) ? grant.deadline : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
                      } catch { return grant.deadline; }
                    })()
                  : "Rolling / TBD",
                sub: grant.days_to_deadline !== undefined ? `${grant.days_to_deadline}d left` : "",
              },
              {
                icon: Globe,
                label: "Geography",
                value: grant.geography || "Global",
                sub: "",
              },
              {
                icon: Tag,
                label: "Type",
                value: (grant.grant_type || "Grant").replace(/_/g, " "),
                sub: "",
              },
            ].map(({ icon: Icon, label, value, sub }) => (
              <div
                key={label}
                className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3"
              >
                <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-gray-400">
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </div>
                <p className="mt-1 text-sm font-semibold text-gray-900 truncate" title={value}>
                  {value}
                </p>
                {sub && <p className="text-[11px] text-gray-400">{sub}</p>}
              </div>
            ))}
          </div>

          {/* Links */}
          <div className="mt-4 flex flex-wrap gap-2">
            {grant.url && (
              <a
                href={grant.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Grant Page
              </a>
            )}
            {grant.application_url && grant.application_url !== grant.url && (
              <a
                href={grant.application_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-sm font-medium text-green-700 transition-colors hover:bg-green-100"
              >
                <FileText className="h-3.5 w-3.5" />
                Application Portal
              </a>
            )}
            {da.contact?.email && (
              <a
                href={`mailto:${da.contact.email}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900"
              >
                @&nbsp;{da.contact.email}
              </a>
            )}
          </div>
        </div>

        {/* ── Two-column layout ──────────────────────────────── */}
        <div className="grid gap-6 xl:grid-cols-[1fr_280px]">
          {/* Left — main content */}
          <div className="space-y-4 min-w-0">

            {/* AI Summary */}
            {(grant.rationale || grant.reasoning) && (
              <Section title="AI Summary" icon={Sparkles}>
                {grant.rationale && (
                  <p className="text-sm leading-relaxed text-gray-700">{grant.rationale}</p>
                )}
                {grant.reasoning && grant.reasoning !== grant.rationale && (
                  <p className="mt-3 rounded-lg bg-gray-50 p-3 text-sm italic text-gray-500">
                    {grant.reasoning}
                  </p>
                )}
              </Section>
            )}

            {/* Score Breakdown */}
            {grant.scores && Object.keys(grant.scores).length > 0 && (
              <Section title="Score Breakdown" icon={Target}>
                <div className="grid gap-6 sm:grid-cols-2">
                  <div className="space-y-3">
                    {Object.entries(grant.scores as Record<string, number>)
                      .filter(([, v]) => typeof v === "number")
                      .map(([key, value]) => (
                        <ScoreBar
                          key={key}
                          label={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                          value={value}
                        />
                      ))}
                  </div>
                  <div className="flex items-center justify-center">
                    <ScoreRadar scores={grant.scores} height={200} />
                  </div>
                </div>
              </Section>
            )}

            {/* Eligibility */}
            {grant.eligibility && (
              <Section title="Eligibility" icon={CheckCircle}>
                <p className="text-sm leading-relaxed text-gray-700">{grant.eligibility}</p>
              </Section>
            )}

            {/* Eligibility Checklist */}
            {da.eligibility_checklist && da.eligibility_checklist.length > 0 && (
              <Section
                title="Eligibility Checklist"
                icon={CheckCircle}
                badge={
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                    {da.eligibility_checklist.filter((c: EligibilityCheck) => c.altcarbon_status === "met").length}
                    /{da.eligibility_checklist.length} met
                  </span>
                }
              >
                <div className="space-y-2">
                  {da.eligibility_checklist.map((c: EligibilityCheck, i: number) => (
                    <div
                      key={i}
                      className={`rounded-lg border p-3 ${STATUS_BG[c.altcarbon_status] || "bg-gray-50 border-gray-200"}`}
                    >
                      <div className="flex items-start gap-2.5">
                        <span className="text-lg shrink-0">{STATUS_ICON[c.altcarbon_status] || "\u2753"}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900">{c.criterion}</p>
                          {c.note && (
                            <p className="mt-0.5 text-xs text-gray-500">{c.note}</p>
                          )}
                        </div>
                        <span className="shrink-0 text-[10px] font-medium text-gray-400 uppercase">
                          {STATUS_LABEL[c.altcarbon_status] || c.altcarbon_status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Evidence */}
            {((grant.evidence_found?.length ?? 0) > 0 ||
              (grant.evidence_gaps?.length ?? 0) > 0) && (
              <Section title="Evidence" icon={CheckCircle} defaultOpen={false}>
                <div className="grid gap-4 sm:grid-cols-2">
                  {grant.evidence_found && grant.evidence_found.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-green-700">
                        Supporting Evidence
                      </p>
                      <ul className="space-y-1.5">
                        {grant.evidence_found.map((e: string, i: number) => (
                          <li
                            key={i}
                            className="flex items-start gap-2 text-sm text-gray-700"
                          >
                            <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                            {e}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {grant.evidence_gaps && grant.evidence_gaps.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700">
                        Gaps to Address
                      </p>
                      <ul className="space-y-1.5">
                        {grant.evidence_gaps.map((e: string, i: number) => (
                          <li
                            key={i}
                            className="flex items-start gap-2 text-sm text-gray-700"
                          >
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                            {e}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </Section>
            )}

            {/* Red Flags */}
            {grant.red_flags && grant.red_flags.length > 0 && (
              <Section title="Red Flags" icon={XCircle} defaultOpen={false}>
                <div className="space-y-2">
                  {grant.red_flags.map((r: string, i: number) => (
                    <div
                      key={i}
                      className="flex items-start gap-2.5 rounded-lg border border-red-100 bg-red-50 p-3"
                    >
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                      <p className="text-sm text-red-800">{r}</p>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Strategic Advice */}
            {(da.strategic_angle || (da.application_tips?.length ?? 0) > 0) && (
              <Section title="Strategy & Tips" icon={Sparkles} defaultOpen={false}>
                {da.strategic_angle && (
                  <p className="text-sm leading-relaxed text-gray-700">{da.strategic_angle}</p>
                )}
                {da.application_tips && da.application_tips.length > 0 && (
                  <div className="mt-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-700">
                      Application Tips
                    </p>
                    <ul className="space-y-1.5">
                      {da.application_tips.map((t: string, i: number) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 text-sm text-gray-700"
                        >
                          <span className="mt-0.5 shrink-0 text-blue-500 font-bold">\u2192</span>
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Section>
            )}

            {/* Requirements */}
            {da.requirements && (
              <Section title="Requirements" icon={FileText} defaultOpen={false}>
                <dl className="space-y-4 text-sm">
                  {da.requirements.submission_format && (
                    <div>
                      <dt className="font-semibold text-gray-700">Submission Format</dt>
                      <dd className="mt-0.5 text-gray-600">{da.requirements.submission_format}</dd>
                    </div>
                  )}
                  {da.requirements.word_page_limits && (
                    <div>
                      <dt className="font-semibold text-gray-700">Word / Page Limits</dt>
                      <dd className="mt-0.5 text-gray-600">{da.requirements.word_page_limits}</dd>
                    </div>
                  )}
                  {da.requirements.co_funding_required && (
                    <div>
                      <dt className="font-semibold text-gray-700">Co-funding Required</dt>
                      <dd className="mt-0.5 text-gray-600">{da.requirements.co_funding_required}</dd>
                    </div>
                  )}
                  {da.requirements.documents_needed &&
                    da.requirements.documents_needed.length > 0 && (
                      <div>
                        <dt className="mb-1.5 font-semibold text-gray-700">Documents Needed</dt>
                        <ul className="space-y-1">
                          {da.requirements.documents_needed.map((d: string, i: number) => (
                            <li key={i} className="flex items-start gap-2 text-gray-600">
                              <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" />
                              {d}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                </dl>
              </Section>
            )}

            {/* Key Dates */}
            {da.key_dates && Object.values(da.key_dates).some(Boolean) && (
              <Section title="Key Dates" icon={Calendar} defaultOpen={false}>
                <div className="grid grid-cols-2 gap-3">
                  {Object.entries(da.key_dates as Record<string, string>)
                    .filter(([, v]) => v)
                    .map(([k, v]) => (
                      <div key={k} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
                        <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                          {k.replace(/_/g, " ")}
                        </p>
                        <p className="mt-0.5 text-sm font-semibold text-gray-900">{v}</p>
                      </div>
                    ))}
                </div>
              </Section>
            )}

            {/* Opportunity Summary */}
            {grant.about_opportunity && (
              <Section title="About This Opportunity" icon={Info}>
                <p className="text-sm leading-relaxed text-gray-700 whitespace-pre-line">
                  {grant.about_opportunity}
                </p>
              </Section>
            )}

            {/* Application Process */}
            {grant.application_process && (
              <Section title="Application Process" icon={ClipboardList} defaultOpen={false}>
                <p className="text-sm leading-relaxed text-gray-700 whitespace-pre-line">
                  {grant.application_process}
                </p>
              </Section>
            )}

            {/* Funding Terms */}
            {da.funding_terms && Object.values(da.funding_terms).some(Boolean) && (
              <Section title="Funding Terms" icon={Banknote} defaultOpen={false}>
                <dl className="space-y-4 text-sm">
                  {da.funding_terms.disbursement_schedule && da.funding_terms.disbursement_schedule !== "null" && (
                    <div>
                      <dt className="font-semibold text-gray-700">Disbursement Schedule</dt>
                      <dd className="mt-0.5 text-gray-600">{da.funding_terms.disbursement_schedule}</dd>
                    </div>
                  )}
                  {da.funding_terms.reporting_requirements && da.funding_terms.reporting_requirements !== "null" && (
                    <div>
                      <dt className="font-semibold text-gray-700">Reporting Requirements</dt>
                      <dd className="mt-0.5 text-gray-600">{da.funding_terms.reporting_requirements}</dd>
                    </div>
                  )}
                  {da.funding_terms.ip_ownership && da.funding_terms.ip_ownership !== "null" && (
                    <div>
                      <dt className="font-semibold text-gray-700">IP Ownership</dt>
                      <dd className="mt-0.5 text-gray-600">{da.funding_terms.ip_ownership}</dd>
                    </div>
                  )}
                  {da.funding_terms.audit_requirement && da.funding_terms.audit_requirement !== "null" && (
                    <div>
                      <dt className="font-semibold text-gray-700">Audit Requirement</dt>
                      <dd className="mt-0.5 text-gray-600">{da.funding_terms.audit_requirement}</dd>
                    </div>
                  )}
                  {da.funding_terms.permitted_costs?.length > 0 && (
                    <div>
                      <dt className="mb-1.5 font-semibold text-gray-700">Permitted Costs</dt>
                      <ul className="flex flex-wrap gap-1.5">
                        {da.funding_terms.permitted_costs.map((c: string, i: number) => (
                          <li key={i} className="rounded-full bg-green-50 px-2.5 py-0.5 text-xs text-green-700">
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {da.funding_terms.excluded_costs?.length > 0 && (
                    <div>
                      <dt className="mb-1.5 font-semibold text-gray-700">Excluded Costs</dt>
                      <ul className="flex flex-wrap gap-1.5">
                        {da.funding_terms.excluded_costs.map((c: string, i: number) => (
                          <li key={i} className="rounded-full bg-red-50 px-2.5 py-0.5 text-xs text-red-700">
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </dl>
              </Section>
            )}

            {/* Application Sections */}
            {da.application_sections && da.application_sections.length > 0 && (
              <Section title="Application Sections" icon={ClipboardList} defaultOpen={false}>
                <div className="space-y-3">
                  {da.application_sections.map((sec: { section: string; limit?: string; what_to_cover: string }, i: number) => (
                    <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-semibold text-gray-900">{sec.section}</p>
                        {sec.limit && (
                          <span className="text-[10px] font-medium text-gray-400">{sec.limit}</span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-gray-500">{sec.what_to_cover}</p>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Resources & Links */}
            {grant.resources && (
              (() => {
                const r = grant.resources;
                const hasLinks = r.guidelines_url || r.faq_url ||
                  r.brochure_urls?.length > 0 || r.info_session_urls?.length > 0 ||
                  r.template_urls?.length > 0;
                if (!hasLinks) return null;
                return (
                  <Section title="Resources & Links" icon={Link2} defaultOpen={false}>
                    <div className="space-y-2">
                      {r.guidelines_url && (
                        <a href={r.guidelines_url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-blue-600 hover:underline">
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          Program Guidelines
                        </a>
                      )}
                      {r.faq_url && (
                        <a href={r.faq_url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-blue-600 hover:underline">
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          FAQ
                        </a>
                      )}
                      {r.brochure_urls?.map((url: string, i: number) => (
                        <a key={`b${i}`} href={url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-blue-600 hover:underline">
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          Brochure / Guide {r.brochure_urls.length > 1 ? i + 1 : ""}
                        </a>
                      ))}
                      {r.template_urls?.map((url: string, i: number) => (
                        <a key={`t${i}`} href={url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-blue-600 hover:underline">
                          <FileText className="h-3.5 w-3.5 shrink-0" />
                          Template {r.template_urls.length > 1 ? i + 1 : ""}
                        </a>
                      ))}
                      {r.info_session_urls?.map((url: string, i: number) => (
                        <a key={`i${i}`} href={url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-blue-600 hover:underline">
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          Info Session {r.info_session_urls.length > 1 ? i + 1 : ""}
                        </a>
                      ))}
                    </div>
                  </Section>
                );
              })()
            )}
          </div>

          {/* Right sidebar (1/3) */}
          <div className="space-y-4">
            {/* Themes */}
            {grant.themes_detected && grant.themes_detected.length > 0 && (
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Themes
                </p>
                <div className="flex flex-wrap gap-2">
                  {grant.themes_detected.map((t: string) => (
                    <span
                      key={t}
                      className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"
                    >
                      {t.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Past Winners */}
            {pw.winners && pw.winners.length > 0 && (
              <Section title="Past Winners" icon={Users} defaultOpen={false}>
                {pw.funder_pattern && (
                  <p className="mb-3 text-sm text-gray-600">{pw.funder_pattern}</p>
                )}
                {pw.strategic_note && (
                  <p className="mb-3 rounded-lg bg-blue-50 p-2.5 text-xs font-medium text-blue-700">
                    {pw.strategic_note}
                  </p>
                )}
                <div className="space-y-2">
                  {pw.winners.slice(0, 5).map(
                    (
                      w: {
                        name: string;
                        year?: number;
                        country?: string;
                        altcarbon_similarity: string;
                        project_brief: string;
                      },
                      i: number
                    ) => (
                      <div
                        key={i}
                        className="rounded-lg border border-gray-100 bg-gray-50 p-2.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-gray-900 truncate">
                            {w.name}
                          </span>
                          <span
                            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                              w.altcarbon_similarity === "high"
                                ? "bg-green-100 text-green-700"
                                : w.altcarbon_similarity === "medium"
                                ? "bg-amber-100 text-amber-700"
                                : "bg-gray-100 text-gray-500"
                            }`}
                          >
                            {w.altcarbon_similarity}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-gray-500 line-clamp-2">
                          {w.project_brief}
                        </p>
                      </div>
                    )
                  )}
                </div>
              </Section>
            )}

            {/* Human Override */}
            {grant.human_override && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-amber-600" />
                  <p className="text-sm font-semibold text-amber-800">AI Recommendation Overridden</p>
                </div>
                {grant.override_reason && (
                  <p className="mt-2 text-sm text-amber-700">{grant.override_reason}</p>
                )}
                {grant.override_at && (
                  <p className="mt-1 text-xs text-amber-500">
                    {new Date(grant.override_at).toLocaleString()}
                  </p>
                )}
              </div>
            )}

            {/* Contact */}
            {da.contact && (da.contact.name || da.contact.email || da.contact.office) && (
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Contact
                </p>
                {da.contact.name && (
                  <p className="text-sm font-medium text-gray-900">{da.contact.name}</p>
                )}
                {da.contact.office && (
                  <p className="text-xs text-gray-500">{da.contact.office}</p>
                )}
                {da.contact.email && (
                  <a
                    href={`mailto:${da.contact.email}`}
                    className="mt-1 block text-sm text-blue-600 hover:underline"
                  >
                    {da.contact.email}
                  </a>
                )}
                {da.contact.emails_all && da.contact.emails_all.length > 1 && (
                  <div className="mt-2 space-y-1">
                    {da.contact.emails_all
                      .filter((e: string) => e !== da.contact.email)
                      .map((e: string, i: number) => (
                        <a key={i} href={`mailto:${e}`}
                          className="block text-xs text-gray-500 hover:text-blue-600 hover:underline">
                          {e}
                        </a>
                      ))}
                  </div>
                )}
                {da.contact.phone && (
                  <p className="mt-1 text-xs text-gray-500">{da.contact.phone}</p>
                )}
              </div>
            )}

            {/* Similar Grants to Track */}
            {da.similar_grants && da.similar_grants.length > 0 && (
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Also Track
                </p>
                <ul className="space-y-1.5">
                  {da.similar_grants.map((g: string, i: number) => (
                    <li key={i} className="text-xs text-gray-600">
                      {g}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        {/* ── Discussion & Activity ──────────────────────────── */}
        <div className="mt-6 rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="flex border-b border-gray-100">
            <button
              onClick={() => setCollabTab("discussion")}
              className={`flex flex-1 items-center justify-center gap-2 px-4 py-3.5 text-sm font-semibold transition-colors ${
                collabTab === "discussion"
                  ? "border-b-2 border-blue-600 text-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              <MessageSquare className="h-4 w-4" />
              Discussion
            </button>
            <button
              onClick={() => setCollabTab("activity")}
              className={`flex flex-1 items-center justify-center gap-2 px-4 py-3.5 text-sm font-semibold transition-colors ${
                collabTab === "activity"
                  ? "border-b-2 border-blue-600 text-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              <History className="h-4 w-4" />
              Activity
            </button>
          </div>
          <div className="p-4">
            {collabTab === "discussion" ? (
              <CommentThread grantId={grant._id} />
            ) : (
              <GrantActivity grantId={grant._id} grant={grant} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
