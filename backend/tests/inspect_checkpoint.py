"""Inspect the latest checkpoint for the drafter thread in detail."""
import asyncio
import json
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    client = AsyncIOMotorClient(
        "mongodb+srv://gowtham_db_user:x6mYVxlgVnBrk4kD@grantee.xnnf8gp.mongodb.net/altcarbon_grants?appName=Grantee"
    )
    db = client["altcarbon_grants"]

    thread_id = "draft_699efbe1_4340c2"

    # Get latest checkpoint
    doc = await db.graph_checkpoints.find_one(
        {"thread_id": thread_id},
        sort=[("checkpoint_id", -1)],
    )
    if not doc:
        print("No checkpoint found!")
        return

    print(f"Checkpoint ID: {doc['checkpoint_id']}")
    print(f"Step: {json.loads(doc.get('metadata', '{}')).get('step', '?')}")

    cp = json.loads(doc.get("checkpoint", "{}"))
    cv = cp.get("channel_values", {})

    print(f"\nChannel value keys: {list(cv.keys())}")

    # Print all non-null/non-empty fields
    for k, v in sorted(cv.items()):
        if v is None:
            print(f"  {k}: null")
        elif isinstance(v, str) and len(v) > 200:
            print(f"  {k}: (string, {len(v)} chars) {v[:200]}...")
        elif isinstance(v, dict):
            s = json.dumps(v, default=str)
            if len(s) > 300:
                print(f"  {k}: (dict, {len(s)} chars) {s[:300]}...")
            else:
                print(f"  {k}: {s}")
        elif isinstance(v, list):
            print(f"  {k}: (list, {len(v)} items)")
            if v and len(v) <= 5:
                for item in v:
                    s = json.dumps(item, default=str) if isinstance(item, dict) else str(item)
                    print(f"    - {s[:150]}")
        else:
            print(f"  {k}: {v}")

    # Check pending_writes
    pw = doc.get("pending_writes", {})
    if pw:
        print(f"\nPending writes: {len(pw)} task(s)")
        for task_id, writes in pw.items():
            print(f"  Task {task_id}:")
            for w in writes:
                channel = w.get("channel", "?")
                val = w.get("value", "")
                if isinstance(val, str) and len(val) > 300:
                    print(f"    channel={channel}: {val[:300]}...")
                else:
                    print(f"    channel={channel}: {val}")

    client.close()


asyncio.run(main())
