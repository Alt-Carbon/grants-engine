/**
 * GET /api/drafter/global-settings
 *
 * Returns the global drafter agent_config defaults (used by manual drafts
 * that have no per-grant MongoDB document).
 */
import { getDb } from "@/lib/mongodb";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const db = await getDb();
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
