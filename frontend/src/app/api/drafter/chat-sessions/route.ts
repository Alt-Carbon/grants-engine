/**
 * GET  /api/drafter/chat-sessions?pipeline_id=X  — list authenticated user's past sessions
 * POST /api/drafter/chat-sessions?pipeline_id=X&snapshot_id=Y  — restore a snapshot
 */
import { apiGet, proxyHeaders } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const pipelineId = req.nextUrl.searchParams.get("pipeline_id");
    if (!pipelineId) {
      return NextResponse.json(
        { error: "pipeline_id is required" },
        { status: 400 }
      );
    }
    const path = `/drafter/chat-sessions/${encodeURIComponent(pipelineId)}`;
    const data = await apiGet(path);
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-sessions GET]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const pipelineId = req.nextUrl.searchParams.get("pipeline_id");
    const snapshotId = req.nextUrl.searchParams.get("snapshot_id");
    if (!pipelineId || !snapshotId) {
      return NextResponse.json(
        { error: "pipeline_id and snapshot_id are required" },
        { status: 400 }
      );
    }

    const url = `${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/drafter/chat-sessions/${encodeURIComponent(pipelineId)}/${encodeURIComponent(snapshotId)}/restore`;
    const res = await fetch(url, {
      method: "POST",
      headers: await proxyHeaders(false),
      cache: "no-store",
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`FastAPI restore failed (${res.status}): ${text}`);
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-sessions POST]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
