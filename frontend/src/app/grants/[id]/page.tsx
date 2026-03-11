import { getGrantById } from "@/lib/queries";
import { notFound } from "next/navigation";
import { GrantDetailPage } from "./GrantDetailPage";

export const revalidate = 0;

export default async function GrantPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const grant = await getGrantById(id);
  if (!grant) notFound();

  // Serialize for client component
  const serialized = JSON.parse(JSON.stringify(grant));

  return <GrantDetailPage grant={serialized} />;
}
