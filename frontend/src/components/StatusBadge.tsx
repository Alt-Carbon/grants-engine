import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  triage:         "bg-amber-100 text-amber-800",
  watch:          "bg-yellow-100 text-yellow-800",
  pursue:         "bg-green-100 text-green-800",
  pursuing:       "bg-green-100 text-green-800",
  drafting:       "bg-purple-100 text-purple-800",
  draft_complete: "bg-indigo-100 text-indigo-800",
  reviewed:       "bg-blue-100 text-blue-800",
  submitted:      "bg-cyan-100 text-cyan-800",
  won:            "bg-emerald-100 text-emerald-800",
  passed:         "bg-red-100 text-red-600",
  auto_pass:      "bg-red-100 text-red-600",
  human_passed:   "bg-red-200 text-red-700",
  hold:           "bg-orange-100 text-orange-800",
  reported:       "bg-red-100 text-red-600",
  guardrail_rejected: "bg-rose-100 text-rose-700",
};

/** Display-friendly labels — internal status key → UI label */
const STATUS_LABELS: Record<string, string> = {
  triage:         "Shortlisted",
  watch:          "Watch",
  pursue:         "Pursue",
  pursuing:       "Pursuing",
  drafting:       "Drafting",
  draft_complete: "Draft Complete",
  reviewed:       "Reviewed",
  submitted:      "Submitted",
  won:            "Won",
  passed:         "Rejected",
  auto_pass:      "Auto Rejected",
  human_passed:   "Rejected",
  hold:           "Hold",
  reported:       "Reported",
  guardrail_rejected: "Guardrail Rejected",
};

export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600";
  const label = getStatusLabel(status);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        style
      )}
    >
      {label}
    </span>
  );
}
