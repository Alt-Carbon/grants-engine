import { getAgentConfig } from "@/lib/queries";
import type { AgentConfig } from "@/lib/queries";
import { DrafterSettings } from "./DrafterSettings";

export const revalidate = 0;

export default async function DrafterSettingsPage() {
  const config = (await getAgentConfig("drafter")) as AgentConfig;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Drafter Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure writing style, tone, and theme-specific behaviour
        </p>
      </div>
      <DrafterSettings initialConfig={config} />
    </div>
  );
}
