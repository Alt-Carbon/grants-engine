/**
 * POST /api/run/sync-profile — re-sync AltCarbon profile from Notion
 *
 * Triggers the backend to fetch key Notion pages and rebuild
 * the static knowledge profile used by Analyst & Drafter agents.
 */
const FASTAPI_URL = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
const INTERNAL_SECRET = process.env.INTERNAL_SECRET!;

export async function POST() {
  try {
    const res = await fetch(`${FASTAPI_URL}/run/sync-profile`, {
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
