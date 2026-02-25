import { Clock } from "lucide-react";

interface DeadlineChipProps {
  deadline?: string;
  daysLeft?: number;
}

export function DeadlineChip({ deadline, daysLeft }: DeadlineChipProps) {
  const label =
    daysLeft !== undefined
      ? `${daysLeft}d left`
      : deadline
      ? deadline.slice(0, 10)
      : "Urgent";

  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      <Clock className="h-3 w-3" />
      {label}
    </span>
  );
}
