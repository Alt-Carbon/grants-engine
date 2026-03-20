/**
 * POST /api/grants/replay
 * Proxy to FastAPI POST /grants/replay — reset a grant for re-testing.
 */
import { proxyHeaders } from "@/lib/api";
import { auth } from "@/lib/auth";

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const body = await req.json();
    const res = await fetch(`${url}/grants/replay`, {
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
