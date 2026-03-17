/**
 * POST /api/run/scout   — trigger a manual scout run (forwards user identity)
 * GET  /api/run/scout   — poll scout job status
 */
import { proxyHeaders } from "@/lib/api";

function env() {
  return {
    url: (process.env.FASTAPI_URL ?? "").replace(/\/+$/, ""),
    secret: process.env.INTERNAL_SECRET ?? "",
  };
}

export async function POST() {
  const { url } = env();
  try {
    const res = await fetch(`${url}/run/scout`, {
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

export async function GET() {
  const { url, secret } = env();
  try {
    const res = await fetch(`${url}/status/scout`, {
      headers: { "x-internal-secret": secret },
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
