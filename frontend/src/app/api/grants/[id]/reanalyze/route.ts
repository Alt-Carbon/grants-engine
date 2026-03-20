/**
 * POST /api/grants/[id]/reanalyze
 * Proxy to FastAPI POST /run/analyst/rescore/{grant_id} — re-run analyst on a single grant.
 */
import { proxyHeaders } from "@/lib/api";
import { NextRequest } from "next/server";

function env() {
  return {
    url: (process.env.FASTAPI_URL ?? "").replace(/\/+$/, ""),
  };
}

export async function POST(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  const { url } = env();
  const { id } = await props.params;
  try {
    const res = await fetch(`${url}/run/analyst/rescore/${id}`, {
      method: "POST",
      headers: await proxyHeaders(),
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
