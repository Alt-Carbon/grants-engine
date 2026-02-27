import { getAgentConfig } from "@/lib/queries";
import { ConfigEditor } from "./ConfigEditor";
import type { AgentConfig } from "@/lib/queries";

export const revalidate = 0;

export default async function ConfigPage() {
  const configs = (await getAgentConfig()) as Record<string, AgentConfig>;

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Agent Config</h1>
        <p className="mt-1 text-sm text-gray-500">
          Edit search themes, scoring weights, and agent behaviour
        </p>
      </div>

      <ConfigEditor initialConfigs={configs} />
    </div>
  );
}
