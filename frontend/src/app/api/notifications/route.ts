import { NextResponse } from "next/server";
import { getNotifications, getUnreadNotificationCount } from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const [notifications, unread] = await Promise.all([
      getNotifications(30),
      getUnreadNotificationCount(),
    ]);
    return NextResponse.json({ notifications, unread });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Failed to fetch notifications" },
      { status: 500 },
    );
  }
}
