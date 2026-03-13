import { getKnowledgeStatus, getSyncLogs } from "@/lib/queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SyncButton } from "./SyncButton";
import { PendingChangesBanner } from "./PendingChangesBanner";
import { TableOfContent } from "./TableOfContent";
import { DocumentsList } from "./DocumentsList";
import { NotionSources } from "./NotionSources";
import { Database, FileText, Cloud, CheckCircle, AlertTriangle, XCircle } from "lucide-react";

export const revalidate = 60; // ISR: refresh every 60s (sync runs daily)

function StatusChip({ status }: { status: "healthy" | "thin" | "critical" }) {
  const map = {
    healthy:  { cls: "bg-green-100 text-green-800",  icon: CheckCircle,    label: "Healthy"  },
    thin:     { cls: "bg-amber-100 text-amber-800",  icon: AlertTriangle,  label: "Thin"     },
    critical: { cls: "bg-red-100 text-red-800",       icon: XCircle,        label: "Critical" },
  };
  const { cls, icon: Icon, label } = map[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${cls}`}>
      <Icon className="h-4 w-4" />
      {label}
    </span>
  );
}

export default async function KnowledgePage() {
  const [health, logs] = await Promise.all([
    getKnowledgeStatus().catch(() => ({
      status: "critical" as const, total_chunks: 0, notion_chunks: 0,
      drive_chunks: 0, past_grant_chunks: 0, last_synced: null, by_type: {},
    })),
    getSyncLogs(5).catch(() => []),
  ]);

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Knowledge Health</h1>
          <p className="mt-1 text-sm text-gray-500">
            Company Brain index — Notion + Google Drive
          </p>
        </div>
        <SyncButton />
      </div>

      {/* Pending changes banner */}
      <PendingChangesBanner />

      {/* Status card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Vector Index Status</CardTitle>
            <StatusChip status={health.status} />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat icon={Database} label="Total Chunks" value={health.total_chunks} />
            <Stat icon={FileText} label="Notion" value={health.notion_chunks} />
            <Stat icon={Cloud} label="Drive" value={health.drive_chunks} />
            <Stat icon={FileText} label="Past Grants" value={health.past_grant_chunks} />
          </div>

          {health.last_synced && (
            <p className="mt-4 text-xs text-gray-500">
              Last synced: {new Date(health.last_synced).toLocaleString()}
            </p>
          )}
          {!health.last_synced && (
            <p className="mt-4 text-xs text-amber-600">Never synced — trigger a sync now</p>
          )}
        </CardContent>
      </Card>

      {/* Knowledge Registry (Table of Content) */}
      <TableOfContent />

      {/* Grant Articulation Documents */}
      <DocumentsList />

      {/* Notion Sources */}
      <NotionSources />

      {/* By type */}
      {Object.keys(health.by_type).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Chunks by Document Type</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {Object.entries(health.by_type)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => (
                  <div
                    key={type}
                    className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"
                  >
                    <span className="text-xs text-gray-600 capitalize">
                      {type.replace(/_/g, " ")}
                    </span>
                    <span className="text-sm font-semibold text-gray-900">{count}</span>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent sync logs */}
      {logs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent Sync Logs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="divide-y divide-gray-100">
              {logs.map((log, i) => (
                <div key={i} className="flex items-center justify-between py-2.5">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {String(log.source || "knowledge")} sync
                    </p>
                    <p className="text-xs text-gray-500">
                      {log.total_chunks !== undefined && `${String(log.total_chunks)} chunks saved`}
                      {log.chunks_skipped ? ` · ${String(log.chunks_skipped)} skipped` : ""}
                      {log.stale_deleted ? ` · ${String(log.stale_deleted)} stale cleaned` : ""}
                    </p>
                  </div>
                  <span className="text-xs text-gray-400">
                    {log.synced_at ? new Date(String(log.synced_at)).toLocaleString() : "—"}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
      <div className="flex items-center gap-2 text-gray-500">
        <Icon className="h-4 w-4" />
        <span className="text-xs">{label}</span>
      </div>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}
