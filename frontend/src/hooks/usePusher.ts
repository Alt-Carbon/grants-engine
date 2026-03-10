"use client";

import { useEffect, useRef } from "react";
import PusherClient from "pusher-js";
import type { Channel } from "pusher-js";

let pusherClient: PusherClient | null = null;

function getClient(): PusherClient | null {
  if (typeof window === "undefined") return null;
  const key = process.env.NEXT_PUBLIC_PUSHER_KEY;
  const cluster = process.env.NEXT_PUBLIC_PUSHER_CLUSTER;
  if (!key || !cluster) return null;

  if (!pusherClient) {
    pusherClient = new PusherClient(key, { cluster });
  }
  return pusherClient;
}

/**
 * Subscribe to a Pusher channel and bind an event handler.
 * Cleans up on unmount. No-ops gracefully if Pusher isn't configured.
 */
export function usePusherEvent(
  channelName: string | null,
  eventName: string,
  handler: (data: unknown) => void
) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (!channelName) return;
    const client = getClient();
    if (!client) return;

    const channel: Channel = client.subscribe(channelName);
    const boundHandler = (data: unknown) => handlerRef.current(data);
    channel.bind(eventName, boundHandler);

    return () => {
      channel.unbind(eventName, boundHandler);
      client.unsubscribe(channelName);
    };
  }, [channelName, eventName]);
}
