"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  DragDropContext,
  Droppable,
  Draggable,
  type DropResult,
  type DragStart,
  type DragUpdate,
} from "@hello-pangea/dnd";
import { GrantCard } from "./GrantCard";
import { GrantDetailSheet } from "./GrantDetailSheet";
import { useLastSeen, isNewSince } from "@/hooks/useLastSeen";
import { useGrantUrl } from "@/hooks/useGrantUrl";
import type { Grant } from "@/lib/queries";

const COLUMNS = [
  {
    id: "shortlisted",
    label: "Shortlisted",
    targetStatus: "triage",
    color: "amber",
    headerCls: "border-amber-300 bg-amber-50",
    countCls: "bg-amber-100 text-amber-800",
    dropHighlight: "bg-amber-50/80 ring-2 ring-inset ring-amber-300",
    barIdle: "border-amber-200 bg-amber-50 text-amber-700",
    barOver: "border-amber-400 bg-amber-100 text-amber-900 scale-105 shadow-md",
  },
  {
    id: "pursue",
    label: "Pursue",
    targetStatus: "pursue",
    color: "green",
    headerCls: "border-green-300 bg-green-50",
    countCls: "bg-green-100 text-green-800",
    dropHighlight: "bg-green-50/80 ring-2 ring-inset ring-green-300",
    barIdle: "border-green-200 bg-green-50 text-green-700",
    barOver: "border-green-400 bg-green-100 text-green-900 scale-105 shadow-md",
  },
  {
    id: "hold",
    label: "Hold",
    targetStatus: "hold",
    color: "orange",
    headerCls: "border-orange-300 bg-orange-50",
    countCls: "bg-orange-100 text-orange-800",
    dropHighlight: "bg-orange-50/80 ring-2 ring-inset ring-orange-300",
    barIdle: "border-orange-200 bg-orange-50 text-orange-700",
    barOver: "border-orange-400 bg-orange-100 text-orange-900 scale-105 shadow-md",
  },
  {
    id: "drafting",
    label: "Drafting",
    targetStatus: "drafting",
    color: "purple",
    headerCls: "border-purple-300 bg-purple-50",
    countCls: "bg-purple-100 text-purple-800",
    dropHighlight: "bg-purple-50/80 ring-2 ring-inset ring-purple-300",
    barIdle: "border-purple-200 bg-purple-50 text-purple-700",
    barOver: "border-purple-400 bg-purple-100 text-purple-900 scale-105 shadow-md",
  },
  {
    id: "submitted",
    label: "Submitted",
    targetStatus: "submitted",
    color: "cyan",
    headerCls: "border-cyan-300 bg-cyan-50",
    countCls: "bg-cyan-100 text-cyan-800",
    dropHighlight: "bg-cyan-50/80 ring-2 ring-inset ring-cyan-300",
    barIdle: "border-cyan-200 bg-cyan-50 text-cyan-700",
    barOver: "border-cyan-400 bg-cyan-100 text-cyan-900 scale-105 shadow-md",
  },
  {
    id: "rejected",
    label: "Rejected",
    targetStatus: "human_passed",
    color: "red",
    headerCls: "border-red-300 bg-red-50",
    countCls: "bg-red-100 text-red-600",
    dropHighlight: "bg-red-50/80 ring-2 ring-inset ring-red-300",
    barIdle: "border-red-200 bg-red-50 text-red-600",
    barOver: "border-red-400 bg-red-100 text-red-900 scale-105 shadow-md",
  },
] as const;

type ColumnId = (typeof COLUMNS)[number]["id"];

function statusToColumn(status: string): ColumnId {
  if (status === "triage") return "shortlisted";
  if (status === "pursue" || status === "pursuing") return "pursue";
  if (status === "hold") return "hold";
  if (status === "drafting") return "drafting";
  if (
    status === "submitted" ||
    status === "draft_complete" ||
    status === "won"
  )
    return "submitted";
  return "rejected";
}

// ── Auto-scroll ─────────────────────────────────────────────────────────────
const EDGE_ZONE = 120;
const MAX_SPEED = 25;

function autoScroll(container: HTMLElement, clientX: number) {
  const rect = container.getBoundingClientRect();
  if (clientX < rect.left + EDGE_ZONE && container.scrollLeft > 0) {
    const p = Math.max(0, 1 - (clientX - rect.left) / EDGE_ZONE);
    container.scrollLeft -= Math.ceil(MAX_SPEED * p * p);
  } else if (
    clientX > rect.right - EDGE_ZONE &&
    container.scrollLeft < container.scrollWidth - container.clientWidth
  ) {
    const p = Math.max(0, 1 - (rect.right - clientX) / EDGE_ZONE);
    container.scrollLeft += Math.ceil(MAX_SPEED * p * p);
  }
}

// ─────────────────────────────────────────────────────────────────────────────

interface PipelineBoardProps {
  initialGrants: Record<string, Grant[]>;
}

export function PipelineBoard({ initialGrants }: PipelineBoardProps) {
  const router = useRouter();
  const [grants, setGrants] = useState<Record<string, Grant[]>>(initialGrants);

  // Sync with filtered grants from parent (search/filter changes)
  useEffect(() => {
    setGrants(initialGrants);
  }, [initialGrants]);
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [selectedGrantId, setSelectedGrantId] = useGrantUrl();
  const [isDragging, setIsDragging] = useState(false);
  const [dragSourceCol, setDragSourceCol] = useState<ColumnId | null>(null);
  const { lastSeenAt } = useLastSeen();

  const scrollRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const pointerXRef = useRef<number>(0);

  // Auto-scroll during drag
  useEffect(() => {
    if (!isDragging) return;

    function trackPointer(e: MouseEvent | PointerEvent | TouchEvent) {
      const x = "clientX" in e ? e.clientX : e.touches?.[0]?.clientX ?? 0;
      pointerXRef.current = x;
    }

    function tick() {
      const container = scrollRef.current;
      if (container && pointerXRef.current > 0) {
        autoScroll(container, pointerXRef.current);
      }
      rafRef.current = requestAnimationFrame(tick);
    }

    window.addEventListener("mousemove", trackPointer, { capture: true });
    window.addEventListener("pointermove", trackPointer, { capture: true });
    window.addEventListener("touchmove", trackPointer, { capture: true });
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("mousemove", trackPointer, { capture: true });
      window.removeEventListener("pointermove", trackPointer, { capture: true });
      window.removeEventListener("touchmove", trackPointer, { capture: true });
      cancelAnimationFrame(rafRef.current);
      pointerXRef.current = 0;
    };
  }, [isDragging]);

  const markUpdating = useCallback((id: string, on: boolean) => {
    setUpdatingIds((prev) => {
      const next = new Set(prev);
      on ? next.add(id) : next.delete(id);
      return next;
    });
  }, []);

  async function persistStatus(grantId: string, newStatus: string) {
    const res = await fetch("/api/grants/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant_id: grantId, status: newStatus }),
    });
    if (!res.ok) throw new Error(await res.text());
  }

  async function updateStatus(
    grantId: string,
    newStatus: string,
    srcColId?: ColumnId
  ) {
    markUpdating(grantId, true);
    setError(null);

    if (!srcColId) {
      for (const col of COLUMNS) {
        if (grants[col.id]?.some((g) => g._id === grantId)) {
          srcColId = col.id;
          break;
        }
      }
    }
    const dstColId = statusToColumn(newStatus);
    const snapshot = { ...grants };

    if (srcColId && srcColId !== dstColId) {
      setGrants((prev) => {
        const srcList = (prev[srcColId!] ?? []).filter(
          (g) => g._id !== grantId
        );
        const movedGrant = (prev[srcColId!] ?? []).find(
          (g) => g._id === grantId
        );
        if (!movedGrant) return prev;
        const dstList = [
          ...(prev[dstColId] ?? []),
          { ...movedGrant, status: newStatus },
        ];
        return { ...prev, [srcColId!]: srcList, [dstColId]: dstList };
      });
    }

    try {
      await persistStatus(grantId, newStatus);
    } catch (e) {
      setGrants(snapshot);
      setError(
        `Failed to update: ${e instanceof Error ? e.message : "unknown"}`
      );
    } finally {
      markUpdating(grantId, false);
    }
  }

  // ── Drag & drop ───────────────────────────────────────────────────────────

  const didDragRef = useRef(false);

  function onDragStart(start: DragStart) {
    setIsDragging(true);
    didDragRef.current = false;
    setDragSourceCol(start.source.droppableId as ColumnId);
  }

  function onDragUpdate(update: DragUpdate) {
    didDragRef.current = true;
  }

  /** Shared move logic for both column drops and quick-bar drops */
  async function moveCard(
    draggableId: string,
    srcId: ColumnId,
    dstId: ColumnId,
    dstIndex: number
  ) {
    const column = COLUMNS.find((c) => c.id === dstId);
    if (!column) return;

    const srcList = [...(grants[srcId] ?? [])];
    const dstList = [...(grants[dstId] ?? [])];
    const srcIndex = srcList.findIndex((g) => g._id === draggableId);
    if (srcIndex < 0) return;

    const [moved] = srcList.splice(srcIndex, 1);
    const updatedGrant = { ...moved, status: column.targetStatus };
    dstList.splice(dstIndex, 0, updatedGrant);

    const snapshot = { ...grants };
    setGrants((prev) => ({ ...prev, [srcId]: srcList, [dstId]: dstList }));
    markUpdating(draggableId, true);
    setError(null);

    try {
      await persistStatus(draggableId, column.targetStatus);

      // If moved to Drafting → trigger start-draft and navigate to drafter
      if (dstId === "drafting") {
        try {
          await fetch("/api/drafter/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ grant_id: draggableId }),
          });
        } catch {
          // Draft trigger failed — still allow the status change
        }
        router.push("/drafter");
      }
    } catch (e) {
      setGrants(snapshot);
      setError(
        `Failed to update status: ${e instanceof Error ? e.message : "unknown error"}`
      );
    } finally {
      markUpdating(draggableId, false);
    }
  }

  async function onDragEnd(result: DropResult) {
    setIsDragging(false);
    setDragSourceCol(null);
    const { source, destination, draggableId } = result;
    if (!destination) return;

    const srcId = source.droppableId as ColumnId;
    let dstId = destination.droppableId as string;

    // Quick-bar drop targets have id "bar-{columnId}"
    if (dstId.startsWith("bar-")) {
      dstId = dstId.replace("bar-", "") as ColumnId;
      if (srcId === dstId) return;
      await moveCard(draggableId, srcId, dstId as ColumnId, 0);
      return;
    }

    const dstColId = dstId as ColumnId;

    // Same column reorder
    if (srcId === dstColId) {
      if (source.index === destination.index) return;
      setGrants((prev) => {
        const list = [...(prev[srcId] ?? [])];
        const [moved] = list.splice(source.index, 1);
        list.splice(destination.index, 0, moved);
        return { ...prev, [srcId]: list };
      });
      return;
    }

    // Cross-column move
    await moveCard(draggableId, srcId, dstColId, destination.index);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col gap-2">
      {error && (
        <div className="flex items-center justify-between rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="ml-3 text-red-400 hover:text-red-600"
          >
            &times;
          </button>
        </div>
      )}

      <DragDropContext
        onDragStart={onDragStart}
        onDragUpdate={onDragUpdate}
        onDragEnd={onDragEnd}
      >
        {/* ── Quick-drop bar — visible only during drag ──────────────── */}
        <div
          className={`grid grid-cols-5 gap-2 overflow-hidden transition-all duration-200 ${
            isDragging
              ? "max-h-16 opacity-100"
              : "pointer-events-none max-h-0 opacity-0"
          }`}
        >
          {COLUMNS.map((col) => {
            const isSrc = col.id === dragSourceCol;
            return (
              <Droppable key={`bar-${col.id}`} droppableId={`bar-${col.id}`}>
                {(provided, snapshot) => (
                  <div
                    ref={provided.innerRef}
                    {...provided.droppableProps}
                    className={`flex items-center justify-center rounded-lg border-2 border-dashed px-2 py-2.5 text-center text-xs font-semibold transition-all duration-150 ${
                      isSrc
                        ? "border-gray-200 bg-gray-50 text-gray-400"
                        : snapshot.isDraggingOver
                        ? col.barOver
                        : col.barIdle
                    }`}
                  >
                    {col.label}
                    {/* Hidden placeholder so DnD doesn't complain */}
                    <div className="hidden">{provided.placeholder}</div>
                  </div>
                )}
              </Droppable>
            );
          })}
        </div>

        {isDragging && (
          <p className="text-center text-[11px] text-gray-400">
            Drop on a label above to move directly to any column
          </p>
        )}

        {/* ── Kanban columns ─────────────────────────────────────────── */}
        <div ref={scrollRef} className="flex gap-3 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const colGrants = grants[col.id] ?? [];
            return (
              <div
                key={col.id}
                className={`flex w-72 shrink-0 flex-col rounded-xl border-2 ${col.headerCls}`}
                style={{ maxHeight: "calc(100vh - 260px)" }}
              >
                {/* Column header */}
                <div className="flex items-center justify-between px-3 py-2.5">
                  <span className="text-sm font-semibold text-gray-700">
                    {col.label}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${col.countCls}`}
                  >
                    {colGrants.length}
                  </span>
                </div>

                {/* Droppable card area */}
                <Droppable droppableId={col.id}>
                  {(provided, snapshot) => (
                    <div
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                      className={`flex min-h-[8rem] flex-1 flex-col gap-2 overflow-y-auto rounded-b-lg px-2 pb-2 transition-all duration-150 ${
                        snapshot.isDraggingOver ? col.dropHighlight : ""
                      }`}
                    >
                      {colGrants.map((grant, index) => (
                        <Draggable
                          key={grant._id}
                          draggableId={grant._id}
                          index={index}
                        >
                          {(dragProvided, dragSnapshot) => (
                            <div
                              ref={dragProvided.innerRef}
                              {...dragProvided.draggableProps}
                              {...dragProvided.dragHandleProps}
                              className={`cursor-grab rounded-lg transition-shadow duration-150 active:cursor-grabbing ${
                                dragSnapshot.isDragging
                                  ? "z-50 scale-[1.02] shadow-2xl ring-2 ring-indigo-400"
                                  : "hover:shadow-md"
                              } ${updatingIds.has(grant._id) ? "opacity-60" : ""}`}
                              onClick={() => {
                                if (!didDragRef.current) {
                                  setSelectedGrantId(grant._id);
                                }
                                didDragRef.current = false;
                              }}
                            >
                              <GrantCard
                                grant={grant}
                                compact
                                isNew={isNewSince(grant.scored_at || grant.scraped_at, lastSeenAt)}
                                onStatusChange={(grantId, newStatus) =>
                                  updateStatus(grantId, newStatus, col.id)
                                }
                              />
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                      {colGrants.length === 0 && !snapshot.isDraggingOver && (
                        <div className="flex flex-1 items-center justify-center">
                          <p className="text-xs text-gray-400">
                            Drag cards here
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </Droppable>
              </div>
            );
          })}
        </div>
      </DragDropContext>

      <GrantDetailSheet
        grantId={selectedGrantId}
        onClose={() => setSelectedGrantId(null)}
      />
    </div>
  );
}
