import { NextRequest, NextResponse } from "next/server";
import { markNotificationsRead, markAllNotificationsRead } from "@/lib/queries";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const ids: string[] = body.ids ?? [];

    if (body.all) {
      await markAllNotificationsRead();
      return NextResponse.json({ status: "ok", marked: "all" });
    }

    if (ids.length) {
      await markNotificationsRead(ids);
      return NextResponse.json({ status: "ok", marked: ids.length });
    }

    return NextResponse.json({ status: "ok", marked: 0 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Failed to mark read" },
      { status: 500 },
    );
  }
}
