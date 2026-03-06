import { getAuditLogs, type AuditEntry } from "@/lib/queries";
import { AuditView } from "./AuditView";

export const revalidate = 0;

export default async function AuditPage() {
  const logs = await getAuditLogs(undefined, 200);
  return <AuditView logs={logs} />;
}
