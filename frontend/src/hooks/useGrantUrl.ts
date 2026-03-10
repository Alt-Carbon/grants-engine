"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";

/**
 * Syncs the selected grant (and optional comment) with URL search params.
 *
 *   ?grant=<id>             → opens GrantDetailSheet
 *   ?grant=<id>&comment=<id> → opens sheet + scrolls to comment
 *
 * Returns [selectedGrantId, setSelectedGrantId] — drop-in replacement for useState.
 */
export function useGrantUrl() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const grantParam = searchParams.get("grant");
  const commentParam = searchParams.get("comment");

  const [selectedGrantId, setSelectedGrantIdRaw] = useState<string | null>(
    grantParam
  );

  // Sync from URL → state (e.g. shared link opened)
  useEffect(() => {
    if (grantParam !== selectedGrantId) {
      setSelectedGrantIdRaw(grantParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grantParam]);

  // Scroll to comment when detail sheet is ready
  useEffect(() => {
    if (!commentParam || !grantParam) return;
    const timeout = setTimeout(() => {
      const el = document.getElementById(`comment-${commentParam}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-blue-400", "ring-offset-2", "rounded-lg");
        setTimeout(() => {
          el.classList.remove("ring-2", "ring-blue-400", "ring-offset-2", "rounded-lg");
        }, 3000);
      }
    }, 800);
    return () => clearTimeout(timeout);
  }, [commentParam, grantParam]);

  // State → URL sync
  const setSelectedGrantId = useCallback(
    (id: string | null) => {
      setSelectedGrantIdRaw(id);
      const params = new URLSearchParams(searchParams.toString());
      if (id) {
        params.set("grant", id);
      } else {
        params.delete("grant");
        params.delete("comment");
      }
      const qs = params.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [searchParams, router, pathname]
  );

  return [selectedGrantId, setSelectedGrantId] as const;
}
