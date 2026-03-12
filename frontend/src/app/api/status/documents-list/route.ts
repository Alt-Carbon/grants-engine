/**
 * GET /api/status/documents-list — Articulation documents from Notion
 */
export async function GET() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/status/documents-list`, {
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    return Response.json(
      {
        documents: [],
        total: 0,
        articulation_structure: [],
        error: e instanceof Error ? e.message : "Backend unreachable",
      },
      { status: 200 }
    );
  }
}
