"""Run a dedicated durable-workflow worker for the grants platform."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from backend.platform.worker import WorkflowWorker
from backend.projects.grants_engine.workflow_runtime import get_grants_orchestrator


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _main(args: argparse.Namespace) -> None:
    orchestrator = get_grants_orchestrator()
    worker = WorkflowWorker(
        orchestrator,
        workflow_names=args.workflow,
        batch_size=args.batch_size,
        poll_interval_seconds=args.poll_interval,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            pass

    await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the grants durable workflow worker")
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="Optional workflow name filter. Can be passed multiple times.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Maximum number of runs to process per drain batch.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Sleep interval in seconds when the queue is empty.",
    )
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
