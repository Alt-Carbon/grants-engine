"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ScoreRadar } from "./ScoreRadar";
import { DeadlineChip } from "./DeadlineChip";
import { StatusBadge } from "./StatusBadge";
import { CommentThread } from "./CommentThread";
import { GrantActivity } from "./GrantActivity";
import {
  X,
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
  Loader2,
  MessageSquare,
  History,
  Maximize2,
  PlayCircle,
} from "lucide-react";

interface GrantDetailSheetProps {
  grantId: string | null;
  onClose: () => void;
}

// Matches the deep_analysis shape written by analyst.py
interface EligibilityCheck {
  criterion: string;
  altcarbon_status: "met" | "likely_met" | "verify" | "not_met";
  note: string;
}
interface KeyDates {
  application_deadline?: string;
  loi_deadline?: string;
  notification_date?: string;
  project_duration?: string;
}
interface Requirements {
  documents_needed?: string[];
  submission_format?: string;
  word_page_limits?: string;
  co_funding_required?: string;
}
interface FundingTerms {
  disbursement_schedule?: string;
  reporting_requirements?: string;
  ip_ownership?: string;
  permitted_costs?: string[];
  excluded_costs?: string[];
  audit_requirement?: string;
}
interface DeepAnalysis {
  eligibility_checklist?: EligibilityCheck[];
  key_dates?: KeyDates;
  requirements?: Requirements;
  evaluation_criteria?: { criterion: string; weight?: string; what_they_look_for: string }[];
  red_flags?: string[];
  strategic_angle?: string;
  application_tips?: string[];
  contact?: { name?: string; email?: string; emails_all?: string[]; phone?: string; office?: string };
  funding_terms?: FundingTerms;
  past_winners?: PastWinners;
  application_sections?: { section: string; limit?: string; what_to_cover: string }[];
  similar_grants?: string[];
  opportunity_summary?: string;
  application_process_detailed?: string;
}
interface PastWinners {
  funder_pattern?: string;
  altcarbon_fit_verdict?: "strong" | "moderate" | "weak" | "unknown";
  strategic_note?: string;
  winners?: { name: string; year?: number; country?: string; altcarbon_similarity: string; project_brief: string }[];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GrantFull = Record<string, any> & {
  _id: string;
  grant_name?: string;
  title?: string;
  funder?: string;
  status: string;
  weighted_total?: number;
  deadline_urgent?: boolean;
  deadline?: string;
  days_to_deadline?: number;
  geography?: string;
  eligibility?: string;
  max_funding_usd?: number;
  max_funding?: number;
  url?: string;
  application_url?: string;
  scores?: Record<string, number>;
  rationale?: string;
  reasoning?: string;
  evidence_found?: string[];
  evidence_gaps?: string[];
  red_flags?: string[];
  deep_analysis?: DeepAnalysis;
  past_winners?: PastWinners;
  notes?: string;
  themes_detected?: string[];
  grant_type?: string;
  amount?: string;
  currency?: string;
  human_override?: boolean;
  override_reason?: string;
};

const STATUS_ICON: Record<string, string> = {
  met:        "✅",
  likely_met: "🟡",
  verify:     "🔍",
  not_met:    "❌",
};

function Section({ title, children, defaultOpen = true }: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-6 py-3.5 text-left transition-colors hover:bg-gray-50/80"
      >
        <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">{title}</span>
        {open ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
      </button>
      {open && <div className="px-6 pb-5">{children}</div>}
    </div>
  );
}

export function GrantDetailSheet({ grantId, onClose }: GrantDetailSheetProps) {
  const router = useRouter();
  const [grant, setGrant] = useState<GrantFull | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const fetchGrant = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/grants/${id}`);
      if (!res.ok) throw new Error(await res.text());
      setGrant(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (grantId) fetchGrant(grantId);
    else setGrant(null);
  }, [grantId, fetchGrant]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const isOpen = !!grantId;
  const name    = grant?.grant_name || grant?.title || "Grant Details";
  const score   = grant?.weighted_total ?? 0;
  const funding = grant?.max_funding_usd || grant?.max_funding;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/30 transition-opacity ${
          isOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />

      {/* Sheet */}
      <div
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l border-gray-200 bg-white shadow-2xl transition-transform duration-300 ease-in-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex shrink-0 items-start justify-between border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white px-6 py-5">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          ) : error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : grant ? (
            <div className="flex-1 min-w-0 pr-4">
              <h2 className="text-lg font-bold text-gray-900 leading-tight">{name}</h2>
              {grant.funder && <p className="mt-1 text-sm text-gray-500">{grant.funder}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <StatusBadge status={grant.status} />
                <span
                  className={`rounded-full px-2.5 py-0.5 text-sm font-bold ${
                    score >= 6.5 ? "bg-green-100 text-green-800" :
                    score >= 5.0 ? "bg-amber-100 text-amber-800" :
                    "bg-red-100 text-red-800"
                  }`}
                >
                  {score.toFixed(1)} / 10
                </span>
                {grant.deadline_urgent && (
                  <DeadlineChip deadline={grant.deadline} daysLeft={grant.days_to_deadline} />
                )}
                {(grant.status === "pursue" || grant.status === "pursuing" || grant.status === "hold" || grant.status === "triage") && (
                  <button
                    onClick={async () => {
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
                        onClose();
                        router.push("/drafter");
                      } catch {
                        setDraftError("Network error");
                      } finally {
                        setDraftLoading(false);
                      }
                    }}
                    disabled={draftLoading}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-1 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-purple-700 disabled:opacity-50"
                  >
                    {draftLoading ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <PlayCircle className="h-3 w-3" />
                    )}
                    {draftLoading ? "Starting..." : "Start Draft"}
                  </button>
                )}
                {grant.status === "drafting" && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-semibold text-purple-700">
                    <FileText className="h-3 w-3" />
                    Drafting
                  </span>
                )}
              </div>
              {draftError && (
                <div className="mt-2 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  <p className="text-xs text-red-700">{draftError}</p>
                </div>
              )}
            </div>
          ) : null}
          <div className="flex shrink-0 items-center gap-1">
            {grant && (
              <button
                onClick={() => {
                  onClose();
                  router.push(`/grants/${grant._id}`);
                }}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors"
                title="Open full page"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Scrollable body + collaboration */}
        {grant && (
          <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto">

            {/* Quick-facts row */}
            <div className="grid grid-cols-3 gap-px border-b border-gray-100 bg-gray-200/60">
              {[
                { icon: Globe,     label: "Geography", value: grant.geography || "—" },
                {
                  icon: DollarSign, label: "Funding",
                  value: funding ? `$${(funding / 1000).toFixed(0)}K` : (grant.amount || "—"),
                },
                { icon: Clock,     label: "Deadline",  value: grant.deadline || "—" },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} className="flex flex-col gap-1 bg-white px-4 py-3.5">
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-gray-400">
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </div>
                  <p className="text-sm font-semibold text-gray-900 truncate">{value}</p>
                </div>
              ))}
            </div>

            {/* Links */}
            {(grant.url || grant.application_url || grant.notion_page_url) && (
              <div className="flex gap-3 border-b border-gray-100 px-5 py-3">
                {grant.url && (
                  <a href={grant.url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-blue-600 hover:underline">
                    <ExternalLink className="h-3.5 w-3.5" />Grant page
                  </a>
                )}
                {grant.application_url && grant.application_url !== grant.url && (
                  <a href={grant.application_url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm font-medium text-green-700 hover:underline">
                    <FileText className="h-3.5 w-3.5" />Apply now
                  </a>
                )}
                {grant.notion_page_url && (
                  <a href={grant.notion_page_url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:underline">
                    <svg className="h-3.5 w-3.5" viewBox="0 0 100 100" fill="currentColor"><path d="M6.6 12.4c4.1 3.3 5.6 3 13.3 2.5L81 8.1c1.6-.2 .2-1.6-.6-1.8L67.3.3C64.5-1.4 60.7.3 58.2 2.3L17.5 5.5c-2.4.2-2.9 1.4-1.2 2.5zm4.6 12.6v64.8c0 3.5 1.8 4.8 5.8 4.6l67-3.9c3.9-.2 4.4-2.6 4.4-5.5V21c0-2.9-1.2-4.4-3.7-4.2L16.9 20.7c-2.7.2-3.7 1.4-3.7 4.3zm65.7 1.6c.4 1.8 0 3.6-1.8 3.8l-3.2.6v47.8c-2.8 1.5-5.4 2.3-7.5 2.3-3.5 0-4.4-1.1-7-4L35.8 43v32.6l6.6 1.5s0 3.6-5.1 3.6l-14 .8c-.4-.8 0-2.9 1.5-3.2l3.9-1.1V36.4l-5.4-.4c-.4-1.8.6-4.4 3.5-4.6l15-.9L64 65V35l-5.6-.6c-.4-2.2 1.2-3.7 3.3-3.9z"/></svg>
                    Open in Notion
                  </a>
                )}
              </div>
            )}

            {/* Score radar */}
            {grant.scores && Object.keys(grant.scores).length > 0 && (
              <Section title="Score Breakdown">
                <ScoreRadar scores={grant.scores} height={200} />
              </Section>
            )}

            {/* Eligibility */}
            {grant.eligibility && (
              <Section title="Eligibility">
                <p className="text-sm leading-relaxed text-gray-700">{grant.eligibility}</p>
              </Section>
            )}

            {/* AI Rationale */}
            {(grant.rationale || grant.reasoning) && (
              <Section title="AI Rationale">
                {grant.rationale && <p className="text-sm text-gray-700">{grant.rationale}</p>}
                {grant.reasoning && (
                  <p className="mt-2 text-sm text-gray-500 italic">{grant.reasoning}</p>
                )}
              </Section>
            )}

            {/* Evidence */}
            {((grant.evidence_found?.length ?? 0) > 0 || (grant.evidence_gaps?.length ?? 0) > 0) && (
              <Section title="Evidence" defaultOpen={false}>
                {grant.evidence_found && grant.evidence_found.length > 0 && (
                  <div className="mb-3">
                    <p className="mb-1 text-xs font-medium text-green-700">Found</p>
                    <ul className="space-y-1">
                      {grant.evidence_found.map((e: string, i: number) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                          <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                          {e}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {grant.evidence_gaps && grant.evidence_gaps.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-medium text-amber-700">Gaps</p>
                    <ul className="space-y-1">
                      {grant.evidence_gaps.map((e: string, i: number) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                          {e}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Section>
            )}

            {/* Red flags */}
            {grant.red_flags && grant.red_flags.length > 0 && (
              <Section title="Red Flags" defaultOpen={false}>
                <ul className="space-y-1">
                  {grant.red_flags.map((r: string, i: number) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-red-700">
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {r}
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {/* Opportunity Summary */}
            {grant.about_opportunity && (
              <Section title="About This Opportunity">
                <p className="text-sm leading-relaxed text-gray-700 whitespace-pre-line">
                  {grant.about_opportunity}
                </p>
              </Section>
            )}

            {/* Deep analysis — eligibility checklist */}
            {grant.deep_analysis?.eligibility_checklist && grant.deep_analysis.eligibility_checklist.length > 0 && (
              <Section title="Eligibility Checklist (Deep Analysis)">
                <div className="space-y-2">
                  {grant.deep_analysis.eligibility_checklist.map((c: EligibilityCheck, i: number) => (
                    <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                      <div className="flex items-start gap-2">
                        <span className="text-base">{STATUS_ICON[c.altcarbon_status] || "❓"}</span>
                        <div>
                          <p className="text-sm font-medium text-gray-900">{c.criterion}</p>
                          {c.note && <p className="mt-0.5 text-xs text-gray-500">{c.note}</p>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Deep analysis — key dates */}
            {grant.deep_analysis?.key_dates && (
              <Section title="Key Dates" defaultOpen={false}>
                <dl className="space-y-2">
                  {Object.entries(grant.deep_analysis.key_dates)
                    .filter(([, v]) => v)
                    .map(([k, v]) => (
                      <div key={k} className="flex justify-between text-sm">
                        <dt className="text-gray-500 capitalize">{k.replace(/_/g, " ")}</dt>
                        <dd className="font-medium text-gray-900">{v as string}</dd>
                      </div>
                    ))}
                </dl>
              </Section>
            )}

            {/* Deep analysis — requirements */}
            {grant.deep_analysis?.requirements && (
              <Section title="Requirements" defaultOpen={false}>
                <dl className="space-y-3 text-sm">
                  {grant.deep_analysis.requirements.submission_format && (
                    <div>
                      <dt className="font-medium text-gray-700">Submission format</dt>
                      <dd className="text-gray-600">{grant.deep_analysis.requirements.submission_format}</dd>
                    </div>
                  )}
                  {grant.deep_analysis.requirements.word_page_limits && (
                    <div>
                      <dt className="font-medium text-gray-700">Word / page limits</dt>
                      <dd className="text-gray-600">{grant.deep_analysis.requirements.word_page_limits}</dd>
                    </div>
                  )}
                  {grant.deep_analysis.requirements.documents_needed && grant.deep_analysis.requirements.documents_needed.length > 0 && (
                    <div>
                      <dt className="mb-1 font-medium text-gray-700">Documents needed</dt>
                      <ul className="list-disc pl-4 space-y-0.5">
                        {grant.deep_analysis.requirements.documents_needed.map((d: string, i: number) => (
                          <li key={i} className="text-gray-600">{d}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </dl>
              </Section>
            )}

            {/* Deep analysis — strategy */}
            {(grant.deep_analysis?.strategic_angle || (grant.deep_analysis?.application_tips?.length ?? 0) > 0) && (
              <Section title="Strategic Advice" defaultOpen={false}>
                {grant.deep_analysis?.strategic_angle && (
                  <p className="mb-3 text-sm text-gray-700">{grant.deep_analysis.strategic_angle}</p>
                )}
                {grant.deep_analysis?.application_tips && grant.deep_analysis.application_tips.length > 0 && (
                  <ul className="space-y-1">
                    {grant.deep_analysis.application_tips.map((t: string, i: number) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                        <span className="shrink-0 text-blue-500">→</span>
                        {t}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            )}

            {/* Application Process */}
            {grant.application_process && (
              <Section title="Application Process" defaultOpen={false}>
                <p className="text-sm leading-relaxed text-gray-700 whitespace-pre-line">
                  {grant.application_process}
                </p>
              </Section>
            )}

            {/* Funding Terms */}
            {grant.deep_analysis?.funding_terms && Object.values(grant.deep_analysis.funding_terms).some(Boolean) && (
              <Section title="Funding Terms" defaultOpen={false}>
                <dl className="space-y-3 text-sm">
                  {grant.deep_analysis.funding_terms.disbursement_schedule && grant.deep_analysis.funding_terms.disbursement_schedule !== "null" && (
                    <div>
                      <dt className="font-medium text-gray-700">Disbursement</dt>
                      <dd className="text-gray-600">{grant.deep_analysis.funding_terms.disbursement_schedule}</dd>
                    </div>
                  )}
                  {grant.deep_analysis.funding_terms.reporting_requirements && grant.deep_analysis.funding_terms.reporting_requirements !== "null" && (
                    <div>
                      <dt className="font-medium text-gray-700">Reporting</dt>
                      <dd className="text-gray-600">{grant.deep_analysis.funding_terms.reporting_requirements}</dd>
                    </div>
                  )}
                  {grant.deep_analysis.funding_terms.ip_ownership && grant.deep_analysis.funding_terms.ip_ownership !== "null" && (
                    <div>
                      <dt className="font-medium text-gray-700">IP Ownership</dt>
                      <dd className="text-gray-600">{grant.deep_analysis.funding_terms.ip_ownership}</dd>
                    </div>
                  )}
                </dl>
              </Section>
            )}

            {/* Past winners */}
            {(() => {
              const pw = grant.past_winners?.winners?.length ? grant.past_winners : grant.deep_analysis?.past_winners;
              if (!pw) return null;
              return (
              <Section title="Past Winners Analysis" defaultOpen={false}>
                {pw.funder_pattern && (
                  <p className="mb-2 text-sm text-gray-700">{pw.funder_pattern}</p>
                )}
                {pw.strategic_note && (
                  <p className="mb-3 text-sm font-medium text-blue-700">{pw.strategic_note}</p>
                )}
                {pw.winners && pw.winners.length > 0 && (
                  <div className="space-y-2">
                    {pw.winners.slice(0, 5).map((w: { name: string; altcarbon_similarity: string; project_brief: string }, i: number) => (
                      <div key={i} className="rounded border border-gray-100 bg-gray-50 p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-gray-900">{w.name}</span>
                          <span className={`rounded-full px-2 py-0.5 text-xs ${
                            w.altcarbon_similarity === "high"   ? "bg-green-100 text-green-700" :
                            w.altcarbon_similarity === "medium" ? "bg-amber-100 text-amber-700" :
                            "bg-gray-100 text-gray-500"
                          }`}>
                            {w.altcarbon_similarity} similarity
                          </span>
                        </div>
                        <p className="mt-1 text-gray-500">{w.project_brief}</p>
                      </div>
                    ))}
                  </div>
                )}
              </Section>
              );
            })()}

            {/* Themes */}
            {grant.themes_detected && grant.themes_detected.length > 0 && (
              <Section title="Themes Detected" defaultOpen={false}>
                <div className="flex flex-wrap gap-2">
                  {grant.themes_detected.map((t: string) => (
                    <span key={t} className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                      {t.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {/* Human override */}
            {grant.human_override && (
              <Section title="Human Override" defaultOpen={false}>
                <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
                  <p className="font-medium">AI recommendation overridden</p>
                  {grant.override_reason && <p className="mt-1">{grant.override_reason}</p>}
                  {grant.override_at && (
                    <p className="mt-1 text-xs text-amber-600">
                      {new Date(grant.override_at).toLocaleString()}
                    </p>
                  )}
                </div>
              </Section>
            )}

            {/* ── Collaboration (inside scroll) ─────────────────── */}
            <CollaborationPanel grantId={grant._id} grant={grant} />

          </div>
          </div>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Collaboration Panel — Discussion + Activity tabs
// ---------------------------------------------------------------------------

function CollaborationPanel({
  grantId,
  grant,
}: {
  grantId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  grant: any;
}) {
  const [tab, setTab] = useState<"discussion" | "activity">("discussion");

  return (
    <div className="border-t border-gray-200 bg-white">
      {/* Tab bar */}
      <div className="sticky top-0 z-10 flex border-b border-gray-100 bg-white">
        <button
          onClick={() => setTab("discussion")}
          className={`flex flex-1 items-center justify-center gap-1.5 px-4 py-3 text-xs font-semibold transition-colors ${
            tab === "discussion"
              ? "border-b-2 border-blue-600 text-blue-600"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Discussion
        </button>
        <button
          onClick={() => setTab("activity")}
          className={`flex flex-1 items-center justify-center gap-1.5 px-4 py-3 text-xs font-semibold transition-colors ${
            tab === "activity"
              ? "border-b-2 border-blue-600 text-blue-600"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <History className="h-3.5 w-3.5" />
          Activity
        </button>
      </div>

      {/* Tab content */}
      {tab === "discussion" ? (
        <CommentThread grantId={grantId} />
      ) : (
        <GrantActivity grantId={grantId} grant={grant} />
      )}
    </div>
  );
}
