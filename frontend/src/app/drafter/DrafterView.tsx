"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
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
  History,
  Settings,
  X,
  Trash2,
  Cloud,
  CloudOff,
} from "lucide-react";
import { DrafterSettings } from "@/components/DrafterSettings";

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
    agentName?: string;
    agentTheme?: string;
    sourcesUsed?: string[];
    agentTemperature?: number;
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

const THEME_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; gradient: string; desc: string }
> = {
  climatetech: {
    label: "ClimaTech",
    color: "text-emerald-700",
    bg: "bg-emerald-100",
    gradient: "from-emerald-500 to-teal-600",
    desc: "carbon removal, MRV, and net-zero technology",
  },
  agritech: {
    label: "AgriTech",
    color: "text-lime-700",
    bg: "bg-lime-100",
    gradient: "from-lime-500 to-green-600",
    desc: "soil carbon, regenerative agriculture, and precision farming",
  },
  ai_for_sciences: {
    label: "AI for Sciences",
    color: "text-blue-700",
    bg: "bg-blue-100",
    gradient: "from-blue-500 to-indigo-600",
    desc: "ML/AI applied to environmental and scientific problems",
  },
  applied_earth_sciences: {
    label: "Earth Sciences",
    color: "text-amber-700",
    bg: "bg-amber-100",
    gradient: "from-amber-500 to-orange-600",
    desc: "remote sensing, geospatial analysis, and earth observation",
  },
  social_impact: {
    label: "Social Impact",
    color: "text-pink-700",
    bg: "bg-pink-100",
    gradient: "from-pink-500 to-rose-600",
    desc: "inclusive climate solutions, community development, and equity",
  },
  deeptech: {
    label: "Deep Tech",
    color: "text-violet-700",
    bg: "bg-violet-100",
    gradient: "from-violet-500 to-purple-600",
    desc: "advanced materials, frontier science, and breakthrough engineering",
  },
};

function getThemeForPipeline(pipeline?: { grant_themes?: string[] }): string {
  return pipeline?.grant_themes?.[0] || "climatetech";
}

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
function initSystemMessage(label: string, theme?: string): ChatMessage {
  const guidance = SECTION_GUIDANCE[label];
  const tc = theme ? THEME_CONFIG[theme] : null;
  const agentLine = tc
    ? `**${tc.label} Drafter** activated — specialized in ${tc.desc}.`
    : "";
  const sectionLine = guidance
    ? `**${label}** — Target ~${guidance.wordLimit} words.\n\nCriteria: ${guidance.criteria}`
    : `**${label}** — Paste the grant question or requirements below, and the agent will draft a response.`;
  return {
    role: "system",
    content: agentLine ? `${agentLine}\n\n${sectionLine}` : sectionLine,
    timestamp: now(),
    metadata: { wordLimit: guidance?.wordLimit, agentTheme: theme },
  };
}

/** Build initial chat history for a tile from existing draft data */
function initMessagesFromDraft(
  label: string,
  section: DraftSection,
  theme?: string
): ChatMessage[] {
  const msgs: ChatMessage[] = [initSystemMessage(label, theme)];
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
    const ordered = [
      ...SECTION_ORDER.filter((s) => s in sections),
      ...sectionNames.filter((s) => !SECTION_ORDER.includes(s)),
    ];
    return ordered.map((name, i) => ({ id: `tile-${i}`, label: name }));
  }
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

  events.sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
  return events;
}

let tileCounter = 100;

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

/** Convert in-memory chatHistories (keyed by pipelineId::tileId) to section-name-keyed format for DB */
function serializeHistories(
  tiles: Tile[],
  pipelineId: string,
  chatHistories: Record<string, ChatMessage[]>
): Record<string, ChatMessage[]> {
  const out: Record<string, ChatMessage[]> = {};
  for (const tile of tiles) {
    const key = buildKey(pipelineId, tile.id);
    const msgs = chatHistories[key];
    if (msgs && msgs.length > 0) {
      out[tile.label] = msgs;
    }
  }
  return out;
}

/** Save chat histories to backend */
async function saveChatHistories(
  pipelineId: string,
  grantId: string,
  tiles: Tile[],
  chatHistories: Record<string, ChatMessage[]>
): Promise<boolean> {
  try {
    const sections = serializeHistories(tiles, pipelineId, chatHistories);
    await fetch("/api/drafter/chat-history", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pipeline_id: pipelineId,
        grant_id: grantId,
        sections,
      }),
    });
    return true;
  } catch {
    return false;
  }
}

/** Load chat histories from backend */
async function loadChatHistories(
  pipelineId: string
): Promise<Record<string, ChatMessage[]> | null> {
  try {
    const res = await fetch(
      `/api/drafter/chat-history?pipeline_id=${encodeURIComponent(pipelineId)}`
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data.sections ?? null;
  } catch {
    return null;
  }
}

/** Clear a single section's chat history */
async function clearSectionHistory(
  pipelineId: string,
  sectionName: string
): Promise<boolean> {
  try {
    const res = await fetch(
      `/api/drafter/chat-history?pipeline_id=${encodeURIComponent(pipelineId)}&section_name=${encodeURIComponent(sectionName)}`,
      { method: "DELETE" }
    );
    return res.ok;
  } catch {
    return false;
  }
}

/** Format date for date separators */
function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

/** Check if two timestamps are on different calendar days */
function isDifferentDay(a: string, b: string): boolean {
  try {
    return new Date(a).toDateString() !== new Date(b).toDateString();
  } catch {
    return false;
  }
}

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
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [agentInfo, setAgentInfo] = useState<
    Record<string, { name: string; theme: string }>
  >({});
  const [historyLoaded, setHistoryLoaded] = useState<Set<string>>(new Set());
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [clearingSection, setClearingSection] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatHistoriesRef = useRef(chatHistories);
  chatHistoriesRef.current = chatHistories;
  const tilesRef = useRef<Tile[]>([]);

  // -- Derived ---------------------------------------------------------------
  const selectedPipeline = pipelines.find((p) => p._id === selectedId);
  const sections: Record<string, DraftSection> =
    selectedPipeline?.latest_draft?.sections ?? {};
  const tiles = tilesMap[selectedId] ?? [];
  tilesRef.current = tiles;
  const activeTile = tiles.find((t) => t.id === activeTileId) ?? null;
  const activeKey = activeTile ? buildKey(selectedId, activeTile.id) : null;
  const activeMessages = activeKey ? chatHistories[activeKey] ?? [] : [];
  const allApproved =
    tiles.length > 0 &&
    tiles.every((t) => approvedSections.has(buildKey(selectedId, t.id)));

  // Theme-specific sub-agent for the selected pipeline
  const activeTheme = getThemeForPipeline(selectedPipeline as { grant_themes?: string[] } | undefined);
  const themeConfig = THEME_CONFIG[activeTheme] || THEME_CONFIG.climatetech;
  const currentAgent = agentInfo[selectedId] || {
    name: `${themeConfig.label} Drafter`,
    theme: activeTheme,
  };

  const timeline = buildTimeline(
    tiles,
    selectedId,
    chatHistories,
    approvedSections
  );

  const approvedCount = tiles.filter((t) =>
    approvedSections.has(buildKey(selectedId, t.id))
  ).length;

  // -- Init tiles & histories on grant change --------------------------------
  useEffect(() => {
    if (!selectedPipeline) return;

    const pipelineTheme = getThemeForPipeline(selectedPipeline as { grant_themes?: string[] });

    if (!tilesMap[selectedId]) {
      const newTiles = buildInitialTiles(sections);
      setTilesMap((prev) => ({ ...prev, [selectedId]: newTiles }));

      setChatHistories((prev) => {
        const next = { ...prev };
        const sectionNames = Object.keys(sections);
        for (const tile of newTiles) {
          const key = buildKey(selectedId, tile.id);
          if (!next[key]) {
            if (sectionNames.includes(tile.label) && sections[tile.label]) {
              next[key] = initMessagesFromDraft(
                tile.label,
                sections[tile.label],
                pipelineTheme
              );
              if (sections[tile.label]?.approved) {
                setApprovedSections((s) => new Set(s).add(key));
              }
            } else {
              next[key] = [initSystemMessage(tile.label, pipelineTheme)];
            }
          }
        }
        return next;
      });
    }

    if (!activeTileId && (tilesMap[selectedId] ?? []).length > 0) {
      setActiveTileId((tilesMap[selectedId] ?? [])[0]?.id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedPipeline]);

  useEffect(() => {
    if (!activeTileId && tiles.length > 0) {
      setActiveTileId(tiles[0].id);
    }
  }, [tiles, activeTileId]);

  // -- Load persisted chat history from DB -----------------------------------
  useEffect(() => {
    if (!selectedId || !selectedPipeline || historyLoaded.has(selectedId)) return;
    if (tiles.length === 0) return; // wait for tiles to be initialized

    let cancelled = false;
    (async () => {
      const savedSections = await loadChatHistories(selectedId);
      if (cancelled || !savedSections) {
        setHistoryLoaded((prev) => new Set(prev).add(selectedId));
        return;
      }

      setChatHistories((prev) => {
        const next = { ...prev };
        for (const tile of tiles) {
          const key = buildKey(selectedId, tile.id);
          const savedMsgs = savedSections[tile.label];
          if (savedMsgs && savedMsgs.length > 0) {
            // Persisted history takes priority over init-from-draft
            next[key] = savedMsgs;
            // Restore approved state
            if (savedMsgs.some((m) => m.role === "system" && m.metadata?.status === "Approved")) {
              setApprovedSections((s) => new Set(s).add(key));
            }
          }
        }
        return next;
      });

      setHistoryLoaded((prev) => new Set(prev).add(selectedId));
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tiles.length]);

  // -- Debounced auto-save (uses refs for latest state) ----------------------
  const triggerSave = useCallback(() => {
    if (!selectedPipeline) return;
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);

    setSaveStatus("saving");
    saveTimeoutRef.current = setTimeout(async () => {
      const ok = await saveChatHistories(
        selectedId,
        selectedPipeline.grant_id,
        tilesRef.current,
        chatHistoriesRef.current
      );
      setSaveStatus(ok ? "saved" : "error");
      setTimeout(() => setSaveStatus("idle"), 2000);
    }, 800);
  }, [selectedId, selectedPipeline]);

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
      [key]: [initSystemMessage(newTile.label, activeTheme)],
    }));
    setActiveTileId(newTile.id);
    setError(null);
  }, [tiles, selectedId, activeTheme]);

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
      const currentMsgs = chatHistories[activeKey] ?? [];
      const chatHistory = currentMsgs
        .filter((m) => m.role !== "system")
        .map((m) => ({
          role: m.role === "agent" ? "assistant" : m.role,
          content: m.content,
        }));

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

      // Store agent info from backend response
      if (data.agent_name && data.agent_theme) {
        setAgentInfo((prev) => ({
          ...prev,
          [selectedId]: { name: data.agent_name, theme: data.agent_theme },
        }));
      }

      const agentMsg: ChatMessage = {
        role: "agent",
        content: revised,
        timestamp: now(),
        metadata: {
          wordCount: wc,
          wordLimit: guidance?.wordLimit,
          evidenceGaps: data.evidence_gaps ?? [],
          status: "Draft",
          agentName: data.agent_name,
          agentTheme: data.agent_theme,
          sourcesUsed: data.sources_used ?? [],
          agentTemperature: data.agent_temperature,
        },
      };

      setChatHistories((prev) => ({
        ...prev,
        [activeKey]: [...(prev[activeKey] ?? []), agentMsg],
      }));
      // Auto-save after agent response (next tick so state is updated)
      setTimeout(() => triggerSave(), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to get revision");
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [activeKey, activeTile, selectedPipeline, inputValue, selectedId, chatHistories, triggerSave]);

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
      setTimeout(() => triggerSave(), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  }, [activeKey, activeTile, selectedPipeline, activeMessages, triggerSave]);

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

  // -- Clear section chat ----------------------------------------------------
  const clearChat = useCallback(async () => {
    if (!activeKey || !activeTile || !selectedPipeline) return;
    setClearingSection(true);
    try {
      await clearSectionHistory(selectedId, activeTile.label);
      const pipelineTheme = getThemeForPipeline(selectedPipeline as { grant_themes?: string[] });
      setChatHistories((prev) => ({
        ...prev,
        [activeKey]: [initSystemMessage(activeTile.label, pipelineTheme)],
      }));
      setApprovedSections((prev) => {
        const next = new Set(prev);
        next.delete(activeKey);
        return next;
      });
      triggerSave();
    } finally {
      setClearingSection(false);
    }
  }, [activeKey, activeTile, selectedPipeline, selectedId, triggerSave]);

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
    <div className="relative flex h-full overflow-hidden">
      {/* ---- LEFT SIDEBAR ------------------------------------------------ */}
      <div className="flex w-[280px] shrink-0 flex-col border-r border-gray-200 bg-white">
        {/* Header */}
        <div className="border-b border-gray-100 px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-600">
                <FileText className="h-3.5 w-3.5 text-white" />
              </div>
              <h1 className="text-sm font-bold text-gray-900">Drafter</h1>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setSettingsOpen(true)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                title="Drafter settings"
              >
                <Settings className="h-4 w-4" />
              </button>
              <button
                onClick={() => setTimelineOpen(true)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                title="Activity timeline"
              >
                <History className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Grant selector */}
        <div className="border-b border-gray-100 px-4 py-3">
          <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            Grant
          </label>
          <select
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value);
              setActiveTileId(null);
            }}
            className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm font-medium text-gray-800 transition-colors focus:border-violet-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-violet-100"
          >
            {pipelines.map((p) => (
              <option key={p._id} value={p._id}>
                {p.grant_title || "Untitled"}
              </option>
            ))}
          </select>
          {selectedPipeline?.grant_funder && (
            <p className="mt-1 text-[11px] text-gray-400 truncate">
              {selectedPipeline.grant_funder}
            </p>
          )}
          <span
            className={`mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${themeConfig.bg} ${themeConfig.color}`}
          >
            {currentAgent.name}
          </span>
        </div>

        {/* Progress bar */}
        <div className="border-b border-gray-100 px-4 py-2.5">
          <div className="flex items-center justify-between text-[11px]">
            <span className="font-medium text-gray-500">Progress</span>
            <span className="font-semibold text-gray-700">
              {approvedCount}/{tiles.length}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 to-purple-500 transition-all duration-500"
              style={{
                width: tiles.length
                  ? `${(approvedCount / tiles.length) * 100}%`
                  : "0%",
              }}
            />
          </div>
        </div>

        {/* Tile list */}
        <div className="flex-1 overflow-y-auto">
          <div className="flex items-center justify-between px-4 pb-1 pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              Sections
            </p>
            <button
              onClick={addTile}
              className="flex h-5 w-5 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
              title="Add section"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="px-2 pb-2">
            {tiles.map((tile, idx) => {
              const key = buildKey(selectedId, tile.id);
              const status = getTileStatus(
                key,
                approvedSections,
                chatHistories
              );
              const isActive = activeTileId === tile.id;
              const isEditing = editingTileId === tile.id;
              const msgCount = (chatHistories[key] ?? []).filter(
                (m) => m.role !== "system"
              ).length;

              return (
                <div
                  key={tile.id}
                  className={`group relative flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-all cursor-pointer mb-0.5 ${
                    isActive
                      ? "bg-violet-50 ring-1 ring-violet-200"
                      : "hover:bg-gray-50"
                  }`}
                  onClick={() => {
                    if (!isEditing) {
                      setActiveTileId(tile.id);
                      setError(null);
                    }
                  }}
                >
                  {/* Number badge */}
                  <span
                    className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold ${
                      status === "Approved"
                        ? "bg-green-100 text-green-600"
                        : isActive
                          ? "bg-violet-100 text-violet-600"
                          : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {status === "Approved" ? (
                      <CheckCircle className="h-3.5 w-3.5" />
                    ) : (
                      idx + 1
                    )}
                  </span>

                  {/* Label */}
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editingLabel}
                        onChange={(e) => setEditingLabel(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            saveTileRename(tile.id, editingLabel);
                          else if (e.key === "Escape") setEditingTileId(null);
                        }}
                        onBlur={() => saveTileRename(tile.id, editingLabel)}
                        className="w-full rounded border border-violet-300 bg-white px-1.5 py-0.5 text-sm text-gray-900 focus:outline-none focus:ring-1 focus:ring-violet-400"
                      />
                    ) : (
                      <>
                        <div className="flex items-center gap-1">
                          <p
                            className={`truncate text-[13px] leading-tight ${
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
                        <div className="mt-1 flex items-center gap-1.5">
                          <span
                            className={`inline-block rounded px-1.5 py-px text-[10px] font-medium ${
                              status === "Approved"
                                ? "bg-green-100 text-green-700"
                                : status === "In Review"
                                  ? "bg-amber-100 text-amber-700"
                                  : "bg-gray-100 text-gray-500"
                            }`}
                          >
                            {status}
                          </span>
                          {msgCount > 0 && (
                            <span className="text-[10px] text-gray-400">
                              {msgCount} msg{msgCount !== 1 ? "s" : ""}
                            </span>
                          )}
                          {(() => {
                            const msgs = chatHistories[key] ?? [];
                            const lastMsg = msgs.filter((m) => m.role !== "system").pop();
                            if (!lastMsg) return null;
                            return (
                              <span className="text-[10px] text-gray-300" title={lastMsg.timestamp}>
                                {formatDate(lastMsg.timestamp)}
                              </span>
                            );
                          })()}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Add section button */}
            <button
              onClick={addTile}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-dashed border-gray-300 text-gray-400">
                <Plus className="h-3.5 w-3.5" />
              </span>
              Add section
            </button>
          </div>
        </div>

        {/* Export */}
        {allApproved && tiles.length > 0 && (
          <div className="border-t border-gray-100 p-3">
            <Button
              variant="default"
              size="sm"
              className="w-full bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700"
              onClick={exportDraft}
            >
              <Download className="h-4 w-4" />
              Export Draft
            </Button>
          </div>
        )}
      </div>

      {/* ---- CENTER: CHAT PANEL ------------------------------------------ */}
      <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
        {!activeTile ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-white shadow-sm ring-1 ring-gray-100">
                <MessageSquare className="h-7 w-7 text-violet-400" />
              </div>
              <p className="text-base font-semibold text-gray-700">
                Select a section to begin
              </p>
              <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-gray-400">
                Pick a section tile on the left, then paste the grant question or
                requirements. The agent will draft a response.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-2.5 shadow-sm">
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${themeConfig.gradient}`}
                >
                  <Bot className="h-4 w-4 text-white" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-sm font-semibold text-gray-900">
                      {currentAgent.name}
                    </h2>
                    <span className="text-gray-300">·</span>
                    <span className="text-sm text-gray-500 truncate">
                      {activeTile.label}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-400 truncate">
                    {selectedPipeline?.grant_title ?? ""}
                    {SECTION_GUIDANCE[activeTile.label]
                      ? ` · ~${SECTION_GUIDANCE[activeTile.label].wordLimit} words target`
                      : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {/* Save status indicator */}
                {saveStatus === "saving" && (
                  <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Saving...
                  </span>
                )}
                {saveStatus === "saved" && (
                  <span className="inline-flex items-center gap-1 text-[10px] text-green-500">
                    <Cloud className="h-3 w-3" />
                    Saved
                  </span>
                )}
                {saveStatus === "error" && (
                  <span className="inline-flex items-center gap-1 text-[10px] text-red-400">
                    <CloudOff className="h-3 w-3" />
                    Save failed
                  </span>
                )}
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${themeConfig.bg} ${themeConfig.color}`}
                >
                  {themeConfig.label}
                </span>
                {activeKey && approvedSections.has(activeKey) && (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700 ring-1 ring-green-200">
                    <CheckCircle className="h-3 w-3" />
                    Approved
                  </span>
                )}
                {/* Clear chat button */}
                {activeMessages.length > 1 && (
                  <button
                    onClick={clearChat}
                    disabled={clearingSection}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors disabled:opacity-40"
                    title="Clear chat history"
                  >
                    {clearingSection ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
              </div>
            </div>

            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
              {activeMessages.map((msg, i) => {
                const showDateSep =
                  i > 0 && isDifferentDay(activeMessages[i - 1].timestamp, msg.timestamp);
                return (
                  <div key={i}>
                    {showDateSep && (
                      <div className="flex items-center gap-3 py-2">
                        <div className="flex-1 border-t border-gray-200" />
                        <span className="text-[10px] font-medium text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full">
                          {formatDate(msg.timestamp)}
                        </span>
                        <div className="flex-1 border-t border-gray-200" />
                      </div>
                    )}
                    <ChatBubble message={msg} />
                  </div>
                );
              })}

              {/* Typing indicator */}
              {sending && (
                <div className="flex gap-3">
                  <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${themeConfig.gradient} shadow-sm`}>
                    <Bot className="h-4 w-4 text-white" />
                  </div>
                  <div className="flex items-center gap-2.5 rounded-2xl rounded-tl-md bg-white px-4 py-3 shadow-sm ring-1 ring-gray-100">
                    <div className="flex gap-1">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-violet-400 [animation-delay:0ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-violet-400 [animation-delay:150ms]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-violet-400 [animation-delay:300ms]" />
                    </div>
                    <span className="text-sm text-gray-500">
                      {currentAgent.name} drafting...
                    </span>
                  </div>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            {/* Error banner */}
            {error && (
              <div className="mx-5 mb-2 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span className="flex-1">{error}</span>
                <button
                  onClick={() => setError(null)}
                  className="shrink-0 rounded p-0.5 text-red-400 hover:text-red-600"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
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
                <div className="flex flex-col gap-2">
                  <div className="relative">
                    <textarea
                      ref={textareaRef}
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={3}
                      placeholder={
                        activeMessages.some((m) => m.role === "agent")
                          ? "Type revision instructions or follow-up..."
                          : "Paste the grant question or requirements here..."
                      }
                      className="w-full resize-none rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 pr-14 text-sm text-gray-800 placeholder:text-gray-400 transition-colors focus:border-violet-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-violet-100"
                      disabled={sending}
                    />
                    <button
                      onClick={sendMessage}
                      disabled={!inputValue.trim() || sending}
                      className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600 text-white shadow-sm transition-all hover:bg-violet-700 disabled:opacity-40 disabled:hover:bg-violet-600"
                    >
                      <Send className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="flex items-center justify-between px-1">
                    <p className="text-[11px] text-gray-400">
                      Enter to send &middot; Shift+Enter for new line
                    </p>
                    {activeMessages.some((m) => m.role === "agent") && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={approveSection}
                        disabled={approving}
                        className="h-7 gap-1.5 rounded-lg border-green-200 text-green-700 hover:bg-green-50 hover:text-green-800"
                      >
                        {approving ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <CheckCircle className="h-3 w-3" />
                        )}
                        Approve Section
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ---- RIGHT: SETTINGS SLIDE-OVER ---------------------------------- */}
      <DrafterSettings open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* ---- RIGHT: ACTIVITY TIMELINE (SLIDE-OVER) ----------------------- */}
      {timelineOpen && (
        <>
          {/* Backdrop */}
          <div
            className="absolute inset-0 z-30 bg-black/10 backdrop-blur-[1px]"
            onClick={() => setTimelineOpen(false)}
          />
          {/* Panel */}
          <div className="absolute right-0 top-0 bottom-0 z-40 flex w-72 flex-col border-l border-gray-200 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-gray-400" />
                <span className="text-sm font-semibold text-gray-700">
                  Activity
                </span>
              </div>
              <button
                onClick={() => setTimelineOpen(false)}
                className="flex h-6 w-6 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {timeline.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Clock className="mb-2 h-8 w-8 text-gray-200" />
                  <p className="text-sm font-medium text-gray-400">
                    No activity yet
                  </p>
                  <p className="mt-1 text-xs text-gray-300">
                    Start chatting to see activity
                  </p>
                </div>
              ) : (
                <div className="relative px-4 py-3">
                  {/* Vertical line */}
                  <div className="absolute left-[27px] top-6 bottom-6 w-px bg-gray-100" />

                  {timeline.map((evt) => (
                    <button
                      key={evt.id}
                      onClick={() => {
                        setActiveTileId(evt.tileId);
                        setError(null);
                        setTimelineOpen(false);
                      }}
                      className="relative flex w-full gap-3 rounded-lg px-1 py-2.5 text-left transition-colors hover:bg-gray-50"
                    >
                      {/* Icon dot */}
                      <span className="relative z-10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white ring-2 ring-gray-100">
                        {evt.type === "approved" && (
                          <CheckCircle className="h-3 w-3 text-green-500" />
                        )}
                        {evt.type === "drafted" && (
                          <Sparkles className="h-3 w-3 text-violet-500" />
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
                        <p className="text-xs font-medium text-gray-700">
                          {evt.type === "created" && "Section created"}
                          {evt.type === "drafted" && "Agent drafted"}
                          {evt.type === "revised" && "Agent revised"}
                          {evt.type === "approved" && "Section approved"}
                          {evt.type === "user_message" && "You sent"}
                        </p>
                        <p className="mt-0.5 text-[11px] text-gray-400 truncate">
                          {evt.section}
                          {evt.detail ? ` · ${evt.detail}` : ""}
                        </p>
                        <p className="mt-0.5 text-[10px] text-gray-300">
                          {formatTime(evt.timestamp)}
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
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
        <div className={`max-w-lg rounded-xl border border-violet-100 bg-violet-50/50 px-5 py-3 text-center`}>
          <div className="prose prose-sm max-w-none text-violet-700 [&_p]:text-[13px] [&_p]:leading-relaxed [&_strong]:text-violet-800">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
          <p className="mt-2 text-[10px] text-violet-400">
            {formatTime(timestamp)}
          </p>
        </div>
      </div>
    );
  }

  if (role === "agent") {
    const msgTheme = metadata?.agentTheme
      ? THEME_CONFIG[metadata.agentTheme]
      : null;
    const gradient = msgTheme?.gradient || "from-violet-500 to-purple-600";
    const labelColor = msgTheme?.color || "text-violet-700";
    const agentLabel = metadata?.agentName || "Drafter Agent";

    return (
      <div className="flex gap-3">
        <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${gradient} shadow-sm`}>
          <Bot className="h-4 w-4 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <span className={`text-xs font-semibold ${labelColor}`}>
              {agentLabel}
            </span>
            <span className="text-[10px] text-gray-400">
              {formatTime(timestamp)}
            </span>
          </div>
          <div className="rounded-2xl rounded-tl-md bg-white p-5 shadow-sm ring-1 ring-gray-100">
            <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:mt-4 prose-headings:mb-2 prose-p:my-2 prose-p:leading-relaxed prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2 prose-strong:text-gray-900 prose-blockquote:border-gray-300 prose-blockquote:text-gray-600 prose-h2:text-base prose-h3:text-sm first:prose-headings:mt-0">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>

            {metadata && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3">
                {metadata.wordCount != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${
                      metadata.wordLimit &&
                      metadata.wordCount > metadata.wordLimit
                        ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                        : "bg-gray-50 text-gray-600 ring-1 ring-gray-100"
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
                        ? "bg-green-50 text-green-700 ring-1 ring-green-200"
                        : metadata.status === "In Review"
                          ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                          : "bg-gray-50 text-gray-600 ring-1 ring-gray-100"
                    }`}
                  >
                    {metadata.status}
                  </span>
                )}
                {metadata.agentTemperature != null && (
                  <span className="rounded-md bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-500 ring-1 ring-gray-100">
                    temp: {metadata.agentTemperature}
                  </span>
                )}
                {metadata.sourcesUsed && metadata.sourcesUsed.length > 0 && (
                  <>
                    {metadata.sourcesUsed.map((src) => {
                      const srcStyles: Record<string, string> = {
                        company_profile: "bg-violet-50 text-violet-700 ring-violet-200",
                        knowledge_chunks: "bg-blue-50 text-blue-700 ring-blue-200",
                        notion_live: "bg-green-50 text-green-700 ring-green-200",
                        grant_deep_analysis: "bg-amber-50 text-amber-700 ring-amber-200",
                      };
                      const srcLabels: Record<string, string> = {
                        company_profile: "Company Profile",
                        knowledge_chunks: "Knowledge Base",
                        notion_live: "Notion (Live)",
                        grant_deep_analysis: "Grant Analysis",
                      };
                      return (
                        <span
                          key={src}
                          className={`rounded-md px-2 py-0.5 text-[10px] font-medium ring-1 ${
                            srcStyles[src] || "bg-gray-50 text-gray-600 ring-gray-100"
                          }`}
                        >
                          {srcLabels[src] || src}
                        </span>
                      );
                    })}
                  </>
                )}
              </div>
            )}

            {metadata?.evidenceGaps && metadata.evidenceGaps.length > 0 && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <div className="mb-2 flex items-center gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                  <span className="text-xs font-semibold text-amber-700">
                    Evidence Gaps
                  </span>
                </div>
                <ul className="space-y-1.5">
                  {metadata.evidenceGaps.map((gap, j) => (
                    <li
                      key={j}
                      className="text-xs leading-snug text-amber-700 pl-3 border-l-2 border-amber-300"
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

  // User message
  return (
    <div className="flex gap-3 justify-end">
      <div className="flex-1 min-w-0 max-w-[70%] ml-auto">
        <div className="mb-1.5 flex items-center gap-2 justify-end">
          <span className="text-[10px] text-gray-400">
            {formatTime(timestamp)}
          </span>
          <span className="text-xs font-semibold text-gray-600">You</span>
        </div>
        <div className="rounded-2xl rounded-tr-md bg-gradient-to-br from-blue-500 to-blue-600 px-5 py-3 text-sm leading-relaxed text-white shadow-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-600 shadow-sm">
        <User className="h-4 w-4 text-white" />
      </div>
    </div>
  );
}
