import { AlertTriangle } from "lucide-react";

interface WarningsBannerProps {
  warnings: string[];
}

export function WarningsBanner({ warnings }: WarningsBannerProps) {
  if (!warnings || warnings.length === 0) return null;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="flex gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <p key={i} className="text-sm text-amber-800">
              {w}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
