"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentControls } from "./AgentControls";
import { NotificationBell } from "./NotificationBell";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/pipeline", label: "Pipeline", icon: Kanban },
  { href: "/triage", label: "Shortlisted", icon: ListChecks },
  { href: "/drafter", label: "Drafter", icon: FileText },
  { href: "/monitoring", label: "Mission Control", icon: Activity },
  { href: "/knowledge", label: "Knowledge", icon: Database },
];

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
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href || pathname.startsWith(href + "/");
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

      {/* Agent run controls */}
      <div className="border-t border-gray-800">
        <AgentControls />
      </div>

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
