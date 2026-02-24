"""View 6 — Knowledge Health: monitor Company Brain status and trigger syncs."""
from __future__ import annotations

import os

import httpx
import plotly.express as px
import streamlit as st

from app.db.queries import get_sync_logs, knowledge_base_health
from app.ui import icons

RAILWAY_URL = os.environ.get("RAILWAY_URL", "http://localhost:8000")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")


def _trigger_sync(source: str = "all"):
    try:
        r = httpx.post(
            f"{RAILWAY_URL}/run/knowledge-sync",
            headers={"x-internal-secret": INTERNAL_SECRET},
            json={"source": source},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception as e:
        st.error(f"Failed to trigger sync: {e}")
        return False


def render():
    icons.page_header("database", "Knowledge Health", "Monitor Company Brain and trigger knowledge syncs")

    health = knowledge_base_health()
    total = health["total_chunks"]
    status = health["status"]

    # ── Status banner ─────────────────────────────────────────────────────────
    if status == "healthy":
        st.markdown(
            f"<div style='background:var(--green-bg);border:1px solid var(--green-border);border-radius:10px;"
            f"padding:14px 18px;display:flex;gap:10px;align-items:center;margin-bottom:16px;'>"
            f"{icons.svg('check-circle',20,'var(--green)')}"
            f"<span style='color:var(--green-2);font-weight:500;'>Knowledge base healthy — {total} chunks indexed</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif status == "thin":
        st.markdown(
            f"<div style='background:var(--orange-bg);border:1px solid var(--orange-border);border-radius:10px;"
            f"padding:14px 18px;display:flex;gap:10px;align-items:center;margin-bottom:16px;'>"
            f"{icons.svg('alert-triangle',20,'var(--orange)')}"
            f"<span style='color:var(--orange-2);font-weight:500;'>Knowledge base thin ({total} chunks). "
            f"Consider adding more content to Notion/Drive.</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='background:var(--red-bg);border:1px solid var(--red-border);border-radius:10px;"
            f"padding:14px 18px;display:flex;gap:10px;align-items:center;margin-bottom:16px;'>"
            f"{icons.svg('alert-circle',20,'var(--red)')}"
            f"<span style='color:var(--red-2);font-weight:500;'>Knowledge base critically low ({total} chunks). "
            f"Drafts will be generic without more content.</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if health["past_grant_application_chunks"] == 0:
        st.markdown(
            f"<div style='background:var(--red-bg);border:1px solid var(--red-border);border-radius:10px;"
            f"padding:14px 18px;display:flex;gap:10px;align-items:flex-start;margin-bottom:16px;'>"
            f"{icons.svg('file-text',20,'var(--red)')}"
            f"<div><div style='color:var(--red-2);font-weight:600;margin-bottom:4px;'>"
            f"No past grant applications found!</div>"
            f"<div style='color:var(--red);font-size:0.88em;'>Drafter will write generic applications. "
            f"Add past grant docs to Notion or Drive with titles containing 'grant application', then re-sync.</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Top metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Chunks", total)
    c2.metric("From Notion", health["notion_chunks"])
    c3.metric("From Drive", health["drive_chunks"])
    c4.metric("Past Applications", health["past_grant_application_chunks"])

    last_sync = health.get("last_synced", "Never")
    if last_sync and last_sync != "Never":
        last_sync = last_sync[:16]
    st.markdown(
        icons.meta_chip("clock", f"Last synced: {last_sync}", "var(--text-3)"),
        unsafe_allow_html=True,
    )

    st.divider()

    col_left, col_right = st.columns(2)

    # ── By document type ──────────────────────────────────────────────────────
    with col_left:
        icons.section_header("file-text", "Chunks by Document Type")
        by_type = health.get("by_type", {})
        if by_type:
            if by_type.get("past_grant_application", 0) == 0:
                st.markdown(
                    f"{icons.svg('alert-triangle',13,'var(--red)')} "
                    f"<span style='color:var(--red);font-size:0.82em;'>`past_grant_application` = 0 — critical!</span>",
                    unsafe_allow_html=True,
                )
            fig = px.bar(
                x=list(by_type.values()),
                y=[k.replace("_", " ").title() for k in by_type.keys()],
                orientation="h",
                color_discrete_sequence=["#4299e1"],
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "#e2e8f0"},
                margin={"l": 10, "r": 10, "t": 10, "b": 10},
                height=260,
                xaxis={"title": "Chunks", "gridcolor": "#2d3748"},
                yaxis={"title": ""},
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No chunks yet — run a knowledge sync.")

    # ── By theme ──────────────────────────────────────────────────────────────
    with col_right:
        icons.section_header("filter", "Chunks by Theme")
        by_theme = health.get("by_theme", {})
        if by_theme:
            fig = px.pie(
                names=[k.replace("_", " ").title() for k in by_theme.keys()],
                values=list(by_theme.values()),
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font={"color": "#e2e8f0"},
                margin={"l": 0, "r": 0, "t": 10, "b": 0},
                height=260,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No theme data yet.")

    st.divider()

    # ── Sync controls ─────────────────────────────────────────────────────────
    icons.section_header("refresh-cw", "Sync Controls")
    sc1, sc2, sc3 = st.columns(3)
    if sc1.button("Sync Notion", use_container_width=True):
        with st.spinner("Syncing Notion…"):
            ok = _trigger_sync("notion")
        st.success("Notion sync triggered!") if ok else st.error("Sync failed")

    if sc2.button("Sync Google Drive", use_container_width=True):
        with st.spinner("Syncing Drive…"):
            ok = _trigger_sync("drive")
        st.success("Drive sync triggered!") if ok else st.error("Sync failed")

    if sc3.button("Full Sync", type="primary", use_container_width=True):
        with st.spinner("Running full sync…"):
            ok = _trigger_sync("all")
        st.success("Full sync triggered!") if ok else st.error("Sync failed")

    st.divider()

    # ── Sync history ──────────────────────────────────────────────────────────
    icons.section_header("clock", "Recent Sync Runs")

    # Filter controls
    log_view = st.radio("Log view", ["Timeline", "Table"],
                        horizontal=True, label_visibility="collapsed",
                        key="kb_log_view")

    logs = get_sync_logs(10)
    if not logs:
        st.info("No sync runs yet.")
        return

    if log_view == "Table":
        import pandas as pd
        rows = []
        for log in logs:
            rows.append({
                "Time":     log.get("synced_at", "")[:16],
                "Source":   log.get("source", "all"),
                "Notion":   log.get("notion_pages", 0),
                "Drive":    log.get("drive_files", 0),
                "Chunks":   log.get("total_chunks", 0),
                "Duration": f"{log.get('duration_seconds', 0)}s",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        for log in logs:
            ts = log.get("synced_at", "")[:16]
            notion_c = log.get("notion_pages", 0)
            drive_c = log.get("drive_files", 0)
            chunks = log.get("total_chunks", 0)
            duration = log.get("duration_seconds", 0)
            st.markdown(
                f"<div class='activity-item'>"
                f"<div class='activity-icon'>{icons.svg('refresh-cw',14,'var(--accent)')}</div>"
                f"<div>"
                f"<span style='color:var(--text);font-weight:500;'>{ts}</span>"
                f"<span style='color:var(--text-3);font-size:0.82em;'> — "
                f"{notion_c} Notion · {drive_c} Drive → <b style='color:var(--text-2);'>{chunks} chunks</b>"
                f" ({duration}s)</span>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
