/**
 * GET /api/status/table-of-content — Knowledge sources from Table of Content (Grants DB)
 */
export async function GET() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/status/table-of-content`, {
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    return Response.json(
      {
        sources: [],
        total: 0,
        main_sources: 0,
        synced: 0,
        error: e instanceof Error ? e.message : "Backend unreachable",
      },
      { status: 200 }
    );
  }
}
