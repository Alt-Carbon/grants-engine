"use client";

import { useState } from "react";
import { Plus, Loader2, CheckCircle, XCircle, ChevronDown, ChevronUp, Link } from "lucide-react";

interface ManualGrantResult {
  success: boolean;
  title?: string;
  funder?: string;
  themes?: string[];
  chars_fetched?: number;
  message?: string;
  error?: string;
  detail?: string;
}

export function ManualGrantEntry() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [titleOverride, setTitleOverride] = useState("");
  const [funderOverride, setFunderOverride] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ManualGrantResult | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;

    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/grants/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          title_override: titleOverride.trim(),
          funder_override: funderOverride.trim(),
          notes: notes.trim(),
        }),
      });
      const data: ManualGrantResult = await res.json();
      if (!res.ok) {
        setResult({ success: false, error: data.detail || data.error || `Error ${res.status}` });
      } else {
        setResult(data);
        // Clear form on success
        setUrl("");
        setTitleOverride("");
        setFunderOverride("");
        setNotes("");
      }
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : "Unknown error" });
    } finally {
      setLoading(false);
    }
  }

  function handleDismiss() {
    setResult(null);
  }

  return (
    <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50">
      {/* Toggle header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-gray-600">
          <Plus className="h-4 w-4 text-indigo-500" />
          Add grant manually
        </div>
        {open ? (
          <ChevronUp className="h-4 w-4 text-gray-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-gray-400" />
        )}
      </button>

      {open && (
        <div className="border-t border-gray-200 px-4 pb-4 pt-3">
          {/* Success / error banner */}
          {result && (
            <div
              className={`mb-3 flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm ${
                result.success
                  ? "bg-green-50 text-green-800"
                  : "bg-red-50 text-red-800"
              }`}
            >
              {result.success ? (
                <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              )}
              <div className="flex-1">
                {result.success ? (
                  <>
                    <p className="font-medium">{result.title}</p>
                    {result.themes && (
                      <p className="mt-0.5 text-xs text-green-700">
                        {result.funder} · themes: {result.themes.join(", ")} · {result.chars_fetched?.toLocaleString()} chars
                      </p>
                    )}
                    <p className="mt-0.5 text-xs text-green-600">
                      Saved — run the Analyst to score it.
                    </p>
                  </>
                ) : (
                  <p>{result.error}</p>
                )}
              </div>
              <button
                onClick={handleDismiss}
                className="shrink-0 text-xs opacity-60 hover:opacity-100"
              >
                ✕
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-2.5">
            {/* URL — required */}
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Grant URL <span className="text-red-400">*</span>
              </label>
              <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 focus-within:border-indigo-400 focus-within:ring-1 focus-within:ring-indigo-200">
                <Link className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                <input
                  type="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://example.com/grant"
                  className="flex-1 text-sm outline-none placeholder:text-gray-300"
                />
              </div>
            </div>

            {/* Funder + Title row */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Funder <span className="text-gray-400">(auto-detected)</span>
                </label>
                <input
                  type="text"
                  value={funderOverride}
                  onChange={(e) => setFunderOverride(e.target.value)}
                  placeholder="e.g. Bill Gates Foundation"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none placeholder:text-gray-300 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Title <span className="text-gray-400">(auto-detected)</span>
                </label>
                <input
                  type="text"
                  value={titleOverride}
                  onChange={(e) => setTitleOverride(e.target.value)}
                  placeholder="e.g. Climate Solutions Grant"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none placeholder:text-gray-300 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
                />
              </div>
            </div>

            {/* Notes */}
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Notes</label>
              <textarea
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Why you want to pursue this, key context for the drafter…"
                className="w-full resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none placeholder:text-gray-300 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200"
              />
            </div>

            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-400">
                Content fetched via Jina · Analyst will score it next
              </p>
              <button
                type="submit"
                disabled={loading || !url.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Fetching…
                  </>
                ) : (
                  <>
                    <Plus className="h-3.5 w-3.5" />
                    Save Grant
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
