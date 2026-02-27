/**
 * POST /api/grants/status
 * Update a grant's status directly in MongoDB.
 */
import { ObjectId } from "mongodb";
import { getDb } from "@/lib/mongodb";

const VALID_STATUSES = new Set([
  "triage",
  "pursue",
  "pursuing",
  "watch",
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

    const db = await getDb();

    // Build the update — track human overrides for passed statuses
    const isHumanOverride = status === "human_passed";
    const update: Record<string, unknown> = { status };
    if (isHumanOverride) {
      update.human_override = true;
      update.override_at = new Date().toISOString();
    }

    let filter: Record<string, unknown>;
    try {
      filter = { _id: new ObjectId(grant_id) };
    } catch {
      // If grant_id isn't a valid ObjectId, try as string
      filter = { _id: grant_id };
    }

    const result = await db
      .collection("grants_scored")
      .updateOne(filter, { $set: update });

    if (result.matchedCount === 0) {
      return Response.json(
        { error: "Grant not found" },
        { status: 404 }
      );
    }

    return Response.json({ ok: true, status });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
