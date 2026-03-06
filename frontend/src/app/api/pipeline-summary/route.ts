/**
 * GET /api/pipeline-summary — Pipeline funnel stats for Mission Control
 */
import { getPipelineSummary } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const summary = await getPipelineSummary();
    return Response.json(summary);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
