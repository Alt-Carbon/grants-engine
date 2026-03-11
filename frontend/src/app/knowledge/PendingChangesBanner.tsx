"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";

interface PendingPage {
  page_id: string;
  title: string;
  edited_at: string;
  last_synced: string;
}

export function PendingChangesBanner() {
  const [pending, setPending] = useState<PendingPage[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/status/knowledge-pending")
      .then((r) => r.json())
      .then((data) => {
        if (data.pending && data.pending.length > 0) {
          setPending(data.pending);
        }
      })
      .catch(() => setError(true));
  }, []);

  if (error || pending.length === 0) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div>
        <p className="text-sm font-medium text-amber-800">
          {pending.length} page{pending.length !== 1 ? "s have" : " has"} unsynced
          changes
        </p>
        <p className="mt-0.5 text-xs text-amber-600">
          {pending
            .slice(0, 3)
            .map((p) => p.title)
            .join(", ")}
          {pending.length > 3 && ` and ${pending.length - 3} more`}
          {" — trigger a sync or wait for the next auto-check."}
        </p>
      </div>
    </div>
  );
}
