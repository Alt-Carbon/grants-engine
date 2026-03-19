/**
 * GET  /api/config          — read agent config from MongoDB
 * POST /api/config          — save agent config to MongoDB
 */
import { getAgentConfig, saveAgentConfig } from "@/lib/queries";
import { auth } from "@/lib/auth";
import { NextRequest } from "next/server";

export async function GET(req: NextRequest) {
  const agent = req.nextUrl.searchParams.get("agent") || undefined;
  try {
    const config = await getAgentConfig(agent);
    return Response.json(config);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    const { agent, config } = await req.json() as { agent: string; config: Record<string, unknown> };
    if (!agent) return Response.json({ error: "agent required" }, { status: 400 });
    await saveAgentConfig(agent, config);
    return Response.json({ status: "saved", agent });
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
