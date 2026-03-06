"""Check drafter pipeline status and graph checkpoints."""
import asyncio
import json
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    client = AsyncIOMotorClient(
        "mongodb+srv://gowtham_db_user:x6mYVxlgVnBrk4kD@grantee.xnnf8gp.mongodb.net/altcarbon_grants?appName=Grantee"
    )
    db = client["altcarbon_grants"]

    thread_id = "draft_699efbe1_4340c2"

    # Pipeline record
    pipe = await db.grants_pipeline.find_one({"thread_id": thread_id})
    if pipe:
        pipe["_id"] = str(pipe["_id"])
        print("Pipeline record:")
        print(json.dumps(pipe, indent=2, default=str))
    else:
        print("No pipeline record found!")

    # Graph checkpoints
    checkpoints = await db.graph_checkpoints.find(
        {"thread_id": thread_id}
    ).sort("checkpoint_id", -1).to_list(10)
    print(f"\nGraph checkpoints: {len(checkpoints)}")
    for cp in checkpoints:
        cp_id = cp.get("checkpoint_id", "?")[:24]
        metadata = json.loads(cp.get("metadata", "{}")) if isinstance(cp.get("metadata"), str) else cp.get("metadata", {})
        source = metadata.get("source", "?")
        step = metadata.get("step", "?")
        node = metadata.get("writes", {})
        # Try to get node info from metadata
        print(f"  step={step} | source={source} | id={cp_id}... | metadata_keys={list(metadata.keys())}")

        # Check checkpoint content for pending_interrupt
        try:
            cp_data = json.loads(cp.get("checkpoint", "{}")) if isinstance(cp.get("checkpoint"), str) else {}
            channel_vals = cp_data.get("channel_values", {})
            if isinstance(channel_vals, dict):
                pending = channel_vals.get("pending_interrupt")
                approved = channel_vals.get("approved_sections", {})
                section_idx = channel_vals.get("current_section_index", "?")
                grant_id = channel_vals.get("selected_grant_id", "?")
                company_ctx = channel_vals.get("company_context")
                grant_req = channel_vals.get("grant_requirements")
                print(f"    grant_id={grant_id} | section_idx={section_idx} | approved={len(approved) if isinstance(approved, dict) else '?'}")
                print(f"    company_context={'set' if company_ctx else 'null'} | grant_requirements={'set' if grant_req else 'null'}")
                if pending:
                    pending_str = json.dumps(pending, default=str)
                    print(f"    PENDING INTERRUPT: {pending_str[:300]}")
        except Exception as e:
            print(f"    (parse error: {e})")

    client.close()


asyncio.run(main())
