import { getDashboardStats, getGrantsActivity, getPipelineGrants } from "@/lib/queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WarningsBanner } from "@/components/WarningsBanner";
import { ActivityChart } from "@/components/ActivityChart";
import { PipelineTable } from "@/components/PipelineTable";
import {
  Telescope,
  ListChecks,
  Target,
  FileText,
  Clock,
} from "lucide-react";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [stats, activity, grants] = await Promise.all([
    getDashboardStats(),
    getGrantsActivity(30),
    getPipelineGrants(),
  ]);

  const kpis = [
    {
      label:   "Total Discovered",
      value:   stats.total_discovered,
      icon:    Telescope,
      color:   "text-blue-600",
      bgColor: "bg-blue-50",
    },
    {
      label:   "In Triage",
      value:   stats.in_triage,
      icon:    ListChecks,
      color:   "text-amber-600",
      bgColor: "bg-amber-50",
    },
    {
      label:   "Pursuing",
      value:   stats.pursuing,
      icon:    Target,
      color:   "text-green-600",
      bgColor: "bg-green-50",
    },
    {
      label:   "Drafting",
      value:   stats.drafting,
      icon:    FileText,
      color:   "text-purple-600",
      bgColor: "bg-purple-50",
    },
    {
      label:   "Urgent Deadlines",
      value:   stats.deadline_urgent_count,
      icon:    Clock,
      color:   "text-red-600",
      bgColor: "bg-red-50",
    },
  ];

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">Grant pipeline overview</p>
      </div>

      {/* Warnings */}
      <WarningsBanner warnings={stats.warnings} />

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
        {kpis.map(({ label, value, icon: Icon, color, bgColor }) => (
          <Card key={label}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-gray-500">{label}</p>
                  <p className={`mt-1 text-3xl font-bold ${color}`}>{value}</p>
                </div>
                <div className={`rounded-xl p-2.5 ${bgColor}`}>
                  <Icon className={`h-5 w-5 ${color}`} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Activity Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Grants Discovered — Last 30 Days</CardTitle>
        </CardHeader>
        <CardContent>
          <ActivityChart data={activity} />
        </CardContent>
      </Card>

      {/* Extra stats row */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-medium text-gray-500">Watching</p>
            <p className="mt-1 text-2xl font-bold text-blue-700">{stats.watching}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-medium text-gray-500">On Hold</p>
            <p className="mt-1 text-2xl font-bold text-orange-600">{stats.on_hold}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-medium text-gray-500">Draft Complete</p>
            <p className="mt-1 text-2xl font-bold text-indigo-600">{stats.draft_complete}</p>
          </CardContent>
        </Card>
      </div>

      {/* All discovered grants */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-900">All Discovered Grants</h2>
        <PipelineTable initialGrants={grants} />
      </div>
    </div>
  );
}
