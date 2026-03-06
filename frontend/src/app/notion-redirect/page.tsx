import { ExternalLink, Leaf, Database, BarChart3, Users, Shield } from "lucide-react";

const NOTION_WORKSPACE_URL = process.env.NOTION_WORKSPACE_URL
  || "https://notion.so/31679a8ef08b815a9575c79db12a67f9";

export default function NotionRedirectPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 px-4 text-white">
      <div className="w-full max-w-lg text-center">
        {/* Logo */}
        <div className="mb-8 flex items-center justify-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-500/20 ring-1 ring-green-500/30">
            <Leaf className="h-6 w-6 text-green-400" />
          </div>
          <div className="text-left">
            <h1 className="text-xl font-bold">AltCarbon Grants</h1>
            <p className="text-sm text-gray-400">Intelligence Platform</p>
          </div>
        </div>

        {/* Main card */}
        <div className="rounded-2xl border border-gray-700 bg-gray-800/50 p-8 shadow-2xl backdrop-blur">
          <h2 className="mb-2 text-2xl font-bold">Mission Control</h2>
          <p className="mb-6 text-gray-400">
            Your grant pipeline lives in Notion. Scout, Analyst, and Drafter
            agents sync data automatically.
          </p>

          <a
            href={NOTION_WORKSPACE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-6 py-3 font-semibold text-white shadow-lg transition-all hover:bg-blue-500 hover:shadow-xl hover:scale-[1.02] active:scale-[0.98]"
          >
            <ExternalLink className="h-5 w-5" />
            Open Notion Workspace
          </a>
        </div>

        {/* Feature badges */}
        <div className="mt-8 grid grid-cols-2 gap-3 text-left">
          {[
            { icon: Database, label: "Grant Pipeline", desc: "All scored grants with AI analysis" },
            { icon: BarChart3, label: "Agent Runs", desc: "Scout & Analyst run history" },
            { icon: Users, label: "Team Triage", desc: "Collaborative triage decisions" },
            { icon: Shield, label: "Error Logs", desc: "Agent error tracking & resolution" },
          ].map(({ icon: Icon, label, desc }) => (
            <div
              key={label}
              className="rounded-xl border border-gray-700/50 bg-gray-800/30 p-3"
            >
              <div className="mb-1 flex items-center gap-2">
                <Icon className="h-4 w-4 text-gray-400" />
                <span className="text-sm font-medium">{label}</span>
              </div>
              <p className="text-xs text-gray-500">{desc}</p>
            </div>
          ))}
        </div>

        <p className="mt-6 text-xs text-gray-600">
          Version A — Notion-Only &middot; Agents sync every 48h
        </p>
      </div>
    </div>
  );
}
