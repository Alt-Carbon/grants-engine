/**
 * POST /api/run/analyst/hold — re-run analyst on all hold grants
 */
import { proxyHeaders } from "@/lib/api";

function env() {
  return {
    url: (process.env.FASTAPI_URL ?? "").replace(/\/+$/, ""),
  };
}

export async function POST() {
  const { url } = env();
  try {
    const res = await fetch(`${url}/run/analyst/hold`, {
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
