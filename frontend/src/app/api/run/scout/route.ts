/**
 * POST /api/run/scout   — trigger a manual scout run
 * GET  /api/run/scout   — poll scout job status
 */
const FASTAPI_URL = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
const INTERNAL_SECRET = process.env.INTERNAL_SECRET!;

export async function POST() {
  try {
    const res = await fetch(`${FASTAPI_URL}/run/scout`, {
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
    const res = await fetch(`${FASTAPI_URL}/status/scout`, {
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
