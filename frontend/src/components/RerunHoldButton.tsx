"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

export function RerunHoldButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/run/analyst/hold", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        setResult("Analyst re-run started");
      } else {
        setResult(data?.error || data?.status || "Failed");
      }
    } catch {
      setResult("Network error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={handleClick}
        disabled={loading}
        className="inline-flex items-center gap-1.5 rounded-md bg-orange-100 px-2.5 py-1 text-xs font-medium text-orange-700 transition-colors hover:bg-orange-200 disabled:opacity-50"
      >
        <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
        {loading ? "Running..." : "Re-run Analyst"}
      </button>
      {result && (
        <p className="mt-1 text-xs text-gray-500">{result}</p>
      )}
    </div>
  );
}
