import {
  getActivityFeed,
  getRecentDiscoveries,
  getPipelineSummary,
  getScoutRuns,
} from "@/lib/queries";
import MissionControl from "./MissionControl";

export const revalidate = 0;

export default async function MonitoringPage() {
  const [activity, discoveries, pipeline, scoutRuns] = await Promise.all([
    getActivityFeed(30),
    getRecentDiscoveries(20),
    getPipelineSummary(),
    getScoutRuns(10),
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
