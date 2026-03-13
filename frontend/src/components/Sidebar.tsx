"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { useSession, signOut } from "next-auth/react";
import {
  BarChart3,
  Kanban,
  ListChecks,
  FileText,
  Database,
  Menu,
  X,
  Activity,
  LogOut,
  Wrench,
  ExternalLink,
  PlusCircle,
  Timer,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  isHybridMode,
  HYBRID_HIDDEN_ROUTES,
  NOTION_WORKSPACE_URL,
} from "@/lib/deployment";
import { AgentControls } from "./AgentControls";
import { NotificationBell } from "./NotificationBell";

function NextTriggerCountdown() {
  const [label, setLabel] = useState("");
  const [countdown, setCountdown] = useState("");
  const [targetMs, setTargetMs] = useState<number | null>(null);

  // Fetch scheduler status on mount and every 5 minutes
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/api/status/scheduler");
        if (!res.ok) return;
        const data = await res.json();
        const jobs: { id: string; name: string; next_run: string | null }[] = data.jobs ?? [];
        // Only show agent pipeline jobs, not frequent polling
        const AGENT_JOBS = new Set([
          "scout_cron",
          "knowledge_cron",
          "profile_cron",
          "weekly_monday_pipeline",
        ]);
        let soonest: { name: string; ms: number } | null = null;
        const now = Date.now();
        for (const j of jobs) {
          if (!j.next_run || !AGENT_JOBS.has(j.id)) continue;
          const ms = new Date(j.next_run).getTime();
          if (ms > now && (!soonest || ms < soonest.ms)) {
            soonest = { name: j.name, ms };
          }
        }
        if (!cancelled && soonest) {
          setLabel(soonest.name);
          setTargetMs(soonest.ms);
        }
      } catch { /* ignore */ }
    }
    load();
    const id = setInterval(load, 5 * 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Tick every second
  useEffect(() => {
    if (!targetMs) return;
    function tick() {
      const diff = Math.max(0, (targetMs as number) - Date.now());
      if (diff <= 0) { setCountdown("now"); return; }
      const d = Math.floor(diff / 86_400_000);
      const h = Math.floor((diff % 86_400_000) / 3_600_000);
      const m = Math.floor((diff % 3_600_000) / 60_000);
      const s = Math.floor((diff % 60_000) / 1_000);
      setCountdown(
        d > 0 ? `${d}d ${h}h ${m}m` : h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`
      );
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetMs]);

  if (!countdown) return null;

  return (
    <div className="border-t border-gray-800 px-4 py-2.5">
      <div className="flex items-center gap-2 text-[10px] text-gray-500">
        <Timer className="h-3 w-3 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate">{label}</p>
          <p className="font-mono text-xs text-gray-400">{countdown}</p>
        </div>
      </div>
    </div>
  );
}

interface NavItem {
  href: string;
  label: string;
  icon: React.ElementType;
  external?: boolean;
}

const ALL_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/pipeline", label: "Pipeline", icon: Kanban },
  { href: "/triage", label: "Shortlisted", icon: ListChecks },
  { href: "/drafter", label: "Drafter", icon: FileText },
  { href: "/monitoring", label: "Mission Control", icon: Activity },
  { href: "/toolkit", label: "Toolkit", icon: Wrench },
  { href: "/knowledge", label: "Knowledge", icon: Database },
];

const HYBRID_NAV: NavItem[] = [
  { href: "/monitoring", label: "Mission Control", icon: Activity },
  {
    href: NOTION_WORKSPACE_URL,
    label: "Grants Pipeline",
    icon: Kanban,
    external: true,
  },
  { href: "/add-grant", label: "Add Grant", icon: PlusCircle },
  { href: "/drafter", label: "Drafter", icon: FileText },
  { href: "/knowledge", label: "Knowledge", icon: Database },
];

const NAV = isHybridMode
  ? HYBRID_NAV
  : ALL_NAV.filter((n) => !HYBRID_HIDDEN_ROUTES.has(n.href));

export function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { data: session } = useSession();

  const navContent = (
    <>
      {/* Logo + Notifications */}
      <div className="flex h-14 items-center justify-between border-b border-gray-800 px-4">
        <div className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/AltLogoWhite-mnemonic.png" alt="Alt Carbon" className="h-5 w-5 object-contain" />
          <span className="text-sm font-semibold text-white">
            Grants Engine
          </span>
        </div>
        <div className="flex items-center gap-1">
          <NotificationBell />
          {/* Close button — mobile only */}
          <button
            onClick={() => setMobileOpen(false)}
            className="rounded p-1 text-gray-400 hover:text-white lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map(({ href, label, icon: Icon, external }) => {
          const active =
            !external && (pathname === href || pathname.startsWith(href + "/"));

          if (external) {
            return (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
                <ExternalLink className="ml-auto h-3 w-3 opacity-50" />
              </a>
            );
          }

          return (
            <Link
              key={href}
              href={href}
              onClick={() => setMobileOpen(false)}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-blue-700 text-white"
                  : "text-gray-400 hover:bg-gray-800 hover:text-white"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Agent run controls — full mode only (hybrid has them in Mission Control) */}
      {!isHybridMode && (
        <div className="border-t border-gray-800">
          <AgentControls />
        </div>
      )}

      {/* Next scheduled trigger countdown */}
      <NextTriggerCountdown />

      {/* User & Sign out */}
      <div className="border-t border-gray-800 px-4 py-3">
        {session?.user ? (
          <div className="flex items-center gap-2">
            {session.user.image ? (
              <img
                src={session.user.image}
                alt=""
                className="h-7 w-7 rounded-full ring-1 ring-gray-700"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-700 text-xs font-bold text-gray-300">
                {(session.user.name ?? session.user.email ?? "?")[0].toUpperCase()}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="truncate text-xs font-medium text-gray-300">
                {session.user.name ?? "User"}
              </p>
              <p className="truncate text-[10px] text-gray-600">
                {session.user.email}
              </p>
            </div>
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="shrink-0 rounded p-1 text-gray-600 hover:bg-gray-800 hover:text-gray-400 transition-colors"
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <p className="text-xs text-gray-600">Internal tool &middot; v0.1</p>
        )}
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger — visible below lg */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-3 top-3 z-40 rounded-lg bg-gray-900 p-2 text-white shadow-lg lg:hidden"
        aria-label="Open menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar — always visible on lg+, slide-over on mobile */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-gray-800 bg-gray-900 transition-transform duration-200 lg:static lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {navContent}
      </aside>
    </>
  );
}
