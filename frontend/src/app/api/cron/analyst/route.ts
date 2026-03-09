/**
 * GET /api/cron/analyst
 * Called by Vercel Cron every 48h at 4 AM UTC (2h after scout).
 * Scores any unprocessed grants sitting in grants_raw.
 */
export async function GET(req: Request) {
  const auth = req.headers.get("authorization");
  if (auth !== `Bearer ${process.env.CRON_SECRET}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const res = await fetch(`${(process.env.FASTAPI_URL ?? "").replace(/\/+$/, "")}/run/analyst`, {
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
    console.error("Cron analyst trigger failed:", e);
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
