/**
 * GET /api/drafter/chat-sessions/[id]?pipeline_id=X — get full snapshot content
 */
import { apiGet } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const pipelineId = req.nextUrl.searchParams.get("pipeline_id");
    if (!pipelineId) {
      return NextResponse.json(
        { error: "pipeline_id is required" },
        { status: 400 }
      );
    }
    const path = `/drafter/chat-sessions/${encodeURIComponent(pipelineId)}/${encodeURIComponent(id)}`;
    const data = await apiGet(path);
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-sessions/[id] GET]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
