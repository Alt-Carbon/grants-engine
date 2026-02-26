import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  triage:         "bg-amber-100 text-amber-800",
  pursue:         "bg-green-100 text-green-800",
  pursuing:       "bg-green-100 text-green-800",
  watch:          "bg-blue-100 text-blue-800",
  drafting:       "bg-purple-100 text-purple-800",
  draft_complete: "bg-indigo-100 text-indigo-800",
  submitted:      "bg-cyan-100 text-cyan-800",
  won:            "bg-emerald-100 text-emerald-800",
  passed:         "bg-gray-100 text-gray-500",
  auto_pass:      "bg-gray-100 text-gray-500",
  human_passed:   "bg-gray-200 text-gray-600",
  hold:           "bg-orange-100 text-orange-800",
  reported:       "bg-red-100 text-red-600",
};

/** Display-friendly labels — internal status key → UI label */
const STATUS_LABELS: Record<string, string> = {
  triage:         "Shortlisted",
  pursue:         "Pursue",
  pursuing:       "Pursuing",
  watch:          "Watch",
  drafting:       "Drafting",
  draft_complete: "Draft Complete",
  submitted:      "Submitted",
  won:            "Won",
  passed:         "Passed",
  auto_pass:      "Auto Passed",
  human_passed:   "Human Passed",
  hold:           "Hold",
  reported:       "Reported",
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
