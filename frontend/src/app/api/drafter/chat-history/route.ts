/**
 * GET  /api/drafter/chat-history?pipeline_id=X  — load persisted chat history
 * PUT  /api/drafter/chat-history                — save/upsert chat history
 * DELETE /api/drafter/chat-history?pipeline_id=X&section_name=Y — clear one section
 */
import { apiGet, apiPost } from "@/lib/api";
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
    const data = await apiGet(
      `/drafter/chat-history/${encodeURIComponent(pipelineId)}`
    );
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-history GET]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PUT(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.pipeline_id || !body.grant_id) {
      return NextResponse.json(
        { error: "pipeline_id and grant_id are required" },
        { status: 400 }
      );
    }

    // apiPost but we need PUT — use fetch directly
    const url = `${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/drafter/chat-history`;
    const res = await fetch(url, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": process.env.INTERNAL_SECRET ?? "",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`FastAPI PUT failed (${res.status}): ${text}`);
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-history PUT]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const pipelineId = req.nextUrl.searchParams.get("pipeline_id");
    const sectionName = req.nextUrl.searchParams.get("section_name");
    if (!pipelineId || !sectionName) {
      return NextResponse.json(
        { error: "pipeline_id and section_name are required" },
        { status: 400 }
      );
    }

    const url = `${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/drafter/chat-history/${encodeURIComponent(pipelineId)}/${encodeURIComponent(sectionName)}`;
    const res = await fetch(url, {
      method: "DELETE",
      headers: {
        "x-internal-secret": process.env.INTERNAL_SECRET ?? "",
      },
      cache: "no-store",
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`FastAPI DELETE failed (${res.status}): ${text}`);
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat-history DELETE]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
