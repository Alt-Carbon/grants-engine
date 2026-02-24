"""Backfill and deduplication jobs for existing grant data.

run_field_backfill()  — extract missing structured fields on existing grants
run_deduplication()   — remove duplicate grants across both collections
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s


def _content_hash(title: str, funder: str) -> str:
    """Stable MD5 of normalized (title + funder) — used for content-based dedup."""
    key = f"{_normalize_text(title)}|{_normalize_text(funder)}"
    return hashlib.md5(key.encode()).hexdigest()


# ── Prompts ────────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """Extract structured grant information from this grant page content.
Return ONLY valid JSON. Use null for any field not explicitly mentioned.

Source URL: {url}
Page Title: {title}

Content:
{content}

JSON format:
{{
  "grant_name": "<exact official name of the grant or program>",
  "sponsor": "<full legal name of the organization offering this grant>",
  "grant_type": "<one of: grant | prize | challenge | accelerator | fellowship | contract | loan | equity | other>",
  "geography": "<eligible countries or regions — e.g. 'India only', 'Global', 'Developing countries'>",
  "amount": "<funding amount exactly as stated — e.g. 'up to $500,000', 'INR 50 lakh per startup'>",
  "max_funding_usd": <numeric USD integer estimate, or null>,
  "currency": "<3-letter code: USD, EUR, GBP, INR — default USD>",
  "deadline": "<deadline exactly as stated — e.g. 'March 31, 2026', 'Rolling', or null>",
  "eligibility": "<who can apply: org type, stage, sector, geography — max 120 words>",
  "application_url": "<direct apply URL if different from source URL, else null>"
}}"""

_RATIONALE_PROMPT = """You are a grant specialist for AltCarbon, a climate technology startup in India.
AltCarbon focuses on: carbon removal MRV, agritech soil carbon, AI for earth sciences, geospatial remote sensing, social impact climate.

Based on this grant analysis, write a 2-3 sentence rationale for why AltCarbon should apply.
Start with "AltCarbon should apply because..."

Grant: {title}
Funder: {funder}
Score: {score}/10
Geography: {geography}
Reasoning: {reasoning}
Evidence of fit: {evidence}

Write ONLY the rationale sentence(s). No preamble."""


# ── Pass 1: Backfill grants_raw ────────────────────────────────────────────────

async def _backfill_one_raw(doc: Dict, raw_col, sem: asyncio.Semaphore) -> None:
    from backend.utils.llm import chat, HAIKU

    async with sem:
        content = (doc.get("raw_content") or "")[:6000]
        extracted: Dict = {}

        if len(content) >= 150:
            prompt = _EXTRACTION_PROMPT.format(
                url=doc.get("url", ""),
                title=doc.get("title", ""),
                content=content,
            )
            try:
                raw = await chat(prompt, model=HAIKU, max_tokens=600)
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                extracted = json.loads(raw)
            except Exception as e:
                logger.debug("Extraction failed for %s: %s", doc.get("url"), e)

        title = extracted.get("grant_name") or doc.get("title", "")
        funder = extracted.get("sponsor") or doc.get("funder", "")

        update: Dict = {
            "grant_type": extracted.get("grant_type") or "grant",
            "geography":  extracted.get("geography") or "",
            "amount":     extracted.get("amount") or "",
            "eligibility": extracted.get("eligibility") or "",
            "application_url": extracted.get("application_url") or doc.get("url", ""),
            "content_hash": _content_hash(title, funder),
        }
        if extracted.get("grant_name"):
            update["title"] = extracted["grant_name"]
        if extracted.get("sponsor"):
            update["funder"] = extracted["sponsor"]
        if extracted.get("deadline") and not doc.get("deadline"):
            update["deadline"] = extracted["deadline"]
        if extracted.get("max_funding_usd") and not doc.get("max_funding"):
            update["max_funding"] = extracted["max_funding_usd"]
            update["currency"] = extracted.get("currency") or "USD"

        await raw_col.update_one({"_id": doc["_id"]}, {"$set": update})


# ── Pass 2: Backfill grants_scored ────────────────────────────────────────────

async def _backfill_one_scored(doc: Dict, raw_col, scored_col, sem: asyncio.Semaphore) -> None:
    from backend.utils.llm import chat, HAIKU
    from bson import ObjectId

    async with sem:
        update: Dict = {}

        # Try to pull new fields from the corresponding raw doc
        raw_grant_id = doc.get("raw_grant_id")
        if raw_grant_id:
            try:
                raw_doc = await raw_col.find_one({"_id": ObjectId(raw_grant_id)})
                if raw_doc:
                    update["grant_type"]     = raw_doc.get("grant_type", "grant")
                    update["geography"]      = raw_doc.get("geography", "")
                    update["amount"]         = raw_doc.get("amount", "")
                    update["eligibility"]    = raw_doc.get("eligibility", "")
                    update["application_url"] = raw_doc.get("application_url") or doc.get("url", "")
                    if raw_doc.get("deadline") and not doc.get("deadline"):
                        update["deadline"] = raw_doc["deadline"]
                    if raw_doc.get("max_funding") and not doc.get("max_funding"):
                        update["max_funding"] = raw_doc["max_funding"]
                    if raw_doc.get("title"):
                        update["title"] = raw_doc["title"]
                    if raw_doc.get("funder"):
                        update["funder"] = raw_doc["funder"]
            except Exception:
                pass

        # Defaults when raw not found
        if "grant_type" not in update:
            update["grant_type"] = "grant"
        if "application_url" not in update:
            update["application_url"] = doc.get("url", "")

        # Compute content_hash for this scored doc
        update["content_hash"] = _content_hash(
            update.get("title") or doc.get("title", ""),
            update.get("funder") or doc.get("funder", ""),
        )

        # Generate rationale if missing
        if not doc.get("rationale"):
            evidence = "; ".join((doc.get("evidence_found") or [])[:3]) or "N/A"
            prompt = _RATIONALE_PROMPT.format(
                title=update.get("title") or doc.get("title", "Unknown Grant"),
                funder=update.get("funder") or doc.get("funder", "Unknown"),
                score=doc.get("weighted_total", 0),
                geography=update.get("geography") or doc.get("geography", "Not specified"),
                reasoning=doc.get("reasoning", "N/A"),
                evidence=evidence,
            )
            try:
                rationale = await chat(prompt, model=HAIKU, max_tokens=200)
                update["rationale"] = rationale.strip()
            except Exception as e:
                logger.debug("Rationale failed for %s: %s", doc.get("title"), e)
                update["rationale"] = doc.get("reasoning", "")

        if update:
            await scored_col.update_one({"_id": doc["_id"]}, {"$set": update})


# ── Main backfill entry point ──────────────────────────────────────────────────

async def run_field_backfill() -> Dict:
    """Backfill structured fields + rationale on all existing grants in the DB."""
    from backend.db.mongo import grants_raw, grants_scored

    raw_col    = grants_raw()
    scored_col = grants_scored()
    sem        = asyncio.Semaphore(5)

    # Pass 1 — grants_raw
    raw_missing = await raw_col.find(
        {"grant_type": {"$exists": False}}
    ).to_list(length=5000)
    logger.info("Backfill: %d raw grants need field extraction", len(raw_missing))
    await asyncio.gather(*(_backfill_one_raw(d, raw_col, sem) for d in raw_missing))
    logger.info("Backfill pass 1 complete")

    # Pass 2 — grants_scored
    scored_missing = await scored_col.find(
        {"$or": [
            {"grant_type": {"$exists": False}},
            {"rationale": {"$exists": False}},
            {"rationale": ""},
        ]}
    ).to_list(length=5000)
    logger.info("Backfill: %d scored grants need update", len(scored_missing))
    await asyncio.gather(*(_backfill_one_scored(d, raw_col, scored_col, sem) for d in scored_missing))
    logger.info("Backfill pass 2 complete")

    return {
        "raw_backfilled": len(raw_missing),
        "scored_backfilled": len(scored_missing),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Deduplication ──────────────────────────────────────────────────────────────

async def run_deduplication() -> Dict:
    """Remove duplicate grants from both collections.

    Strategy:
    1. Ensure every doc has a content_hash (title+funder).
    2. Group by content_hash → keep the one with the highest score (or newest),
       delete the rest — but never delete grants already being pursued/drafted.
    3. Log summary.
    """
    from backend.db.mongo import grants_raw, grants_scored

    raw_col    = grants_raw()
    scored_col = grants_scored()
    removed_raw    = 0
    removed_scored = 0

    # ── Stamp content_hash on any docs missing it ─────────────────────────────
    raw_no_hash = await raw_col.find(
        {"content_hash": {"$exists": False}},
        {"_id": 1, "title": 1, "funder": 1},
    ).to_list(length=10000)
    for doc in raw_no_hash:
        ch = _content_hash(doc.get("title", ""), doc.get("funder", ""))
        await raw_col.update_one({"_id": doc["_id"]}, {"$set": {"content_hash": ch}})
    logger.info("Dedup: stamped content_hash on %d raw docs", len(raw_no_hash))

    scored_no_hash = await scored_col.find(
        {"content_hash": {"$exists": False}},
        {"_id": 1, "title": 1, "funder": 1},
    ).to_list(length=10000)
    for doc in scored_no_hash:
        ch = _content_hash(doc.get("title", ""), doc.get("funder", ""))
        await scored_col.update_one({"_id": doc["_id"]}, {"$set": {"content_hash": ch}})
    logger.info("Dedup: stamped content_hash on %d scored docs", len(scored_no_hash))

    # ── Dedup grants_raw (keep oldest/first, delete later dupes) ─────────────
    raw_dupe_pipeline = [
        {"$group": {
            "_id": "$content_hash",
            "ids": {"$push": "$_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}, "_id": {"$ne": None}}},
    ]
    for group in await raw_col.aggregate(raw_dupe_pipeline).to_list(length=5000):
        keep = group["ids"][0]   # keep first (oldest)
        for oid in group["ids"][1:]:
            await raw_col.delete_one({"_id": oid})
            removed_raw += 1
    logger.info("Dedup: removed %d duplicate raw grants", removed_raw)

    # ── Dedup grants_scored (keep highest score, never delete active grants) ──
    scored_dupe_pipeline = [
        {"$group": {
            "_id": "$content_hash",
            "ids": {"$push": "$_id"},
            "scores": {"$push": "$weighted_total"},
            "statuses": {"$push": "$status"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}, "_id": {"$ne": None}}},
    ]
    _SAFE_STATUSES = {"pursue", "pursuing", "drafting", "draft_complete", "reported"}

    for group in await scored_col.aggregate(scored_dupe_pipeline).to_list(length=5000):
        ids      = group["ids"]
        scores   = group["scores"]
        statuses = group["statuses"]

        # Find best: prefer active status, then highest score
        best_idx = 0
        for i, status in enumerate(statuses):
            if status in _SAFE_STATUSES:
                best_idx = i
                break
        else:
            best_idx = scores.index(max(scores))

        for i, oid in enumerate(ids):
            if i == best_idx:
                continue
            # Never delete a grant that's in an active workflow
            if statuses[i] in _SAFE_STATUSES:
                continue
            await scored_col.delete_one({"_id": oid})
            removed_scored += 1
    logger.info("Dedup: removed %d duplicate scored grants", removed_scored)

    return {
        "raw_duplicates_removed": removed_raw,
        "scored_duplicates_removed": removed_scored,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
