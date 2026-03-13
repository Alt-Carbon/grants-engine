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
    getPipelineSummary().catch(() => ({
      total_discovered: 0, in_triage: 0, pursuing: 0, on_hold: 0,
      drafting: 0, submitted: 0, rejected: 0, urgent: 0, unprocessed: 0,
    })),
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
