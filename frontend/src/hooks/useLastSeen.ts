"use client";

import { useState, useEffect } from "react";

const STORAGE_KEY = "altcarbon_last_seen_at";

/**
 * Tracks when the user last visited the app.
 * Returns the *previous* visit timestamp (or null for first visit).
 * Updates the stored timestamp to "now" on mount.
 */
export function useLastSeen(): {
  lastSeenAt: string | null;
  isReturningUser: boolean;
  daysSince: number;
  markSeen: () => void;
} {
  const [lastSeenAt, setLastSeenAt] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    setLastSeenAt(stored);
    setReady(true);
    // Update to current time for next visit
    localStorage.setItem(STORAGE_KEY, new Date().toISOString());
  }, []);

  const daysSince = lastSeenAt
    ? Math.floor((Date.now() - new Date(lastSeenAt).getTime()) / 86_400_000)
    : 0;

  return {
    lastSeenAt: ready ? lastSeenAt : null,
    isReturningUser: ready && lastSeenAt !== null && daysSince >= 1,
    daysSince,
    markSeen: () => {
      localStorage.setItem(STORAGE_KEY, new Date().toISOString());
      setLastSeenAt(new Date().toISOString());
    },
  };
}

/**
 * Check if a grant was added after the user's last visit.
 */
export function isNewSince(
  grantDate: string | null | undefined,
  lastSeenAt: string | null
): boolean {
  if (!grantDate || !lastSeenAt) return false;
  return new Date(grantDate).getTime() > new Date(lastSeenAt).getTime();
}
