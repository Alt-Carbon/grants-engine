"""Workflow blueprint for the grants engine.

This does not replace the current runtime yet. It is the typed blueprint that
the reusable platform can target as the backend is migrated away from the
current monolithic orchestration paths.
"""
from __future__ import annotations

from backend.platform.contracts import StepKind, WorkflowDefinition, WorkflowStep


GRANTS_PIPELINE_WORKFLOW = WorkflowDefinition(
    name="grants_pipeline",
    project="grants_engine",
    version="v1",
    description="Scout, score, triage, draft, review, and track grant opportunities.",
    entrypoint="scout_discovery",
    steps=[
        WorkflowStep(
            id="scout_discovery",
            kind=StepKind.AGENT,
            target="scout",
            description="Discover and normalize grant opportunities.",
            next_steps=["analysis"],
        ),
        WorkflowStep(
            id="analysis",
            kind=StepKind.AGENT,
            target="analyst",
            description="Score the opportunity and identify blockers or hold conditions.",
            next_steps=["triage_review"],
            checkpoint=True,
        ),
        WorkflowStep(
            id="triage_review",
            kind=StepKind.HUMAN,
            target="triage_decision",
            description="Human chooses pursue, hold, or reject.",
            next_steps=["context_prep"],
            checkpoint=True,
        ),
        WorkflowStep(
            id="context_prep",
            kind=StepKind.AGENT,
            target="company_brain",
            description="Load company context and grant requirements before drafting.",
            next_steps=["draft_guardrail"],
        ),
        WorkflowStep(
            id="draft_guardrail",
            kind=StepKind.SERVICE,
            target="draft_guardrail",
            description="Validate eligibility and readiness before drafting starts.",
            next_steps=["draft_sections"],
        ),
        WorkflowStep(
            id="draft_sections",
            kind=StepKind.AGENT,
            target="drafter",
            description="Draft sections with human review checkpoints.",
            next_steps=["review_bundle"],
            checkpoint=True,
        ),
        WorkflowStep(
            id="review_bundle",
            kind=StepKind.AGENT,
            target="reviewer",
            description="Review the completed draft for alignment, rigor, and quality.",
            next_steps=["finalize_submission"],
        ),
        WorkflowStep(
            id="finalize_submission",
            kind=StepKind.HUMAN,
            target="submission_tracking",
            description="Human confirms external submission and tracks outcome.",
            checkpoint=True,
        ),
    ],
    metadata={
        "current_runtime": "fastapi_background_tasks + langgraph",
        "target_runtime": "durable_workflow_engine",
        "human_checkpoints": [
            "triage_review",
            "draft_sections",
            "finalize_submission",
        ],
    },
)
