import { ExternalLink } from "lucide-react";
import { DeadlineChip } from "./DeadlineChip";
import { StatusPicker } from "./StatusPicker";
import { ScoreBadge, PriorityBadge } from "./ScoreBadge";
import { getThemeLabel, formatCurrency } from "@/lib/utils";
import type { Grant } from "@/lib/queries";

interface GrantCardProps {
  grant: Grant;
  compact?: boolean;
  href?: string;
  isNew?: boolean;
  onStatusChange?: (grantId: string, newStatus: string) => void;
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
  isNew = false,
  onStatusChange,
}: GrantCardProps) {
  const name = grant.grant_name || grant.title || "Unnamed Grant";
  const score = grant.weighted_total ?? 0;
  const funding = grant.max_funding_usd || grant.max_funding;
  const isPassed = ["auto_pass", "human_passed", "passed"].includes(
    grant.status
  );

  return (
    <div className={`rounded-lg border bg-white p-3 shadow-sm hover:shadow-md transition-shadow ${
      isNew ? "border-blue-300 ring-1 ring-blue-100" : "border-gray-200"
    }`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {isNew && (
            <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-bold uppercase text-blue-700">
              New
            </span>
          )}
          <h3
            className={`font-medium text-gray-900 ${
              compact ? "line-clamp-2 text-xs" : "text-sm"
            }`}
          >
            {name}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <PriorityBadge score={score} />
          <ScoreBadge score={score} />
        </div>
      </div>

      {grant.funder && (
        <p className="mt-1 truncate text-xs text-gray-500">{grant.funder}</p>
      )}

      {/* Theme badges */}
      {grant.themes_detected && grant.themes_detected.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {grant.themes_detected.map((t) => {
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
            {formatCurrency(funding)}
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
        {!compact && grant.notion_page_url && (
          <a
            href={grant.notion_page_url}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex items-center gap-0.5 text-xs text-gray-500 hover:text-gray-800 hover:underline ${!grant.url ? "ml-auto" : ""}`}
            onClick={(e) => e.stopPropagation()}
            title="Open in Notion"
          >
            <svg className="h-3 w-3" viewBox="0 0 100 100" fill="currentColor"><path d="M6.6 12.4c4.1 3.3 5.6 3 13.3 2.5L81 8.1c1.6-.2 .2-1.6-.6-1.8L67.3.3C64.5-1.4 60.7.3 58.2 2.3L17.5 5.5c-2.4.2-2.9 1.4-1.2 2.5zm4.6 12.6v64.8c0 3.5 1.8 4.8 5.8 4.6l67-3.9c3.9-.2 4.4-2.6 4.4-5.5V21c0-2.9-1.2-4.4-3.7-4.2L16.9 20.7c-2.7.2-3.7 1.4-3.7 4.3zm65.7 1.6c.4 1.8 0 3.6-1.8 3.8l-3.2.6v47.8c-2.8 1.5-5.4 2.3-7.5 2.3-3.5 0-4.4-1.1-7-4L35.8 43v32.6l6.6 1.5s0 3.6-5.1 3.6l-14 .8c-.4-.8 0-2.9 1.5-3.2l3.9-1.1V36.4l-5.4-.4c-.4-1.8.6-4.4 3.5-4.6l15-.9L64 65V35l-5.6-.6c-.4-2.2 1.2-3.7 3.3-3.9z"/></svg>
            Notion
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
