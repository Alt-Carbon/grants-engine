/**
 * POST /api/run/sync-profile — re-sync AltCarbon profile from Notion
 *
 * Triggers the backend to fetch key Notion pages and rebuild
 * the static knowledge profile used by Analyst & Drafter agents.
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
    const res = await fetch(`${url}/run/sync-profile`, {
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
