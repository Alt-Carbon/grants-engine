"use client";

import { useState } from "react";
import {
  PlusCircle,
  Loader2,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  Sparkles,
} from "lucide-react";

export default function AddGrantPage() {
  const [url, setUrl] = useState("");
  const [titleOverride, setTitleOverride] = useState("");
  const [funderOverride, setFunderOverride] = useState("");
  const [notes, setNotes] = useState("");
  const [autoAnalyze, setAutoAnalyze] = useState(true);
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [result, setResult] = useState<{
    message?: string;
    notion_page_id?: string;
    title?: string;
    funder?: string;
    themes?: string[];
    chars_fetched?: number;
    error?: string;
  } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;

    setStatus("loading");
    setResult(null);

    try {
      const res = await fetch("/api/grants/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url.trim(),
          title_override: titleOverride.trim() || "",
          funder_override: funderOverride.trim() || "",
          notes: notes.trim() || "",
          auto_analyze: autoAnalyze,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setStatus("error");
        setResult({ error: data.detail || data.error || "Failed to add grant" });
        return;
      }

      setStatus("success");
      setResult(data);
      setUrl("");
      setTitleOverride("");
      setFunderOverride("");
      setNotes("");
    } catch (err) {
      setStatus("error");
      setResult({ error: err instanceof Error ? err.message : "Network error" });
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Add Grant Manually</h1>
        <p className="mt-1.5 text-sm text-gray-500">
          Paste a grant URL that the Scout missed. It will be scraped, added to the
          Notion pipeline, and optionally scored by the Analyst agent.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* URL */}
        <div>
          <label htmlFor="url" className="mb-1.5 block text-sm font-semibold text-gray-700">
            Grant URL <span className="text-red-500">*</span>
          </label>
          <input
            id="url"
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/grant-opportunity"
            className="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        {/* Title override */}
        <div>
          <label htmlFor="title" className="mb-1.5 block text-sm font-medium text-gray-600">
            Title override <span className="text-xs text-gray-400">(optional — auto-detected from page)</span>
          </label>
          <input
            id="title"
            type="text"
            value={titleOverride}
            onChange={(e) => setTitleOverride(e.target.value)}
            placeholder="e.g. Climate Innovation Fund 2026"
            className="w-full rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        {/* Funder override */}
        <div>
          <label htmlFor="funder" className="mb-1.5 block text-sm font-medium text-gray-600">
            Funder override <span className="text-xs text-gray-400">(optional — auto-detected from domain)</span>
          </label>
          <input
            id="funder"
            type="text"
            value={funderOverride}
            onChange={(e) => setFunderOverride(e.target.value)}
            placeholder="e.g. European Commission"
            className="w-full rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        {/* Notes */}
        <div>
          <label htmlFor="notes" className="mb-1.5 block text-sm font-medium text-gray-600">
            Notes <span className="text-xs text-gray-400">(optional — context for the analyst)</span>
          </label>
          <textarea
            id="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="e.g. Heard about this from partner org, deadline is April..."
            className="w-full rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        {/* Auto-analyze toggle */}
        <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
          <input
            type="checkbox"
            checked={autoAnalyze}
            onChange={(e) => setAutoAnalyze(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <span className="flex items-center gap-1.5 text-sm font-medium text-gray-800">
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              Auto-analyze with Analyst agent
            </span>
            <p className="mt-0.5 text-xs text-gray-500">
              Immediately score and place the grant in the pipeline based on fit
            </p>
          </div>
        </label>

        {/* Submit */}
        <button
          type="submit"
          disabled={status === "loading" || !url.trim()}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {status === "loading" ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {autoAnalyze ? "Scraping & Analyzing..." : "Scraping..."}
            </>
          ) : (
            <>
              <PlusCircle className="h-4 w-4" />
              Add Grant
            </>
          )}
        </button>
      </form>

      {/* Result */}
      {result && status === "success" && (
        <div className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-green-600" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-green-800">{result.message}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {result.themes?.map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700"
                  >
                    {t.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
              {result.notion_page_id && (
                <a
                  href={`https://notion.so/${result.notion_page_id.replace(/-/g, "")}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-green-700 hover:text-green-900"
                >
                  <ExternalLink className="h-3 w-3" />
                  View in Notion
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      {result && status === "error" && (
        <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
            <p className="text-sm text-red-700">{result.error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
