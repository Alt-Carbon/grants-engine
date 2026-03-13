"""
Migrate data from MongoDB to SQLite.

Collections migrated:
  - audit_logs
  - notifications
  - grant_comments
  - agent_config
  - knowledge_chunks
  - knowledge_sync_logs
  - scout_runs

Usage:
    cd /Users/GowthamReddy/Desktop/Gowtham/grants-engine
    python -m scripts.migrate_mongo_to_sqlite
"""
from __future__ import annotations

import asyncio
import json
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.mongo import get_db as get_mongo_db
from backend.db.sqlite import get_conn as get_sqlite_conn, ensure_tables


def _json_serial(val):
    """Serialize a value to a JSON string if it's a dict or list."""
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)
    return val


def _to_str(val, default=""):
    """Convert a value to string, handling None and datetime objects."""
    if val is None:
        return default
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


async def migrate_audit_logs(mongo_db, sqlite_conn):
    """audit_logs -> sqlite audit_logs (node, action, metadata_json, created_at)"""
    col = mongo_db["audit_logs"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        # Build metadata: everything except the mapped fields and _id
        metadata = {k: v for k, v in doc.items() if k not in ("_id", "node", "action", "created_at", "metadata", "metadata_json")}
        # If there's an explicit metadata field, merge it in
        if "metadata" in doc and isinstance(doc["metadata"], dict):
            metadata.update(doc["metadata"])
        if "metadata_json" in doc:
            try:
                extra = json.loads(doc["metadata_json"]) if isinstance(doc["metadata_json"], str) else doc["metadata_json"]
                if isinstance(extra, dict):
                    metadata.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass

        rows.append((
            _to_str(doc.get("node"), ""),
            _to_str(doc.get("action"), ""),
            json.dumps(metadata, default=str),
            _to_str(doc.get("created_at"), ""),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO audit_logs (node, action, metadata_json, created_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  audit_logs: {len(rows)} records migrated")
    return len(rows)


async def migrate_notifications(mongo_db, sqlite_conn):
    """notifications -> sqlite notifications"""
    col = mongo_db["notifications"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        metadata = {k: v for k, v in doc.items()
                    if k not in ("_id", "user_email", "type", "title", "body",
                                 "action_url", "metadata", "metadata_json", "read", "created_at")}
        if "metadata" in doc and isinstance(doc["metadata"], dict):
            metadata.update(doc["metadata"])
        if "metadata_json" in doc:
            try:
                extra = json.loads(doc["metadata_json"]) if isinstance(doc["metadata_json"], str) else doc["metadata_json"]
                if isinstance(extra, dict):
                    metadata.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass

        rows.append((
            _to_str(doc.get("user_email"), ""),
            _to_str(doc.get("type"), ""),
            _to_str(doc.get("title"), ""),
            _to_str(doc.get("body"), ""),
            _to_str(doc.get("action_url"), ""),
            json.dumps(metadata, default=str),
            1 if doc.get("read") else 0,
            _to_str(doc.get("created_at"), ""),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO notifications (user_email, type, title, body, action_url, metadata_json, read, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  notifications: {len(rows)} records migrated")
    return len(rows)


async def migrate_grant_comments(mongo_db, sqlite_conn):
    """grant_comments -> sqlite grant_comments"""
    col = mongo_db["grant_comments"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        rows.append((
            _to_str(doc.get("grant_id"), ""),
            _to_str(doc.get("user_email"), ""),
            _to_str(doc.get("user_name"), ""),
            _to_str(doc.get("text"), ""),
            _to_str(doc.get("created_at"), ""),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO grant_comments (grant_id, user_email, user_name, text, created_at) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  grant_comments: {len(rows)} records migrated")
    return len(rows)


async def migrate_agent_config(mongo_db, sqlite_conn):
    """agent_config -> sqlite agent_config"""
    col = mongo_db["agent_config"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        # The config is everything except _id, agent, config_json, updated_at
        config = doc.get("config_json") or doc.get("config")
        if config is None:
            config = {k: v for k, v in doc.items() if k not in ("_id", "agent", "updated_at")}

        rows.append((
            _to_str(doc.get("agent"), ""),
            json.dumps(config, default=str) if isinstance(config, (dict, list)) else _to_str(config, "{}"),
            _to_str(doc.get("updated_at"), ""),
        ))

    if rows:
        # Use INSERT OR REPLACE since agent is PRIMARY KEY
        await sqlite_conn.executemany(
            "INSERT OR REPLACE INTO agent_config (agent, config_json, updated_at) VALUES (?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  agent_config: {len(rows)} records migrated")
    return len(rows)


async def migrate_knowledge_chunks(mongo_db, sqlite_conn):
    """knowledge_chunks -> sqlite knowledge_chunks"""
    col = mongo_db["knowledge_chunks"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        # Build metadata from leftover fields
        metadata = {k: v for k, v in doc.items()
                    if k not in ("_id", "source_id", "chunk_index", "doc_type",
                                 "source_title", "content", "content_hash",
                                 "themes", "last_synced", "metadata", "metadata_json")}
        if "metadata" in doc and isinstance(doc["metadata"], dict):
            metadata.update(doc["metadata"])
        if "metadata_json" in doc:
            try:
                extra = json.loads(doc["metadata_json"]) if isinstance(doc["metadata_json"], str) else doc["metadata_json"]
                if isinstance(extra, dict):
                    metadata.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass

        themes = doc.get("themes", [])
        if isinstance(themes, list):
            themes_str = json.dumps(themes, default=str)
        else:
            themes_str = _to_str(themes, "[]")

        rows.append((
            _to_str(doc.get("source_id"), ""),
            doc.get("chunk_index", 0) or 0,
            _to_str(doc.get("doc_type"), "notion"),
            _to_str(doc.get("source_title"), ""),
            _to_str(doc.get("content"), ""),
            _to_str(doc.get("content_hash"), ""),
            themes_str,
            _to_str(doc.get("last_synced"), ""),
            json.dumps(metadata, default=str),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO knowledge_chunks (source_id, chunk_index, doc_type, source_title, content, content_hash, themes, last_synced, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  knowledge_chunks: {len(rows)} records migrated")
    return len(rows)


async def migrate_knowledge_sync_logs(mongo_db, sqlite_conn):
    """knowledge_sync_logs -> sqlite knowledge_sync_logs"""
    col = mongo_db["knowledge_sync_logs"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        rows.append((
            _to_str(doc.get("source_id"), ""),
            _to_str(doc.get("action"), ""),
            doc.get("chunks_upserted", 0) or 0,
            _to_str(doc.get("status"), "success"),
            _to_str(doc.get("error"), ""),
            _to_str(doc.get("created_at"), ""),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO knowledge_sync_logs (source_id, action, chunks_upserted, status, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  knowledge_sync_logs: {len(rows)} records migrated")
    return len(rows)


async def migrate_scout_runs(mongo_db, sqlite_conn):
    """scout_runs -> sqlite scout_runs"""
    col = mongo_db["scout_runs"]
    cursor = col.find({})
    rows = []
    async for doc in cursor:
        # Serialize the entire run document (minus _id) as run_json
        run_data = doc.get("run_json")
        if run_data is None:
            run_data = {k: v for k, v in doc.items() if k not in ("_id", "run_at")}

        rows.append((
            json.dumps(run_data, default=str) if isinstance(run_data, (dict, list)) else _to_str(run_data, "{}"),
            _to_str(doc.get("run_at"), ""),
        ))

    if rows:
        await sqlite_conn.executemany(
            "INSERT OR IGNORE INTO scout_runs (run_json, run_at) VALUES (?, ?)",
            rows,
        )
        await sqlite_conn.commit()

    print(f"  scout_runs: {len(rows)} records migrated")
    return len(rows)


async def main():
    print("=" * 60)
    print("MongoDB -> SQLite Migration")
    print("=" * 60)

    # Connect to MongoDB
    mongo_db = get_mongo_db()
    print(f"\nMongoDB database: {mongo_db.name}")

    # List available collections
    collections = await mongo_db.list_collection_names()
    print(f"Available MongoDB collections: {sorted(collections)}")

    # Connect to SQLite (this also ensures tables exist)
    sqlite_conn = await get_sqlite_conn()
    print(f"SQLite connected\n")

    print("Migrating collections...")
    print("-" * 40)

    total = 0
    total += await migrate_audit_logs(mongo_db, sqlite_conn)
    total += await migrate_notifications(mongo_db, sqlite_conn)
    total += await migrate_grant_comments(mongo_db, sqlite_conn)
    total += await migrate_agent_config(mongo_db, sqlite_conn)
    total += await migrate_knowledge_chunks(mongo_db, sqlite_conn)
    total += await migrate_knowledge_sync_logs(mongo_db, sqlite_conn)
    total += await migrate_scout_runs(mongo_db, sqlite_conn)

    print("-" * 40)
    print(f"\nDone! Total records migrated: {total}")
    print("=" * 60)

    # Close SQLite
    from backend.db.sqlite import close_conn
    await close_conn()


if __name__ == "__main__":
    asyncio.run(main())
