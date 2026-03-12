/**
 * POST /api/run/notion-mcp/reconnect
 *
 * Proxy to FastAPI /run/notion-mcp/reconnect
 */
import { NextResponse } from "next/server";

export async function POST() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  const secret = process.env.INTERNAL_SECRET ?? "";
  try {
    const res = await fetch(`${url}/run/notion-mcp/reconnect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": secret,
      },
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

