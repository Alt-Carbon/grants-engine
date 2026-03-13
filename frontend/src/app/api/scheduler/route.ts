import { apiPost } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { action } = await req.json();
    if (action === "pause") {
      const data = await apiPost("/scheduler/pause", {});
      return NextResponse.json(data);
    } else if (action === "resume") {
      const data = await apiPost("/scheduler/resume", {});
      return NextResponse.json(data);
    }
    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown" },
      { status: 500 }
    );
  }
}
