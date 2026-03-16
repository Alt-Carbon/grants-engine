import { getReviewableGrants } from "@/lib/queries";
import { ReviewersView } from "./ReviewersView";

export const revalidate = 0;

export default async function ReviewersPage() {
  const grants = await getReviewableGrants();

  return (
    <div className="flex h-full flex-col">
      {grants.length === 0 ? (
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
                  d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-700">
              No completed drafts
            </p>
            <p className="mt-1.5 text-sm text-gray-400">
              Complete a draft in the Drafter to run reviews
            </p>
          </div>
        </div>
      ) : (
        <ReviewersView grants={grants} />
      )}
    </div>
  );
}
