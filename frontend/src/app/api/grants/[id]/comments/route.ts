import { getDb } from "@/lib/mongodb";
import { triggerEvent } from "@/lib/pusher";
import { auth } from "@/lib/auth";
import { NextRequest, NextResponse } from "next/server";

/** Strip HTML tags to prevent XSS in stored comments. */
function sanitize(input: string): string {
  return input.replace(/<[^>]*>/g, "").trim();
}

/**
 * GET /api/grants/[id]/comments
 * Fetch all comments for a grant. Pinned first, then oldest-first.
 */
export async function GET(
  _req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const db = await getDb();

    const comments = await db
      .collection("grant_comments")
      .find({ grant_id: id })
      .sort({ pinned: -1, created_at: 1 })
      .toArray();

    // Serialize _id and parent_id
    const result = comments.map((c) => ({
      ...c,
      _id: String(c._id),
      parent_id: c.parent_id ? String(c.parent_id) : null,
      pinned: c.pinned ?? false,
      reactions: c.reactions ?? {},
      edited_at: c.edited_at ?? null,
    }));

    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/grants/[id]/comments
 * Add a new comment or reply.
 * Body: { user_name, user_email?, user_image?, message, parent_id? }
 */
export async function POST(
  req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const { id } = await props.params;
    const body = await req.json();
    const { user_name, user_email, user_image, message, parent_id } = body;

    if (!message || typeof message !== "string" || !message.trim()) {
      return NextResponse.json(
        { error: "message is required" },
        { status: 400 }
      );
    }

    const cleanMessage = sanitize(message);
    if (!cleanMessage) {
      return NextResponse.json(
        { error: "message is required" },
        { status: 400 }
      );
    }

    if (cleanMessage.length > 5000) {
      return NextResponse.json(
        { error: "message too long (max 5000 characters)" },
        { status: 400 }
      );
    }

    const doc: Record<string, unknown> = {
      grant_id: id,
      user_name:
        typeof user_name === "string" && user_name.trim()
          ? sanitize(user_name)
          : session.user.name || "Team Member",
      message: cleanMessage,
      created_at: new Date().toISOString(),
      parent_id: parent_id || null,
      pinned: false,
      pinned_at: null,
      pinned_by: null,
      reactions: {},
      edited_at: null,
    };
    if (user_email) doc.user_email = user_email;
    if (user_image) doc.user_image = user_image;

    const db = await getDb();
    const result = await db.collection("grant_comments").insertOne(doc);
    const comment = { ...doc, _id: String(result.insertedId) };

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
