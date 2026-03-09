"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FileText,
  Database,
  ExternalLink,
  Wifi,
  WifiOff,
  Loader2,
  Search,
  BookMarked,
} from "lucide-react";

interface NotionSource {
  page_id: string;
  title: string;
  type: string;
  icon: string;
  indexed: boolean;
  notion_url: string;
  last_edited: string;
}

interface SourcesData {
  mcp_status: string;
  mcp_tools: number | null;
  sources: NotionSource[];
  total_sources: number;
  indexed_count: number;
  last_synced: string | null;
}

export function NotionSources() {
  const [data, setData] = useState<SourcesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    fetch("/api/status/knowledge-sources")
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
            Discovering Notion workspace...
          </span>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const isConnected = data.mcp_status === "connected";

  const filtered = data.sources.filter(
    (s) =>
      !filter ||
      s.title.toLowerCase().includes(filter.toLowerCase()) ||
      s.type.toLowerCase().includes(filter.toLowerCase())
  );

  const displayed = showAll ? filtered : filtered.slice(0, 20);
  const hasMore = filtered.length > 20 && !showAll;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Notion Workspace</CardTitle>
            <p className="mt-1 text-xs text-gray-500">
              {data.total_sources} pages discovered · {data.indexed_count}{" "}
              indexed for AI agents
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
              isConnected
                ? "bg-green-100 text-green-800"
                : "bg-red-100 text-red-800"
            }`}
          >
            {isConnected ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {isConnected
              ? `Connected · ${data.mcp_tools} tools`
              : "Disconnected"}
          </span>
        </div>

        {data.sources.length > 10 && (
          <div className="relative mt-3">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Filter pages..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-2 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-300 focus:outline-none focus:ring-1 focus:ring-blue-300"
            />
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="divide-y divide-gray-100">
          {displayed.map((src) => (
            <div
              key={src.page_id}
              className="flex items-center justify-between py-2.5"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                {src.icon ? (
                  <span className="text-base flex-shrink-0">{src.icon}</span>
                ) : src.type === "database" ? (
                  <Database className="h-4 w-4 text-blue-400 flex-shrink-0" />
                ) : (
                  <FileText className="h-4 w-4 text-gray-400 flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {src.title || "Untitled"}
                    </p>
                    {src.indexed && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 flex-shrink-0">
                        <BookMarked className="h-3 w-3" />
                        Indexed
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400">
                    {src.type}
                    {src.last_edited &&
                      ` · edited ${new Date(src.last_edited).toLocaleDateString()}`}
                  </p>
                </div>
              </div>
              <a
                href={src.notion_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 flex-shrink-0"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>
          ))}
        </div>

        {hasMore && (
          <button
            onClick={() => setShowAll(true)}
            className="mt-3 w-full rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Show all {filtered.length} pages
          </button>
        )}

        {displayed.length === 0 && (
          <p className="py-6 text-center text-sm text-gray-400">
            {filter ? "No pages match your filter" : "No pages found"}
          </p>
        )}

        <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3">
          <p className="text-xs text-gray-500">
            Connected to Notion via MCP
          </p>
          {data.last_synced && (
            <p className="text-xs text-gray-400">
              Profile synced: {new Date(data.last_synced).toLocaleString()}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
