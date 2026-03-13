/**
 * POST /api/grants/status
 * Update a grant's status — proxies to backend v2 API (Notion).
 */
import { apiPost } from "@/lib/api";

const VALID_STATUSES = new Set([
  "triage",
  "pursue",
  "pursuing",
  "drafting",
  "draft_complete",
  "submitted",
  "won",
  "passed",
  "auto_pass",
  "human_passed",
  "hold",
  "reported",
]);

export async function POST(req: Request) {
  try {
    const { grant_id, status } = await req.json();

    if (!grant_id || !status) {
      return Response.json(
        { error: "grant_id and status are required" },
        { status: 400 }
      );
    }

    if (!VALID_STATUSES.has(status)) {
      return Response.json(
        { error: `Invalid status: ${status}` },
        { status: 400 }
      );
    }

    const result = await apiPost("/api/v2/grants/status", { grant_id, status });
    return Response.json(result);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
