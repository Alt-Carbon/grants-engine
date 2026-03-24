/**
 * POST /api/drafter/finalize
 * Proxy to FastAPI POST /drafter/finalize — saves draft and triggers review.
 */
import { proxyHeaders } from "@/lib/api";

export async function POST(req: Request) {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const body = await req.json();
    const res = await fetch(`${url}/drafter/finalize`, {
      method: "POST",
      headers: await proxyHeaders(),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: `FastAPI /drafter/finalize failed (${res.status}): ${text.slice(0, 200)}` };
    }
    return Response.json(data, { status: res.status });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
