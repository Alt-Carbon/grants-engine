"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import ReactMarkdown from "react-markdown";
import type { PipelineRecord, DraftSection } from "@/lib/queries";
import {
  Send,
  CheckCircle,
  FileText,
  ChevronRight,
  ChevronDown,
  Download,
  MessageSquare,
  Bot,
  User,
  AlertTriangle,
  Loader2,
  Plus,
  Pencil,
  Clock,
  PenLine,
  RotateCcw,
  Sparkles,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: "system" | "agent" | "user";
  content: string;
  timestamp: string;
  metadata?: {
    wordCount?: number;
    wordLimit?: number;
    evidenceGaps?: string[];
    status?: string;
  };
}

interface Tile {
  id: string;
  label: string;
}

interface DrafterViewProps {
  pipelines: PipelineRecord[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SECTION_ORDER = [
  "Executive Summary",
  "Problem Statement",
  "Solution Overview",
  "Impact & Theory of Change",
  "Team & Credentials",
  "Budget",
  "Conclusion",
];

const SECTION_GUIDANCE: Record<
  string,
  { wordLimit: number; criteria: string }
> = {
  "Executive Summary": {
    wordLimit: 300,
    criteria:
      "Clear overview of project, compelling value proposition, alignment with funder priorities.",
  },
  "Problem Statement": {
    wordLimit: 500,
    criteria:
      "Data-driven problem definition, evidence of need, clear scope and affected populations.",
  },
  "Solution Overview": {
    wordLimit: 600,
    criteria:
      "Concrete approach, innovation angle, feasibility evidence, and competitive advantage.",
  },
  "Impact & Theory of Change": {
    wordLimit: 500,
    criteria:
      "Measurable outcomes, logical causal chain, realistic KPIs and evaluation methodology.",
  },
  "Team & Credentials": {
    wordLimit: 400,
    criteria:
      "Relevant track record, named personnel with roles, institutional capacity evidence.",
  },
  Budget: {
    wordLimit: 400,
    criteria:
      "Itemised cost breakdown, value for money justification, co-funding or leverage.",
  },
  Conclusion: {
    wordLimit: 200,
    criteria:
      "Strong closing, call to action, reiteration of alignment with funder mission.",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function now() {
  return new Date().toISOString();
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function countWords(text: string) {
  return text
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0).length;
}

function buildKey(pipelineId: string, tileId: string) {
  return `${pipelineId}::${tileId}`;
}

/** Extract a short label from user text (first line, max 40 chars) */
function extractLabel(text: string): string {
  const first = text.split("\n")[0].trim();
  return first.length > 40 ? first.slice(0, 40) + "..." : first;
}

/** Build initial system message for a tile */
function initSystemMessage(label: string): ChatMessage {
  const guidance = SECTION_GUIDANCE[label];
  return {
    role: "system",
    content: guidance
      ? `**${label}** — Target ~${guidance.wordLimit} words.\n\nCriteria: ${guidance.criteria}`
      : `**${label}** — Paste the grant question or requirements below, and the agent will draft a response.`,
    timestamp: now(),
    metadata: { wordLimit: guidance?.wordLimit },
  };
}

/** Build initial chat history for a tile from existing draft data */
function initMessagesFromDraft(
  label: string,
  section: DraftSection
): ChatMessage[] {
  const msgs: ChatMessage[] = [initSystemMessage(label)];
  const guidance = SECTION_GUIDANCE[label];
  const wc = section.word_count ?? countWords(section.content);
  msgs.push({
    role: "agent",
    content: section.content,
    timestamp: now(),
    metadata: {
      wordCount: wc,
      wordLimit: guidance?.wordLimit,
      status: section.approved ? "Approved" : "Draft",
    },
  });
  return msgs;
}

function getTileStatus(
  key: string,
  approved: Set<string>,
  histories: Record<string, ChatMessage[]>
): "Approved" | "In Review" | "Draft" {
  if (approved.has(key)) return "Approved";
  const msgs = histories[key];
  if (msgs && msgs.some((m) => m.role === "user")) return "In Review";
  return "Draft";
}

/** Build tiles from existing draft sections, or default numbered tiles */
function buildInitialTiles(
  sections: Record<string, DraftSection>
): Tile[] {
  const sectionNames = Object.keys(sections);
  if (sectionNames.length > 0) {
    // Use sections from draft data
    const ordered = [
      ...SECTION_ORDER.filter((s) => s in sections),
      ...sectionNames.filter((s) => !SECTION_ORDER.includes(s)),
    ];
    return ordered.map((name, i) => ({ id: `tile-${i}`, label: name }));
  }
  // No draft data — create 5 empty numbered tiles
  return Array.from({ length: 5 }, (_, i) => ({
    id: `tile-${i}`,
    label: `Section ${i + 1}`,
  }));
}

// ---------------------------------------------------------------------------
// Activity timeline types
// ---------------------------------------------------------------------------

interface ActivityEvent {
  id: string;
  type: "created" | "drafted" | "revised" | "approved" | "user_message";
  section: string;
  tileId: string;
  timestamp: string;
  detail?: string;
}

/** Build a chronological activity timeline from all chat histories for a grant */
function buildTimeline(
  tiles: Tile[],
  pipelineId: string,
  histories: Record<string, ChatMessage[]>,
  approved: Set<string>
): ActivityEvent[] {
  const events: ActivityEvent[] = [];

  for (const tile of tiles) {
    const key = buildKey(pipelineId, tile.id);
    const msgs = histories[key] ?? [];
    let draftCount = 0;

    for (let i = 0; i < msgs.length; i++) {
      const msg = msgs[i];
      if (msg.role === "system" && i === 0) {
        // Section created
        events.push({
          id: `${key}-created`,
          type: "created",
          section: tile.label,
          tileId: tile.id,
          timestamp: msg.timestamp,
        });
      } else if (msg.role === "user") {
        events.push({
          id: `${key}-user-${i}`,
          type: "user_message",
          section: tile.label,
          tileId: tile.id,
          timestamp: msg.timestamp,
          detail:
            msg.content.length > 60
              ? msg.content.slice(0, 60) + "..."
              : msg.content,
        });
      } else if (msg.role === "agent") {
        draftCount++;
        events.push({
          id: `${key}-agent-${i}`,
          type: draftCount === 1 ? "drafted" : "revised",
          section: tile.label,
          tileId: tile.id,
          timestamp: msg.timestamp,
          detail: `${msg.metadata?.wordCount ?? "?"} words`,
        });
      } else if (msg.role === "system" && msg.metadata?.status === "Approved") {
        events.push({
          id: `${key}-approved-${i}`,
          type: "approved",
          section: tile.label,
          tileId: tile.id,
          timestamp: msg.timestamp,
        });
      }
    }
  }

  // Sort newest first
  events.sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
  return events;
}

let tileCounter = 100; // for generating unique IDs for new tiles

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function DrafterView({ pipelines }: DrafterViewProps) {
  const [selectedId, setSelectedId] = useState(pipelines[0]?._id ?? "");
  const [activeTileId, setActiveTileId] = useState<string | null>(null);
  const [tilesMap, setTilesMap] = useState<Record<string, Tile[]>>({});
  const [chatHistories, setChatHistories] = useState<
    Record<string, ChatMessage[]>
  >({});
  const [approvedSections, setApprovedSections] = useState<Set<string>>(
    new Set()
  );
  const [inputValue, setInputValue] = useState("");
  const [sending, setSending] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTileId, setEditingTileId] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState("");
  const [timelineOpen, setTimelineOpen] = useState(true);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // -- Derived ---------------------------------------------------------------
  const selectedPipeline = pipelines.find((p) => p._id === selectedId);
  const sections: Record<string, DraftSection> =
    selectedPipeline?.latest_draft?.sections ?? {};
  const tiles = tilesMap[selectedId] ?? [];
  const activeTile = tiles.find((t) => t.id === activeTileId) ?? null;
  const activeKey = activeTile ? buildKey(selectedId, activeTile.id) : null;
  const activeMessages = activeKey ? chatHistories[activeKey] ?? [] : [];
  const allApproved =
    tiles.length > 0 &&
    tiles.every((t) => approvedSections.has(buildKey(selectedId, t.id)));

  const timeline = buildTimeline(tiles, selectedId, chatHistories, approvedSections);

  // -- Init tiles & histories on grant change --------------------------------
  useEffect(() => {
    if (!selectedPipeline) return;

    // Build tiles if not already initialised for this grant
    if (!tilesMap[selectedId]) {
      const newTiles = buildInitialTiles(sections);
      setTilesMap((prev) => ({ ...prev, [selectedId]: newTiles }));

      // Init chat histories
      setChatHistories((prev) => {
        const next = { ...prev };
        const sectionNames = Object.keys(sections);
        for (const tile of newTiles) {
          const key = buildKey(selectedId, tile.id);
          if (!next[key]) {
            // If tile label matches a draft section, seed with draft content
            if (sectionNames.includes(tile.label) && sections[tile.label]) {
              next[key] = initMessagesFromDraft(
                tile.label,
                sections[tile.label]
              );
              if (sections[tile.label]?.approved) {
                setApprovedSections((s) => new Set(s).add(key));
              }
            } else {
              next[key] = [initSystemMessage(tile.label)];
            }
          }
        }
        return next;
      });
    }

    // Auto-select first tile
    if (!activeTileId && (tilesMap[selectedId] ?? []).length > 0) {
      setActiveTileId((tilesMap[selectedId] ?? [])[0]?.id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedPipeline]);

  // Also auto-select when tiles first appear
  useEffect(() => {
    if (!activeTileId && tiles.length > 0) {
      setActiveTileId(tiles[0].id);
    }
  }, [tiles, activeTileId]);

  // -- Auto-scroll -----------------------------------------------------------
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeMessages.length, sending]);

  // -- Add new tile ----------------------------------------------------------
  const addTile = useCallback(() => {
    const nextNum = tiles.length + 1;
    const newTile: Tile = {
      id: `tile-${++tileCounter}`,
      label: `Section ${nextNum}`,
    };
    setTilesMap((prev) => ({
      ...prev,
      [selectedId]: [...(prev[selectedId] ?? []), newTile],
    }));
    const key = buildKey(selectedId, newTile.id);
    setChatHistories((prev) => ({
      ...prev,
      [key]: [initSystemMessage(newTile.label)],
    }));
    setActiveTileId(newTile.id);
    setError(null);
  }, [tiles, selectedId]);

  // -- Rename tile -----------------------------------------------------------
  const saveTileRename = useCallback(
    (tileId: string, newLabel: string) => {
      const label = newLabel.trim() || "Untitled";
      setTilesMap((prev) => ({
        ...prev,
        [selectedId]: (prev[selectedId] ?? []).map((t) =>
          t.id === tileId ? { ...t, label } : t
        ),
      }));
      setEditingTileId(null);
    },
    [selectedId]
  );

  // -- Send message ----------------------------------------------------------
  const sendMessage = useCallback(async () => {
    if (!activeKey || !activeTile || !selectedPipeline || !inputValue.trim())
      return;

    const userMsg: ChatMessage = {
      role: "user",
      content: inputValue.trim(),
      timestamp: now(),
    };

    setChatHistories((prev) => ({
      ...prev,
      [activeKey]: [...(prev[activeKey] ?? []), userMsg],
    }));
    setInputValue("");
    setSending(true);
    setError(null);

    // Auto-rename tile if still a default "Section N" name
    if (/^Section \d+$/.test(activeTile.label)) {
      const autoLabel = extractLabel(userMsg.content);
      setTilesMap((prev) => ({
        ...prev,
        [selectedId]: (prev[selectedId] ?? []).map((t) =>
          t.id === activeTile.id ? { ...t, label: autoLabel } : t
        ),
      }));
    }

    try {
      // Build chat history for context (exclude system messages)
      const currentMsgs = chatHistories[activeKey] ?? [];
      const chatHistory = currentMsgs
        .filter((m) => m.role !== "system")
        .map((m) => ({ role: m.role === "agent" ? "assistant" : m.role, content: m.content }));

      const res = await fetch("/api/drafter/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_name: activeTile.label,
          message: userMsg.content,
          grant_id: selectedPipeline.grant_id,
          chat_history: chatHistory,
        }),
      });

      if (!res.ok)
        throw new Error((await res.text()) || `Error ${res.status}`);

      const data = await res.json();
      const revised =
        data.revised_content ?? data.content ?? data.message ?? "";
      const wc = countWords(revised);
      const guidance = SECTION_GUIDANCE[activeTile.label];

      const agentMsg: ChatMessage = {
        role: "agent",
        content: revised,
        timestamp: now(),
        metadata: {
          wordCount: wc,
          wordLimit: guidance?.wordLimit,
          evidenceGaps: data.evidence_gaps ?? [],
          status: "Draft",
        },
      };

      setChatHistories((prev) => ({
        ...prev,
        [activeKey]: [...(prev[activeKey] ?? []), agentMsg],
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to get revision");
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [activeKey, activeTile, selectedPipeline, inputValue, selectedId]);

  // -- Approve section -------------------------------------------------------
  const approveSection = useCallback(async () => {
    if (!activeKey || !activeTile || !selectedPipeline) return;
    setApproving(true);
    setError(null);

    const agentMsgs = activeMessages.filter((m) => m.role === "agent");
    const latestContent = agentMsgs.length
      ? agentMsgs[agentMsgs.length - 1].content
      : "";

    try {
      const res = await fetch("/api/drafter/section-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: selectedPipeline.thread_id,
          section_name: activeTile.label,
          action: "approve",
          edited_content: latestContent,
        }),
      });
      if (!res.ok) throw new Error(await res.text());

      setApprovedSections((prev) => new Set(prev).add(activeKey));

      setChatHistories((prev) => ({
        ...prev,
        [activeKey]: [
          ...(prev[activeKey] ?? []),
          {
            role: "system" as const,
            content: `**${activeTile.label}** has been approved.`,
            timestamp: now(),
            metadata: { status: "Approved" },
          },
        ],
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  }, [activeKey, activeTile, selectedPipeline, activeMessages]);

  // -- Export ----------------------------------------------------------------
  const exportDraft = useCallback(() => {
    if (!selectedPipeline) return;
    const lines = [
      `# ${selectedPipeline.grant_title || "Grant Draft"}`,
      "",
      `> Exported ${new Date().toLocaleDateString()}`,
      "",
    ];
    for (const tile of tiles) {
      const key = buildKey(selectedId, tile.id);
      const msgs = chatHistories[key] ?? [];
      const agentMsgs = msgs.filter((m) => m.role === "agent");
      const content = agentMsgs.length
        ? agentMsgs[agentMsgs.length - 1].content
        : "";
      if (content) lines.push(`## ${tile.label}`, "", content, "");
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(selectedPipeline.grant_title || "draft").replace(/\s+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [selectedPipeline, tiles, chatHistories, selectedId]);

  // -- Enter key handler -----------------------------------------------------
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div className="flex h-full gap-0 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      {/* ---- LEFT SIDEBAR ------------------------------------------------ */}
      <div className="flex w-72 shrink-0 flex-col border-r border-gray-200 bg-gray-50/70">
        {/* Grant selector */}
        <div className="border-b border-gray-200 p-3">
          <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            Active Grant
          </label>
          <select
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value);
              setActiveTileId(null);
            }}
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
          >
            {pipelines.map((p) => (
              <option key={p._id} value={p._id}>
                {p.grant_title || "Untitled"}{" "}
                {p.grant_funder ? `(${p.grant_funder})` : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Tile list */}
        <div className="flex-1 overflow-y-auto">
          <div className="flex items-center justify-between px-3 pb-1 pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              Sections
            </p>
            <button
              onClick={addTile}
              className="flex h-5 w-5 items-center justify-center rounded text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors"
              title="Add section"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {tiles.map((tile, idx) => {
            const key = buildKey(selectedId, tile.id);
            const status = getTileStatus(key, approvedSections, chatHistories);
            const isActive = activeTileId === tile.id;
            const isEditing = editingTileId === tile.id;

            return (
              <div
                key={tile.id}
                className={`group flex w-full items-center gap-2 px-3 py-2.5 text-left transition-all cursor-pointer ${
                  isActive
                    ? "border-r-2 border-r-blue-600 bg-white shadow-sm"
                    : "hover:bg-white/60"
                }`}
                onClick={() => {
                  if (!isEditing) {
                    setActiveTileId(tile.id);
                    setError(null);
                  }
                }}
              >
                {/* Number badge */}
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-gray-200/80 text-[11px] font-semibold text-gray-500">
                  {status === "Approved" ? (
                    <CheckCircle className="h-3.5 w-3.5 text-green-500" />
                  ) : (
                    idx + 1
                  )}
                </span>

                {/* Label — inline edit or display */}
                <div className="flex-1 min-w-0">
                  {isEditing ? (
                    <div className="flex items-center gap-1">
                      <input
                        autoFocus
                        value={editingLabel}
                        onChange={(e) => setEditingLabel(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            saveTileRename(tile.id, editingLabel);
                          } else if (e.key === "Escape") {
                            setEditingTileId(null);
                          }
                        }}
                        onBlur={() => saveTileRename(tile.id, editingLabel)}
                        className="w-full rounded border border-blue-300 bg-white px-1.5 py-0.5 text-sm text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <p
                        className={`truncate text-sm ${
                          isActive
                            ? "font-semibold text-gray-900"
                            : "font-medium text-gray-700"
                        }`}
                      >
                        {tile.label}
                      </p>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingTileId(tile.id);
                          setEditingLabel(tile.label);
                        }}
                        className="ml-auto hidden shrink-0 rounded p-0.5 text-gray-300 hover:text-gray-500 group-hover:block"
                        title="Rename"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                  <span
                    className={`mt-0.5 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      status === "Approved"
                        ? "bg-green-100 text-green-700"
                        : status === "In Review"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {status}
                  </span>
                </div>

                <ChevronRight
                  className={`h-3.5 w-3.5 shrink-0 transition-colors ${
                    isActive
                      ? "text-blue-500"
                      : "text-gray-300 group-hover:text-gray-400"
                  }`}
                />
              </div>
            );
          })}

          {/* Add section button (bottom) */}
          <button
            onClick={addTile}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-gray-400 hover:bg-white/60 hover:text-gray-600 transition-colors"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-dashed border-gray-300 text-gray-400">
              <Plus className="h-3.5 w-3.5" />
            </span>
            Add section
          </button>
        </div>

        {/* Export */}
        {allApproved && tiles.length > 0 && (
          <div className="border-t border-gray-200 p-3">
            <Button
              variant="default"
              size="sm"
              className="w-full"
              onClick={exportDraft}
            >
              <Download className="h-4 w-4" />
              Export Draft
            </Button>
          </div>
        )}
      </div>

      {/* ---- RIGHT: CHAT PANEL ------------------------------------------- */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {!activeTile ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-gray-100">
                <MessageSquare className="h-6 w-6 text-gray-400" />
              </div>
              <p className="font-medium text-gray-500">
                Select a section to begin
              </p>
              <p className="mt-1 max-w-xs text-sm text-gray-400">
                Pick a section tile on the left, then paste the grant question
                or requirements. The agent will draft a response.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-100">
                  <FileText className="h-4 w-4 text-purple-600" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">
                    {activeTile.label}
                  </h2>
                  {SECTION_GUIDANCE[activeTile.label] && (
                    <p className="text-xs text-gray-400">
                      Target: ~
                      {SECTION_GUIDANCE[activeTile.label].wordLimit} words
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {activeKey && approvedSections.has(activeKey) && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
                    <CheckCircle className="h-3.5 w-3.5" />
                    Approved
                  </span>
                )}
              </div>
            </div>

            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 bg-gray-50/40">
              {activeMessages.map((msg, i) => (
                <ChatBubble key={i} message={msg} />
              ))}

              {/* Typing indicator */}
              {sending && (
                <div className="flex gap-3">
                  <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple-500 to-purple-600 shadow-sm">
                    <Bot className="h-4 w-4 text-white" />
                  </div>
                  <div className="flex items-center gap-2 rounded-xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
                    <Loader2 className="h-4 w-4 animate-spin text-purple-500" />
                    <span className="text-sm text-gray-500">
                      Drafting response...
                    </span>
                  </div>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            {/* Error banner */}
            {error && (
              <div className="mx-5 mb-2 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            {/* Input area */}
            <div className="border-t border-gray-200 bg-white px-5 py-3">
              {activeKey && approvedSections.has(activeKey) ? (
                <p className="py-2 text-center text-sm text-gray-400">
                  This section is approved. Select another section or export the
                  draft.
                </p>
              ) : (
                <div className="flex flex-col gap-2.5">
                  <div className="flex gap-2">
                    <Textarea
                      ref={textareaRef}
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={3}
                      placeholder={
                        activeMessages.some((m) => m.role === "agent")
                          ? "Type revision instructions or follow-up..."
                          : "Paste the grant question or requirements here — the agent will draft a response..."
                      }
                      className="flex-1 resize-none text-sm min-h-[56px] bg-gray-50"
                      disabled={sending}
                    />
                    <Button
                      size="icon"
                      variant="default"
                      onClick={sendMessage}
                      disabled={!inputValue.trim() || sending}
                      className="h-[56px] w-[48px] shrink-0 self-end"
                    >
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] text-gray-400">
                      Enter to send &middot; Shift+Enter for new line
                    </p>
                    <Button
                      variant="success"
                      size="sm"
                      onClick={approveSection}
                      loading={approving}
                      disabled={
                        approving ||
                        !activeMessages.some((m) => m.role === "agent")
                      }
                    >
                      <CheckCircle className="h-3.5 w-3.5" />
                      Approve
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ---- RIGHT: ACTIVITY TIMELINE ------------------------------------ */}
      <div className="flex w-64 shrink-0 flex-col border-l border-gray-200 bg-gray-50/70 overflow-hidden">
        <button
          onClick={() => setTimelineOpen(!timelineOpen)}
          className="flex items-center justify-between border-b border-gray-200 px-3 py-2.5"
        >
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-gray-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              Activity
            </span>
          </div>
          <ChevronDown
            className={`h-3.5 w-3.5 text-gray-400 transition-transform ${
              timelineOpen ? "" : "-rotate-90"
            }`}
          />
        </button>

        {timelineOpen && (
          <div className="flex-1 overflow-y-auto">
            {timeline.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-gray-400">
                No activity yet
              </p>
            ) : (
              <div className="relative px-3 py-2">
                {/* Vertical line */}
                <div className="absolute left-[21px] top-4 bottom-4 w-px bg-gray-200" />

                {timeline.map((evt) => (
                  <button
                    key={evt.id}
                    onClick={() => {
                      setActiveTileId(evt.tileId);
                      setError(null);
                    }}
                    className="relative flex w-full gap-2.5 py-2 text-left hover:bg-white/60 rounded-md px-1 transition-colors"
                  >
                    {/* Icon dot */}
                    <span className="relative z-10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-gray-200">
                      {evt.type === "approved" && (
                        <CheckCircle className="h-3 w-3 text-green-500" />
                      )}
                      {evt.type === "drafted" && (
                        <Sparkles className="h-3 w-3 text-purple-500" />
                      )}
                      {evt.type === "revised" && (
                        <RotateCcw className="h-3 w-3 text-blue-500" />
                      )}
                      {evt.type === "user_message" && (
                        <PenLine className="h-3 w-3 text-blue-500" />
                      )}
                      {evt.type === "created" && (
                        <Plus className="h-3 w-3 text-gray-400" />
                      )}
                    </span>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-700 truncate">
                        {evt.type === "created" && "Section created"}
                        {evt.type === "drafted" && "Agent drafted"}
                        {evt.type === "revised" && "Agent revised"}
                        {evt.type === "approved" && "Section approved"}
                        {evt.type === "user_message" && "You sent"}
                      </p>
                      <p className="text-[10px] text-gray-400 truncate">
                        {evt.section}
                        {evt.detail ? ` · ${evt.detail}` : ""}
                      </p>
                      <p className="text-[10px] text-gray-300">
                        {formatTime(evt.timestamp)}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChatBubble
// ---------------------------------------------------------------------------

function ChatBubble({ message }: { message: ChatMessage }) {
  const { role, content, timestamp, metadata } = message;

  if (role === "system") {
    return (
      <div className="flex justify-center">
        <div className="max-w-lg rounded-lg border border-blue-100 bg-blue-50/60 px-4 py-3 text-center">
          <div className="prose prose-xs max-w-none text-blue-700 [&_p]:text-xs [&_p]:leading-relaxed [&_strong]:text-blue-800">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
          <p className="mt-1.5 text-[10px] text-blue-400">
            {formatTime(timestamp)}
          </p>
        </div>
      </div>
    );
  }

  if (role === "agent") {
    return (
      <div className="flex gap-3">
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple-500 to-purple-600 shadow-sm">
          <Bot className="h-4 w-4 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-purple-700">
              Drafter Agent
            </span>
            <span className="text-[10px] text-gray-400">
              {formatTime(timestamp)}
            </span>
          </div>
          <div className="rounded-xl rounded-tl-sm border border-gray-200 bg-white p-4 shadow-sm">
            <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:mt-3 prose-headings:mb-2 prose-p:my-1.5 prose-p:leading-relaxed prose-li:my-0.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-strong:text-gray-900 prose-blockquote:border-gray-300 prose-blockquote:text-gray-600 prose-h2:text-base prose-h3:text-sm first:prose-headings:mt-0">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>

            {metadata && (
              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-gray-100 pt-3">
                {metadata.wordCount != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${
                      metadata.wordLimit &&
                      metadata.wordCount > metadata.wordLimit
                        ? "bg-amber-50 text-amber-700"
                        : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {metadata.wordCount}
                    {metadata.wordLimit
                      ? ` / ${metadata.wordLimit} words`
                      : " words"}
                  </span>
                )}
                {metadata.status && (
                  <span
                    className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                      metadata.status === "Approved"
                        ? "bg-green-100 text-green-700"
                        : metadata.status === "In Review"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {metadata.status}
                  </span>
                )}
              </div>
            )}

            {metadata?.evidenceGaps && metadata.evidenceGaps.length > 0 && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <div className="mb-1.5 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                  <span className="text-xs font-semibold text-amber-700">
                    Evidence Gaps
                  </span>
                </div>
                <ul className="space-y-1">
                  {metadata.evidenceGaps.map((gap, j) => (
                    <li
                      key={j}
                      className="text-xs leading-snug text-amber-700 pl-2 border-l-2 border-amber-300"
                    >
                      {gap}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 justify-end">
      <div className="flex-1 min-w-0 max-w-[75%] ml-auto">
        <div className="flex items-center gap-2 mb-1 justify-end">
          <span className="text-[10px] text-gray-400">
            {formatTime(timestamp)}
          </span>
          <span className="text-xs font-semibold text-gray-600">You</span>
        </div>
        <div className="rounded-xl rounded-tr-sm bg-blue-600 px-4 py-3 text-sm leading-relaxed text-white shadow-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-600 shadow-sm">
        <User className="h-4 w-4 text-white" />
      </div>
    </div>
  );
}

