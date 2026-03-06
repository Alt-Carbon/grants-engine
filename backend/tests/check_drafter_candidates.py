"""Quick check: find grants suitable for drafter testing."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    client = AsyncIOMotorClient(
        "mongodb+srv://gowtham_db_user:x6mYVxlgVnBrk4kD@grantee.xnnf8gp.mongodb.net/altcarbon_grants?appName=Grantee"
    )
    db = client["altcarbon_grants"]

    # Find grants with pursue/pursuing status
    pursue = await db.grants_scored.find(
        {"status": {"$in": ["pursue", "pursuing"]}}
    ).to_list(10)
    print(f"Pursuing grants: {len(pursue)}")
    for g in pursue:
        name = g.get("grant_name") or g.get("title") or "?"
        print(f"  - {name[:60]} | score={g.get('weighted_total', 0):.1f} | id={g['_id']} | url={g.get('url', 'N/A')[:50]}")

    # High-score triage grants as candidates
    high = await db.grants_scored.find(
        {"status": "triage", "weighted_total": {"$gte": 6.5}}
    ).sort("weighted_total", -1).to_list(5)
    print(f"\nHigh-score triage grants (drafter candidates): {len(high)}")
    for g in high:
        name = g.get("grant_name") or g.get("title") or "?"
        print(f"  - {name[:60]} | score={g.get('weighted_total', 0):.1f} | id={g['_id']} | url={g.get('url', 'N/A')[:50]}")

    # Existing pipeline records
    pipes = await db.grants_pipeline.find({}).to_list(10)
    print(f"\nExisting pipeline records: {len(pipes)}")
    for p in pipes:
        print(f"  - grant_id={p.get('grant_id')} | status={p.get('status')} | thread={p.get('thread_id')}")

    client.close()


asyncio.run(main())
