import { getDraftGrants } from "@/lib/queries";
import { DrafterView } from "./DrafterView";

export const revalidate = 0;

export default async function DrafterPage() {
  const pipelines = await getDraftGrants();

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Drafter</h1>
        <p className="mt-1 text-sm text-gray-500">
          {pipelines.length} active draft{pipelines.length !== 1 ? "s" : ""}
        </p>
      </div>

      {pipelines.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-gray-400">
          <p className="font-medium">No active drafts</p>
          <p className="mt-1 text-sm">
            Approve a grant in Triage and start a draft to begin
          </p>
        </div>
      ) : (
        <DrafterView pipelines={pipelines} />
      )}
    </div>
  );
}
