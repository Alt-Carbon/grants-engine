"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Search,
  BarChart3,
  ArrowRight,
  AlertTriangle,
  MessageSquare,
  CheckCircle,
  Loader2,
  Clock,
  Shield,
} from "lucide-react";

interface ActivityItem {
  id: string;
  type: "scored" | "status_change" | "override" | "comment" | "discovered";
  title: string;
  detail?: string;
  user?: string;
  timestamp: string;
}

interface GrantActivityProps {
  grantId: string;
  grant: {
    scored_at?: string;
    scraped_at?: string;
    status?: string;
    human_override?: boolean;
    override_reason?: string;
    override_at?: string;
    weighted_total?: number;
  } | null;
}

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

const ICON_MAP = {
  discovered: { icon: Search, color: "text-blue-500", bg: "bg-blue-50" },
  scored: { icon: BarChart3, color: "text-violet-500", bg: "bg-violet-50" },
  status_change: { icon: ArrowRight, color: "text-green-500", bg: "bg-green-50" },
  override: { icon: Shield, color: "text-amber-500", bg: "bg-amber-50" },
  comment: { icon: MessageSquare, color: "text-blue-500", bg: "bg-blue-50" },
};

export function GrantActivity({ grantId, grant }: GrantActivityProps) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  const buildTimeline = useCallback(async () => {
    const timeline: ActivityItem[] = [];

    // Discovered
    if (grant?.scraped_at) {
      timeline.push({
        id: "discovered",
        type: "discovered",
        title: "Grant discovered by Scout",
        timestamp: grant.scraped_at,
      });
    }

    // Scored
    if (grant?.scored_at) {
      timeline.push({
        id: "scored",
        type: "scored",
        title: "Scored by Analyst",
        detail: grant.weighted_total
          ? `Score: ${grant.weighted_total.toFixed(1)}/10`
          : undefined,
        timestamp: grant.scored_at,
      });
    }

    // Override
    if (grant?.human_override && grant.override_at) {
      timeline.push({
        id: "override",
        type: "override",
        title: "Status overridden by team",
        detail: grant.override_reason || undefined,
        timestamp: grant.override_at,
      });
    }

    // Fetch comments to include in timeline
    try {
      const res = await fetch(`/api/grants/${grantId}/comments`);
      if (res.ok) {
        const comments = await res.json();
        for (const c of comments) {
          timeline.push({
            id: `comment-${c._id}`,
            type: "comment",
            title: `${c.user_name} commented`,
            detail:
              c.message.length > 80
                ? c.message.slice(0, 80) + "..."
                : c.message,
            user: c.user_name,
            timestamp: c.created_at,
          });
        }
      }
    } catch {
      // skip comments in timeline if fetch fails
    }

    // Sort newest first
    timeline.sort(
      (a, b) =>
        new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );

    setItems(timeline);
    setLoading(false);
  }, [grantId, grant]);

  useEffect(() => {
    setLoading(true);
    buildTimeline();
  }, [buildTimeline]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading activity...
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1.5 py-8 text-center">
        <Clock className="h-8 w-8 text-gray-200" />
        <p className="text-sm font-medium text-gray-400">No activity yet</p>
      </div>
    );
  }

  return (
    <div className="max-h-80 overflow-y-auto px-5 py-3">
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-[11px] top-3 bottom-3 w-px bg-gray-100" />

        <div className="space-y-4">
          {items.map((item) => {
            const config = ICON_MAP[item.type];
            const Icon = config.icon;
            return (
              <div key={item.id} className="relative flex gap-3">
                <div
                  className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${config.bg}`}
                >
                  <Icon className={`h-3 w-3 ${config.color}`} />
                </div>
                <div className="flex-1 min-w-0 pt-0.5">
                  <p className="text-sm font-medium text-gray-800">
                    {item.title}
                  </p>
                  {item.detail && (
                    <p className="mt-0.5 text-xs text-gray-500 line-clamp-2">
                      {item.detail}
                    </p>
                  )}
                  <p className="mt-0.5 text-[10px] text-gray-400">
                    {timeAgo(item.timestamp)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
