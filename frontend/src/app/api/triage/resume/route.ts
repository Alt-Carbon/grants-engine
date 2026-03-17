/**
 * POST /api/triage/resume
 * Proxy to FastAPI POST /resume/triage — forwards user identity.
 */
import { proxyHeaders } from "@/lib/api";

export async function POST(req: Request) {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const body = await req.json();
    const res = await fetch(`${url}/resume/triage`, {
      method: "POST",
      headers: await proxyHeaders(),
      body: JSON.stringify(body),
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
