import { apiPost } from "@/lib/api";
import { auth } from "@/lib/auth";
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    const { action } = await req.json();
    const validActions: Record<string, string> = {
      backfill: "/admin/backfill-fields",
      deduplicate: "/admin/deduplicate",
      "notion-backfill": "/admin/notion-backfill",
      "reconnect-mcp": "/run/mcp/reconnect-all",
      "reconnect-notion": "/run/notion-mcp/reconnect",
    };
    const path = validActions[action];
    if (!path) {
      return NextResponse.json({ error: "Invalid action" }, { status: 400 });
    }
    const data = await apiPost(path, {});
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown" },
      { status: 500 }
    );
  }
}
