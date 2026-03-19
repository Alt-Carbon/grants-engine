"use client";

import { useState } from "react";
import { ScoreRadar } from "@/components/ScoreRadar";
import { DeadlineChip } from "@/components/DeadlineChip";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { GrantDetailSheet } from "@/components/GrantDetailSheet";
import type { Grant } from "@/lib/queries";
import { getPriority, getThemeLabel, formatCurrency } from "@/lib/utils";
import { CheckCircle, XCircle, ChevronDown, ChevronUp, AlertTriangle, ExternalLink } from "lucide-react";

interface TriageQueueProps {
  grants: Grant[];
}

interface TriageResult {
  grantId: string;
  decision: "pursue" | "pass";
}

export function TriageQueue({ grants: initialGrants }: TriageQueueProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, "pursue" | "pass">>({});
  const [overrideReasons, setOverrideReasons] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [detailGrantId, setDetailGrantId] = useState<string | null>(null);

  const pending = initialGrants.filter((g) => !submitted.has(g._id));

  async function handleSubmit(grant: Grant) {
    const decision = decisions[grant._id];
    if (!decision) return;

    const aiRec = grant.recommended_action;
    const isOverride = aiRec && aiRec !== decision;

    setSubmitting(grant._id);
    setErrors((prev) => ({ ...prev, [grant._id]: "" }));

    try {
      const res = await fetch("/api/triage/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: grant.thread_id || grant._id,
          grant_id: grant._id,
          decision,
          human_override: isOverride,
          override_reason: isOverride ? overrideReasons[grant._id] || "" : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSubmitted((prev) => new Set(prev).add(grant._id));
    } catch (e) {
      setErrors((prev) => ({
        ...prev,
        [grant._id]: e instanceof Error ? e.message : "Submission failed",
      }));
    } finally {
      setSubmitting(null);
    }
  }

  if (pending.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-gray-400">
        <p className="font-medium">All shortlisted grants reviewed!</p>
        <p className="mt-1 text-sm">Check the Pipeline to see their status</p>
      </div>
    );
  }

  return (
    <>
    <div className="flex flex-col gap-4">
      {pending.map((grant) => {
        const name = grant.grant_name || grant.title || "Unnamed Grant";
        const isExpanded = expanded === grant._id;
        const decision = decisions[grant._id];
        const aiRec = grant.recommended_action;
        const isOverride = aiRec && decision && aiRec !== decision;

        return (
          <div
            key={grant._id}
            className="rounded-xl border border-gray-200 bg-white shadow-sm"
          >
            {/* Card header — always visible */}
            <div className="flex items-start gap-4 p-4">
              {/* Score + priority badge */}
              <div className="flex flex-col items-center gap-1">
                <span
                  className={`rounded-full px-3 py-1 text-lg font-bold ${
                    (grant.weighted_total ?? 0) >= 6.5
                      ? "bg-green-100 text-green-800"
                      : (grant.weighted_total ?? 0) >= 5.0
                      ? "bg-amber-100 text-amber-800"
                      : "bg-red-100 text-red-800"
                  }`}
                >
                  {(grant.weighted_total ?? 0).toFixed(1)}
                </span>
                {(() => {
                  const p = getPriority(grant.weighted_total ?? 0);
                  return (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${p.className}`}>
                      {p.label}
                    </span>
                  );
                })()}
                {aiRec && (
                  <span className="text-xs text-gray-400">AI: {aiRec}</span>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <h2 className="font-semibold text-gray-900">{name}</h2>
                <p className="text-sm text-gray-500">{grant.funder}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {grant.deadline_urgent && (
                    <DeadlineChip
                      deadline={grant.deadline}
                      daysLeft={grant.days_to_deadline}
                    />
                  )}
                  {grant.geography && (
                    <Badge variant="secondary">{grant.geography}</Badge>
                  )}
                  {grant.grant_type && (
                    <Badge variant="outline">{grant.grant_type}</Badge>
                  )}
                  {(grant.max_funding_usd || grant.max_funding) && (
                    <Badge variant="secondary">
                      {formatCurrency(grant.max_funding_usd || grant.max_funding)}
                    </Badge>
                  )}
                  {grant.themes_detected?.map((t) => {
                    const theme = getThemeLabel(t);
                    return (
                      <span
                        key={t}
                        className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{ backgroundColor: theme.bg, color: theme.color }}
                      >
                        {theme.label}
                      </span>
                    );
                  })}
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <button
                  onClick={() => setDetailGrantId(grant._id)}
                  className="text-gray-400 hover:text-indigo-600"
                  title="View full details"
                >
                  <ExternalLink className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setExpanded(isExpanded ? null : grant._id)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  {isExpanded ? (
                    <ChevronUp className="h-5 w-5" />
                  ) : (
                    <ChevronDown className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Expanded detail */}
            {isExpanded && (
              <div className="border-t border-gray-100 px-4 pb-4 pt-3">
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {/* Score radar */}
                  {grant.scores && Object.keys(grant.scores).length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                        Score Breakdown
                      </p>
                      <ScoreRadar scores={grant.scores} />
                    </div>
                  )}

                  {/* Eligibility + rationale */}
                  <div className="space-y-3">
                    {grant.eligibility && (
                      <div>
                        <p className="mb-1 text-xs font-medium text-gray-500 uppercase tracking-wide">
                          Eligibility
                        </p>
                        <p className="text-sm text-gray-700">{grant.eligibility}</p>
                      </div>
                    )}
                    {grant.rationale && (
                      <div>
                        <p className="mb-1 text-xs font-medium text-gray-500 uppercase tracking-wide">
                          AI Rationale
                        </p>
                        <p className="text-sm text-gray-600 italic">{grant.rationale}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Decision row */}
            <div className="flex flex-wrap items-center gap-3 border-t border-gray-100 px-4 py-3">
              <Button
                size="sm"
                variant={decision === "pursue" ? "success" : "outline"}
                onClick={() => setDecisions((p) => ({ ...p, [grant._id]: "pursue" }))}
              >
                <CheckCircle className="h-4 w-4" />
                Pursue
              </Button>
              <Button
                size="sm"
                variant={decision === "pass" ? "destructive" : "outline"}
                onClick={() => setDecisions((p) => ({ ...p, [grant._id]: "pass" }))}
              >
                <XCircle className="h-4 w-4" />
                Pass
              </Button>

              {/* Override reason */}
              {isOverride && (
                <div className="w-full">
                  <div className="mb-1 flex items-center gap-1 text-xs text-amber-600">
                    <AlertTriangle className="h-3 w-3" />
                    Overriding AI recommendation ({aiRec} → {decision}) — reason:
                  </div>
                  <Textarea
                    placeholder="Explain why you're overriding the AI recommendation…"
                    rows={2}
                    value={overrideReasons[grant._id] || ""}
                    onChange={(e) =>
                      setOverrideReasons((p) => ({ ...p, [grant._id]: e.target.value }))
                    }
                    className="text-sm"
                  />
                </div>
              )}

              {errors[grant._id] && (
                <p className="w-full text-xs text-red-600">{errors[grant._id]}</p>
              )}

              {decision && (
                <Button
                  size="sm"
                  onClick={() => handleSubmit(grant)}
                  loading={submitting === grant._id}
                  className="ml-auto"
                >
                  Submit Decision
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>

    <GrantDetailSheet
      grantId={detailGrantId}
      onClose={() => setDetailGrantId(null)}
    />
    </>
  );
}
