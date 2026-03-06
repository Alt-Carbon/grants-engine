/**
 * GET /api/activity — Live activity feed for Mission Control
 * Returns recent audit log entries for real-time display.
 */
import { getActivityFeed } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const events = await getActivityFeed(30);
    return Response.json(events);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
