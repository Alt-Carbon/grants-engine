import Pusher from "pusher";

let instance: Pusher | null = null;

export function getPusher(): Pusher {
  if (!instance) {
    instance = new Pusher({
      appId: process.env.PUSHER_APP_ID!,
      key: process.env.NEXT_PUBLIC_PUSHER_KEY!,
      secret: process.env.PUSHER_SECRET!,
      cluster: process.env.NEXT_PUBLIC_PUSHER_CLUSTER!,
      useTLS: true,
    });
  }
  return instance;
}

/** Fire-and-forget trigger — won't throw if Pusher isn't configured */
export async function triggerEvent(
  channel: string,
  event: string,
  data: unknown
) {
  try {
    if (
      process.env.PUSHER_APP_ID &&
      process.env.NEXT_PUBLIC_PUSHER_KEY &&
      process.env.PUSHER_SECRET
    ) {
      await getPusher().trigger(channel, event, data);
    }
  } catch {
    // Pusher is optional — don't break the request if it fails
  }
}
