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
  hold:           "bg-orange-100 text-orange-800",
  reported:       "bg-red-100 text-red-600",
};

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600";
  const label = status.replace(/_/g, " ");
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
