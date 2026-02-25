"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Kanban,
  ListChecks,
  FileText,
  Settings,
  Database,
  Leaf,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard",  icon: BarChart3  },
  { href: "/pipeline",  label: "Pipeline",   icon: Kanban     },
  { href: "/triage",    label: "Triage",     icon: ListChecks },
  { href: "/drafter",   label: "Drafter",    icon: FileText   },
  { href: "/config",    label: "Config",     icon: Settings   },
  { href: "/knowledge", label: "Knowledge",  icon: Database   },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-gray-800 bg-gray-900">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-gray-800 px-4">
        <Leaf className="h-5 w-5 text-green-400" />
        <span className="text-sm font-semibold text-white">AltCarbon Grants</span>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
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

      {/* Footer */}
      <div className="border-t border-gray-800 px-4 py-3">
        <p className="text-xs text-gray-600">Internal tool · v0.1</p>
      </div>
    </aside>
  );
}
