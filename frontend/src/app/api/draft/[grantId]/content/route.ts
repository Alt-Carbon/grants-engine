/**
 * GET /api/draft/[grantId]/content
 * Returns draft content for export (PDF/Markdown).
 * Looks in grants_pipeline.latest_draft, then grant_drafts collection.
 */
import { getDb } from "@/lib/mongodb";
import { ObjectId } from "mongodb";
import { NextRequest, NextResponse } from "next/server";

export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ grantId: string }> }
) {
  try {
    const { grantId } = await props.params;
    const db = await getDb();

    // 1. Try grants_pipeline.latest_draft
    let pipeline;
    try {
      pipeline = await db.collection("grants_pipeline").findOne(
        { grant_id: grantId, status: { $nin: ["cancelled"] } },
        { sort: { started_at: -1 }, projection: { latest_draft: 1 } }
      );
    } catch {
      // grantId might not be valid — ignore
    }

    let sections = pipeline?.latest_draft?.sections;

    // 2. Fallback: grant_drafts collection
    if (!sections || Object.keys(sections).length === 0) {
      const draft = await db.collection("grant_drafts").findOne(
        { grant_id: grantId },
        { sort: { version: -1 } }
      );
      sections = draft?.sections;
    }

    if (!sections || Object.keys(sections).length === 0) {
      return NextResponse.json({ error: "No draft found" }, { status: 404 });
    }

    // 3. Load grant metadata
    let grant;
    try {
      grant = await db.collection("grants_scored").findOne(
        { _id: new ObjectId(grantId) },
        { projection: { grant_name: 1, title: 1, funder: 1, deadline: 1, max_funding_usd: 1, max_funding: 1 } }
      );
    } catch {
      grant = null;
    }

    // 4. Build response matching DraftContent interface
    let totalWords = 0;
    const formattedSections: Record<string, unknown> = {};
    for (const [name, sec] of Object.entries(sections)) {
      const s = sec as Record<string, unknown>;
      const wc = (s.word_count as number) || (s.content as string || "").split(/\s+/).length;
      totalWords += wc;
      formattedSections[name] = {
        content: s.content || "",
        word_count: wc,
        word_limit: (s.word_limit as number) || 500,
        within_limit: wc <= ((s.word_limit as number) || 500),
      };
    }

    return NextResponse.json({
      grant_id: grantId,
      grant_title: grant?.grant_name || grant?.title || "Untitled",
      funder: grant?.funder || "",
      deadline: grant?.deadline || "",
      max_funding: grant?.max_funding_usd || grant?.max_funding || "",
      version: pipeline?.latest_draft?.version || 1,
      sections: formattedSections,
      evidence_gaps: [],
      total_word_count: totalWords,
      created_at: pipeline?.latest_draft?.created_at || new Date().toISOString(),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
