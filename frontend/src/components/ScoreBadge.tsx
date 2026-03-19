import { getPriority } from "@/lib/utils";

export function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 6.5
      ? "bg-green-100 text-green-800 ring-green-200"
      : score >= 5.0
      ? "bg-amber-100 text-amber-800 ring-amber-200"
      : "bg-red-100 text-red-800 ring-red-200";

  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ring-1 ${color}`}
    >
      {score.toFixed(1)}
    </span>
  );
}

export function PriorityBadge({ score }: { score: number }) {
  const { label, className } = getPriority(score);
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${className}`}
    >
      {label}
    </span>
  );
}

export function ScoreCell({ score }: { score: number }) {
  const color =
    score >= 6.5
      ? "bg-green-100 text-green-800"
      : score >= 5.0
      ? "bg-amber-100 text-amber-800"
      : "bg-red-100 text-red-800";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ${color}`}
    >
      {score.toFixed(1)}
    </span>
  );
}
