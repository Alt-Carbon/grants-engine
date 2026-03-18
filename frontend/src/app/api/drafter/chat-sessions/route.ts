/**
 * GET  /api/drafter/chat-sessions?pipeline_id=X&user_email=Y  — list past sessions
 * POST /api/drafter/chat-sessions?pipeline_id=X&snapshot_id=Y&user_email=Z  — restore a snapshot
 */
import { apiGet } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const pipelineId = req.nextUrl.searchParams.get("pipeline_id");
    const userEmail = req.nextUrl.searchParams.get("user_email");
    if (!pipelineId) {
      return NextResponse.json(
        { error: "pipeline_id is required" },
        { status: 400 }
      );
    }
    let path = `/drafter/chat-sessions/${encodeURIComponent(pipelineId)}`;
    if (userEmail) path += `?user_email=${encodeURIComponent(userEmail)}`;
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
    const userEmail = req.nextUrl.searchParams.get("user_email");
    if (!pipelineId || !snapshotId) {
      return NextResponse.json(
        { error: "pipeline_id and snapshot_id are required" },
        { status: 400 }
      );
    }

    let url = `${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/drafter/chat-sessions/${encodeURIComponent(pipelineId)}/${encodeURIComponent(snapshotId)}/restore`;
    if (userEmail) url += `?user_email=${encodeURIComponent(userEmail)}`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "x-internal-secret": process.env.INTERNAL_SECRET ?? "",
      },
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
