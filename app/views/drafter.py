"""View 4 — Drafter: section-by-section review of active draft applications."""
from __future__ import annotations

import os

import httpx
import streamlit as st

from app.db.queries import get_active_drafts, get_thread_interrupt
from app.ui import icons

RAILWAY_URL = os.environ.get("RAILWAY_URL", "http://localhost:8000")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")


def _resume_section(thread_id: str, section_name: str, action: str,
                    edited_content: str = "", instructions: str = ""):
    try:
        r = httpx.post(
            f"{RAILWAY_URL}/resume/section-review",
            json={
                "thread_id": thread_id,
                "section_name": section_name,
                "action": action,
                "edited_content": edited_content,
                "instructions": instructions,
            },
            headers={"x-internal-secret": INTERNAL_SECRET},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception as e:
        st.error(f"Failed to resume graph: {e}")
        return False


def _start_draft(grant_id: str):
    try:
        r = httpx.post(
            f"{RAILWAY_URL}/resume/start-draft",
            json={"grant_id": grant_id},
            headers={"x-internal-secret": INTERNAL_SECRET},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception as e:
        st.error(f"Failed to start draft: {e}")
        return False


def _download_draft(thread_id: str) -> str:
    try:
        r = httpx.get(
            f"{RAILWAY_URL}/drafts/{thread_id}/download",
            headers={"x-internal-secret": INTERNAL_SECRET},
            timeout=10.0,
        )
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def render():
    icons.page_header("pen-line", "Drafter", "Section-by-section review of active grant applications")

    drafts = get_active_drafts()

    if not drafts:
        st.markdown(
            f"<div style='background:var(--bg-card);border:1px solid var(--border);border-radius:10px;"
            f"padding:20px;display:flex;gap:12px;align-items:flex-start;'>"
            f"{icons.svg('info',20,'var(--accent)')}"
            f"<div><div style='color:var(--text);font-weight:500;margin-bottom:4px;'>No active drafts</div>"
            f"<div style='color:var(--text-3);font-size:0.88em;'>Go to the Triage Queue, approve a grant, then click Start Draft.</div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        return

    # ── Filter bar ────────────────────────────────────────────────────────────
    df1, df2 = st.columns([3, 1])
    with df2:
        status_filter = st.selectbox(
            "Filter", ["All", "Drafting", "Complete"],
            label_visibility="collapsed", key="drafter_status_filter",
        )

    if status_filter == "Drafting":
        drafts = [d for d in drafts if d.get("status") == "drafting"]
    elif status_filter == "Complete":
        drafts = [d for d in drafts if d.get("status") == "draft_complete"]

    with df1:
        st.markdown(
            f"<p style='color:var(--text-3);font-size:0.85em;margin-bottom:0;'>"
            f"{icons.svg('pen-line',13,'var(--text-3)')} "
            f"<b style='color:var(--text-2);'>{len(drafts)}</b> active draft(s)</p>",
            unsafe_allow_html=True,
        )

    if not drafts:
        st.info("No drafts match the filter.")
        return

    # ── Draft selector ────────────────────────────────────────────────────────
    draft_options = {
        f"{d['grant_title']} (v{d.get('current_draft_version', 0)})": d
        for d in drafts
    }
    selected_label = st.selectbox("Active drafts", list(draft_options.keys()))
    active = draft_options[selected_label]
    thread_id = active.get("thread_id", "")
    grant_title = active.get("grant_title", "")
    status = active.get("status", "")

    st.markdown(
        icons.meta_chip("git-branch", f"Thread: {thread_id}", "var(--text-4)") +
        icons.status_badge(status),
        unsafe_allow_html=True,
    )

    # ── Progress bar ──────────────────────────────────────────────────────────
    latest_draft = active.get("latest_draft") or {}
    approved = latest_draft.get("sections", {})
    total_sections = max(len(approved) + 1, 5)
    progress = len(approved) / total_sections
    st.progress(progress, text=f"{len(approved)}/{total_sections} sections approved")

    if approved:
        with st.expander(f"{len(approved)} approved sections"):
            for sec_name, sec_data in approved.items():
                wc = sec_data.get("word_count", 0)
                wl = sec_data.get("word_limit", 500)
                ok = sec_data.get("within_limit", True)
                color = "var(--green)" if ok else "var(--red)"
                icon_name = "check-circle" if ok else "alert-circle"
                st.markdown(
                    f"{icons.svg(icon_name,14,color)} "
                    f"<span style='color:var(--text);font-weight:500;'>{sec_name}</span> "
                    f"<span style='color:var(--text-4);font-size:0.82em;'>{wc}/{wl} words</span>",
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── Complete draft download ────────────────────────────────────────────────
    if status == "draft_complete":
        st.markdown(
            f"<div style='background:var(--green-bg);border:1px solid var(--green-border);border-radius:10px;"
            f"padding:16px 20px;display:flex;gap:10px;align-items:center;margin-bottom:16px;'>"
            f"{icons.svg('award',20,'var(--green)')}"
            f"<span style='color:var(--green-2);font-weight:600;'>All sections approved! Draft is ready for download.</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        md_content = _download_draft(thread_id)
        if md_content:
            st.download_button(
                "Download Draft (.md)",
                data=md_content,
                file_name=f"{grant_title[:40].replace(' ', '_')}.md",
                mime="text/markdown",
                type="primary",
            )
            with st.expander("Preview (first 2000 chars)"):
                st.markdown(md_content[:2000])
        return

    # ── Current section in review ─────────────────────────────────────────────
    interrupt = get_thread_interrupt(thread_id)

    if not interrupt:
        st.markdown(
            f"<div style='background:var(--bg-card);border:1px solid var(--border);border-radius:10px;"
            f"padding:16px;display:flex;gap:10px;align-items:center;'>"
            f"{icons.svg('loader',18,'var(--accent)')}"
            f"<span style='color:var(--accent);'>Waiting for drafter to write the next section…</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("Refresh"):
            st.rerun()
        return

    section_name = interrupt.get("section_name", "Section")
    content = interrupt.get("content", "")
    word_count = interrupt.get("word_count", 0)
    word_limit = interrupt.get("word_limit", 500)
    within_limit = interrupt.get("within_limit", True)
    evidence_gaps = interrupt.get("evidence_gaps", [])

    wc_color = "var(--green)" if within_limit else "var(--red)"
    wc_icon = "check-circle" if within_limit else "alert-circle"
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:12px;'>"
        f"{icons.svg('file-text',20,'var(--accent)')}"
        f"<span style='font-size:1.1rem;font-weight:600;color:var(--text);'>{section_name}</span>"
        f"<span style='margin-left:auto;display:flex;align-items:center;gap:5px;color:{wc_color};font-size:0.85em;'>"
        f"{icons.svg(wc_icon,14,wc_color)} {word_count} / {word_limit} words"
        f"{'  ✓' if within_limit else '  OVER LIMIT'}"
        f"</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if evidence_gaps:
        with st.expander(f"{len(evidence_gaps)} evidence gap(s)"):
            for gap in evidence_gaps:
                st.markdown(
                    f"<div style='display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-subtle);'>"
                    f"{icons.svg('alert-triangle',13,'var(--orange)')}"
                    f"<span style='color:var(--text);font-size:0.88em;'>{gap}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    edited = st.text_area(
        "Draft content (you can edit directly)",
        value=content,
        height=400,
        key=f"content_{section_name}_{thread_id}",
    )

    approve_col, revise_col = st.columns(2)

    with approve_col:
        if st.button("Approve Section", type="primary", key=f"approve_{thread_id}"):
            with st.spinner("Saving approval…"):
                ok = _resume_section(thread_id, section_name, "approve", edited_content=edited)
            if ok:
                st.success(f"{section_name} approved!")
                st.rerun()

    with revise_col:
        with st.expander("Request Revision"):
            revision_note = st.text_area(
                "Revision instructions",
                placeholder="e.g. 'Add more specific metrics about our MRV accuracy.'",
                key=f"revision_{thread_id}",
            )
            if st.button("Send Revision Request", key=f"send_revision_{thread_id}"):
                if revision_note.strip():
                    with st.spinner("Sending revision instructions…"):
                        ok = _resume_section(thread_id, section_name, "revise",
                                             instructions=revision_note, edited_content=edited)
                    if ok:
                        st.info("Revision request sent. Drafter is rewriting…")
                        st.rerun()
                else:
                    st.warning("Please add revision instructions before sending.")
