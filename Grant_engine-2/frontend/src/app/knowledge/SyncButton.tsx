"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { RefreshCw, CheckCircle } from "lucide-react";

export function SyncButton() {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSync() {
    setLoading(true);
    setDone(false);
    setError(null);

    try {
      const res = await fetch("/api/knowledge/sync", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {done && (
        <span className="flex items-center gap-1 text-sm text-green-600">
          <CheckCircle className="h-4 w-4" />
          Sync started
        </span>
      )}
      {error && <span className="text-sm text-red-600">{error}</span>}
      <Button onClick={handleSync} loading={loading} variant="outline">
        <RefreshCw className="h-4 w-4" />
        Trigger Sync
      </Button>
    </div>
  );
}
