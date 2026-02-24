"""MongoDB-backed LangGraph checkpointer.

LangGraph doesn't ship a MongoDB saver natively, so we implement one using
the BaseCheckpointSaver interface. State is stored in the `graph_checkpoints`
collection keyed by (thread_id, checkpoint_id).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from backend.db.mongo import graph_checkpoints


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoCheckpointSaver(BaseCheckpointSaver):
    """Async MongoDB checkpoint saver for LangGraph."""

    def _get_thread_id(self, config: RunnableConfig) -> str:
        return config["configurable"]["thread_id"]

    def _checkpoint_id(self, config: RunnableConfig) -> Optional[str]:
        return config["configurable"].get("checkpoint_id")

    # ── Sync interface (required by base class) ────────────────────────────────

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        raise NotImplementedError("Use async interface")

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use async interface")

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        raise NotImplementedError("Use async interface")

    # ── Async interface ────────────────────────────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._checkpoint_id(config)

        col = graph_checkpoints()
        query: Dict[str, Any] = {"thread_id": thread_id}
        if checkpoint_id:
            query["checkpoint_id"] = checkpoint_id
            doc = await col.find_one(query)
        else:
            doc = await col.find_one(query, sort=[("checkpoint_id", -1)])

        if not doc:
            return None

        checkpoint = json.loads(doc["checkpoint"])
        metadata = json.loads(doc.get("metadata", "{}"))
        parent_id = doc.get("parent_checkpoint_id")

        result_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": doc["checkpoint_id"],
            }
        }
        parent_config = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": parent_id,
                }
            }
            if parent_id
            else None
        )
        return CheckpointTuple(
            config=result_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
        )

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if not config:
            return
        thread_id = self._get_thread_id(config)
        query: Dict[str, Any] = {"thread_id": thread_id}
        if filter:
            for k, v in filter.items():
                query[f"metadata.{k}"] = v

        col = graph_checkpoints()
        cursor = col.find(query, sort=[("checkpoint_id", -1)])
        if limit:
            cursor = cursor.limit(limit)

        async for doc in cursor:
            checkpoint = json.loads(doc["checkpoint"])
            metadata = json.loads(doc.get("metadata", "{}"))
            parent_id = doc.get("parent_checkpoint_id")
            result_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": doc["checkpoint_id"],
                }
            }
            parent_config = (
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": parent_id,
                    }
                }
                if parent_id
                else None
            )
            yield CheckpointTuple(
                config=result_config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        thread_id = self._get_thread_id(config)
        checkpoint_id = checkpoint["id"]
        parent_id = self._checkpoint_id(config)

        col = graph_checkpoints()
        await col.update_one(
            {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
            {
                "$set": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "parent_checkpoint_id": parent_id,
                    "checkpoint": json.dumps(checkpoint),
                    "metadata": json.dumps(dict(metadata)),
                    "saved_at": _utcnow(),
                }
            },
            upsert=True,
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        # Pending writes — store alongside checkpoint for debugging
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._checkpoint_id(config)
        col = graph_checkpoints()
        await col.update_one(
            {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
            {
                "$set": {
                    f"pending_writes.{task_id}": [
                        {"channel": c, "value": json.dumps(v)} for c, v in writes
                    ]
                }
            },
        )
