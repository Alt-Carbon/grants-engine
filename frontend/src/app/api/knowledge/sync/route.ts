/**
 * POST /api/knowledge/sync
 * Proxy to FastAPI POST /run/knowledge-sync.
 */
export async function POST() {
  try {
    const res = await fetch(`${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/run/knowledge-sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": process.env.INTERNAL_SECRET!,
      },
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
