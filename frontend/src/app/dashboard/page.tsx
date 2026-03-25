import {
  getDashboardStats,
  getGrantsActivity,
  getPipelineGrants,
} from "@/lib/queries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WarningsBanner } from "@/components/WarningsBanner";
import { WhatsNewDigest } from "@/components/WhatsNewDigest";
import { ActivityChart } from "@/components/ActivityChart";
import { PipelineTable } from "@/components/PipelineTable";
import { RerunHoldButton } from "@/components/RerunHoldButton";
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
      label: "Total Discovered",
      value: stats.total_discovered,
      icon: Telescope,
      color: "text-blue-600",
      bgColor: "bg-blue-50",
    },
    {
      label: "Shortlisted",
      value: stats.in_triage,
      icon: ListChecks,
      color: "text-amber-600",
      bgColor: "bg-amber-50",
    },
    {
      label: "Pursuing",
      value: stats.pursuing,
      icon: Target,
      color: "text-green-600",
      bgColor: "bg-green-50",
    },
    {
      label: "Drafting",
      value: stats.drafting,
      icon: FileText,
      color: "text-purple-600",
      bgColor: "bg-purple-50",
    },
    {
      label: "Urgent Deadlines",
      value: stats.deadline_urgent_count,
      icon: Clock,
      color: "text-red-600",
      bgColor: "bg-red-50",
    },
  ];

  return (
    <div className="flex flex-col gap-4 p-4 sm:gap-6 sm:p-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-gray-500">Grant pipeline overview</p>
      </div>

      {/* What's New — returning user digest */}
      <WhatsNewDigest />

      {/* Warnings */}
      <WarningsBanner warnings={stats.warnings} />

      {/* KPI cards — 2 cols mobile, 3 cols sm, 5 cols xl */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-5">
        {kpis.map(({ label, value, icon: Icon, color, bgColor }) => (
          <Card key={label}>
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-medium text-gray-500 sm:text-xs">
                    {label}
                  </p>
                  <p
                    className={`mt-1 text-2xl font-bold sm:text-3xl ${color}`}
                  >
                    {value}
                  </p>
                </div>
                <div
                  className={`shrink-0 rounded-xl p-2 sm:p-2.5 ${bgColor}`}
                >
                  <Icon className={`h-4 w-4 sm:h-5 sm:w-5 ${color}`} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Activity Chart */}
      <Card>
        <CardHeader className="px-4 py-3 sm:px-6 sm:py-4">
          <CardTitle className="text-sm sm:text-base">
            Grants Discovered &mdash; Last 30 Days
          </CardTitle>
        </CardHeader>
        <CardContent className="px-2 pb-4 sm:px-6">
          <ActivityChart data={activity} />
        </CardContent>
      </Card>

      {/* Extra stats row — stack on mobile, 3 cols on sm+ */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
        <Card>
          <CardContent className="p-4 sm:p-5">
            <p className="text-xs font-medium text-gray-500">On Hold</p>
            <p className="mt-1 text-2xl font-bold text-orange-600">
              {stats.on_hold}
            </p>
            {stats.on_hold > 0 && <RerunHoldButton />}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 sm:p-5">
            <p className="text-xs font-medium text-gray-500">Submitted</p>
            <p className="mt-1 text-2xl font-bold text-cyan-600">
              {stats.draft_complete}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* All discovered grants */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-gray-900 sm:text-lg">
          All Discovered Grants
        </h2>
        <PipelineTable initialGrants={grants} defaultFilter="all" />
      </div>
    </div>
  );
}
