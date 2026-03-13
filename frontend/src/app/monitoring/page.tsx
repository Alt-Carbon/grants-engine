import {
  getActivityFeed,
  getRecentDiscoveries,
  getPipelineSummary,
  getScoutRuns,
} from "@/lib/queries";
import MissionControl from "./MissionControl";

export const revalidate = 0;

export default async function MonitoringPage() {
  // Fetch in parallel with individual error boundaries — never block page render
  const [activity, discoveries, pipeline, scoutRuns] = await Promise.all([
    getActivityFeed(30).catch(() => []),
    getRecentDiscoveries(20).catch(() => []),
    getPipelineSummary().catch(() => null),
    getScoutRuns(10).catch(() => []),
  ]);

  return (
    <div className="min-h-screen bg-slate-50/50 p-4 sm:p-6">
      <MissionControl
        initialActivity={activity}
        initialDiscoveries={discoveries}
        initialPipeline={pipeline}
        initialScoutRuns={scoutRuns}
      />
    </div>
  );
}
