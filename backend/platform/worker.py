"""Reusable workflow worker loop."""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from backend.platform.orchestrators import MongoWorkflowOrchestrator


logger = logging.getLogger(__name__)


class WorkflowWorker:
    """Small async worker that continuously drains a durable workflow queue."""

    def __init__(
        self,
        orchestrator: MongoWorkflowOrchestrator,
        *,
        workflow_names: Optional[Iterable[str]] = None,
        batch_size: int = 10,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.orchestrator = orchestrator
        self.workflow_names = list(workflow_names or [])
        self.batch_size = max(1, batch_size)
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> int:
        return await self.orchestrator.drain(
            allowed_workflows=self.workflow_names or None,
            limit=self.batch_size,
        )

    async def run_forever(self) -> None:
        logger.info(
            "Workflow worker started: workflows=%s batch_size=%d poll_interval=%.2fs",
            self.workflow_names or ["*"],
            self.batch_size,
            self.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            processed = await self.run_once()
            if processed > 0:
                logger.debug("Workflow worker processed %d run(s)", processed)
                continue
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue
        logger.info("Workflow worker stopped")
