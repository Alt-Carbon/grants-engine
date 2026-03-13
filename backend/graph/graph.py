"""LangGraph pipelines — split into Discovery (autonomous) and Drafting (per-grant).

Graph A — Discovery Pipeline (no human interrupts):
  START → scout → company_brain_load → analyst → pre_triage_guardrail → END
  Output: Notion pages with Status="Shortlisted" or "Rejected".
  Humans triage asynchronously in Notion (change status to "Pursue").

Graph B — Drafting Pipeline (per-grant, triggered by Notion status change):
  START → company_brain → grant_reader → draft_guardrail
       → [INTERRUPT: drafter] (loops per section)
       → reviewer → export → END
  Input: notion_page_id for a grant with Status="Pursue".

Legacy: build_graph() still builds the full pipeline for backward compat.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict

from langgraph.graph import END, START, StateGraph

from backend.agents.analyst import analyst_node, notify_triage_node
from backend.agents.company_brain import company_brain_node, company_brain_load_node
from backend.agents.pre_triage_guardrail import pre_triage_guardrail_node
from backend.agents.drafter.drafter_node import drafter_node
from backend.agents.drafter.exporter import exporter_node
from backend.agents.drafter.draft_guardrail import draft_guardrail_node
from backend.agents.drafter.grant_reader import grant_reader_node
from backend.agents.reviewer import reviewer_node
from backend.agents.scout import scout_node
from backend.graph.checkpointer import SqliteCheckpointSaver
from backend.graph.router import route_after_drafter, route_after_guardrail, route_triage
from backend.graph.state import GrantState

logger = logging.getLogger(__name__)


async def human_triage_node(state: GrantState) -> Dict:
    """Placeholder node — graph interrupts BEFORE this node via compile(interrupt_before=[...]).
    When resumed, this node just passes the decision through."""
    return {
        "audit_log": state.get("audit_log", []) + [{
            "node": "human_triage",
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": state.get("human_triage_decision"),
            "grant_id": state.get("selected_grant_id"),
        }]
    }


async def pipeline_update_node(state: GrantState) -> Dict:
    """Update pipeline status for watch/pass/guardrail_rejected decisions."""
    guardrail_result = state.get("draft_guardrail_result")
    if guardrail_result and not guardrail_result.get("passed", True):
        decision = "guardrail_rejected"
    else:
        decision = state.get("human_triage_decision", "pass")

    # Primary: update Notion
    notion_page_id = state.get("selected_notion_page_id")
    if notion_page_id:
        try:
            from backend.integrations.notion_data import update_grant_status
            status_key = "auto_pass" if decision == "guardrail_rejected" else decision
            await update_grant_status(notion_page_id, status_key)
        except Exception as e:
            logger.warning("pipeline_update: Notion update failed for %s: %s", notion_page_id, e)

    # Fallback: update MongoDB
    grant_id = state.get("selected_grant_id")
    if grant_id:
        try:
            from backend.db.mongo import grants_scored
            from bson import ObjectId
            await grants_scored().update_one(
                {"_id": ObjectId(grant_id)},
                {"$set": {"status": decision}},
            )
        except Exception as e:
            logger.warning("pipeline_update: failed to update grant %s: %s", grant_id, e)

    return {
        "audit_log": state.get("audit_log", []) + [{
            "node": "pipeline_update",
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": decision,
        }]
    }


# ── Graph A: Discovery Pipeline (autonomous, no interrupts) ─────────────────

def build_discovery_graph() -> StateGraph:
    """Discovery pipeline: scout → analyst → pre-triage → END.

    Runs autonomously. Output goes to Notion Grant Pipeline.
    Humans triage asynchronously in Notion.
    """
    builder = StateGraph(GrantState)

    builder.add_node("scout", scout_node)
    builder.add_node("company_brain_load", company_brain_load_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("pre_triage_guardrail", pre_triage_guardrail_node)
    builder.add_node("notify_triage", notify_triage_node)

    builder.add_edge(START, "scout")
    builder.add_edge("scout", "company_brain_load")
    builder.add_edge("company_brain_load", "analyst")
    builder.add_edge("analyst", "pre_triage_guardrail")
    builder.add_edge("pre_triage_guardrail", "notify_triage")
    builder.add_edge("notify_triage", END)

    return builder


# ── Graph B: Drafting Pipeline (per-grant, triggered by Notion) ──────────────

def build_drafting_graph() -> StateGraph:
    """Drafting pipeline: company_brain → grant_reader → drafter → reviewer → export.

    Triggered when a grant's status changes to "Pursue" in Notion.
    Still has section-review interrupt for human review of draft sections.
    """
    builder = StateGraph(GrantState)

    builder.add_node("company_brain", company_brain_node)
    builder.add_node("grant_reader", grant_reader_node)
    builder.add_node("draft_guardrail", draft_guardrail_node)
    builder.add_node("drafter", drafter_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("export", exporter_node)
    builder.add_node("pipeline_update", pipeline_update_node)

    builder.add_edge(START, "company_brain")
    builder.add_edge("company_brain", "grant_reader")
    builder.add_edge("grant_reader", "draft_guardrail")

    builder.add_conditional_edges(
        "draft_guardrail",
        route_after_guardrail,
        {
            "drafter": "drafter",
            "pipeline_update": "pipeline_update",
        },
    )

    builder.add_conditional_edges(
        "drafter",
        route_after_drafter,
        {
            "drafter": "drafter",
            "reviewer": "reviewer",
        },
    )

    builder.add_edge("reviewer", "export")
    builder.add_edge("export", END)
    builder.add_edge("pipeline_update", END)

    return builder


# ── Legacy: Full Pipeline (backward compat) ──────────────────────────────────

def build_graph() -> StateGraph:
    """Full pipeline — kept for backward compatibility with existing endpoints."""
    builder = StateGraph(GrantState)

    builder.add_node("scout", scout_node)
    builder.add_node("company_brain_load", company_brain_load_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("pre_triage_guardrail", pre_triage_guardrail_node)
    builder.add_node("notify_triage", notify_triage_node)
    builder.add_node("human_triage", human_triage_node)
    builder.add_node("company_brain", company_brain_node)
    builder.add_node("grant_reader", grant_reader_node)
    builder.add_node("draft_guardrail", draft_guardrail_node)
    builder.add_node("drafter", drafter_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("export", exporter_node)
    builder.add_node("pipeline_update", pipeline_update_node)

    builder.add_edge(START, "scout")
    builder.add_edge("scout", "company_brain_load")
    builder.add_edge("company_brain_load", "analyst")
    builder.add_edge("analyst", "pre_triage_guardrail")
    builder.add_edge("pre_triage_guardrail", "notify_triage")
    builder.add_edge("notify_triage", "human_triage")

    builder.add_conditional_edges(
        "human_triage",
        route_triage,
        {
            "company_brain": "company_brain",
            "pipeline_update": "pipeline_update",
        },
    )

    builder.add_edge("company_brain", "grant_reader")
    builder.add_edge("grant_reader", "draft_guardrail")

    builder.add_conditional_edges(
        "draft_guardrail",
        route_after_guardrail,
        {
            "drafter": "drafter",
            "pipeline_update": "pipeline_update",
        },
    )

    builder.add_conditional_edges(
        "drafter",
        route_after_drafter,
        {
            "drafter": "drafter",
            "reviewer": "reviewer",
        },
    )

    builder.add_edge("reviewer", "export")
    builder.add_edge("export", END)
    builder.add_edge("pipeline_update", END)

    return builder


# ── Compilers ────────────────────────────────────────────────────────────────

def compile_discovery_graph(checkpointer: SqliteCheckpointSaver | None = None):
    """Compile discovery graph — no interrupts, fully autonomous."""
    builder = build_discovery_graph()
    saver = checkpointer or SqliteCheckpointSaver()
    return builder.compile(checkpointer=saver)


def compile_drafting_graph(checkpointer: SqliteCheckpointSaver | None = None):
    """Compile drafting graph — interrupt before drafter for section review."""
    builder = build_drafting_graph()
    saver = checkpointer or SqliteCheckpointSaver()
    return builder.compile(
        checkpointer=saver,
        interrupt_before=["drafter"],
    )


def compile_graph(checkpointer: SqliteCheckpointSaver | None = None):
    """Compile legacy full graph with SQLite checkpointer and interrupt points."""
    builder = build_graph()
    saver = checkpointer or SqliteCheckpointSaver()
    return builder.compile(
        checkpointer=saver,
        interrupt_before=["human_triage", "drafter"],
    )


# ── Singletons ───────────────────────────────────────────────────────────────

_compiled_graph = None
_discovery_graph = None
_drafting_graph = None


def get_graph():
    """Get the legacy full pipeline graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph


def get_discovery_graph():
    """Get the discovery pipeline graph (autonomous, no interrupts)."""
    global _discovery_graph
    if _discovery_graph is None:
        _discovery_graph = compile_discovery_graph()
    return _discovery_graph


def get_drafting_graph():
    """Get the drafting pipeline graph (per-grant, with section review interrupt)."""
    global _drafting_graph
    if _drafting_graph is None:
        _drafting_graph = compile_drafting_graph()
    return _drafting_graph
