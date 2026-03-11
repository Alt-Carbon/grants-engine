"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BookOpen,
  ExternalLink,
  Loader2,
  Star,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Globe,
  Sheet,
} from "lucide-react";

interface TocSource {
  id: string;
  name: string;
  content_type: string;
  is_main_source: boolean;
  themes: string[];
  url: string;
  notion_page_id: string;
  extra_url: string;
  sync_chunks: number;
  sync_chars: number;
  last_synced: string | null;
}

interface TocData {
  sources: TocSource[];
  total: number;
  main_sources: number;
  synced: number;
  error?: string;
}

const THEME_STYLES: Record<string, string> = {
  climatetech: "bg-emerald-50 text-emerald-700 border-emerald-200",
  agritech: "bg-purple-50 text-purple-700 border-purple-200",
  ai_for_sciences: "bg-amber-50 text-amber-700 border-amber-200",
  applied_earth_sciences: "bg-pink-50 text-pink-700 border-pink-200",
  deeptech: "bg-gray-50 text-gray-700 border-gray-200",
  general: "bg-blue-50 text-blue-700 border-blue-200",
};

const THEME_LABELS: Record<string, string> = {
  climatetech: "Climate Tech",
  agritech: "Agri Tech",
  ai_for_sciences: "AI for Sciences",
  applied_earth_sciences: "Earth Sciences",
  deeptech: "Deep Tech",
  general: "General",
};

const TYPE_ICON: Record<string, typeof FileText> = {
  "Notion Page": FileText,
  "Google Docx": FileText,
  "Notion Site": Globe,
  Sheets: Sheet,
};

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatChars(chars: number): string {
  if (chars >= 1000) return `${(chars / 1000).toFixed(1)}k`;
  return String(chars);
}

export function TableOfContent() {
  const [data, setData] = useState<TocData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/status/table-of-content")
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          <span className="ml-2 text-sm text-gray-400">
            Loading knowledge sources...
          </span>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.sources.length === 0) return null;

  const byType = data.sources.reduce(
    (acc, s) => {
      const t = s.content_type || "Unknown";
      acc[t] = (acc[t] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-indigo-500" />
              Knowledge Registry
            </CardTitle>
            <p className="mt-1 text-xs text-gray-500">
              {data.total} sources &middot;{" "}
              {data.main_sources} main &middot;{" "}
              {data.synced}/{data.total} indexed &middot;{" "}
              {Object.entries(byType)
                .map(([t, c]) => `${c} ${t}`)
                .join(", ")}
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="divide-y divide-gray-100">
          {data.sources.map((src) => {
            const Icon = TYPE_ICON[src.content_type] || FileText;
            return (
              <div
                key={src.id}
                className="flex items-center justify-between py-2.5 gap-3"
              >
                <div className="flex items-start gap-2.5 min-w-0 flex-1">
                  <Icon className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {src.name}
                      </p>
                      {src.is_main_source && (
                        <span className="inline-flex items-center gap-0.5 rounded-full bg-yellow-50 border border-yellow-200 px-2 py-0.5 text-[10px] font-semibold text-yellow-700">
                          <Star className="h-3 w-3" />
                          Main
                        </span>
                      )}
                      <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                        {src.content_type || "Unknown"}
                      </span>
                    </div>

                    {/* Theme tags */}
                    {src.themes.length > 0 && (
                      <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                        {src.themes.map((theme) => (
                          <span
                            key={theme}
                            className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${THEME_STYLES[theme] ?? "bg-gray-50 text-gray-600 border-gray-200"}`}
                          >
                            {THEME_LABELS[theme] ?? theme}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Sync status */}
                    <div className="mt-1 flex items-center gap-2">
                      {src.sync_chunks > 0 ? (
                        <span className="inline-flex items-center gap-1 text-[10px] text-green-600">
                          <CheckCircle2 className="h-3 w-3" />
                          {src.sync_chunks} chunks &middot;{" "}
                          {formatChars(src.sync_chars)} chars
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
                          <Database className="h-3 w-3" />
                          Not indexed
                        </span>
                      )}
                      {src.last_synced && (
                        <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
                          <Clock className="h-3 w-3" />
                          {formatRelativeTime(src.last_synced)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {src.url && (
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                      title="Open source"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                  {src.extra_url && (
                    <a
                      href={src.extra_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded p-1 text-indigo-400 hover:bg-indigo-50 hover:text-indigo-600 transition-colors"
                      title="Extra source"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 border-t border-gray-100 pt-3">
          <p className="text-xs text-gray-500">
            Sources from the Table of Content in Grants DB. Main sources are
            prioritized during knowledge retrieval.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
