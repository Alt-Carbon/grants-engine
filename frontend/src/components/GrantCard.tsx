import { ExternalLink } from "lucide-react";
import { DeadlineChip } from "./DeadlineChip";
import { StatusPicker } from "./StatusPicker";
import type { Grant } from "@/lib/queries";

interface GrantCardProps {
  grant: Grant;
  compact?: boolean;
  href?: string;
  onStatusChange?: (grantId: string, newStatus: string) => void;
}

function ScoreBadge({ score }: { score: number }) {
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

function PassedLabel({ status }: { status: string }) {
  if (status === "auto_pass")
    return (
      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
        Auto
      </span>
    );
  if (status === "human_passed" || status === "passed")
    return (
      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-600">
        Human
      </span>
    );
  return null;
}

export function GrantCard({
  grant,
  compact = false,
  onStatusChange,
}: GrantCardProps) {
  const name = grant.grant_name || grant.title || "Unnamed Grant";
  const score = grant.weighted_total ?? 0;
  const funding = grant.max_funding_usd || grant.max_funding;
  const isPassed = ["auto_pass", "human_passed", "passed"].includes(
    grant.status
  );

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <h3
          className={`font-medium text-gray-900 ${
            compact ? "line-clamp-2 text-xs" : "text-sm"
          }`}
        >
          {name}
        </h3>
        <ScoreBadge score={score} />
      </div>

      {grant.funder && (
        <p className="mt-1 truncate text-xs text-gray-500">{grant.funder}</p>
      )}

      {!compact && grant.eligibility && (
        <p className="mt-2 line-clamp-2 text-xs text-gray-600">
          {grant.eligibility}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {/* Clickable status badge */}
        {onStatusChange && (
          <StatusPicker
            status={grant.status}
            grantId={grant._id}
            onStatusChange={onStatusChange}
            size="sm"
          />
        )}
        {grant.deadline_urgent && (
          <DeadlineChip
            deadline={grant.deadline}
            daysLeft={grant.days_to_deadline}
          />
        )}
        {grant.geography && (
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
            {grant.geography}
          </span>
        )}
        {funding !== undefined && funding > 0 && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            ${(funding / 1000).toFixed(0)}K
          </span>
        )}
        {isPassed && <PassedLabel status={grant.status} />}
        {!compact && grant.url && (
          <a
            href={grant.url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto inline-flex items-center gap-0.5 text-xs text-blue-600 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-3 w-3" />
            View
          </a>
        )}
      </div>

      {grant.human_override && !compact && (
        <div className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">
          Human override — {grant.override_reason || "no reason given"}
        </div>
      )}
    </div>
  );
}
