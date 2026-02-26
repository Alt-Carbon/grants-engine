import { getPipelineGrants } from "@/lib/queries";
import { PipelineView } from "@/components/PipelineView";

export const revalidate = 0;

export default async function PipelinePage() {
  const grants = await getPipelineGrants();

  return (
    <div className="flex h-full flex-col gap-4 p-4 sm:p-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">
          Pipeline
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Drag cards between columns &middot; click status badge to change
          &middot; search to filter
        </p>
      </div>

      {/* Kanban / Table view */}
      <div className="flex-1 overflow-hidden">
        <PipelineView initialGrants={grants} />
      </div>
    </div>
  );
}
