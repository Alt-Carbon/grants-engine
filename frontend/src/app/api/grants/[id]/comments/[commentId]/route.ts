/**
 * PATCH /api/grants/[id]/comments/[commentId]
 *
 * Actions: pin, unpin, react, unreact, edit
 * Proxies to backend v2 API (SQLite).
 */
import { apiPost } from "@/lib/api";
import { triggerEvent } from "@/lib/pusher";
import { NextRequest, NextResponse } from "next/server";

export async function PATCH(
  req: NextRequest,
  props: { params: Promise<{ id: string; commentId: string }> }
) {
  try {
    const { id: grantId, commentId } = await props.params;
    const body = await req.json();

    // Forward the action to the backend
    await apiPost(`/api/v2/comments/${commentId}`, body);

    // Real-time push for relevant actions
    const { action } = body;
    if (action === "pin" || action === "unpin") {
      await triggerEvent(`grant-${grantId}`, "comment:pin", {
        commentId,
        pinned: action === "pin",
        pinned_by: body.user_email,
      });
    } else if (action === "edit") {
      await triggerEvent(`grant-${grantId}`, "comment:edit", {
        commentId,
        message: body.message?.trim(),
        edited_at: new Date().toISOString(),
      });
    }

    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
