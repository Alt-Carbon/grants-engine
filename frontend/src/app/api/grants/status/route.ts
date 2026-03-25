/**
 * POST /api/grants/status
 * Proxy to FastAPI POST /update/grant-status so there is a single mutation path.
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
    const grantId = body.grant_id ?? body.grantId;
    const status = body.status;

    if (!grantId || !status) {
      return Response.json(
        { error: "grant_id and status are required" },
        { status: 400 }
      );
    }

    const res = await fetch(`${url}/update/grant-status`, {
      method: "POST",
      headers: await proxyHeaders(),
      body: JSON.stringify({ grant_id: grantId, status }),
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
