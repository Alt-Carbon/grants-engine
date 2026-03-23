/**
 * GET  /api/grants/[id]/drafter-settings — read per-grant drafter settings (fallback to global)
 * POST /api/grants/[id]/drafter-settings — save per-grant drafter settings
 */
import { getDb } from "@/lib/mongodb";
import { auth } from "@/lib/auth";
import { ObjectId } from "mongodb";
import { NextRequest, NextResponse } from "next/server";

/**
 * GET — Returns the grant's drafter_settings if they exist,
 * otherwise falls back to the global drafter config from agent_config
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
        .findOne({ _id: new ObjectId(id) }, { projection: { drafter_settings: 1 } });
    } catch {
      return NextResponse.json({ error: "Invalid grant ID" }, { status: 400 });
    }

    if (!grantDoc) {
      return NextResponse.json({ error: "Grant not found" }, { status: 404 });
    }

    const grantSettings = grantDoc.drafter_settings;

    if (grantSettings && Object.keys(grantSettings).length > 0) {
      // Per-grant settings exist — return them
      return NextResponse.json({
        writing_style: grantSettings.writing_style ?? null,
        custom_instructions: grantSettings.custom_instructions ?? null,
        temperature: grantSettings.temperature ?? null,
        theme_settings: grantSettings.theme_settings ?? null,
        is_default: false,
      });
    }

    // No per-grant settings — fall back to global config
    const globalCfg = await db
      .collection("agent_config")
      .findOne({ agent: "drafter" });

    return NextResponse.json({
      writing_style: globalCfg?.writing_style ?? "professional",
      custom_instructions: globalCfg?.custom_instructions ?? "",
      temperature: globalCfg?.temperature ?? null,
      theme_settings: globalCfg?.theme_settings ?? null,
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
 * POST — Save per-grant drafter settings on the grant document.
 * Body: { writing_style?, custom_instructions?, temperature? }
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
    const { writing_style, custom_instructions, temperature, theme_settings } = body as {
      writing_style?: string;
      custom_instructions?: string;
      temperature?: number;
      theme_settings?: Record<string, unknown>;
    };

    const db = await getDb();

    // Validate writing_style if provided (trained on reference grants)
    const VALID_STYLES = ["professional", "scientific"];
    if (writing_style !== undefined && !VALID_STYLES.includes(writing_style)) {
      return NextResponse.json(
        { error: `Invalid writing_style. Must be one of: ${VALID_STYLES.join(", ")}` },
        { status: 400 }
      );
    }

    // Build the drafter_settings object (only include provided fields)
    const drafterSettings: Record<string, unknown> = {};
    if (writing_style !== undefined) drafterSettings.writing_style = writing_style;
    if (custom_instructions !== undefined) drafterSettings.custom_instructions = custom_instructions;
    if (temperature !== undefined) drafterSettings.temperature = temperature;
    if (theme_settings !== undefined) drafterSettings.theme_settings = theme_settings;
    drafterSettings.updated_at = new Date().toISOString();
    drafterSettings.updated_by = session.user.email || session.user.name || "unknown";

    let result;
    try {
      result = await db.collection("grants_scored").updateOne(
        { _id: new ObjectId(id) },
        { $set: { drafter_settings: drafterSettings } }
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
      drafter_settings: drafterSettings,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * DELETE — Remove per-grant drafter settings, reverting to global defaults.
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
        { $unset: { drafter_settings: "" } }
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
