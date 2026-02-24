"""View 3 — Triage Queue: primary daily-use view for pursue / watch / pass decisions."""
from __future__ import annotations

import os

import httpx
import streamlit as st

from app.db.queries import get_triage_queue, update_grant_status, report_grant, REPORT_REASONS
from app.ui import icons
from app.ui.filters import (
    AMOUNT_OPTIONS, DEADLINE_OPTIONS,
    amount_bucket_to_range, apply_deadline_filter,
    filter_amount_not_specified, active_filter_labels,
)

RAILWAY_URL     = os.environ.get("RAILWAY_URL", "http://localhost:8000")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")

THEME_LABELS = {
    "climatetech":            "Climate Tech",
    "agritech":               "Agri Tech",
    "ai_for_sciences":        "AI for Sciences",
    "applied_earth_sciences": "Earth Sciences",
    "social_impact":          "Social Impact",
}

GRANT_TYPES = ["grant", "prize", "challenge", "accelerator", "fellowship",
               "contract", "loan", "equity", "other"]


def _post_triage_decision(thread_id: str, grant_id: str, decision: str, notes: str = ""):
    try:
        r = httpx.post(
            f"{RAILWAY_URL}/resume/triage",
            json={"thread_id": thread_id, "grant_id": grant_id,
                  "decision": decision, "notes": notes},
            headers={"x-internal-secret": INTERNAL_SECRET},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception as e:
        st.error(f"Failed to resume graph: {e}")
        return False


def _fmt_amount(g: dict) -> str:
    if g.get("amount"):
        return g["amount"]
    amt = g.get("max_funding")
    cur = g.get("currency", "USD")
    if not amt:
        return "Not specified"
    return f"${amt:,.0f}" if cur == "USD" else f"{amt:,.0f} {cur}"


def render():
    icons.page_header("zap", "Triage Queue",
                      "Review AI-scored opportunities and decide: Pursue · Watch · Pass")

    # ── Row 1: primary filters ─────────────────────────────────────────────────
    f1, f2, f3, f4, f5 = st.columns([2.5, 1.4, 1.4, 1.2, 0.9])
    with f1:
        search = st.text_input("Search", placeholder="Search title, funder, geography…",
                               label_visibility="collapsed", key="triage_search")
    with f2:
        theme_options = ["All themes"] + list(THEME_LABELS.keys())
        theme_filter = st.selectbox("Theme", theme_options,
                                    label_visibility="collapsed", key="triage_theme",
                                    format_func=lambda x: THEME_LABELS.get(x, x) if x != "All themes" else x)
        theme_filter = "" if theme_filter == "All themes" else theme_filter
    with f3:
        type_options = ["All types"] + GRANT_TYPES
        type_filter = st.selectbox("Type", type_options,
                                   label_visibility="collapsed", key="triage_type")
        type_filter = "" if type_filter == "All types" else type_filter
    with f4:
        min_score = st.slider("Min score", 0.0, 10.0, 0.0, step=0.5,
                              key="triage_min_score", label_visibility="collapsed",
                              help="Minimum AI score (0 = show all)")
    with f5:
        layout = st.radio("View", ["Cards", "Table"],
                          horizontal=True, label_visibility="collapsed",
                          key="triage_layout")

    # ── Row 2: amount + deadline filters ──────────────────────────────────────
    a1, a2, a3, a4 = st.columns([0.6, 1.5, 0.6, 1.8])
    with a1:
        st.markdown(
            f"<div style='color:var(--text-3);font-size:0.78em;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.06em;padding-top:8px;'>"
            f"{icons.svg('banknote',13,'var(--text-3)')} Amount</div>",
            unsafe_allow_html=True,
        )
    with a2:
        amount_filter = st.selectbox("Amount", AMOUNT_OPTIONS,
                                     label_visibility="collapsed", key="triage_amount")
    with a3:
        st.markdown(
            f"<div style='color:var(--text-3);font-size:0.78em;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.06em;padding-top:8px;'>"
            f"{icons.svg('calendar',13,'var(--text-3)')} Deadline</div>",
            unsafe_allow_html=True,
        )
    with a4:
        deadline_filter = st.selectbox("Deadline", DEADLINE_OPTIONS,
                                       label_visibility="collapsed", key="triage_deadline")

    # ── Resolve amount → MongoDB range ─────────────────────────────────────────
    min_funding, max_funding = amount_bucket_to_range(amount_filter)

    grants = get_triage_queue(
        search=search,
        theme_filter=theme_filter,
        grant_type_filter=type_filter,
        min_score=min_score,
        min_funding=min_funding,
        max_funding=max_funding,
    )

    # Client-side filters
    if amount_filter == "Not specified":
        grants = filter_amount_not_specified(grants, amount_filter)
    grants = apply_deadline_filter(grants, deadline_filter)

    # ── Active filter chips ────────────────────────────────────────────────────
    active = active_filter_labels("", theme_filter, "", type_filter,
                                  amount_filter, deadline_filter, min_score)
    if search:
        active.insert(0, 'Search: "' + search + '"')

    if active:
        chip_html = "".join(
            f"<span style='background:var(--accent-bg);color:var(--accent);"
            f"border:1px solid var(--accent-border);border-radius:20px;"
            f"padding:2px 10px;font-size:0.78em;margin-right:6px;'>{lbl}</span>"
            for lbl in active
        )
        st.markdown(
            f"<div style='margin-bottom:8px;'>{chip_html}</div>",
            unsafe_allow_html=True,
        )

    if not grants:
        any_filter = search or theme_filter or type_filter or min_score or \
                     amount_filter != "Any amount" or deadline_filter != "Any deadline"
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;"
            f"background:var(--green-bg);border:1px solid var(--green-border);"
            f"border-radius:10px;padding:16px 20px;'>"
            f"{icons.svg('check-circle', 20, 'var(--green)')}"
            f"<span style='color:var(--green-2);font-weight:500;'>"
            f"{'No grants match the active filters.' if any_filter else 'Triage queue is empty — all grants have been reviewed.'}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
        return

    # ── Counts + batch actions ─────────────────────────────────────────────────
    col_meta, col_batch = st.columns([3, 1])
    with col_meta:
        st.markdown(
            f"<p style='color:var(--text-3);font-size:0.85em;margin-bottom:4px;'>"
            f"{icons.svg('inbox',14,'var(--text-3)')} "
            f"<b style='color:var(--text-2);'>{len(grants)}</b> grants awaiting review — ranked by score"
            f"</p>",
            unsafe_allow_html=True,
        )
    with col_batch:
        with st.popover("Batch Actions", use_container_width=True):
            auto_threshold = st.slider(
                "Auto-pursue grants scoring above:",
                min_value=5.0, max_value=10.0, value=8.0, step=0.1,
                key="batch_threshold",
            )
            auto_candidates = [g for g in grants if g.get("weighted_total", 0) >= auto_threshold]
            st.markdown(
                f"{icons.svg('zap',14,'var(--accent)')} "
                f"<span style='color:var(--accent);font-size:0.88em;'>"
                f"<b>{len(auto_candidates)}</b> grants would be auto-pursued</span>",
                unsafe_allow_html=True,
            )
            if st.button(f"Auto-pursue {len(auto_candidates)} grants",
                         type="primary", key="batch_pursue"):
                for g in auto_candidates:
                    update_grant_status(g["_id"], "pursue")
                st.success(f"Marked {len(auto_candidates)} grants as pursue")
                st.rerun()

    st.divider()

    if layout == "Cards":
        _render_cards(grants)
    else:
        _render_table(grants)


# ── Cards view ────────────────────────────────────────────────────────────────

def _render_cards(grants: list):
    for g in grants:
        grant_id   = g["_id"]
        score      = g.get("weighted_total", 0)
        rec_action = g.get("recommended_action", "")
        grant_type = g.get("grant_type", "grant")
        geography  = g.get("geography") or "Not specified"
        deadline   = g.get("deadline") or "Not specified"
        amount     = _fmt_amount(g)
        source_url = g.get("url", "")
        apply_url  = g.get("application_url") or source_url
        themes     = g.get("themes_detected", [])

        with st.container(border=True):

            # ── Row 1: Title + score + AI rec ─────────────────────────────────
            title_col, score_col, rec_col = st.columns([4, 1, 1.6])

            with title_col:
                st.markdown(
                    f"<div style='font-size:1.12rem;font-weight:700;"
                    f"color:var(--text);line-height:1.3;'>{g.get('title','Untitled Grant')}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='margin-top:4px;display:flex;flex-wrap:wrap;gap:6px;"
                    f"align-items:center;'>"
                    f"{icons.svg('users',13,'var(--text-3)')}"
                    f"<span style='color:var(--text-3);font-size:0.85em;'>"
                    f"{g.get('funder','Unknown')}</span>"
                    f"&nbsp;&nbsp;{icons.grant_type_badge(grant_type)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            with score_col:
                st.markdown(
                    f"<div style='text-align:center;'>"
                    f"<div style='font-size:0.68em;color:var(--text-3);font-weight:700;"
                    f"text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;'>Score</div>"
                    f"{icons.score_badge(score)}"
                    f"<div style='font-size:0.68em;color:var(--text-4);margin-top:2px;'>/ 10</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            with rec_col:
                st.markdown(
                    f"<div style='text-align:center;'>"
                    f"<div style='font-size:0.68em;color:var(--text-3);font-weight:700;"
                    f"text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;'>AI Rec</div>"
                    f"{icons.recommendation_badge(rec_action)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # ── Row 2: Key meta chips ──────────────────────────────────────────
            st.markdown(
                icons.meta_chip("banknote", amount, "var(--green)") +
                icons.meta_chip("calendar", deadline) +
                icons.meta_chip("globe", geography, "var(--accent)"),
                unsafe_allow_html=True,
            )

            # ── Theme chips ───────────────────────────────────────────────────
            if themes:
                st.markdown(
                    "  ".join(
                        f"<span style='font-size:0.75em;background:var(--bg-elevated);"
                        f"color:var(--text-3);border-radius:4px;padding:2px 7px;'>"
                        f"{THEME_LABELS.get(t, t.replace('_',' '))}</span>"
                        for t in themes
                    ),
                    unsafe_allow_html=True,
                )

            # ── Rationale callout ─────────────────────────────────────────────
            if g.get("rationale"):
                st.markdown(icons.rationale_box(g["rationale"]), unsafe_allow_html=True)
            elif g.get("reasoning"):
                st.markdown(
                    f"<div style='background:var(--bg-elevated);border:1px solid var(--border);"
                    f"border-radius:8px;padding:12px 14px;margin:8px 0;font-size:0.87em;"
                    f"color:var(--text-2);'>"
                    f"{icons.svg('info',14,'var(--text-3)')} {g['reasoning']}</div>",
                    unsafe_allow_html=True,
                )

            # ── Links row ─────────────────────────────────────────────────────
            link_col1, link_col2 = st.columns(2)
            with link_col1:
                st.markdown(
                    f"{icons.svg('external-link',13,'var(--text-3)')} "
                    f"[View source page]({source_url})",
                    unsafe_allow_html=True,
                )
            with link_col2:
                if apply_url and apply_url != source_url:
                    st.markdown(
                        f"{icons.svg('send',13,'var(--green)')} "
                        f"[**Apply now →**]({apply_url})",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"{icons.svg('send',13,'var(--green)')} "
                        f"[Apply / Learn more]({source_url})",
                        unsafe_allow_html=True,
                    )

            # ── Score breakdown expander ───────────────────────────────────────
            with st.expander("Score breakdown · Eligibility · Evidence"):

                if g.get("eligibility"):
                    st.markdown(icons.eligibility_box(g["eligibility"]),
                                unsafe_allow_html=True)

                scores = g.get("scores", {})
                if scores:
                    st.markdown(
                        f"<div style='font-size:0.78em;font-weight:700;"
                        f"color:var(--text-3);text-transform:uppercase;"
                        f"letter-spacing:0.07em;margin:12px 0 6px;'>Score breakdown</div>",
                        unsafe_allow_html=True,
                    )
                    score_cols = st.columns(3)
                    for i, (dim, val) in enumerate(scores.items()):
                        score_cols[i % 3].metric(
                            dim.replace("_", " ").title(), f"{val}/10"
                        )

                if g.get("funder_context"):
                    st.markdown(
                        f"<div style='background:var(--bg-elevated);"
                        f"border-radius:8px;padding:10px 12px;margin:10px 0;"
                        f"font-size:0.84em;color:var(--text-2);'>"
                        f"{icons.svg('info',13,'var(--text-3)')} "
                        f"<b>Funder context:</b> {g['funder_context']}</div>",
                        unsafe_allow_html=True,
                    )

                if g.get("evidence_found"):
                    st.markdown(
                        f"<div style='margin:8px 0;'>"
                        f"{icons.svg('check-circle',14,'var(--green)')} "
                        f"<span style='color:var(--green);font-weight:600;"
                        f"font-size:0.85em;'>Evidence of fit:</span></div>",
                        unsafe_allow_html=True,
                    )
                    for e in g["evidence_found"]:
                        st.markdown(f"  - {e}")

                if g.get("evidence_gaps"):
                    st.markdown(
                        f"<div style='margin:8px 0;'>"
                        f"{icons.svg('alert-triangle',14,'var(--orange)')} "
                        f"<span style='color:var(--orange);font-weight:600;"
                        f"font-size:0.85em;'>Evidence gaps:</span></div>",
                        unsafe_allow_html=True,
                    )
                    for e in g["evidence_gaps"]:
                        st.markdown(f"  - {e}")

                if g.get("red_flags"):
                    st.markdown(
                        f"<div style='background:var(--red-bg);"
                        f"border:1px solid var(--red-border);border-radius:8px;"
                        f"padding:10px 12px;display:flex;gap:8px;align-items:flex-start;'>"
                        f"{icons.svg('flag',15,'var(--red)')}"
                        f"<span style='color:var(--red);font-size:0.85em;'>"
                        + "; ".join(g["red_flags"])
                        + "</span></div>",
                        unsafe_allow_html=True,
                    )

            # ── Decision buttons ───────────────────────────────────────────────
            dec1, dec2, dec3, rep_col, notes_col = st.columns([1, 1, 1, 1, 2.5])
            notes_key = f"notes_{grant_id}"
            notes = st.session_state.get(notes_key, "")

            with notes_col:
                note_input = st.text_input(
                    "Note", key=f"note_input_{grant_id}",
                    label_visibility="collapsed",
                    placeholder="Add a note…",
                )
                if note_input:
                    st.session_state[notes_key] = note_input

            thread_id = f"scout_{grant_id[:8]}"

            if dec1.button("Pursue", key=f"pursue_{grant_id}", type="primary",
                           use_container_width=True):
                update_grant_status(grant_id, "pursue")
                _post_triage_decision(thread_id, grant_id, "pursue", notes)
                st.success("Marked as Pursue")
                st.rerun()

            if dec2.button("Watch", key=f"watch_{grant_id}",
                           use_container_width=True):
                update_grant_status(grant_id, "watch")
                _post_triage_decision(thread_id, grant_id, "watch", notes)
                st.info("Marked as Watch")
                st.rerun()

            if dec3.button("Pass", key=f"pass_{grant_id}",
                           use_container_width=True):
                update_grant_status(grant_id, "passed")
                _post_triage_decision(thread_id, grant_id, "pass", notes)
                st.warning("Marked as Passed")
                st.rerun()

            with rep_col:
                with st.popover("Report", use_container_width=True):
                    st.markdown(
                        f"{icons.svg('flag',16,'var(--orange)')} "
                        f"**Why are you reporting this?**",
                        unsafe_allow_html=True,
                    )
                    reason = st.selectbox(
                        "Reason", REPORT_REASONS,
                        key=f"report_reason_{grant_id}",
                        label_visibility="collapsed",
                    )
                    report_note = st.text_input(
                        "Details (optional)",
                        key=f"report_note_{grant_id}",
                        placeholder="Add more detail…",
                    )
                    if st.button("Submit Report",
                                 key=f"report_submit_{grant_id}", type="primary"):
                        report_grant(grant_id, reason, report_note)
                        st.rerun()

        st.divider()


# ── Table view ────────────────────────────────────────────────────────────────

def _render_table(grants: list):
    import pandas as pd

    rows = []
    for g in grants:
        rows.append({
            "Title":      g.get("title", "Untitled")[:60],
            "Funder":     g.get("funder", "–"),
            "Type":       (g.get("grant_type") or "–").title(),
            "Score":      round(g.get("weighted_total", 0), 2),
            "AI Rec":     g.get("recommended_action", "–"),
            "Geography":  g.get("geography") or "–",
            "Amount":     _fmt_amount(g),
            "Deadline":   g.get("deadline") or "–",
            "Themes":     " · ".join(g.get("themes_detected", [])),
            "_id":        g["_id"],
        })

    df = pd.DataFrame(rows)

    def _score_bg(val):
        if val >= 7.5: return "background:var(--green-bg);color:var(--green);font-weight:700"
        if val >= 6.5: return "background:#1c3a2d;color:#68d391;font-weight:700"
        if val >= 5.0: return "background:var(--orange-bg);color:var(--orange);font-weight:700"
        return "background:var(--red-bg);color:var(--red);font-weight:700"

    st.dataframe(
        df.drop(columns=["_id"]).style.applymap(_score_bg, subset=["Score"]),
        use_container_width=True,
        height=min(60 + len(rows) * 38, 680),
    )

    # Per-row actions
    st.markdown("---")
    icons.section_header("zap", "Decision")
    titles = [f"{r['Title'][:50]}  —  {r['Funder']}" for r in rows]
    sel = st.selectbox("Select a grant to decide on", range(len(rows)),
                       format_func=lambda i: titles[i],
                       label_visibility="collapsed",
                       key="triage_table_sel")

    if sel is not None:
        g = grants[sel]
        grant_id = g["_id"]
        thread_id = f"scout_{grant_id[:8]}"
        notes_key = f"tbl_notes_{grant_id}"

        # Show rationale + eligibility
        if g.get("rationale"):
            st.markdown(icons.rationale_box(g["rationale"]), unsafe_allow_html=True)
        if g.get("eligibility"):
            st.markdown(icons.eligibility_box(g["eligibility"]), unsafe_allow_html=True)

        source_url = g.get("url", "")
        apply_url  = g.get("application_url") or source_url
        lc1, lc2 = st.columns(2)
        lc1.markdown(
            f"{icons.svg('external-link',13,'var(--text-3)')} [Source page]({source_url})",
            unsafe_allow_html=True,
        )
        if apply_url and apply_url != source_url:
            lc2.markdown(
                f"{icons.svg('send',13,'var(--green)')} [**Apply now →**]({apply_url})",
                unsafe_allow_html=True,
            )

        note_input = st.text_input("Note (optional)", key=f"tbl_note_{grant_id}",
                                   placeholder="Add a note…")
        if note_input:
            st.session_state[notes_key] = note_input
        notes = st.session_state.get(notes_key, "")

        ac1, ac2, ac3, ac4 = st.columns(4)
        if ac1.button("Pursue", key=f"tbl_pursue_{grant_id}", type="primary",
                      use_container_width=True):
            update_grant_status(grant_id, "pursue")
            _post_triage_decision(thread_id, grant_id, "pursue", notes)
            st.success("Marked as Pursue")
            st.rerun()
        if ac2.button("Watch", key=f"tbl_watch_{grant_id}",
                      use_container_width=True):
            update_grant_status(grant_id, "watch")
            _post_triage_decision(thread_id, grant_id, "watch", notes)
            st.info("Marked as Watch")
            st.rerun()
        if ac3.button("Pass", key=f"tbl_pass_{grant_id}",
                      use_container_width=True):
            update_grant_status(grant_id, "passed")
            _post_triage_decision(thread_id, grant_id, "pass", notes)
            st.warning("Marked as Passed")
            st.rerun()
        with ac4:
            with st.popover("Report", use_container_width=True):
                reason = st.selectbox("Reason", REPORT_REASONS,
                                      key=f"tbl_rep_r_{grant_id}",
                                      label_visibility="collapsed")
                rep_note = st.text_input("Details", key=f"tbl_rep_n_{grant_id}",
                                         placeholder="Add more detail…")
                if st.button("Submit", key=f"tbl_rep_s_{grant_id}", type="primary"):
                    report_grant(grant_id, reason, rep_note)
                    st.rerun()
