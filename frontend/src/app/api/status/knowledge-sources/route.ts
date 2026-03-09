/**
 * GET /api/status/knowledge-sources — Notion sources and MCP status
 */
export async function GET() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/status/knowledge-sources`, {
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    return Response.json(
      {
        mcp_status: "unknown",
        mcp_tools: null,
        sources: [],
        total_sources: 0,
        last_synced: null,
        error: e instanceof Error ? e.message : "Backend unreachable",
      },
      { status: 200 }
    );
  }
}
