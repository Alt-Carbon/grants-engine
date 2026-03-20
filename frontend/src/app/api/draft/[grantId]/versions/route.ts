/**
 * GET /api/draft/[grantId]/versions
 * Proxy to FastAPI GET /draft/{grantId}/versions — list all draft versions.
 */
import { proxyHeaders } from "@/lib/api";
import { NextRequest } from "next/server";

export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ grantId: string }> }
) {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const { grantId } = await props.params;
    const res = await fetch(`${url}/draft/${grantId}/versions`, {
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
