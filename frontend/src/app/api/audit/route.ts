import { getAuditLogs } from "@/lib/queries";
import { NextRequest } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const agent = req.nextUrl.searchParams.get("agent") || undefined;
    const days = req.nextUrl.searchParams.get("days");
    const limit = req.nextUrl.searchParams.get("limit");
    const logs = await getAuditLogs(
      { agent, days: days ? Number(days) : undefined },
      limit ? Number(limit) : 200
    );
    return Response.json(logs);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
