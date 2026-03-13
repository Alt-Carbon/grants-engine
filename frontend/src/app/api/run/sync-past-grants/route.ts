import { apiPost } from "@/lib/api";
import { NextResponse } from "next/server";

export async function POST() {
  try {
    const data = await apiPost("/run/sync-past-grants", {});
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown" },
      { status: 500 }
    );
  }
}
