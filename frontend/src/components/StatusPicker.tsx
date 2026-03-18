"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  triage:         "bg-amber-100 text-amber-800 hover:ring-2 hover:ring-amber-300",
  pursue:         "bg-green-100 text-green-800 hover:ring-2 hover:ring-green-300",
  pursuing:       "bg-green-100 text-green-800 hover:ring-2 hover:ring-green-300",
  drafting:       "bg-purple-100 text-purple-800 hover:ring-2 hover:ring-purple-300",
  draft_complete: "bg-indigo-100 text-indigo-800 hover:ring-2 hover:ring-indigo-300",
  submitted:      "bg-cyan-100 text-cyan-800 hover:ring-2 hover:ring-cyan-300",
  won:            "bg-emerald-100 text-emerald-800 hover:ring-2 hover:ring-emerald-300",
  passed:         "bg-gray-100 text-gray-500 hover:ring-2 hover:ring-gray-300",
  auto_pass:      "bg-gray-100 text-gray-500 hover:ring-2 hover:ring-gray-300",
  human_passed:   "bg-gray-200 text-gray-600 hover:ring-2 hover:ring-gray-400",
  hold:           "bg-orange-100 text-orange-800 hover:ring-2 hover:ring-orange-300",
  reported:       "bg-red-100 text-red-600 hover:ring-2 hover:ring-red-300",
};

const STATUS_LABELS: Record<string, string> = {
  triage:         "Shortlisted",
  pursue:         "Pursue",
  pursuing:       "Pursuing",
  drafting:       "Drafting",
  draft_complete: "Draft Complete",
  submitted:      "Submitted",
  won:            "Won",
  passed:         "Rejected",
  auto_pass:      "Auto Rejected",
  human_passed:   "Rejected",
  hold:           "Hold",
  reported:       "Reported",
};

const MOVE_OPTIONS = [
  { value: "triage",       label: "Shortlisted", dot: "bg-amber-400" },
  { value: "pursue",       label: "Pursue",      dot: "bg-green-400" },
  { value: "hold",         label: "Hold",         dot: "bg-orange-400" },
  { value: "drafting",     label: "Drafting",     dot: "bg-purple-400" },
  { value: "submitted",    label: "Submitted",    dot: "bg-cyan-400" },
  { value: "human_passed", label: "Rejected",      dot: "bg-red-400" },
];

interface StatusPickerProps {
  status: string;
  grantId: string;
  onStatusChange: (grantId: string, newStatus: string) => void;
  size?: "sm" | "md";
}

export function StatusPicker({
  status,
  grantId,
  onStatusChange,
  size = "sm",
}: StatusPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600 hover:ring-2 hover:ring-gray-300";
  const label = STATUS_LABELS[status] ?? status.replace(/_/g, " ");

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onMouseDown={(e) => e.stopPropagation()}
        className={cn(
          "cursor-pointer rounded-full font-medium capitalize transition-all",
          size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-0.5 text-xs",
          style
        )}
      >
        {label}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-40 rounded-lg border border-gray-200 bg-white py-1 shadow-xl">
          {MOVE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={(e) => {
                e.stopPropagation();
                onStatusChange(grantId, opt.value);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors",
                opt.value === status
                  ? "bg-gray-50 font-medium text-gray-900"
                  : "text-gray-600 hover:bg-indigo-50 hover:text-indigo-700"
              )}
            >
              <span className={cn("h-2 w-2 rounded-full", opt.dot)} />
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
