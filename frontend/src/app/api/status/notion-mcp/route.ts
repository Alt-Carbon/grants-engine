/**
 * GET /api/status/notion-mcp
 *
 * Proxy to FastAPI /status/notion-mcp
 */
import { NextResponse } from "next/server";

export async function GET() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  const secret = process.env.INTERNAL_SECRET ?? "";
  try {
    const res = await fetch(`${url}/status/notion-mcp`, {
      headers: { "x-internal-secret": secret },
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      {
        status: "disconnected",
        error: e instanceof Error ? e.message : "Unknown error",
      },
      { status: 200 }
    );
  }
}

