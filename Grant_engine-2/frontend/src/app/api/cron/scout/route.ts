/**
 * GET /api/cron/scout
 * Called by Vercel Cron every Monday at 2 AM UTC (see vercel.json).
 * Vercel attaches an Authorization: Bearer <CRON_SECRET> header automatically.
 */
export async function GET(req: Request) {
  const auth = req.headers.get("authorization");
  if (auth !== `Bearer ${process.env.CRON_SECRET}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const res = await fetch(`${process.env.FASTAPI_URL}/run/scout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": process.env.INTERNAL_SECRET!,
      },
      cache: "no-store",
    });

    const data = await res.json();
    return Response.json({ triggered: true, fastapi: data });
  } catch (e) {
    console.error("Cron scout trigger failed:", e);
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
