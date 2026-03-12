"""All MongoDB read functions used by the Streamlit UI.

Streamlit reads directly from MongoDB — no API layer needed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

# Streamlit uses sync PyMongo (Streamlit isn't async)
_client: MongoClient | None = None


def _db():
    global _client
    if _client is None:
        _client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    return _client["altcarbon_grants"]


# ── Raw scrape preview ─────────────────────────────────────────────────────────

def get_raw_grants_preview(limit: int = 20) -> List[Dict]:
    """Return recently scraped raw grants (before analyst scoring)."""
    db = _db()
    docs = list(
        db["grants_raw"].find(
            {},
            {"title": 1, "url": 1, "funder": 1, "source": 1,
             "themes_detected": 1, "scraped_at": 1, "raw_content": 1, "processed": 1},
            sort=[("scraped_at", -1)],
        ).limit(limit)
    )
    for d in docs:
        d["_id"] = str(d["_id"])
        # Truncate raw_content to a short snippet for display
        content = d.get("raw_content") or ""
        d["snippet"] = content[:300].strip()
        d.pop("raw_content", None)
    return docs


def get_raw_stats() -> Dict:
    db = _db()
    total = db["grants_raw"].count_documents({})
    unprocessed = db["grants_raw"].count_documents({"processed": False})
    scored = db["grants_scored"].count_documents({})
    return {"total_raw": total, "unprocessed": unprocessed, "scored": scored}


# ── Dashboard ──────────────────────────────────────────────────────────────────

def get_tracker_grants(
    search: str = "",
    theme_filter: str = "",
    grant_type_filter: str = "",
    status_filter: str = "",
    min_funding: Optional[int] = None,
    max_funding: Optional[int] = None,
) -> List[Dict]:
    """Return all actionable grants (triage + pursue + watch) sorted by score,
    with all fields needed for the Grant Tracker table."""
    db = _db()
    query: Dict[str, Any] = {
        "status": {"$in": ["triage", "pursue", "pursuing", "watch"]}
    }
    if theme_filter:
        query["$or"] = [
            {"themes_detected": theme_filter},
            {"themes": {"$regex": theme_filter.replace("_", " "), "$options": "i"}},
        ]
    if grant_type_filter:
        query["grant_type"] = grant_type_filter
    if status_filter:
        query["status"] = status_filter
    if min_funding is not None or max_funding is not None:
        fq: Dict[str, Any] = {}
        if min_funding is not None:
            fq["$gte"] = min_funding
        if max_funding is not None:
            fq["$lte"] = max_funding
        query["max_funding_usd"] = fq
    if search:
        sq = {"$regex": search, "$options": "i"}
        query["$or"] = [
            {"title": sq}, {"grant_name": sq},
            {"funder": sq}, {"geography": sq}, {"eligibility": sq},
        ]
    grants = list(
        db["grants_scored"].find(query, sort=[("weighted_total", -1)]).limit(500)
    )
    for g in grants:
        g["_id"] = str(g["_id"])
        # Normalise title: prefer grant_name (from new scraper) over title
        if not g.get("grant_name") and g.get("title"):
            g["grant_name"] = g["title"]
    return grants


def get_tracker_stats() -> Dict:
    """Summary stats for the Grant Tracker section."""
    db = _db()
    total     = db["grants_scored"].count_documents({})
    in_triage = db["grants_scored"].count_documents({"status": "triage"})
    pursuing  = db["grants_scored"].count_documents(
        {"status": {"$in": ["pursue", "pursuing"]}}
    )
    watching  = db["grants_scored"].count_documents({"status": "watch"})
    auto_pass = db["grants_scored"].count_documents(
        {"status": {"$in": ["auto_pass", "passed"]}}
    )
    # Capital targeted = sum max_funding_usd for pursue+watch+triage
    pipeline = db["grants_scored"].find(
        {"status": {"$in": ["triage", "pursue", "pursuing", "watch"]}},
        {"max_funding_usd": 1, "max_funding": 1},
    )
    capital = sum(
        float(g.get("max_funding_usd") or g.get("max_funding") or 0)
        for g in pipeline
    )
    return {
        "total": total,
        "in_triage": in_triage,
        "pursuing": pursuing,
        "watching": watching,
        "auto_pass": auto_pass,
        "capital_targeted": capital,
    }


def get_quick_stats() -> Dict:
    db = _db()
    total = db["grants_scored"].count_documents({})
    triage = db["grants_scored"].count_documents({"status": "triage"})
    pursuing = db["grants_scored"].count_documents({"status": {"$in": ["pursue", "pursuing"]}})
    last_scout = db["scout_runs"].find_one(sort=[("run_at", -1)])
    return {
        "total_grants": total,
        "in_triage": triage,
        "pursuing": pursuing,
        "last_scout": last_scout["run_at"] if last_scout else "Never",
    }


def get_dashboard_stats() -> Dict:
    db = _db()
    total = db["grants_scored"].count_documents({})
    triage = db["grants_scored"].count_documents({"status": "triage"})
    pursuing = db["grants_scored"].count_documents({"status": {"$in": ["pursue", "pursuing"]}})
    drafting = db["grants_pipeline"].count_documents({"status": "drafting"})
    complete = db["grants_pipeline"].count_documents({"status": "draft_complete"})

    # Total capital targeted (sum of max_funding for pursuing grants)
    pipeline_cur = db["grants_scored"].find({"status": {"$in": ["pursue", "pursuing", "drafting"]}})
    capital = sum(g.get("max_funding") or 0 for g in pipeline_cur)

    return {
        "total_discovered": total,
        "in_triage": triage,
        "pursuing": pursuing,
        "drafting": drafting,
        "draft_complete": complete,
        "capital_targeted": capital,
    }


def get_pipeline_funnel() -> List[Dict]:
    db = _db()
    stages = [
        ("Discovered", {}),
        ("In Triage", {"status": "triage"}),
        ("Pursuing", {"status": {"$in": ["pursue", "pursuing"]}}),
        ("Drafting", {"status": "drafting"}),
        ("Draft Complete", {"status": "draft_complete"}),
    ]
    scored = db["grants_scored"]
    pipeline_col = db["grants_pipeline"]
    result = []
    for label, query in stages:
        if label in ("Drafting", "Draft Complete"):
            count = pipeline_col.count_documents({"status": query.get("status", {})})
        else:
            count = scored.count_documents(query)
        result.append({"stage": label, "count": count})
    return result


def get_grants_by_theme() -> Dict[str, int]:
    db = _db()
    pipeline = [
        {"$unwind": "$themes_detected"},
        {"$group": {"_id": "$themes_detected", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    return {r["_id"]: r["count"] for r in db["grants_scored"].aggregate(pipeline)}


def get_score_distribution() -> List[float]:
    db = _db()
    return [g["weighted_total"] for g in db["grants_scored"].find({}, {"weighted_total": 1})]


def get_recent_activity(limit: int = 8) -> List[Dict]:
    db = _db()
    return list(db["audit_logs"].find({}, sort=[("created_at", -1)]).limit(limit))


def get_top_grants(limit: int = 5) -> List[Dict]:
    db = _db()
    grants = list(
        db["grants_scored"].find(
            {"recommended_action": {"$in": ["pursue", "watch"]}},
            sort=[("weighted_total", -1)],
        ).limit(limit)
    )
    for g in grants:
        g["_id"] = str(g["_id"])
    return grants


# ── Manual Grant Entry ─────────────────────────────────────────────────────────

def save_manual_grant(
    url: str,
    title_override: str = "",
    funder_override: str = "",
    notes: str = "",
    jina_key: str = "",
) -> tuple:
    """Fetch a grant URL via Jina, detect themes, and save to grants_raw.

    Returns (success: bool, message: str).
    """
    import hashlib
    import httpx
    from urllib.parse import urlparse

    url = url.strip()
    if not url.startswith("http"):
        return False, "URL must start with http:// or https://"

    url_hash = hashlib.md5(url.lower().encode()).hexdigest()

    existing = _db()["grants_raw"].find_one({"url_hash": url_hash})
    if existing:
        return False, f"Already in database (added {existing.get('scraped_at','previously')[:10]})."

    # Fetch via Jina first, fall back to plain HTTP
    raw_content = ""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"X-Return-Format": "markdown", "X-With-Links-Summary": "false"}
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"
    try:
        r = httpx.get(jina_url, headers=headers, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        raw_content = r.text.strip()[:80_000]
    except Exception as e:
        try:
            r2 = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20.0, follow_redirects=True)
            r2.raise_for_status()
            raw_content = r2.text[:60_000]
        except Exception:
            return False, f"Could not fetch URL: {e}"

    if len(raw_content) < 100:
        return False, "Page returned too little content. Check the URL."

    # Theme detection
    text_lower = (raw_content + " " + title_override).lower()
    themes = []
    if any(k in text_lower for k in ["climate", "carbon", "net zero", "decarboni", "emission", "cdr", "mrv", "cleantech", "renewable"]):
        themes.append("climatetech")
    if any(k in text_lower for k in ["agri", "soil", "farm", "crop", "food", "land use", "regenerative"]):
        themes.append("agritech")
    if any(k in text_lower for k in ["artificial intelligence", "machine learning", "ai for", "deep learning", "nlp"]):
        themes.append("ai_for_sciences")
    if any(k in text_lower for k in ["earth science", "remote sensing", "satellite", "geology", "geospatial", "subsurface"]):
        themes.append("applied_earth_sciences")
    if any(k in text_lower for k in ["social impact", "community", "rural", "livelihood", "inclusive", "women", "development"]):
        themes.append("social_impact")
    if not themes:
        themes = ["climatetech"]

    # Auto-extract title from content if not provided
    title = title_override.strip()
    if not title:
        import re as _re
        # Try <title> tag first (for raw HTML fallback)
        m = _re.search(r"<title[^>]*>([^<]+)</title>", raw_content, _re.IGNORECASE)
        if m:
            title = m.group(1).strip()[:120]
        else:
            # For markdown (Jina output), use the first non-empty heading or line
            for line in raw_content.split("\n"):
                line = line.lstrip("#").strip()
                if len(line) > 10:
                    title = line[:120]
                    break
        if not title:
            title = url

    # Auto-extract funder from domain if not provided
    funder = funder_override.strip()
    if not funder:
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            funder = domain.split(".")[0].upper()
        except Exception:
            funder = "Unknown"

    doc = {
        "title": title,
        "url": url,
        "url_hash": url_hash,
        "funder": funder,
        "raw_content": raw_content,
        "themes_detected": themes,
        "source": "manual",
        "deadline": None,
        "max_funding": None,
        "currency": "USD",
        "eligibility_raw": "",
        "processed": False,
        "notes": notes,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    _db()["grants_raw"].insert_one(doc)
    return True, (
        f"Saved **{title[:70]}** · {len(raw_content):,} chars fetched · "
        f"themes: {', '.join(themes)}"
    )


# ── Grants Pipeline ────────────────────────────────────────────────────────────

def get_all_pipeline_grants(
    search: str = "",
    theme_filter: str = "",
    status_filter: str = "",
    grant_type_filter: str = "",
    min_funding: Optional[int] = None,
    max_funding: Optional[int] = None,
) -> List[Dict]:
    db = _db()
    query: Dict[str, Any] = {}
    if theme_filter:
        query["themes_detected"] = theme_filter
    if status_filter:
        query["status"] = status_filter
    if grant_type_filter:
        query["grant_type"] = grant_type_filter
    if min_funding is not None or max_funding is not None:
        funding_q: Dict[str, Any] = {}
        if min_funding is not None:
            funding_q["$gte"] = min_funding
        if max_funding is not None:
            funding_q["$lte"] = max_funding
        query["max_funding"] = funding_q
    if search:
        query["$or"] = [
            {"title":       {"$regex": search, "$options": "i"}},
            {"funder":      {"$regex": search, "$options": "i"}},
            {"geography":   {"$regex": search, "$options": "i"}},
            {"eligibility": {"$regex": search, "$options": "i"}},
        ]
    grants = list(db["grants_scored"].find(query, sort=[("weighted_total", -1)]).limit(200))
    for g in grants:
        g["_id"] = str(g["_id"])
    return grants


def update_grant_status(grant_id: str, status: str):
    from bson import ObjectId
    _db()["grants_scored"].update_one({"_id": ObjectId(grant_id)}, {"$set": {"status": status}})


REPORT_REASONS = [
    "Not relevant to AltCarbon",
    "News article, not a grant",
    "Wrong / incomplete info scraped",
    "Grant is already closed / expired",
    "Duplicate grant",
    "Other",
]


def report_grant(grant_id: str, reason: str, note: str = ""):
    """Flag a grant as reported — removes it from active queues."""
    from bson import ObjectId
    db = _db()
    db["grants_scored"].update_one(
        {"_id": ObjectId(grant_id)},
        {
            "$set": {"status": "reported"},
            "$push": {
                "reports": {
                    "reason": reason,
                    "note": note,
                    "reported_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        },
    )


# ── Triage Queue ───────────────────────────────────────────────────────────────

def get_triage_queue(
    search: str = "",
    theme_filter: str = "",
    grant_type_filter: str = "",
    min_score: float = 0.0,
    min_funding: Optional[int] = None,
    max_funding: Optional[int] = None,
) -> List[Dict]:
    db = _db()
    query: Dict[str, Any] = {"status": "triage"}
    if theme_filter:
        query["themes_detected"] = theme_filter
    if grant_type_filter:
        query["grant_type"] = grant_type_filter
    if min_score > 0:
        query["weighted_total"] = {"$gte": min_score}
    if min_funding is not None or max_funding is not None:
        funding_q: Dict[str, Any] = {}
        if min_funding is not None:
            funding_q["$gte"] = min_funding
        if max_funding is not None:
            funding_q["$lte"] = max_funding
        query["max_funding"] = funding_q
    if search:
        query["$or"] = [
            {"title":       {"$regex": search, "$options": "i"}},
            {"funder":      {"$regex": search, "$options": "i"}},
            {"geography":   {"$regex": search, "$options": "i"}},
            {"eligibility": {"$regex": search, "$options": "i"}},
        ]
    grants = list(db["grants_scored"].find(query, sort=[("weighted_total", -1)]))
    for g in grants:
        g["_id"] = str(g["_id"])
    return grants


# ── Drafter ────────────────────────────────────────────────────────────────────

def get_active_drafts() -> List[Dict]:
    db = _db()
    pipelines = list(
        db["grants_pipeline"].find(
            {"status": {"$in": ["drafting", "draft_complete"]}},
            sort=[("started_at", -1)],
        )
    )
    result = []
    for p in pipelines:
        p["_id"] = str(p["_id"])
        grant = db["grants_scored"].find_one({"_id": __import__("bson").ObjectId(p["grant_id"])}) if p.get("grant_id") else {}
        p["grant_title"] = (grant or {}).get("title", "Unknown Grant")
        p["grant_funder"] = (grant or {}).get("funder", "")
        # Get latest draft
        draft = db["grant_drafts"].find_one(
            {"pipeline_id": p["_id"]},
            sort=[("version", -1)],
        )
        if draft:
            draft["_id"] = str(draft["_id"])
        p["latest_draft"] = draft
        result.append(p)
    return result


def get_thread_interrupt(thread_id: str) -> Optional[Dict]:
    """Get the current pending section interrupt for a thread."""
    import json
    from bson import ObjectId
    doc = _db()["graph_checkpoints"].find_one(
        {"thread_id": thread_id},
        sort=[("checkpoint_id", -1)],
    )
    if not doc:
        return None
    checkpoint = json.loads(doc.get("checkpoint", "{}"))
    channel_values = checkpoint.get("channel_values", {})
    return channel_values.get("pending_interrupt")


# ── Knowledge Health ───────────────────────────────────────────────────────────

def knowledge_base_health() -> Dict:
    db = _db()
    total = db["knowledge_chunks"].count_documents({})
    notion = db["knowledge_chunks"].count_documents({"source": "notion"})
    drive = db["knowledge_chunks"].count_documents({"source": "drive"})
    past_grants = db["knowledge_chunks"].count_documents({"doc_type": "past_grant_application"})

    by_type_pipeline = [{"$group": {"_id": "$doc_type", "count": {"$sum": 1}}}]
    by_type = {r["_id"]: r["count"] for r in db["knowledge_chunks"].aggregate(by_type_pipeline)}

    by_theme_pipeline = [
        {"$unwind": "$themes"},
        {"$group": {"_id": "$themes", "count": {"$sum": 1}}},
    ]
    by_theme = {r["_id"]: r["count"] for r in db["knowledge_chunks"].aggregate(by_theme_pipeline)}

    last_sync = db["knowledge_sync_logs"].find_one(sort=[("synced_at", -1)])
    status = "healthy" if total >= 200 else ("thin" if total >= 50 else "critical")

    return {
        "total_chunks": total,
        "notion_chunks": notion,
        "drive_chunks": drive,
        "past_grant_application_chunks": past_grants,
        "by_type": by_type,
        "by_theme": by_theme,
        "last_synced": last_sync["synced_at"] if last_sync else None,
        "status": status,
    }


def get_sync_logs(limit: int = 5) -> List[Dict]:
    db = _db()
    logs = list(db["knowledge_sync_logs"].find({}, sort=[("synced_at", -1)]).limit(limit))
    for l in logs:
        l["_id"] = str(l["_id"])
    return logs


# ── Agent Config ───────────────────────────────────────────────────────────────

def get_agent_config(agent: str = "") -> Dict:
    db = _db()
    if agent:
        return db["agent_config"].find_one({"agent": agent}) or {}
    return {r["agent"]: r for r in db["agent_config"].find({})}


def save_agent_config(agent: str, config: Dict):
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    _db()["agent_config"].update_one({"agent": agent}, {"$set": config}, upsert=True)


# ── Export ─────────────────────────────────────────────────────────────────────

def export_grants_csv() -> bytes:
    import csv, io
    grants = get_all_pipeline_grants()
    output = io.StringIO()
    if not grants:
        return b""
    fieldnames = [
        "title", "funder", "grant_type", "geography",
        "amount", "max_funding", "currency",
        "deadline", "eligibility",
        "weighted_total", "status", "recommended_action",
        "rationale", "reasoning",
        "url", "application_url",
        "themes_detected",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for g in grants:
        row = {k: g.get(k, "") for k in fieldnames}
        # Flatten lists
        if isinstance(row.get("themes_detected"), list):
            row["themes_detected"] = " | ".join(row["themes_detected"])
        writer.writerow(row)
    return output.getvalue().encode()
