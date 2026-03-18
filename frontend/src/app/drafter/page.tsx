import { getDraftGrants } from "@/lib/queries";
import { DrafterView } from "./DrafterView";

export const revalidate = 0;

export default async function DrafterPage() {
  const pipelines = await getDraftGrants();

  // Always render DrafterView — even with 0 pipelines, user can use manual draft
  return (
    <div className="flex h-full flex-col">
      <DrafterView pipelines={pipelines} />
    </div>
  );
}
