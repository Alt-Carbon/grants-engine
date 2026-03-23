"""Shared pipeline status contract loaded from the repo-level JSON file."""
from __future__ import annotations

import json
from pathlib import Path


_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "shared" / "pipeline_status_contract.json"


def load_status_contract() -> dict:
    with _CONTRACT_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def valid_statuses() -> set[str]:
    return set(load_status_contract()["statuses"])


def human_editable_statuses() -> set[str]:
    return set(load_status_contract()["human_editable_statuses"])


def pre_draft_cleanup_statuses() -> set[str]:
    return set(load_status_contract()["pre_draft_cleanup_statuses"])


def draft_startable_statuses() -> set[str]:
    return set(load_status_contract()["draft_startable_statuses"])


def allowed_transitions() -> dict[str, set[str]]:
    contract = load_status_contract()
    return {
        status: set(next_statuses)
        for status, next_statuses in contract["transitions"].items()
    }


def is_valid_transition(current_status: str | None, next_status: str) -> bool:
    if next_status not in valid_statuses():
        return False
    if not current_status or current_status == next_status:
        return True
    return next_status in allowed_transitions().get(current_status, set())
