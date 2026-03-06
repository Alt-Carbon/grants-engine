/**
 * GET /api/discoveries — Recently discovered grants for Mission Control
 * Shows what grants were added, when, with scores and status.
 */
import { getRecentDiscoveries } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const grants = await getRecentDiscoveries(20);
    return Response.json(grants);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
