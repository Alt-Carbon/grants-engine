/**
 * POST /api/drafter/chat-stream
 *
 * SSE proxy — forwards the request to FastAPI's /drafter/chat/stream
 * and pipes the Server-Sent Events back to the browser.
 */
import { NextRequest } from "next/server";

function getUrl() {
  return (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
}
function getSecret() {
  return process.env.INTERNAL_SECRET ?? "";
}

export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${getUrl()}/drafter/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-internal-secret": getSecret(),
    },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(JSON.stringify({ error: text }), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Pipe the SSE stream straight through
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
