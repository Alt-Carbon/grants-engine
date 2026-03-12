/**
 * POST /api/run/analyst  — trigger analyst to score unprocessed grants
 * GET  /api/run/analyst  — poll analyst job status
 */
function env() {
  return {
    url: (process.env.FASTAPI_URL ?? "").replace(/\/+$/, ""),
    secret: process.env.INTERNAL_SECRET ?? "",
  };
}

export async function POST() {
  const { url, secret } = env();
  try {
    const res = await fetch(`${url}/run/analyst`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": secret,
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
  const { url, secret } = env();
  try {
    const res = await fetch(`${url}/status/analyst`, {
      headers: { "x-internal-secret": secret },
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
