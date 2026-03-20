/**
 * GET /api/draft/[grantId]/diff?v1=N&v2=M
 * Proxy to FastAPI GET /draft/{grantId}/diff — section-by-section diff between two versions.
 */
import { proxyHeaders } from "@/lib/api";
import { NextRequest } from "next/server";

export async function GET(
  req: NextRequest,
  props: { params: Promise<{ grantId: string }> }
) {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const { grantId } = await props.params;
    const v1 = req.nextUrl.searchParams.get("v1");
    const v2 = req.nextUrl.searchParams.get("v2");
    if (!v1 || !v2) {
      return Response.json({ error: "v1 and v2 query params required" }, { status: 400 });
    }
    const res = await fetch(`${url}/draft/${grantId}/diff?v1=${v1}&v2=${v2}`, {
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
