/**
 * POST /api/run/analyst  — trigger analyst to score unprocessed grants
 * GET  /api/run/analyst  — poll analyst job status
 */
const FASTAPI_URL = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
const INTERNAL_SECRET = process.env.INTERNAL_SECRET!;

export async function POST() {
  try {
    const res = await fetch(`${FASTAPI_URL}/run/analyst`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": INTERNAL_SECRET,
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

export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_URL}/status/analyst`, {
      headers: { "x-internal-secret": INTERNAL_SECRET },
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
