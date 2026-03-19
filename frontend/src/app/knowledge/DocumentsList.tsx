"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FileText,
  ExternalLink,
  Loader2,
  FolderOpen,
  ListChecks,
  Database,
  CheckCircle2,
  Clock,
} from "lucide-react";
import { formatRelativeTime, formatChars } from "@/lib/utils";

interface ArticulationDoc {
  page_id: string;
  name: string;
  status: string;
  focus_areas: string[];
  drive_url: string | null;
  support_from: string;
  notion_url: string;
  sync_chunks: number;
  sync_chars: number;
  last_synced: string | null;
}

interface DocsData {
  documents: ArticulationDoc[];
  total: number;
  synced: number;
  articulation_structure: string[];
  error?: string;
}

const STATUS_STYLES: Record<string, string> = {
  Done: "bg-green-100 text-green-800",
  "Review Completed": "bg-blue-100 text-blue-800",
  "Review Pending": "bg-purple-100 text-purple-800",
  "In progress": "bg-yellow-100 text-yellow-800",
  "Not started": "bg-gray-100 text-gray-600",
};

const FOCUS_COLORS: Record<string, string> = {
  General: "bg-orange-50 text-orange-700 border-orange-200",
  "Climate & Climate Tech": "bg-blue-50 text-blue-700 border-blue-200",
  "Agriculture & Agritech": "bg-purple-50 text-purple-700 border-purple-200",
  "AI for Sciences": "bg-amber-50 text-amber-700 border-amber-200",
  "Deep Tech": "bg-gray-50 text-gray-700 border-gray-200",
  "Social Impact": "bg-red-50 text-red-700 border-red-200",
  "Advanced Earth Sciences": "bg-pink-50 text-pink-700 border-pink-200",
};

export function DocumentsList() {
  const [data, setData] = useState<DocsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showStructure, setShowStructure] = useState(false);

  useEffect(() => {
    fetch("/api/status/documents-list")
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
            Loading articulation documents...
          </span>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.documents.length === 0) return null;

  const statusCounts = data.documents.reduce(
    (acc, d) => {
      acc[d.status] = (acc[d.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const withDrive = data.documents.filter((d) => d.drive_url).length;
  const syncedCount = data.synced ?? 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-indigo-500" />
              Grant Articulation Documents
            </CardTitle>
            <p className="mt-1 text-xs text-gray-500">
              {data.total} documents &middot; {withDrive} linked to Google Drive
              &middot; {syncedCount}/{data.total} indexed &middot; Following the
              12-section structure
            </p>
          </div>
          <button
            onClick={() => setShowStructure((p) => !p)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <ListChecks className="h-3.5 w-3.5" />
            {showStructure ? "Hide" : "Show"} Structure
          </button>
        </div>

        {/* 12-section articulation structure */}
        {showStructure && data.articulation_structure.length > 0 && (
          <div className="mt-3 rounded-lg border border-indigo-100 bg-indigo-50/50 p-3">
            <p className="text-xs font-semibold text-indigo-700 mb-2">
              Grant Base Document Articulation Structure
            </p>
            <ol className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
              {data.articulation_structure.map((section, i) => (
                <li
                  key={i}
                  className="text-[11px] text-indigo-600 flex items-start gap-1.5"
                >
                  <span className="font-semibold text-indigo-400 shrink-0">
                    {i + 1}.
                  </span>
                  {section}
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Status summary */}
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(statusCounts)
            .sort(
              ([a], [b]) =>
                (
                  {
                    "In progress": 0,
                    "Review Pending": 1,
                    "Review Completed": 2,
                    Done: 3,
                    "Not started": 4,
                  } as Record<string, number>
                )[a] -
                (
                  {
                    "In progress": 0,
                    "Review Pending": 1,
                    "Review Completed": 2,
                    Done: 3,
                    "Not started": 4,
                  } as Record<string, number>
                )[b]
            )
            .map(([status, count]) => (
              <span
                key={status}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600"}`}
              >
                {status}: {count}
              </span>
            ))}
        </div>
      </CardHeader>

      <CardContent>
        <div className="divide-y divide-gray-100">
          {data.documents.map((doc) => (
            <div
              key={doc.page_id}
              className="flex items-center justify-between py-2.5 gap-3"
            >
              <div className="flex items-start gap-2.5 min-w-0 flex-1">
                <FileText className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {doc.name}
                    </p>
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLES[doc.status] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {doc.status}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                    {doc.focus_areas.map((area) => (
                      <span
                        key={area}
                        className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${FOCUS_COLORS[area] ?? "bg-gray-50 text-gray-600 border-gray-200"}`}
                      >
                        {area}
                      </span>
                    ))}
                    {doc.support_from && (
                      <span className="text-[10px] text-gray-400">
                        Needs: {doc.support_from}
                      </span>
                    )}
                  </div>
                  {/* Sync status */}
                  <div className="mt-1 flex items-center gap-2">
                    {doc.sync_chunks > 0 ? (
                      <span className="inline-flex items-center gap-1 text-[10px] text-green-600">
                        <CheckCircle2 className="h-3 w-3" />
                        {doc.sync_chunks} chunks &middot;{" "}
                        {formatChars(doc.sync_chars)} chars
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
                        <Database className="h-3 w-3" />
                        Not indexed
                      </span>
                    )}
                    {doc.last_synced && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
                        <Clock className="h-3 w-3" />
                        {formatRelativeTime(doc.last_synced)}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1.5 shrink-0">
                {doc.drive_url && (
                  <a
                    href={doc.drive_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded p-1 text-green-500 hover:bg-green-50 hover:text-green-700 transition-colors"
                    title="Open in Google Drive"
                  >
                    <svg
                      className="h-4 w-4"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                    >
                      <path d="M7.71 3.5L1.15 15l4.58 7.5h13.54l4.58-7.5L17.29 3.5H7.71zm-.32 1h9.22l5.07 9.5H13.4l-5.07-9.5h-.94zm.94 0l5.07 9.5H2.11L7.33 4.5zM2.53 15h10.28l-2.93 5H5.46L2.53 15zm11.07 0h7.87l-2.93 5H10.67l2.93-5z" />
                    </svg>
                  </a>
                )}
                {doc.notion_url && (
                  <a
                    href={doc.notion_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                    title="Open in Notion"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 border-t border-gray-100 pt-3">
          <p className="text-xs text-gray-500">
            Each document follows the 12-section articulation structure. Content
            is fetched from Notion pages and linked Google Drive docs, then
            indexed as high-priority chunks during knowledge sync.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
