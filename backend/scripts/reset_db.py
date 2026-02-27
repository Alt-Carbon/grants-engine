"""One-shot script: wipe all grant data collections and restart fresh.

Keeps: agent_config (custom scoring weights, query overrides)
Clears: grants_raw, grants_scored, grants_pipeline, grant_drafts,
        scout_runs, audit_logs, funder_context_cache, graph_checkpoints,
        knowledge_chunks, knowledge_sync_logs

Usage:
    python3 -m backend.scripts.reset_db
    # or with explicit URI:
    MONGODB_URI="mongodb+srv://..." python3 -m backend.scripts.reset_db
"""
from __future__ import annotations

import asyncio
import os
import sys

# Allow running from project root
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb+srv://gowtham_db_user:x6mYVxlgVnBrk4kD@grantee.xnnf8gp.mongodb.net/altcarbon_grants?appName=Grantee"
)

# Collections to wipe (agent_config is intentionally NOT in this list)
COLLECTIONS_TO_CLEAR = [
    "grants_raw",
    "grants_scored",
    "grants_pipeline",
    "grant_drafts",
    "scout_runs",
    "audit_logs",
    "funder_context_cache",
    "graph_checkpoints",
    "knowledge_chunks",
    "knowledge_sync_logs",
]


async def reset():
    print(f"\nConnecting to MongoDB...")
    client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    db = client["altcarbon_grants"]

    # Verify connection
    await client.admin.command("ping")
    print("Connected.\n")

    total_deleted = 0
    for col_name in COLLECTIONS_TO_CLEAR:
        col = db[col_name]
        count_before = await col.count_documents({})
        result = await col.delete_many({})
        print(f"  {col_name:<30} {count_before:>6} docs → deleted {result.deleted_count}")
        total_deleted += result.deleted_count

    print(f"\nDone. {total_deleted} documents removed across {len(COLLECTIONS_TO_CLEAR)} collections.")
    print("agent_config preserved.\n")
    client.close()


if __name__ == "__main__":
    asyncio.run(reset())
