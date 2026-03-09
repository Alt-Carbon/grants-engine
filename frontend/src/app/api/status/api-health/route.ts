/**
 * GET /api/status/api-health — poll external API credit/quota health
 */
export async function GET() {
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/status/api-health`, {
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    // If backend is down, return all-unknown status
    return Response.json(
      {
        services: {
          tavily: { status: "unknown" },
          exa: { status: "unknown" },
          perplexity: { status: "unknown" },
          jina: { status: "unknown" },
        },
        error: e instanceof Error ? e.message : "Backend unreachable",
      },
      { status: 200 }
    );
  }
}
