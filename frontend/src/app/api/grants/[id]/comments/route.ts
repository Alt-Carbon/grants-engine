import { getDb } from "@/lib/mongodb";
import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/grants/[id]/comments
 * Fetch all comments for a grant, sorted oldest-first.
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
      .sort({ created_at: 1 })
      .toArray();

    return NextResponse.json(comments);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/grants/[id]/comments
 * Add a new comment to a grant.
 * Body: { user_name: string, message: string }
 */
export async function POST(
  req: NextRequest,
  props: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await props.params;
    const { user_name, message } = await req.json();

    if (!message || typeof message !== "string" || !message.trim()) {
      return NextResponse.json(
        { error: "message is required" },
        { status: 400 }
      );
    }

    const doc = {
      grant_id: id,
      user_name: typeof user_name === "string" && user_name.trim()
        ? user_name.trim()
        : "Team Member",
      message: message.trim(),
      created_at: new Date().toISOString(),
    };

    const db = await getDb();
    const result = await db.collection("grant_comments").insertOne(doc);

    return NextResponse.json(
      { ...doc, _id: result.insertedId },
      { status: 201 }
    );
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Unknown error" },
      { status: 500 }
    );
  }
}
