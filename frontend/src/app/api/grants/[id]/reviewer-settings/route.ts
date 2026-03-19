/**
 * GET    /api/grants/[id]/reviewer-settings — read per-grant reviewer settings (fallback to global)
 * POST   /api/grants/[id]/reviewer-settings — save per-grant reviewer settings
 * DELETE /api/grants/[id]/reviewer-settings — remove per-grant reviewer settings (revert to global)
 */
import { getDb } from "@/lib/mongodb";
import { auth } from "@/lib/auth";
import { ObjectId } from "mongodb";
import { NextRequest, NextResponse } from "next/server";

/**
 * GET — Returns the grant's reviewer_settings if they exist,
 * otherwise falls back to the global reviewer config from agent_config
 * with an `is_default: true` flag so the UI knows it's not customized.
 */
export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const db = await getDb();

    // Try to load per-grant settings
    let grantDoc;
    try {
      grantDoc = await db
        .collection("grants_scored")
        .findOne({ _id: new ObjectId(id) }, { projection: { reviewer_settings: 1 } });
    } catch {
      return NextResponse.json({ error: "Invalid grant ID" }, { status: 400 });
    }

    if (!grantDoc) {
      return NextResponse.json({ error: "Grant not found" }, { status: 404 });
    }

    const grantSettings = grantDoc.reviewer_settings;

    if (grantSettings && Object.keys(grantSettings).length > 0) {
      // Per-grant settings exist — return them
      return NextResponse.json({
        funder_strictness: grantSettings.funder_strictness ?? null,
        scientific_strictness: grantSettings.scientific_strictness ?? null,
        funder_focus_areas: grantSettings.funder_focus_areas ?? null,
        scientific_focus_areas: grantSettings.scientific_focus_areas ?? null,
        custom_criteria: grantSettings.custom_criteria ?? null,
        custom_instructions: grantSettings.custom_instructions ?? null,
        is_default: false,
      });
    }

    // No per-grant settings — fall back to global config
    const globalCfg = await db
      .collection("agent_config")
      .findOne({ agent: "reviewer" });

    return NextResponse.json({
      funder_strictness: globalCfg?.funder?.strictness ?? "balanced",
      scientific_strictness: globalCfg?.scientific?.strictness ?? "balanced",
      funder_focus_areas: globalCfg?.funder?.focus_areas ?? [],
      scientific_focus_areas: globalCfg?.scientific?.focus_areas ?? [],
      custom_criteria: globalCfg?.funder?.custom_criteria ?? [],
      custom_instructions: globalCfg?.funder?.custom_instructions ?? "",
      is_default: true,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * POST — Save per-grant reviewer settings on the grant document.
 * Body: { funder_strictness?, scientific_strictness?, funder_focus_areas?,
 *         scientific_focus_areas?, custom_criteria?, custom_instructions? }
 */
export async function POST(
  req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { id } = await props.params;
    const body = await req.json();
    const {
      funder_strictness,
      scientific_strictness,
      funder_focus_areas,
      scientific_focus_areas,
      custom_criteria,
      custom_instructions,
    } = body as {
      funder_strictness?: string;
      scientific_strictness?: string;
      funder_focus_areas?: string[];
      scientific_focus_areas?: string[];
      custom_criteria?: string[];
      custom_instructions?: string;
    };

    const db = await getDb();

    // Build the reviewer_settings object (only include provided fields)
    const reviewerSettings: Record<string, unknown> = {};
    if (funder_strictness !== undefined) reviewerSettings.funder_strictness = funder_strictness;
    if (scientific_strictness !== undefined) reviewerSettings.scientific_strictness = scientific_strictness;
    if (funder_focus_areas !== undefined) reviewerSettings.funder_focus_areas = funder_focus_areas;
    if (scientific_focus_areas !== undefined) reviewerSettings.scientific_focus_areas = scientific_focus_areas;
    if (custom_criteria !== undefined) reviewerSettings.custom_criteria = custom_criteria;
    if (custom_instructions !== undefined) reviewerSettings.custom_instructions = custom_instructions;
    reviewerSettings.updated_at = new Date().toISOString();
    reviewerSettings.updated_by = session.user.email || session.user.name || "unknown";

    let result;
    try {
      result = await db.collection("grants_scored").updateOne(
        { _id: new ObjectId(id) },
        { $set: { reviewer_settings: reviewerSettings } }
      );
    } catch {
      return NextResponse.json({ error: "Invalid grant ID" }, { status: 400 });
    }

    if (result.matchedCount === 0) {
      return NextResponse.json({ error: "Grant not found" }, { status: 404 });
    }

    return NextResponse.json({
      status: "saved",
      grant_id: id,
      reviewer_settings: reviewerSettings,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * DELETE — Remove per-grant reviewer settings, reverting to global defaults.
 */
export async function DELETE(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { id } = await props.params;
    const db = await getDb();

    let result;
    try {
      result = await db.collection("grants_scored").updateOne(
        { _id: new ObjectId(id) },
        { $unset: { reviewer_settings: "" } }
      );
    } catch {
      return NextResponse.json({ error: "Invalid grant ID" }, { status: 400 });
    }

    if (result.matchedCount === 0) {
      return NextResponse.json({ error: "Grant not found" }, { status: 404 });
    }

    return NextResponse.json({ status: "reset", grant_id: id });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
