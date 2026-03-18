"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";
import type { PipelineRecord, DraftSection } from "@/lib/queries";
import {
  Send,
  CheckCircle,
  FileText,
  ChevronDown,
  Download,
  MessageSquare,
  Bot,
  AlertTriangle,
  Copy,
  Check,
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

/** Save chat histories to backend (scoped to user) */
async function saveChatHistories(
  pipelineId: string,
  grantId: string,
  tiles: Tile[],
  chatHistories: Record<string, ChatMessage[]>,
  userEmail?: string,
  sessionId?: string
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
        user_email: userEmail || undefined,
        session_id: sessionId || undefined,
      }),
    });
    return true;
  } catch {
    return false;
  }
}

/** Load chat histories from backend (scoped to user) */
async function loadChatHistories(
  pipelineId: string,
  userEmail?: string
): Promise<Record<string, ChatMessage[]> | null> {
  try {
    let url = `/api/drafter/chat-history?pipeline_id=${encodeURIComponent(pipelineId)}`;
    if (userEmail) url += `&user_email=${encodeURIComponent(userEmail)}`;
    const res = await fetch(url);
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
  sectionName: string,
  userEmail?: string
): Promise<boolean> {
  try {
    let url = `/api/drafter/chat-history?pipeline_id=${encodeURIComponent(pipelineId)}&section_name=${encodeURIComponent(sectionName)}`;
    if (userEmail) url += `&user_email=${encodeURIComponent(userEmail)}`;
    const res = await fetch(url, { method: "DELETE" });
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
// Session cache — survives unmount/remount when navigating between pages
// ---------------------------------------------------------------------------

interface DrafterCache {
  selectedId: string;
  activeTileId: string | null;
  tilesMap: Record<string, Tile[]>;
  chatHistories: Record<string, ChatMessage[]>;
  approvedSections: string[]; // serializable version of Set
  agentInfo: Record<string, { name: string; theme: string }>;
  historyLoaded: string[];
  sessionId: string; // UUID per drafter session
}

const _cache: { current: DrafterCache | null; userEmail: string | null } = {
  current: null,
  userEmail: null,
};

function saveToCache(c: DrafterCache, email?: string) {
  _cache.current = c;
  _cache.userEmail = email ?? null;
}

function loadFromCache(email?: string): DrafterCache | null {
  // Don't return stale cache from a different user
  if (_cache.userEmail && email && _cache.userEmail !== email) {
    _cache.current = null;
    _cache.userEmail = null;
    return null;
  }
  return _cache.current;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function DrafterView({ pipelines }: DrafterViewProps) {
  const { data: session, status: sessionStatus } = useSession();
  const userEmail = session?.user?.email ?? undefined;
  const cached = loadFromCache(userEmail);
  const [sessionId] = useState(
    () => cached?.sessionId ?? crypto.randomUUID()
  );
  const [selectedId, setSelectedId] = useState(
    cached?.selectedId ?? pipelines[0]?._id ?? ""
  );
  const [activeTileId, setActiveTileId] = useState<string | null>(
    cached?.activeTileId ?? null
  );
  const [tilesMap, setTilesMap] = useState<Record<string, Tile[]>>(
    cached?.tilesMap ?? {}
  );
  const [chatHistories, setChatHistories] = useState<
    Record<string, ChatMessage[]>
  >(cached?.chatHistories ?? {});
  const [approvedSections, setApprovedSections] = useState<Set<string>>(
    new Set(cached?.approvedSections ?? [])
  );
  const [inputValue, setInputValue] = useState("");
  const [sendingKeys, setSendingKeys] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTileId, setEditingTileId] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState("");
  const [editingMsgIdx, setEditingMsgIdx] = useState<number | null>(null);
  const [editingMsgContent, setEditingMsgContent] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [drafterModel, setDrafterModel] = useState<"gpt-5.4" | "opus-4.6">("gpt-5.4");
  const [agentInfo, setAgentInfo] = useState<
    Record<string, { name: string; theme: string }>
  >(cached?.agentInfo ?? {});
  const [historyLoaded, setHistoryLoaded] = useState<Set<string>>(
    new Set(cached?.historyLoaded ?? [])
  );
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [clearingSection, setClearingSection] = useState(false);
  const [generatingBrief, setGeneratingBrief] = useState(false);
  const [pastSessions, setPastSessions] = useState<
    { id: string; snapshot_at: string; message_count: number; section_names: string[]; session_id?: string }[]
  >([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [restoringSession, setRestoringSession] = useState<string | null>(null);
  const [streamingByKey, setStreamingByKey] = useState<Record<string, string>>({});
  const [streamStatusByKey, setStreamStatusByKey] = useState<Record<string, string>>({});

  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatHistoriesRef = useRef(chatHistories);
  chatHistoriesRef.current = chatHistories;
  const tilesRef = useRef<Tile[]>([]);
  const abortRef = useRef<Record<string, AbortController>>({});
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const grantDataRef = useRef<Record<string, any>>({});

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

  // Per-key streaming state → derive active values
  const sending = activeKey ? sendingKeys.has(activeKey) : false;
  const streamingContent = activeKey ? streamingByKey[activeKey] ?? "" : "";
  const streamStatus = activeKey ? streamStatusByKey[activeKey] ?? null : null;

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

  // -- Preload full grant data for intelligence brief -------------------------
  useEffect(() => {
    if (!selectedPipeline?.grant_id) return;
    const gid = selectedPipeline.grant_id;
    if (grantDataRef.current[gid]) return; // already loaded
    let cancelled = false;
    fetch(`/api/grants/${encodeURIComponent(gid)}`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) grantDataRef.current[gid] = data;
      })
      .catch(() => {}); // silent — brief will retry on click
    return () => { cancelled = true; };
  }, [selectedPipeline?.grant_id]);

  // -- Load persisted chat history from DB -----------------------------------
  // Build a stable key that includes userEmail so we re-fetch when user changes
  const historyKey = userEmail ? `${selectedId}::${userEmail}` : selectedId;

  useEffect(() => {
    if (!selectedId || !selectedPipeline || historyLoaded.has(historyKey)) return;
    if (tiles.length === 0) return; // wait for tiles to be initialized
    // Wait for session to resolve — don't fetch with undefined email
    if (sessionStatus === "loading") return;

    let cancelled = false;
    (async () => {
      const savedSections = await loadChatHistories(selectedId, userEmail);
      if (cancelled || !savedSections) {
        setHistoryLoaded((prev) => new Set(prev).add(historyKey));
        return;
      }

      const savedNames = Object.keys(savedSections);
      if (savedNames.length === 0) {
        setHistoryLoaded((prev) => new Set(prev).add(historyKey));
        return;
      }

      // Restore tile labels from saved section names (user may have renamed them)
      // Match saved sections to tiles: by label first, then by position
      const matchedSavedNames = new Set<string>();
      const tileToSaved: Record<string, string> = {};

      // Pass 1: exact label match
      for (const tile of tiles) {
        if (savedSections[tile.label]) {
          tileToSaved[tile.id] = tile.label;
          matchedSavedNames.add(tile.label);
        }
      }

      // Pass 2: unmatched saved sections → assign to unmatched tiles by position
      const unmatchedSaved = savedNames.filter((n) => !matchedSavedNames.has(n));
      const unmatchedTiles = tiles.filter((t) => !tileToSaved[t.id]);
      for (let i = 0; i < Math.min(unmatchedSaved.length, unmatchedTiles.length); i++) {
        tileToSaved[unmatchedTiles[i].id] = unmatchedSaved[i];
      }

      // Rename tiles to match saved section names
      const renamedTiles = tiles.map((t) => {
        const savedName = tileToSaved[t.id];
        if (savedName && savedName !== t.label) {
          return { ...t, label: savedName };
        }
        return t;
      });

      // Update tiles if any were renamed
      const tilesChanged = renamedTiles.some((t, i) => t.label !== tiles[i]?.label);
      if (tilesChanged) {
        setTilesMap((prev) => ({ ...prev, [selectedId]: renamedTiles }));
      }

      // Also create tiles for saved sections that don't have a tile yet
      const extraSaved = unmatchedSaved.slice(unmatchedTiles.length);
      if (extraSaved.length > 0) {
        const extraTiles = extraSaved.map((name) => ({
          id: `tile-${++tileCounter}`,
          label: name,
        }));
        setTilesMap((prev) => ({
          ...prev,
          [selectedId]: [...(tilesChanged ? renamedTiles : tiles), ...extraTiles],
        }));
        // Add extra tiles to the mapping
        for (let i = 0; i < extraTiles.length; i++) {
          tileToSaved[extraTiles[i].id] = extraSaved[i];
        }
      }

      // Restore chat histories using the mapping
      setChatHistories((prev) => {
        const next = { ...prev };
        for (const tileId of Object.keys(tileToSaved)) {
          const savedName = tileToSaved[tileId];
          const savedMsgs = savedSections[savedName];
          if (savedMsgs && savedMsgs.length > 0) {
            const key = buildKey(selectedId, tileId);
            next[key] = savedMsgs;
            if (savedMsgs.some((m: ChatMessage) => m.role === "system" && m.metadata?.status === "Approved")) {
              setApprovedSections((s) => new Set(s).add(key));
            }
          }
        }
        return next;
      });

      setHistoryLoaded((prev) => new Set(prev).add(historyKey));
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tiles.length, historyKey, sessionStatus]);

  // -- Load past sessions when timeline opens ---------------------------------
  useEffect(() => {
    if (!timelineOpen || !selectedId) return;
    setLoadingSessions(true);
    let cancelled = false;
    (async () => {
      try {
        let url = `/api/drafter/chat-sessions?pipeline_id=${encodeURIComponent(selectedId)}`;
        if (userEmail) url += `&user_email=${encodeURIComponent(userEmail)}`;
        const res = await fetch(url);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled) setPastSessions(data.sessions ?? []);
      } catch {
        // silent
      } finally {
        if (!cancelled) setLoadingSessions(false);
      }
    })();
    return () => { cancelled = true; };
  }, [timelineOpen, selectedId, userEmail]);

  // -- Restore a past session ------------------------------------------------
  const restoreSession = useCallback(async (snapshotId: string) => {
    if (!selectedId || restoringSession) return;
    setRestoringSession(snapshotId);
    try {
      let url = `/api/drafter/chat-sessions?pipeline_id=${encodeURIComponent(selectedId)}&snapshot_id=${encodeURIComponent(snapshotId)}`;
      if (userEmail) url += `&user_email=${encodeURIComponent(userEmail)}`;
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) throw new Error("Restore failed");

      // Reload chat history from DB
      const savedSections = await loadChatHistories(selectedId, userEmail);
      if (savedSections) {
        setChatHistories((prev) => {
          const next = { ...prev };
          for (const tile of tiles) {
            const key = buildKey(selectedId, tile.id);
            const savedMsgs = savedSections[tile.label];
            if (savedMsgs && savedMsgs.length > 0) {
              next[key] = savedMsgs;
              if (savedMsgs.some((m: ChatMessage) => m.role === "system" && m.metadata?.status === "Approved")) {
                setApprovedSections((s) => new Set(s).add(key));
              }
            }
          }
          return next;
        });
      }

      setTimelineOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Restore failed");
    } finally {
      setRestoringSession(null);
    }
  }, [selectedId, userEmail, tiles, restoringSession]);

  // -- Cache state for navigation persistence ---------------------------------
  useEffect(() => {
    saveToCache({
      selectedId,
      activeTileId,
      tilesMap,
      chatHistories,
      approvedSections: Array.from(approvedSections),
      agentInfo,
      historyLoaded: Array.from(historyLoaded),
      sessionId,
    }, userEmail);
  }, [selectedId, activeTileId, tilesMap, chatHistories, approvedSections, agentInfo, historyLoaded, sessionId, userEmail]);

  // -- Flush pending save on unmount ------------------------------------------
  // Store userEmail in a ref so the cleanup function always has the latest value
  const userEmailRef = useRef(userEmail);
  userEmailRef.current = userEmail;

  useEffect(() => {
    return () => {
      // Cancel any debounced save and save immediately
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
      const pipeline = pipelines.find((p) => p._id === selectedId);
      const email = userEmailRef.current;
      if (pipeline && tilesRef.current.length > 0 && email) {
        saveChatHistories(
          selectedId,
          pipeline.grant_id,
          tilesRef.current,
          chatHistoriesRef.current,
          email,
          sessionId
        );
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, sessionId]);

  // -- Debounced auto-save (uses refs for latest state) ----------------------
  const triggerSave = useCallback(() => {
    if (!selectedPipeline) return;
    // Don't save until we have the user's email — prevents orphan docs
    if (!userEmail) return;
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);

    setSaveStatus("saving");
    saveTimeoutRef.current = setTimeout(async () => {
      const ok = await saveChatHistories(
        selectedId,
        selectedPipeline.grant_id,
        tilesRef.current,
        chatHistoriesRef.current,
        userEmail,
        sessionId
      );
      setSaveStatus(ok ? "saved" : "error");
      setTimeout(() => setSaveStatus("idle"), 2000);
    }, 800);
  }, [selectedId, selectedPipeline, userEmail, sessionId]);

  // -- Non-streaming fallback -------------------------------------------------
  const chatFallback = useCallback(
    async (
      key: string,
      tile: Tile,
      pipeline: PipelineRecord,
      userMessage: string,
      chatHistory: { role: string; content: string }[]
    ) => {
      const res = await fetch("/api/drafter/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_name: tile.label,
          message: userMessage,
          grant_id: pipeline.grant_id,
          chat_history: chatHistory,
          model: drafterModel,
          user_email: userEmail,
          session_id: sessionId,
        }),
      });

      if (!res.ok) throw new Error((await res.text()) || `Error ${res.status}`);
      const data = await res.json();
      const revised = data.revised_content ?? data.content ?? data.message ?? "";
      const wc = countWords(revised);
      const guidance = SECTION_GUIDANCE[tile.label];

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
        [key]: [...(prev[key] ?? []), agentMsg],
      }));
      setTimeout(() => triggerSave(), 50);
    },
    [selectedId, triggerSave, userEmail, sessionId]
  );

  // -- Streaming SSE helper (per-key, falls back to non-streaming) ----------
  const streamChat = useCallback(
    async (
      key: string,
      tile: Tile,
      pipeline: PipelineRecord,
      userMessage: string,
      chatHistory: { role: string; content: string }[]
    ) => {
      setSendingKeys((prev) => new Set(prev).add(key));
      setError(null);
      setStreamingByKey((prev) => ({ ...prev, [key]: "" }));
      setStreamStatusByKey((prev) => ({ ...prev, [key]: "" }));

      // Abort any previous stream for this key
      abortRef.current[key]?.abort();
      const controller = new AbortController();
      abortRef.current[key] = controller;

      try {
        // Try streaming first
        let streamed = false;
        try {
          const res = await fetch("/api/drafter/chat-stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              section_name: tile.label,
              message: userMessage,
              grant_id: pipeline.grant_id,
              chat_history: chatHistory,
              model: drafterModel,
              user_email: userEmail,
              session_id: sessionId,
            }),
            signal: controller.signal,
          });

          if (!res.ok || !res.body) throw new Error("Stream unavailable");

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          let fullContent = "";
          let metadata: ChatMessage["metadata"] | undefined;

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let event = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                event = line.slice(7).trim();
              } else if (line.startsWith("data: ") && event) {
                const currentEvent = event;
                event = "";
                let data;
                try {
                  data = JSON.parse(line.slice(6));
                } catch {
                  continue; // skip malformed JSON
                }
                if (currentEvent === "status") {
                  setStreamStatusByKey((prev) => ({ ...prev, [key]: data.step || "" }));
                } else if (currentEvent === "token") {
                  fullContent += data.content || "";
                  setStreamingByKey((prev) => ({ ...prev, [key]: fullContent }));
                } else if (currentEvent === "metadata") {
                  const guidance = SECTION_GUIDANCE[tile.label];
                  metadata = {
                    wordCount: data.word_count,
                    wordLimit: guidance?.wordLimit,
                    evidenceGaps: data.evidence_gaps ?? [],
                    status: "Draft",
                    agentName: data.agent_name,
                    agentTheme: data.agent_theme,
                    sourcesUsed: data.sources_used ?? [],
                    agentTemperature: data.agent_temperature,
                  };
                  if (data.agent_name && data.agent_theme) {
                    setAgentInfo((prev) => ({
                      ...prev,
                      [selectedId]: { name: data.agent_name, theme: data.agent_theme },
                    }));
                  }
                } else if (currentEvent === "error") {
                  throw new Error(data.message || "Agent error");
                }
              }
            }
          }

          // Finalize — add the complete agent message
          if (fullContent) {
            const agentMsg: ChatMessage = {
              role: "agent",
              content: fullContent,
              timestamp: now(),
              metadata: metadata ?? {
                wordCount: countWords(fullContent),
                status: "Draft",
              },
            };
            setChatHistories((prev) => ({
              ...prev,
              [key]: [...(prev[key] ?? []), agentMsg],
            }));
            setTimeout(() => triggerSave(), 50);
            streamed = true;
          }
        } catch (streamErr) {
          if ((streamErr as Error).name === "AbortError") throw streamErr;
          // Stream failed — will fall back below
          console.warn("[Drafter] Streaming failed, falling back:", (streamErr as Error).message);
        }

        // Fallback to non-streaming if streaming produced nothing
        if (!streamed) {
          setStreamStatusByKey((prev) => ({ ...prev, [key]: "Waiting for response..." }));
          await chatFallback(key, tile, pipeline, userMessage, chatHistory);
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setError(e instanceof Error ? e.message : "Failed to get response");
      } finally {
        setSendingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        setStreamingByKey((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        setStreamStatusByKey((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        delete abortRef.current[key];
        textareaRef.current?.focus();
      }
    },
    [selectedId, triggerSave, chatFallback, userEmail, sessionId]
  );

  // -- Auto-scroll -----------------------------------------------------------
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeMessages.length, sending, streamingContent]);

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

  // -- Send message (streaming) ----------------------------------------------
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

    const currentMsgs = chatHistories[activeKey] ?? [];
    const chatHistory = currentMsgs
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "agent" ? "assistant" : m.role,
        content: m.content,
      }));

    await streamChat(activeKey, activeTile, selectedPipeline, userMsg.content, chatHistory);
  }, [activeKey, activeTile, selectedPipeline, inputValue, selectedId, chatHistories, streamChat]);

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
      await clearSectionHistory(selectedId, activeTile.label, userEmail);
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

  // -- Download Intelligence Brief ------------------------------------------
  const downloadIntelBrief = useCallback(async (format: "md" | "pdf" = "md") => {
    if (!selectedPipeline || generatingBrief) return;
    const grantId = selectedPipeline.grant_id;
    if (!grantId) {
      setError("No grant linked to this pipeline entry");
      return;
    }
    setGeneratingBrief(true);
    setError(null);
    try {
      // Use preloaded grant data if available, otherwise fetch
      let grant = grantDataRef.current[grantId];
      if (!grant) {
        const res = await fetch(`/api/grants/${encodeURIComponent(grantId)}`, {
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error(`Could not load grant (${res.status})`);
        grant = await res.json();
        grantDataRef.current[grantId] = grant;
      }
      const { grantToBriefData, generateIntelBriefMd, generateIntelBriefPdf } =
        await import("@/lib/generateIntelBrief");
      const data = grantToBriefData(grant);
      if (format === "pdf") {
        await generateIntelBriefPdf(data, selectedPipeline.grant_title);
      } else {
        await generateIntelBriefMd(data, selectedPipeline.grant_title);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      console.error("[IntelBrief]", msg);
      setError(`Brief failed: ${msg}`);
    } finally {
      setGeneratingBrief(false);
    }
  }, [selectedPipeline, generatingBrief]);

  // -- Copy agent response ---------------------------------------------------
  const copySnippet = useCallback((msgIdx: number) => {
    const msg = activeMessages[msgIdx];
    if (!msg) return;
    navigator.clipboard.writeText(msg.content);
    setCopiedIdx(msgIdx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }, [activeMessages]);

  // -- Regenerate (re-send last user message, streaming) --------------------
  const regenerate = useCallback(async () => {
    if (!activeKey || !activeTile || !selectedPipeline || sending) return;

    const lastUserIdx = [...activeMessages].reverse().findIndex((m) => m.role === "user");
    if (lastUserIdx === -1) return;
    const lastUser = activeMessages[activeMessages.length - 1 - lastUserIdx];

    // Remove all messages after the last user message (agent responses)
    const trimmed = activeMessages.slice(0, activeMessages.length - lastUserIdx);

    setChatHistories((prev) => ({
      ...prev,
      [activeKey]: trimmed,
    }));

    const chatHistory = trimmed
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "agent" ? "assistant" : m.role,
        content: m.content,
      }));

    await streamChat(activeKey, activeTile, selectedPipeline, lastUser.content, chatHistory.slice(0, -1));
  }, [activeKey, activeTile, selectedPipeline, activeMessages, sending, streamChat]);

  // -- Edit user message (replaces message and re-sends, streaming) ---------
  const saveEditMessage = useCallback(async (msgIdx: number) => {
    if (!activeKey || !activeTile || !selectedPipeline) return;
    const trimmedContent = editingMsgContent.trim();
    if (!trimmedContent) return;

    const before = activeMessages.slice(0, msgIdx);
    const editedMsg: ChatMessage = {
      role: "user",
      content: trimmedContent,
      timestamp: now(),
    };

    setChatHistories((prev) => ({
      ...prev,
      [activeKey]: [...before, editedMsg],
    }));
    setEditingMsgIdx(null);
    setEditingMsgContent("");

    const chatHistory = before
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "agent" ? "assistant" : m.role,
        content: m.content,
      }));

    await streamChat(activeKey, activeTile, selectedPipeline, trimmedContent, chatHistory);
  }, [activeKey, activeTile, selectedPipeline, activeMessages, editingMsgContent, streamChat]);

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
      <div className="flex w-[280px] shrink-0 flex-col border-r border-gray-200 bg-white shadow-sm">
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
              const isTileStreaming = sendingKeys.has(key);
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
                      isTileStreaming
                        ? "bg-violet-100 text-violet-600"
                        : status === "Approved"
                          ? "bg-green-100 text-green-600"
                          : isActive
                            ? "bg-violet-100 text-violet-600"
                            : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {isTileStreaming ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : status === "Approved" ? (
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

        {/* Export & Intelligence Brief */}
        <div className="border-t border-gray-100 p-3 space-y-2">
          {/* Intelligence Brief — .md and .pdf options */}
          <div className="flex gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="flex-1 gap-1.5 border-violet-200 text-violet-700 hover:bg-violet-50"
              onClick={() => downloadIntelBrief("md")}
              disabled={generatingBrief}
            >
              {generatingBrief ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileText className="h-3.5 w-3.5" />
              )}
              Brief .md
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-1 gap-1.5 border-violet-200 text-violet-700 hover:bg-violet-50"
              onClick={() => downloadIntelBrief("pdf")}
              disabled={generatingBrief}
            >
              {generatingBrief ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileText className="h-3.5 w-3.5" />
              )}
              Brief .pdf
            </Button>
          </div>

          {/* Export Draft — only when all sections approved */}
          {allApproved && tiles.length > 0 && (
            <Button
              variant="default"
              size="sm"
              className="w-full bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700"
              onClick={exportDraft}
            >
              <Download className="h-4 w-4" />
              Export Draft
            </Button>
          )}
        </div>
      </div>

      {/* ---- CENTER: CHAT PANEL ------------------------------------------ */}
      <div className="flex flex-1 flex-col overflow-hidden bg-gradient-to-b from-gray-50 to-gray-100/50">
        {!activeTile ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center px-6">
              <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-white shadow-md ring-1 ring-gray-100">
                <MessageSquare className="h-7 w-7 text-violet-400" />
              </div>
              <p className="text-lg font-semibold text-gray-800">
                Select a section to begin
              </p>
              <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-gray-400">
                Pick a section tile on the left, then paste the grant question or
                requirements. The agent will draft a response.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3">
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${themeConfig.gradient} shadow-sm`}
                >
                  <Bot className="h-4.5 w-4.5 text-white" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-sm font-bold text-gray-900">
                      {activeTile.label}
                    </h2>
                  </div>
                  <p className="text-[11px] text-gray-400 truncate">
                    {currentAgent.name}
                    {SECTION_GUIDANCE[activeTile.label]
                      ? ` · ~${SECTION_GUIDANCE[activeTile.label].wordLimit} words`
                      : ""}
                    {selectedPipeline?.grant_title ? ` · ${selectedPipeline.grant_title}` : ""}
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
            <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
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
                    <ChatBubble
                      message={msg}
                      msgIdx={i}
                      userName={session?.user?.name ?? "You"}
                      userImage={session?.user?.image ?? undefined}
                      onCopy={copySnippet}
                      onRegenerate={regenerate}
                      onEditStart={(idx) => {
                        setEditingMsgIdx(idx);
                        setEditingMsgContent(activeMessages[idx].content);
                      }}
                      onEditSave={saveEditMessage}
                      onEditCancel={() => {
                        setEditingMsgIdx(null);
                        setEditingMsgContent("");
                      }}
                      editingMsgIdx={editingMsgIdx}
                      editingMsgContent={editingMsgContent}
                      onEditChange={setEditingMsgContent}
                      copiedIdx={copiedIdx}
                      isLastAgent={
                        i ===
                        activeMessages.length -
                          1 -
                          [...activeMessages]
                            .reverse()
                            .findIndex((m) => m.role === "agent")
                      }
                      sending={sending}
                    />
                  </div>
                );
              })}

              {/* Streaming / typing indicator */}
              {sending && (
                <div className="flex gap-2.5">
                  <div className="mt-0.5 shrink-0">
                    <DrafterAvatar
                      name={currentAgent.name}
                      gradient={themeConfig.gradient}
                      icon={<Bot className="h-3.5 w-3.5 text-white" />}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className={`text-xs font-semibold ${themeConfig.color}`}>
                        {currentAgent.name}
                      </span>
                      {streamStatus && (
                        <span className="flex items-center gap-1.5 text-[10px] text-gray-400">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          {streamStatus}
                        </span>
                      )}
                    </div>

                    {streamingContent ? (
                      /* Live streaming content */
                      <div className="mt-1.5 rounded-lg bg-white p-4 shadow-sm ring-1 ring-gray-100">
                        <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:mt-4 prose-headings:mb-2 prose-p:my-2 prose-p:leading-relaxed prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2 prose-strong:text-gray-900 prose-h2:text-base prose-h3:text-sm first:prose-headings:mt-0">
                          <ReactMarkdown>{streamingContent}</ReactMarkdown>
                        </div>
                        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-gray-400">
                          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />
                          {countWords(streamingContent)} words so far...
                        </div>
                      </div>
                    ) : (
                      /* Status steps before streaming begins */
                      <div className="mt-1.5 rounded-lg bg-white px-4 py-3 shadow-sm ring-1 ring-gray-100">
                        <div className="flex items-center gap-2.5">
                          <div className="flex gap-1">
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400 [animation-delay:0ms]" />
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400 [animation-delay:150ms]" />
                            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400 [animation-delay:300ms]" />
                          </div>
                          <span className="text-sm text-gray-400">
                            {streamStatus || "Connecting..."}
                          </span>
                        </div>
                      </div>
                    )}
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
            <div className="border-t border-gray-200 bg-white px-5 py-3.5 shadow-[0_-1px_3px_rgba(0,0,0,0.04)]">
              {activeKey && approvedSections.has(activeKey) ? (
                <div className="flex items-center justify-center gap-2 rounded-xl bg-green-50 py-3 text-sm text-green-700">
                  <CheckCircle className="h-4 w-4" />
                  Section approved. Select another section or export the draft.
                </div>
              ) : (
                <div className="flex flex-col gap-2.5">
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
                      className="w-full resize-none rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 pr-14 text-sm text-gray-800 placeholder:text-gray-400 transition-all focus:border-violet-300 focus:bg-white focus:outline-none focus:ring-2 focus:ring-violet-100"
                      disabled={sending}
                    />
                    <button
                      onClick={sendMessage}
                      disabled={!inputValue.trim() || sending}
                      className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-r from-violet-600 to-purple-600 text-white shadow-sm transition-all hover:from-violet-700 hover:to-purple-700 disabled:opacity-40"
                    >
                      {sending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                  <div className="flex items-center justify-between px-1">
                    <div className="flex items-center gap-3">
                      <p className="text-[11px] text-gray-400">
                        Enter to send &middot; Shift+Enter for new line
                      </p>
                      <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-0.5">
                        <button
                          onClick={() => setDrafterModel("gpt-5.4")}
                          className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-all ${
                            drafterModel === "gpt-5.4"
                              ? "bg-white text-gray-800 shadow-sm ring-1 ring-gray-200"
                              : "text-gray-400 hover:text-gray-600"
                          }`}
                        >
                          GPT-5.4
                        </button>
                        <button
                          onClick={() => setDrafterModel("opus-4.6")}
                          className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-all ${
                            drafterModel === "opus-4.6"
                              ? "bg-white text-violet-700 shadow-sm ring-1 ring-violet-200"
                              : "text-gray-400 hover:text-gray-600"
                          }`}
                        >
                          Opus 4.6
                        </button>
                      </div>
                    </div>
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

      {/* ---- RIGHT: ACTIVITY TIMELINE + SESSION HISTORY ------------------- */}
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

              {/* ── Past Sessions ─────────────────────────── */}
              <div className="border-t border-gray-100 px-4 py-3">
                <div className="flex items-center gap-2 mb-2">
                  <History className="h-3.5 w-3.5 text-gray-400" />
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Past Sessions
                  </span>
                </div>

                {loadingSessions ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 className="h-4 w-4 animate-spin text-gray-300" />
                  </div>
                ) : pastSessions.length === 0 ? (
                  <p className="text-[11px] text-gray-300 py-2">
                    No past sessions saved yet
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {pastSessions.map((s) => {
                      const date = new Date(s.snapshot_at);
                      const isRestoring = restoringSession === s.id;
                      return (
                        <button
                          key={s.id}
                          onClick={() => restoreSession(s.id)}
                          disabled={!!restoringSession}
                          className="flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-violet-50 disabled:opacity-50"
                        >
                          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-50 text-violet-400">
                            {isRestoring ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <RotateCcw className="h-3 w-3" />
                            )}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-gray-600">
                              {date.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                              {" "}
                              {date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                            </p>
                            <p className="mt-0.5 text-[11px] text-gray-400 truncate">
                              {s.message_count} messages · {s.section_names.length} sections
                            </p>
                            <p className="mt-0.5 text-[10px] text-gray-300 truncate">
                              {s.section_names.slice(0, 3).join(", ")}
                              {s.section_names.length > 3 ? ` +${s.section_names.length - 3}` : ""}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Avatar (matches CommentThread style)
// ---------------------------------------------------------------------------

function DrafterAvatar({
  name,
  image,
  icon,
  gradient,
}: {
  name: string;
  image?: string;
  icon?: React.ReactNode;
  gradient?: string;
}) {
  if (icon && gradient) {
    return (
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${gradient} ring-1 ring-gray-200`}
      >
        {icon}
      </div>
    );
  }
  if (image) {
    return (
      <img
        src={image}
        alt=""
        className="h-7 w-7 rounded-full object-cover ring-1 ring-gray-200"
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-600">
      {(name || "?")[0].toUpperCase()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChatBubble — collaboration-style (left-aligned, avatar + name + timestamp)
// ---------------------------------------------------------------------------

function ChatBubble({
  message,
  msgIdx,
  userName,
  userImage,
  onCopy,
  onRegenerate,
  onEditStart,
  onEditSave,
  onEditCancel,
  editingMsgIdx,
  editingMsgContent,
  onEditChange,
  copiedIdx,
  isLastAgent,
  sending,
}: {
  message: ChatMessage;
  msgIdx: number;
  userName: string;
  userImage?: string;
  onCopy: (idx: number) => void;
  onRegenerate: () => void;
  onEditStart: (idx: number) => void;
  onEditSave: (idx: number) => void;
  onEditCancel: () => void;
  editingMsgIdx: number | null;
  editingMsgContent: string;
  onEditChange: (val: string) => void;
  copiedIdx: number | null;
  isLastAgent: boolean;
  sending: boolean;
}) {
  const { role, content, timestamp, metadata } = message;

  // ── System message (centered, compact) ──
  if (role === "system") {
    return (
      <div className="flex justify-center py-1">
        <div className="max-w-lg rounded-xl border border-violet-100 bg-violet-50/60 px-5 py-3 text-center">
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

  // ── Agent message ──
  if (role === "agent") {
    const msgTheme = metadata?.agentTheme
      ? THEME_CONFIG[metadata.agentTheme]
      : null;
    const gradient = msgTheme?.gradient || "from-violet-500 to-purple-600";
    const labelColor = msgTheme?.color || "text-violet-700";
    const agentLabel = metadata?.agentName || "Drafter Agent";

    return (
      <div className="group flex gap-2.5">
        <div className="mt-0.5 shrink-0">
          <DrafterAvatar
            name={agentLabel}
            gradient={gradient}
            icon={<Bot className="h-3.5 w-3.5 text-white" />}
          />
        </div>
        <div className="flex-1 min-w-0">
          {/* Name + timestamp row */}
          <div className="flex items-baseline gap-2">
            <span className={`text-xs font-semibold ${labelColor}`}>
              {agentLabel}
            </span>
            <span className="text-[10px] text-gray-400">
              {formatTime(timestamp)}
            </span>
          </div>

          {/* Content card */}
          <div className="mt-1.5 rounded-lg bg-white p-4 shadow-sm ring-1 ring-gray-100">
            <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-headings:mt-4 prose-headings:mb-2 prose-p:my-2 prose-p:leading-relaxed prose-li:my-0.5 prose-ul:my-2 prose-ol:my-2 prose-strong:text-gray-900 prose-blockquote:border-gray-300 prose-blockquote:text-gray-600 prose-h2:text-base prose-h3:text-sm first:prose-headings:mt-0">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>

            {/* Metadata chips */}
            {metadata && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-gray-100 pt-3">
                {metadata.wordCount != null && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
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
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      metadata.status === "Approved"
                        ? "bg-green-50 text-green-700"
                        : metadata.status === "In Review"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {metadata.status}
                  </span>
                )}
                {metadata.agentTemperature != null && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                    temp {metadata.agentTemperature}
                  </span>
                )}
                {metadata.sourcesUsed && metadata.sourcesUsed.length > 0 &&
                  metadata.sourcesUsed.map((src) => {
                    const srcStyles: Record<string, string> = {
                      company_profile: "bg-violet-50 text-violet-700",
                      knowledge_chunks: "bg-blue-50 text-blue-700",
                      notion_live: "bg-green-50 text-green-700",
                      grant_deep_analysis: "bg-amber-50 text-amber-700",
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
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                          srcStyles[src] || "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {srcLabels[src] || src}
                      </span>
                    );
                  })}
              </div>
            )}

            {/* Evidence gaps */}
            {metadata?.evidenceGaps && metadata.evidenceGaps.length > 0 && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                <div className="mb-1.5 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                  <span className="text-[11px] font-semibold text-amber-700">
                    Evidence Gaps
                  </span>
                </div>
                <ul className="space-y-1">
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

          {/* Agent action bar */}
          <div className="mt-2 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              onClick={() => onCopy(msgIdx)}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
              title="Copy to clipboard"
            >
              {copiedIdx === msgIdx ? (
                <><Check className="h-3 w-3 text-green-500" /> Copied</>
              ) : (
                <><Copy className="h-3 w-3" /> Copy</>
              )}
            </button>
            {isLastAgent && !sending && (
              <button
                onClick={onRegenerate}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                title="Regenerate response"
              >
                <RotateCcw className="h-3 w-3" /> Regenerate
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── User message (left-aligned, same as collaboration) ──
  const isEditingThis = editingMsgIdx === msgIdx;

  return (
    <div className="group flex gap-2.5">
      <div className="mt-0.5 shrink-0">
        <DrafterAvatar name={userName} image={userImage} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-semibold text-gray-800">
            {userName}
            <span className="ml-1 text-[10px] font-normal text-gray-400">
              (you)
            </span>
          </span>
          <span className="text-[10px] text-gray-400">
            {formatTime(timestamp)}
          </span>
        </div>

        {isEditingThis ? (
          <div className="mt-1.5">
            <textarea
              value={editingMsgContent}
              onChange={(e) => onEditChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onEditSave(msgIdx);
                }
                if (e.key === "Escape") onEditCancel();
              }}
              rows={3}
              className="w-full resize-none rounded-lg border border-violet-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:ring-2 focus:ring-violet-200"
              autoFocus
            />
            <div className="mt-1.5 flex items-center gap-2">
              <button
                onClick={() => onEditSave(msgIdx)}
                className="flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700 transition-colors"
              >
                <Send className="h-3 w-3" /> Save & Resend
              </button>
              <button
                onClick={onEditCancel}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 transition-colors"
              >
                Cancel
              </button>
              <span className="text-[10px] text-gray-400">
                This will regenerate the agent response
              </span>
            </div>
          </div>
        ) : (
          <>
            <p className="mt-1 text-sm leading-relaxed text-gray-700 whitespace-pre-wrap">
              {content}
            </p>
            {/* User action bar */}
            <div className="mt-1.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button
                onClick={() => onEditStart(msgIdx)}
                disabled={sending}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors disabled:opacity-40"
                title="Edit message"
              >
                <Pencil className="h-3 w-3" /> Edit
              </button>
              <button
                onClick={() => onCopy(msgIdx)}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                title="Copy text"
              >
                {copiedIdx === msgIdx ? (
                  <><Check className="h-3 w-3 text-green-500" /> Copied</>
                ) : (
                  <><Copy className="h-3 w-3" /> Copy</>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
