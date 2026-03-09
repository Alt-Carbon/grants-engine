/**
 * POST /api/drafter/section-review
 * Proxy to FastAPI POST /resume/section-review.
 */
export async function POST(req: Request) {
  try {
    const body = await req.json();

    const res = await fetch(`${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/resume/section-review`, {
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
