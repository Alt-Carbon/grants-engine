import { apiGet } from "@/lib/api";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const data = await apiGet("/status/scheduler");
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown" },
      { status: 500 }
    );
  }
}
