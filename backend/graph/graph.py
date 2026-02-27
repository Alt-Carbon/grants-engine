"""Full LangGraph grant pipeline.

Graph structure:
  START → scout → analyst → notify_triage
       → [INTERRUPT: human_triage]
       → company_brain → grant_reader
       → [INTERRUPT: drafter] (loops per section)
       → reviewer → export → END

  [watch/pass] → pipeline_update → END
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict

from langgraph.graph import END, START, StateGraph

from backend.agents.analyst import analyst_node, notify_triage_node
from backend.agents.company_brain import company_brain_node
from backend.agents.drafter.drafter_node import drafter_node
from backend.agents.drafter.exporter import exporter_node
from backend.agents.drafter.grant_reader import grant_reader_node
from backend.agents.reviewer import reviewer_node
from backend.agents.scout import scout_node
from backend.graph.checkpointer import MongoCheckpointSaver
from backend.graph.router import route_after_drafter, route_triage
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
    """Update pipeline status for watch/pass decisions."""
    from backend.db.mongo import grants_scored
    grant_id = state.get("selected_grant_id")
    decision = state.get("human_triage_decision", "pass")
    if grant_id:
        try:
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


def build_graph() -> StateGraph:
    """Construct and compile the full LangGraph pipeline."""
    builder = StateGraph(GrantState)

    # ── Add nodes ─────────────────────────────────────────────────────────────
    builder.add_node("scout", scout_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("notify_triage", notify_triage_node)
    builder.add_node("human_triage", human_triage_node)
    builder.add_node("company_brain", company_brain_node)
    builder.add_node("grant_reader", grant_reader_node)
    builder.add_node("drafter", drafter_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("export", exporter_node)
    builder.add_node("pipeline_update", pipeline_update_node)

    # ── Edges ──────────────────────────────────────────────────────────────────
    builder.add_edge(START, "scout")
    builder.add_edge("scout", "analyst")
    builder.add_edge("analyst", "notify_triage")
    builder.add_edge("notify_triage", "human_triage")

    # Gate 1: triage decision routes to either company_brain or pipeline_update
    builder.add_conditional_edges(
        "human_triage",
        route_triage,
        {
            "company_brain": "company_brain",
            "pipeline_update": "pipeline_update",
        },
    )

    builder.add_edge("company_brain", "grant_reader")
    builder.add_edge("grant_reader", "drafter")

    # Gate 2: drafter loops until all sections approved, then goes to reviewer
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


def compile_graph(checkpointer: MongoCheckpointSaver | None = None):
    """Compile graph with MongoDB checkpointer and interrupt points."""
    builder = build_graph()
    saver = checkpointer or MongoCheckpointSaver()

    return builder.compile(
        checkpointer=saver,
        interrupt_before=["human_triage", "drafter"],
    )


# Singleton — reuse across requests
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph
