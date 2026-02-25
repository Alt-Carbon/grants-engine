"use client";

import { useState, useRef } from "react";
import { DragDropContext, Droppable, Draggable, type DropResult } from "@hello-pangea/dnd";
import { GrantCard } from "./GrantCard";
import { GrantDetailSheet } from "./GrantDetailSheet";
import type { Grant } from "@/lib/queries";

const COLUMNS = [
  {
    id: "triage",
    label: "Triage",
    targetStatus: "triage",
    headerCls: "border-amber-300 bg-amber-50",
    countCls: "bg-amber-100 text-amber-800",
  },
  {
    id: "pursue",
    label: "Pursue",
    targetStatus: "pursue",
    headerCls: "border-green-300 bg-green-50",
    countCls: "bg-green-100 text-green-800",
  },
  {
    id: "watch",
    label: "Watch",
    targetStatus: "watch",
    headerCls: "border-blue-300 bg-blue-50",
    countCls: "bg-blue-100 text-blue-800",
  },
  {
    id: "drafting",
    label: "Drafting",
    targetStatus: "drafting",
    headerCls: "border-purple-300 bg-purple-50",
    countCls: "bg-purple-100 text-purple-800",
  },
  {
    id: "complete",
    label: "Complete",
    targetStatus: "draft_complete",
    headerCls: "border-indigo-300 bg-indigo-50",
    countCls: "bg-indigo-100 text-indigo-800",
  },
] as const;

type ColumnId = (typeof COLUMNS)[number]["id"];

interface PipelineBoardProps {
  initialGrants: Record<string, Grant[]>;
}

export function PipelineBoard({ initialGrants }: PipelineBoardProps) {
  const [grants, setGrants] = useState<Record<string, Grant[]>>(initialGrants);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedGrantId, setSelectedGrantId] = useState<string | null>(null);

  // Track mousedown position to distinguish click vs drag
  const mouseDownPos = useRef<{ x: number; y: number } | null>(null);

  async function onDragEnd(result: DropResult) {
    const { source, destination, draggableId } = result;
    if (!destination || destination.droppableId === source.droppableId) return;

    const srcId = source.droppableId as ColumnId;
    const dstId = destination.droppableId as ColumnId;
    const column = COLUMNS.find((c) => c.id === dstId);
    if (!column) return;

    // Optimistic update
    const srcList = [...(grants[srcId] ?? [])];
    const dstList = [...(grants[dstId] ?? [])];
    const [moved] = srcList.splice(source.index, 1);
    dstList.splice(destination.index, 0, { ...moved, status: column.targetStatus });
    setGrants((prev) => ({ ...prev, [srcId]: srcList, [dstId]: dstList }));
    setUpdatingId(draggableId);
    setError(null);

    try {
      const res = await fetch("/api/grants/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grant_id: draggableId, status: column.targetStatus }),
      });
      if (!res.ok) throw new Error(await res.text());
    } catch (e) {
      // Revert
      const revertSrc = [...srcList.slice(0, source.index), moved, ...srcList.slice(source.index)];
      const revertDst = dstList.filter((g) => g._id !== draggableId);
      setGrants((prev) => ({ ...prev, [srcId]: revertSrc, [dstId]: revertDst }));
      setError(`Failed to update status: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setUpdatingId(null);
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      <DragDropContext onDragEnd={onDragEnd}>
        <div className="flex gap-4 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const colGrants = grants[col.id] ?? [];
            return (
              <div
                key={col.id}
                className={`flex w-64 shrink-0 flex-col rounded-xl border-2 ${col.headerCls} p-3`}
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-700">{col.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${col.countCls}`}
                  >
                    {colGrants.length}
                  </span>
                </div>
                <Droppable droppableId={col.id}>
                  {(provided, snapshot) => (
                    <div
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                      className={`flex min-h-[4rem] flex-col gap-2 rounded-lg transition-colors ${
                        snapshot.isDraggingOver ? "bg-white/60" : ""
                      }`}
                    >
                      {colGrants.map((grant, index) => (
                        <Draggable key={grant._id} draggableId={grant._id} index={index}>
                          {(provided, snapshot) => (
                            <div
                              ref={provided.innerRef}
                              {...provided.draggableProps}
                              {...provided.dragHandleProps}
                              className={`transition-all ${
                                snapshot.isDragging ? "rotate-1 opacity-80 shadow-xl" : ""
                              } ${updatingId === grant._id ? "opacity-40" : ""}`}
                              onMouseDown={(e) => {
                                mouseDownPos.current = { x: e.clientX, y: e.clientY };
                              }}
                              onClick={(e) => {
                                const pos = mouseDownPos.current;
                                if (pos) {
                                  const dx = Math.abs(e.clientX - pos.x);
                                  const dy = Math.abs(e.clientY - pos.y);
                                  // Only treat as click if mouse barely moved (not a drag)
                                  if (dx < 5 && dy < 5) {
                                    setSelectedGrantId(grant._id);
                                  }
                                }
                                mouseDownPos.current = null;
                              }}
                            >
                              <GrantCard grant={grant} compact />
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                      {colGrants.length === 0 && !snapshot.isDraggingOver && (
                        <p className="py-4 text-center text-xs text-gray-400">
                          Drop here
                        </p>
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
