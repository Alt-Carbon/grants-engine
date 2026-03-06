import { getGrantById } from "@/lib/queries";
import { NextRequest } from "next/server";

export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const grant = await getGrantById(id);
    if (!grant) {
      return Response.json({ error: "Grant not found" }, { status: 404 });
    }
    return Response.json(grant);
  } catch (e) {
    return Response.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
