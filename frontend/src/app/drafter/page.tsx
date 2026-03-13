import { getDraftGrants } from "@/lib/queries";
import { DrafterView } from "./DrafterView";

export const revalidate = 0;

export default async function DrafterPage() {
  const pipelines = await getDraftGrants().catch(() => []);

  return (
    <div className="flex h-full flex-col">
      {pipelines.length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-100">
              <svg
                className="h-7 w-7 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-700">
              No active drafts
            </p>
            <p className="mt-1.5 text-sm text-gray-400">
              Approve a grant in the pipeline to start drafting
            </p>
          </div>
        </div>
      ) : (
        <DrafterView pipelines={pipelines} />
      )}
    </div>
  );
}
