/**
 * POST /api/drafter/chat
 *
 * Chat endpoint for the Drafter UI.
 * Calls the FastAPI /drafter/chat endpoint which directly invokes the LLM
 * with grant context and returns the response synchronously.
 *
 * Request body:
 *   { grant_id: string, section_name: string, message: string, chat_history?: {role,content}[] }
 */
import { apiPost } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

interface ChatRequestBody {
  thread_id?: string;
  section_name: string;
  message: string;
  grant_id: string;
  chat_history?: { role: string; content: string }[];
}

export async function POST(req: NextRequest) {
  try {
    const body: ChatRequestBody = await req.json();

    if (!body.grant_id || !body.section_name || !body.message) {
      return NextResponse.json(
        {
          error:
            "Missing required fields: grant_id, section_name, and message are required.",
        },
        { status: 400 }
      );
    }

    const payload = {
      grant_id: body.grant_id,
      section_name: body.section_name,
      message: body.message,
      chat_history: body.chat_history ?? [],
    };

    const data = await apiPost("/drafter/chat", payload);

    return NextResponse.json(data, { status: 200 });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error("[/api/drafter/chat] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
