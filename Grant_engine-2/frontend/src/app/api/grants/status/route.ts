/**
 * POST /api/grants/status
 * Proxy to FastAPI POST /update/grant-status (called by Kanban drag-and-drop).
 */
export async function POST(req: Request) {
  try {
    const body = await req.json();

    const res = await fetch(`${process.env.FASTAPI_URL}/update/grant-status`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": process.env.INTERNAL_SECRET!,
      },
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
