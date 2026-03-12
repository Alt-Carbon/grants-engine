"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { Bell, X, CheckCheck, Telescope, Brain, FileText, AlertTriangle, Database, Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePusherEvent } from "@/hooks/usePusher";

interface Notification {
  _id: string;
  type: string;
  title: string;
  body: string;
  action_url: string;
  priority: string;
  read: boolean;
  created_at: string;
}

const EVENT_ICONS: Record<string, React.ElementType> = {
  scout_complete: Telescope,
  analyst_complete: Brain,
  high_score_grant: Star,
  triage_needed: AlertTriangle,
  draft_section_ready: FileText,
  draft_complete: FileText,
  agent_error: AlertTriangle,
  knowledge_sync: Database,
};

const EVENT_COLORS: Record<string, string> = {
  scout_complete: "text-indigo-400",
  analyst_complete: "text-blue-400",
  high_score_grant: "text-amber-400",
  triage_needed: "text-orange-400",
  draft_section_ready: "text-cyan-400",
  draft_complete: "text-green-400",
  agent_error: "text-red-400",
  knowledge_sync: "text-gray-400",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await fetch("/api/notifications", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setNotifications(data.notifications ?? []);
        setUnread(data.unread ?? 0);
      }
    } catch {
      // ignore
    }
  }, []);

  // Initial fetch + poll every 60s
  useEffect(() => {
    fetchNotifications();
    const id = setInterval(fetchNotifications, 60_000);
    return () => clearInterval(id);
  }, [fetchNotifications]);

  // Real-time via Pusher
  usePusherEvent("notifications", "notification:new", () => {
    fetchNotifications();
  });

  // Calculate dropdown position when opening
  useEffect(() => {
    if (open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPos({
        top: rect.bottom + 6,
        left: rect.left,
      });
    }
  }, [open]);

  // Close on outside click or Escape
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  async function markAllRead() {
    try {
      await fetch("/api/notifications/read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all: true }),
      });
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnread(0);
    } catch {
      // ignore
    }
  }

  async function handleItemClick(n: Notification) {
    if (!n.read) {
      try {
        await fetch("/api/notifications/read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: [n._id] }),
        });
        setNotifications((prev) =>
          prev.map((item) => (item._id === n._id ? { ...item, read: true } : item))
        );
        setUnread((prev) => Math.max(0, prev - 1));
      } catch {
        // ignore
      }
    }
    if (n.action_url) {
      router.push(n.action_url);
    }
    setOpen(false);
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen((p) => !p)}
        className="relative rounded-lg p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
        title="Notifications"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white leading-none">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {/* Fixed-position dropdown — escapes sidebar overflow */}
      {open && (
        <div
          ref={dropdownRef}
          className="fixed z-[200] w-80 rounded-lg border border-gray-700 bg-gray-900 shadow-2xl"
          style={{ top: pos.top, left: pos.left }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-800 px-3 py-2.5">
            <span className="text-xs font-semibold text-gray-300">Notifications</span>
            <div className="flex items-center gap-1.5">
              {unread > 0 && (
                <button
                  onClick={markAllRead}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-gray-500 hover:bg-gray-800 hover:text-gray-300 transition-colors"
                >
                  <CheckCheck className="h-3 w-3" />
                  Mark all read
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="rounded p-0.5 text-gray-500 hover:text-gray-300 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Notification list */}
          <div className="max-h-[360px] overflow-y-auto overscroll-contain">
            {notifications.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-8">
                <Bell className="h-6 w-6 text-gray-700" />
                <p className="text-xs text-gray-600">No notifications yet</p>
                <p className="text-[10px] text-gray-700">
                  You&apos;ll see alerts when agents complete runs
                </p>
              </div>
            ) : (
              notifications.map((n) => {
                const Icon = EVENT_ICONS[n.type] ?? Bell;
                const iconColor = EVENT_COLORS[n.type] ?? "text-gray-400";

                return (
                  <button
                    key={n._id}
                    onClick={() => handleItemClick(n)}
                    className={cn(
                      "flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-gray-800/60 border-b border-gray-800/50 last:border-b-0",
                      !n.read && "bg-gray-800/20"
                    )}
                  >
                    <div className={cn(
                      "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                      n.priority === "high" ? "bg-gray-800" : "bg-gray-800/50"
                    )}>
                      <Icon className={cn("h-3.5 w-3.5", iconColor)} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className={cn(
                          "text-xs leading-snug",
                          n.read ? "text-gray-500" : "font-medium text-gray-200"
                        )}>
                          {!n.read && (
                            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-blue-400 align-middle" />
                          )}
                          {n.title}
                        </span>
                        <span className="shrink-0 text-[10px] text-gray-700 whitespace-nowrap">
                          {timeAgo(n.created_at)}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-gray-600 line-clamp-2 leading-relaxed">
                        {n.body}
                      </p>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </>
  );
}
