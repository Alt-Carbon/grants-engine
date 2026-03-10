import { getDb } from "@/lib/mongodb";
import { triggerEvent } from "@/lib/pusher";
import { ObjectId } from "mongodb";
import { NextRequest, NextResponse } from "next/server";

/**
 * PATCH /api/grants/[id]/comments/[commentId]
 *
 * Actions:
 *   { action: "pin" }
 *   { action: "unpin" }
 *   { action: "react", emoji: string, user_email: string }
 *   { action: "unreact", emoji: string, user_email: string }
 *   { action: "edit", message: string, user_email: string }
 */
export async function PATCH(
  req: NextRequest,
  props: { params: Promise<{ id: string; commentId: string }> }
) {
  try {
    const { id: grantId, commentId } = await props.params;
    const body = await req.json();
    const { action } = body;

    const db = await getDb();
    const col = db.collection("grant_comments");
    const filter = { _id: new ObjectId(commentId) };

    switch (action) {
      case "pin": {
        await col.updateOne(filter, {
          $set: {
            pinned: true,
            pinned_at: new Date().toISOString(),
            pinned_by: body.user_email || null,
          },
        });
        await triggerEvent(`grant-${grantId}`, "comment:pin", {
          commentId,
          pinned: true,
          pinned_by: body.user_email,
        });
        break;
      }

      case "unpin": {
        await col.updateOne(filter, {
          $set: { pinned: false, pinned_at: null, pinned_by: null },
        });
        await triggerEvent(`grant-${grantId}`, "comment:pin", {
          commentId,
          pinned: false,
        });
        break;
      }

      case "react": {
        const { emoji, user_email } = body;
        if (!emoji || !user_email) {
          return NextResponse.json(
            { error: "emoji and user_email required" },
            { status: 400 }
          );
        }
        await col.updateOne(filter, {
          $addToSet: { [`reactions.${emoji}`]: user_email },
        });
        // Fetch updated reactions
        const doc = await col.findOne(filter, {
          projection: { reactions: 1 },
        });
        await triggerEvent(`grant-${grantId}`, "comment:react", {
          commentId,
          reactions: doc?.reactions ?? {},
        });
        break;
      }

      case "unreact": {
        const { emoji: unreactEmoji, user_email: unreactUser } = body;
        if (!unreactEmoji || !unreactUser) {
          return NextResponse.json(
            { error: "emoji and user_email required" },
            { status: 400 }
          );
        }
        await col.updateOne(filter, {
          $pull: { [`reactions.${unreactEmoji}`]: unreactUser },
        });
        const doc2 = await col.findOne(filter, {
          projection: { reactions: 1 },
        });
        await triggerEvent(`grant-${grantId}`, "comment:react", {
          commentId,
          reactions: doc2?.reactions ?? {},
        });
        break;
      }

      case "edit": {
        const { message, user_email: editUser } = body;
        if (!message?.trim()) {
          return NextResponse.json(
            { error: "message required" },
            { status: 400 }
          );
        }
        // Only allow editing own comments
        const existing = await col.findOne(filter);
        if (existing?.user_email && existing.user_email !== editUser) {
          return NextResponse.json(
            { error: "Can only edit your own comments" },
            { status: 403 }
          );
        }
        await col.updateOne(filter, {
          $set: {
            message: message.trim(),
            edited_at: new Date().toISOString(),
          },
        });
        await triggerEvent(`grant-${grantId}`, "comment:edit", {
          commentId,
          message: message.trim(),
          edited_at: new Date().toISOString(),
        });
        break;
      }

      default:
        return NextResponse.json(
          { error: `Unknown action: ${action}` },
          { status: 400 }
        );
    }

    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
