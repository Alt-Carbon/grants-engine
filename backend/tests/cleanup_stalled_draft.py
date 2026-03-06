"""Clean up stalled draft runs so we can retry."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    client = AsyncIOMotorClient(
        "mongodb+srv://gowtham_db_user:x6mYVxlgVnBrk4kD@grantee.xnnf8gp.mongodb.net/altcarbon_grants?appName=Grantee"
    )
    db = client["altcarbon_grants"]

    # Remove all stalled pipeline records for this grant
    r1 = await db.grants_pipeline.delete_many({"grant_id": "699efbe16456a029c582d512"})
    print(f"Deleted {r1.deleted_count} pipeline records")

    # Remove all stalled graph checkpoints with "draft_" prefix
    r2 = await db.graph_checkpoints.delete_many({"thread_id": {"$regex": "^draft_699efbe1"}})
    print(f"Deleted {r2.deleted_count} graph checkpoints")

    client.close()


asyncio.run(main())
