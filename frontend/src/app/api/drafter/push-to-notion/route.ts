/**
 * POST /api/drafter/push-to-notion
 *
 * Proxy to FastAPI /drafter/push-to-notion
 */
import { apiPost } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.grant_id) {
      return NextResponse.json(
        { error: "grant_id is required" },
        { status: 400 }
      );
    }
    const data = await apiPost("/drafter/push-to-notion", body);
    return NextResponse.json(data);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/push-to-notion]", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

