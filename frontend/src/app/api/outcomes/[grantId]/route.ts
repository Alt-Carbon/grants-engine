/**
 * GET /api/outcomes/[grantId]
 * Proxy to FastAPI GET /outcomes/{grantId} — fetch outcome for a grant.
 */
export async function GET(
  _req: Request,
  props: { params: Promise<{ grantId: string }> }
) {
  const { grantId } = await props.params;
  const url = (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${url}/outcomes/${grantId}`, {
      headers: { "x-internal-secret": process.env.INTERNAL_SECRET ?? "" },
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
