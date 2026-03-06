/**
 * GET /api/whats-new?since=ISO_DATE
 * Returns a digest of what happened since the user's last visit.
 */
import { getWhatsNewDigest } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const since = searchParams.get("since");

  if (!since) {
    return Response.json({ error: "Missing 'since' parameter" }, { status: 400 });
  }

  try {
    const digest = await getWhatsNewDigest(since);
    return Response.json(digest);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
