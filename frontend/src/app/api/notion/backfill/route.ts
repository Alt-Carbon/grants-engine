/**
 * POST /api/notion/backfill
 *
 * Proxy to FastAPI /admin/notion-backfill
 */
import { NextRequest, NextResponse } from "next/server";

function env() {
  return {
    url: (process.env.FASTAPI_URL ?? "").replace(/\/+$/, ""),
    secret: process.env.INTERNAL_SECRET ?? "",
  };
}

export async function POST(req: NextRequest) {
  const { url, secret } = env();
  try {
    let setupViews = false;
    try {
      const body = await req.json();
      setupViews = Boolean(body?.setup_views);
    } catch {
      setupViews = false;
    }

    const endpoint = setupViews
      ? `${url}/admin/notion-backfill?setup_views=true`
      : `${url}/admin/notion-backfill`;

    const res = await fetch(endpoint, {
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

