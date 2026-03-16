import { getAgentConfig } from "@/lib/queries";
import type { AgentConfig } from "@/lib/queries";
import { ReviewerSettings } from "./ReviewerSettings";

export const revalidate = 0;

export default async function ReviewerSettingsPage() {
  const config = (await getAgentConfig("reviewer")) as AgentConfig;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Reviewer Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure how the Funder and Scientific reviewer agents evaluate drafts
        </p>
      </div>
      <ReviewerSettings initialConfig={config} />
    </div>
  );
}
