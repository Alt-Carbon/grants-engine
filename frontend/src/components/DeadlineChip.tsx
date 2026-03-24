import { Clock, AlertTriangle } from "lucide-react";

interface DeadlineChipProps {
  deadline?: string;
  daysLeft?: number;
}

export function DeadlineChip({ deadline, daysLeft }: DeadlineChipProps) {
  // Expired: negative days
  if (daysLeft !== undefined && daysLeft < 0) {
    const daysAgo = Math.abs(daysLeft);
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-600 line-through">
        <AlertTriangle className="h-3 w-3" />
        Expired {daysAgo}d ago
      </span>
    );
  }

  // Active deadline
  const label =
    daysLeft !== undefined
      ? `${daysLeft}d left`
      : deadline
      ? deadline.slice(0, 10)
      : "Urgent";

  // Color by urgency
  const isUrgent = daysLeft !== undefined && daysLeft <= 7;
  const isWarning = daysLeft !== undefined && daysLeft <= 30;

  const colors = isUrgent
    ? "bg-red-100 text-red-700"
    : isWarning
    ? "bg-amber-100 text-amber-700"
    : "bg-blue-100 text-blue-700";

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${colors}`}>
      <Clock className="h-3 w-3" />
      {label}
    </span>
  );
}
