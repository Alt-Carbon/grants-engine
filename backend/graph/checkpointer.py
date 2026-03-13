"""SQLite-backed LangGraph checkpointer.

Replaces MongoCheckpointSaver. Uses aiosqlite directly since
langgraph-checkpoint-sqlite may not be installed. Same BaseCheckpointSaver
interface, backed by a table in the shared SQLite database.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles non-serializable types (e.g. bson.ObjectId)."""
    def default(self, o: Any) -> Any:
        try:
            return str(o)
        except Exception:
            return super().default(o)


def _safe_dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_SafeEncoder)
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Sequence, Tuple

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    pending_writes TEXT DEFAULT '{}',
    saved_at TEXT,
    PRIMARY KEY (thread_id, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_gc_thread ON graph_checkpoints(thread_id, checkpoint_id DESC);
"""


class SqliteCheckpointSaver(BaseCheckpointSaver):
    """Async SQLite checkpoint saver for LangGraph."""

    def __init__(self, db_path: str | None = None):
        super().__init__()
        if db_path is None:
            from backend.db.sqlite import get_db_path
            db_path = get_db_path()
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(_CREATE_TABLE)
        return self._conn

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
        conn = await self._get_conn()
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._checkpoint_id(config)

        if checkpoint_id:
            rows = await conn.execute_fetchall(
                "SELECT * FROM graph_checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
                (thread_id, checkpoint_id),
            )
        else:
            rows = await conn.execute_fetchall(
                "SELECT * FROM graph_checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC LIMIT 1",
                (thread_id,),
            )

        if not rows:
            return None

        doc = dict(rows[0])
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

        conn = await self._get_conn()
        thread_id = self._get_thread_id(config)

        query = "SELECT * FROM graph_checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC"
        params: list = [thread_id]
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = await conn.execute_fetchall(query, params)
        for row in rows:
            doc = dict(row)
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
        conn = await self._get_conn()
        thread_id = self._get_thread_id(config)
        checkpoint_id = checkpoint["id"]
        parent_id = self._checkpoint_id(config)

        await conn.execute(
            """INSERT OR REPLACE INTO graph_checkpoints
               (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint, metadata, saved_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                thread_id,
                checkpoint_id,
                parent_id,
                _safe_dumps(checkpoint),
                _safe_dumps(dict(metadata)),
                _utcnow(),
            ),
        )
        await conn.commit()
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
        conn = await self._get_conn()
        thread_id = self._get_thread_id(config)
        checkpoint_id = self._checkpoint_id(config)
        writes_data = _safe_dumps({
            task_id: [{"channel": c, "value": _safe_dumps(v)} for c, v in writes]
        })
        await conn.execute(
            """UPDATE graph_checkpoints SET pending_writes = ?
               WHERE thread_id = ? AND checkpoint_id = ?""",
            (writes_data, thread_id, checkpoint_id),
        )
        await conn.commit()
