"""SQLite backend for agent state, caches, and metadata.

Replaces MongoDB for all internal state. Grants live in Notion (primary).
SQLite is for: checkpoints, knowledge metadata, caches, agent config, chat history.

File: backend/data/grants_engine.db (auto-created, .gitignored)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

log = logging.getLogger(__name__)

# ── Database path ────────────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_DB_PATH = os.path.join(_DB_DIR, "grants_engine.db")


def get_db_path() -> str:
    """Return the SQLite database file path."""
    from backend.config.settings import get_settings
    path = getattr(get_settings(), "sqlite_db_path", "") or ""
    return path if path else _DB_PATH


# ── Connection pool ──────────────────────────────────────────────────────────

_conn: aiosqlite.Connection | None = None


async def get_conn() -> aiosqlite.Connection:
    """Get or create the singleton SQLite connection."""
    global _conn
    if _conn is None:
        db_path = get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _conn = await aiosqlite.connect(db_path)
        _conn.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent read performance
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
        await ensure_tables(_conn)
    return _conn


async def close_conn() -> None:
    """Close the SQLite connection. Call during shutdown."""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
        log.info("SQLite connection closed")


# ── Schema ───────────────────────────────────────────────────────────────────

async def ensure_tables(conn: aiosqlite.Connection) -> None:
    """Create all tables if they don't exist."""
    await conn.executescript("""
        -- Knowledge chunk metadata (vectors stay in Pinecone)
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            doc_type TEXT DEFAULT 'notion',
            source_title TEXT DEFAULT '',
            content TEXT DEFAULT '',
            content_hash TEXT DEFAULT '',
            themes TEXT DEFAULT '[]',
            last_synced TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            UNIQUE(source_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_kc_source ON knowledge_chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_kc_doc_type ON knowledge_chunks(doc_type);
        CREATE INDEX IF NOT EXISTS idx_kc_content_hash ON knowledge_chunks(content_hash);
        CREATE INDEX IF NOT EXISTS idx_kc_last_synced ON knowledge_chunks(last_synced);

        -- Knowledge sync logs
        CREATE TABLE IF NOT EXISTS knowledge_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            action TEXT,
            chunks_upserted INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Agent configuration (3 rows: scout, analyst, drafter)
        CREATE TABLE IF NOT EXISTS agent_config (
            agent TEXT PRIMARY KEY,
            config_json TEXT DEFAULT '{}',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Funder context cache (7-day TTL)
        CREATE TABLE IF NOT EXISTS funder_context_cache (
            funder TEXT PRIMARY KEY,
            context TEXT DEFAULT '',
            cached_at TEXT DEFAULT (datetime('now'))
        );

        -- Deep research cache (7-day TTL)
        CREATE TABLE IF NOT EXISTS deep_research_cache (
            url_hash TEXT PRIMARY KEY,
            research_json TEXT DEFAULT '{}',
            cached_at TEXT DEFAULT (datetime('now'))
        );

        -- Notion page content cache (24h TTL)
        CREATE TABLE IF NOT EXISTS notion_page_cache (
            source_id TEXT PRIMARY KEY,
            content TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            cached_at TEXT DEFAULT (datetime('now'))
        );

        -- Drafter chat history
        CREATE TABLE IF NOT EXISTS drafter_chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            user_email TEXT NOT NULL DEFAULT 'default',
            section_name TEXT DEFAULT '',
            messages_json TEXT DEFAULT '[]',
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(pipeline_id, user_email)
        );

        -- Notion write queue (retry failed writes)
        CREATE TABLE IF NOT EXISTS notion_write_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            retries INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 5,
            last_error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            next_retry_at TEXT DEFAULT (datetime('now'))
        );

        -- Audit logs
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node TEXT DEFAULT '',
            action TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_node ON audit_logs(node);

        -- Scout runs
        CREATE TABLE IF NOT EXISTS scout_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_json TEXT DEFAULT '{}',
            run_at TEXT DEFAULT (datetime('now'))
        );

        -- Notifications (30-day retention)
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT DEFAULT '',
            type TEXT DEFAULT '',
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            action_url TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_email, read, created_at);
        CREATE INDEX IF NOT EXISTS idx_notif_type ON notifications(type, created_at);

        -- Grant comments
        CREATE TABLE IF NOT EXISTS grant_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grant_id TEXT NOT NULL,
            user_email TEXT DEFAULT '',
            user_name TEXT DEFAULT '',
            text TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_comments_grant ON grant_comments(grant_id);
    """)
    await conn.commit()
    log.info("SQLite tables ensured at %s", get_db_path())


# ── Helper: TTL cleanup ─────────────────────────────────────────────────────

async def cleanup_expired() -> None:
    """Remove expired cache entries. Call periodically (e.g. daily)."""
    conn = await get_conn()
    now = datetime.now(timezone.utc).isoformat()

    # 7-day TTL for funder_context_cache
    await conn.execute(
        "DELETE FROM funder_context_cache WHERE datetime(cached_at, '+7 days') < datetime(?)",
        (now,),
    )
    # 7-day TTL for deep_research_cache
    await conn.execute(
        "DELETE FROM deep_research_cache WHERE datetime(cached_at, '+7 days') < datetime(?)",
        (now,),
    )
    # 24h TTL for notion_page_cache
    await conn.execute(
        "DELETE FROM notion_page_cache WHERE datetime(cached_at, '+1 day') < datetime(?)",
        (now,),
    )
    # 30-day TTL for notifications
    await conn.execute(
        "DELETE FROM notifications WHERE datetime(created_at, '+30 days') < datetime(?)",
        (now,),
    )
    await conn.commit()


# ── Collection-like accessors (API-compatible with mongo.py patterns) ────────

class _Table:
    """Thin wrapper providing MongoDB-like async methods on a SQLite table."""

    def __init__(self, table: str):
        self.table = table

    async def find_one(self, filter_dict: dict, projection: dict | None = None) -> dict | None:
        conn = await get_conn()
        where, params = _build_where(filter_dict)
        row = await conn.execute_fetchall(
            f"SELECT * FROM {self.table} WHERE {where} LIMIT 1", params
        )
        if not row:
            return None
        return _row_to_dict(row[0])

    async def insert_one(self, doc: dict) -> None:
        conn = await get_conn()
        # For tables with JSON columns, serialize them
        cols = list(doc.keys())
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in doc.values()]
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        await conn.execute(
            f"INSERT OR IGNORE INTO {self.table} ({col_names}) VALUES ({placeholders})",
            vals,
        )
        await conn.commit()

    async def update_one(self, filter_dict: dict, update: dict, upsert: bool = False) -> None:
        conn = await get_conn()
        set_dict = update.get("$set", update)
        set_parts = []
        set_vals = []
        for k, v in set_dict.items():
            set_parts.append(f"{k} = ?")
            set_vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        where, where_vals = _build_where(filter_dict)
        await conn.execute(
            f"UPDATE {self.table} SET {','.join(set_parts)} WHERE {where}",
            set_vals + where_vals,
        )
        await conn.commit()


def _build_where(filter_dict: dict) -> tuple[str, list]:
    """Build a WHERE clause from a simple filter dict."""
    if not filter_dict:
        return "1=1", []
    parts = []
    vals = []
    for k, v in filter_dict.items():
        parts.append(f"{k} = ?")
        vals.append(v)
    return " AND ".join(parts), vals


def _row_to_dict(row) -> dict:
    """Convert an aiosqlite.Row to a plain dict."""
    if row is None:
        return {}
    return dict(row)


# ── Public accessors (drop-in replacements for mongo.py) ────────────────────

def knowledge_chunks() -> _Table:
    return _Table("knowledge_chunks")

def knowledge_sync_logs() -> _Table:
    return _Table("knowledge_sync_logs")

def agent_config() -> _Table:
    return _Table("agent_config")

def funder_context_cache() -> _Table:
    return _Table("funder_context_cache")

def deep_research_cache() -> _Table:
    return _Table("deep_research_cache")

def notion_page_cache() -> _Table:
    return _Table("notion_page_cache")

def drafter_chat_history() -> _Table:
    return _Table("drafter_chat_history")

class _AuditTable(_Table):
    """Audit logs table with smart insert — packs extra fields into metadata_json."""

    _KNOWN_COLS = {"node", "action", "metadata_json", "created_at"}

    async def insert_one(self, doc: dict) -> None:
        conn = await get_conn()
        # Separate known columns from extra metadata
        row: dict = {}
        extra: dict = {}
        for k, v in doc.items():
            if k in self._KNOWN_COLS:
                row[k] = v
            elif k != "id":
                extra[k] = v
        # Merge extras into metadata_json
        if extra:
            existing = {}
            if "metadata_json" in row:
                try:
                    existing = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
                except (json.JSONDecodeError, TypeError):
                    pass
            if isinstance(existing, dict):
                existing.update(extra)
            else:
                existing = extra
            row["metadata_json"] = json.dumps(existing, default=str)
        elif "metadata_json" not in row:
            row["metadata_json"] = "{}"

        cols = list(row.keys())
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        await conn.execute(
            f"INSERT INTO {self.table} ({col_names}) VALUES ({placeholders})",
            vals,
        )
        await conn.commit()


def audit_logs() -> _AuditTable:
    return _AuditTable("audit_logs")

class _ScoutRunsTable(_Table):
    """Scout runs table — packs extra fields into run_json."""

    _KNOWN_COLS = {"run_json", "run_at"}

    async def insert_one(self, doc: dict) -> None:
        conn = await get_conn()
        row: dict = {}
        extra: dict = {}
        for k, v in doc.items():
            if k in self._KNOWN_COLS:
                row[k] = v
            elif k != "id":
                extra[k] = v
        if extra:
            existing = {}
            if "run_json" in row:
                try:
                    existing = json.loads(row["run_json"]) if isinstance(row["run_json"], str) else row["run_json"]
                except (json.JSONDecodeError, TypeError):
                    pass
            if isinstance(existing, dict):
                existing.update(extra)
            else:
                existing = extra
            row["run_json"] = json.dumps(existing, default=str)
        elif "run_json" not in row:
            row["run_json"] = "{}"

        cols = list(row.keys())
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        await conn.execute(
            f"INSERT INTO {self.table} ({col_names}) VALUES ({placeholders})",
            vals,
        )
        await conn.commit()


def scout_runs() -> _ScoutRunsTable:
    return _ScoutRunsTable("scout_runs")

def notifications() -> _Table:
    return _Table("notifications")

def grant_comments() -> _Table:
    return _Table("grant_comments")

def notion_write_queue() -> _Table:
    return _Table("notion_write_queue")


# ── Startup function (replaces mongo.ensure_indexes) ─────────────────────────

async def ensure_db() -> None:
    """Initialize SQLite database. Call once at startup."""
    await get_conn()
    await cleanup_expired()
    log.info("SQLite database ready")
