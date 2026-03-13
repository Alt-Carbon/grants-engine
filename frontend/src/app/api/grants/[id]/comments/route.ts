/**
 * GET  /api/grants/[id]/comments — fetch all comments for a grant
 * POST /api/grants/[id]/comments — add a new comment
 *
 * Proxies to backend v2 API (SQLite).
 */
import { apiGet, apiPost } from "@/lib/api";
import { triggerEvent } from "@/lib/pusher";
import { NextRequest, NextResponse } from "next/server";

export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const comments = await apiGet(`/api/v2/comments/${id}`);
    return NextResponse.json(comments);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

export async function POST(
  req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const body = await req.json();
    const { user_name, user_email, user_image, message, parent_id } = body;

    if (!message || typeof message !== "string" || !message.trim()) {
      return NextResponse.json(
        { error: "message is required" },
        { status: 400 }
      );
    }

    const comment = await apiPost(`/api/v2/comments/${id}`, {
      user_name:
        typeof user_name === "string" && user_name.trim()
          ? user_name.trim()
          : "Team Member",
      user_email: user_email || "",
      message: message.trim(),
      parent_id: parent_id || null,
    });

    // Real-time push
    await triggerEvent(`grant-${id}`, "comment:new", { comment });

    return NextResponse.json(comment, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
