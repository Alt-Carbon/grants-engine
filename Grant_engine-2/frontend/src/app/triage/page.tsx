import { getTriageQueue } from "@/lib/queries";
import { TriageQueue } from "./TriageQueue";

export const revalidate = 0;

export default async function TriagePage() {
  const grants = await getTriageQueue();

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Triage Queue</h1>
        <p className="mt-1 text-sm text-gray-500">
          {grants.length} grant{grants.length !== 1 ? "s" : ""} awaiting review · sorted by
          score
        </p>
      </div>

      {grants.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-gray-400">
          <p className="text-lg font-medium">Triage queue is empty</p>
          <p className="mt-1 text-sm">Run the Scout to discover new grants</p>
        </div>
      ) : (
        <TriageQueue grants={grants} />
      )}
    </div>
  );
}
