"""View 2 — Grants Pipeline: List · Table · Kanban with full new field display."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db.queries import (
    export_grants_csv,
    get_all_pipeline_grants,
    report_grant,
    update_grant_status,
    REPORT_REASONS,
)
from app.ui import icons
from app.ui.filters import (
    AMOUNT_OPTIONS, DEADLINE_OPTIONS,
    amount_bucket_to_range, apply_deadline_filter,
    filter_amount_not_specified, active_filter_labels,
)

KANBAN_STAGES = ["triage", "pursue", "pursuing", "drafting", "draft_complete",
                 "submitted", "won", "passed"]
ALL_STATUSES  = KANBAN_STAGES + ["auto_pass", "reported"]
_HIDDEN       = {"reported"}

THEME_LABELS = {
    "climatetech":            "Climate Tech",
    "agritech":               "Agri Tech",
    "ai_for_sciences":        "AI for Sciences",
    "applied_earth_sciences": "Earth Sciences",
    "social_impact":          "Social Impact",
}

GRANT_TYPES = ["grant", "prize", "challenge", "accelerator", "fellowship",
               "contract", "loan", "equity", "other"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_amount(g: dict) -> str:
    """Return the raw amount string if available, else format max_funding."""
    if g.get("amount"):
        return g["amount"]
    amt = g.get("max_funding")
    cur = g.get("currency", "USD")
    if not amt:
        return "Not specified"
    return f"${amt:,.0f}" if cur == "USD" else f"{amt:,.0f} {cur}"


def _geography(g: dict) -> str:
    return g.get("geography") or "Not specified"


def _themes_html(themes: list) -> str:
    return "  ".join(
        f"<span style='font-size:0.75em;background:var(--bg-elevated);"
        f"color:var(--text-3);border-radius:4px;padding:2px 7px;'>"
        f"{THEME_LABELS.get(t, t.replace('_', ' '))}</span>"
        for t in themes
    )


def _move_selectbox(g: dict, key_suffix: str):
    current = g.get("status", "triage")
    options = [s for s in KANBAN_STAGES if s != current]
    choice = st.selectbox(
        "Move to", options, index=None, placeholder="Move to…",
        key=f"move_{g['_id']}_{key_suffix}", label_visibility="collapsed",
    )
    if choice:
        update_grant_status(g["_id"], choice)
        st.rerun()


def _report_popover(g: dict, key_suffix: str):
    with st.popover("Report"):
        reason = st.selectbox("Reason", REPORT_REASONS,
                              key=f"rep_r_{g['_id']}_{key_suffix}",
                              label_visibility="collapsed")
        note = st.text_input("Note (optional)", key=f"rep_n_{g['_id']}_{key_suffix}",
                             placeholder="e.g. this is a news article")
        if st.button("Submit", key=f"rep_s_{g['_id']}_{key_suffix}", type="primary"):
            report_grant(g["_id"], reason, note)
            st.rerun()


# ── Page ──────────────────────────────────────────────────────────────────────

def render():
    icons.page_header("git-branch", "Grants Pipeline",
                      "Full visibility across all tracked opportunities")

    # ── Row 1: primary filters ─────────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1.2, 1.2, 1.2, 1.5, 0.7])
    with c1:
        search = st.text_input("Search", placeholder="Search title, funder, geography…",
                               label_visibility="collapsed", key="pipe_search")
    with c2:
        theme_options = ["All themes"] + list(THEME_LABELS.keys())
        theme_filter = st.selectbox("Theme", theme_options, label_visibility="collapsed",
                                    key="pipe_theme",
                                    format_func=lambda x: THEME_LABELS.get(x, x) if x != "All themes" else x)
        theme_filter = "" if theme_filter == "All themes" else theme_filter
    with c3:
        status_options = ["All statuses"] + ALL_STATUSES
        status_filter = st.selectbox("Status", status_options, label_visibility="collapsed",
                                     key="pipe_status")
        status_filter = "" if status_filter == "All statuses" else status_filter
    with c4:
        type_options = ["All types"] + GRANT_TYPES
        type_filter = st.selectbox("Type", type_options, label_visibility="collapsed",
                                   key="pipe_type")
        type_filter = "" if type_filter == "All types" else type_filter
    with c5:
        layout = st.radio("Layout", ["List", "Table", "Kanban"],
                          horizontal=True, label_visibility="collapsed", key="pipe_layout")
    with c6:
        csv = export_grants_csv()
        if csv:
            st.download_button("⬇ CSV", csv, "grants.csv", "text/csv",
                               use_container_width=True)

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
                                     label_visibility="collapsed", key="pipe_amount")
    with a3:
        st.markdown(
            f"<div style='color:var(--text-3);font-size:0.78em;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.06em;padding-top:8px;'>"
            f"{icons.svg('calendar',13,'var(--text-3)')} Deadline</div>",
            unsafe_allow_html=True,
        )
    with a4:
        deadline_filter = st.selectbox("Deadline", DEADLINE_OPTIONS,
                                       label_visibility="collapsed", key="pipe_deadline")

    # ── Resolve amount → MongoDB range ─────────────────────────────────────────
    min_funding, max_funding = amount_bucket_to_range(amount_filter)

    grants = get_all_pipeline_grants(
        search=search,
        theme_filter=theme_filter,
        status_filter=status_filter,
        grant_type_filter=type_filter,
        min_funding=min_funding,
        max_funding=max_funding,
    )

    # Client-side filters (deadline + "not specified" amount)
    if amount_filter == "Not specified":
        grants = filter_amount_not_specified(grants, amount_filter)
    grants = apply_deadline_filter(grants, deadline_filter)

    if status_filter != "reported":
        grants = [g for g in grants if g.get("status") not in _HIDDEN]

    # ── Active filter chips ────────────────────────────────────────────────────
    active = active_filter_labels(search, theme_filter, status_filter, type_filter,
                                  amount_filter, deadline_filter)
    reported_count = sum(
        1 for g in get_all_pipeline_grants() if g.get("status") == "reported"
    )

    chip_html = "".join(
        f"<span style='background:var(--accent-bg);color:var(--accent);border:1px solid var(--accent-border);"
        f"border-radius:20px;padding:2px 10px;font-size:0.78em;margin-right:6px;'>{lbl}</span>"
        for lbl in active
    )
    meta_parts = [f"<b style='color:var(--text-2);'>{len(grants)}</b> grants"]
    if reported_count and status_filter != "reported":
        meta_parts.append(f"{reported_count} reported (hidden)")
    st.markdown(
        f"<div style='display:flex;align-items:center;flex-wrap:wrap;gap:6px;"
        f"margin-bottom:12px;font-size:0.85em;color:var(--text-3);'>"
        f"{'  ·  '.join(meta_parts)}"
        f"{'  &nbsp;' + chip_html if chip_html else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not grants:
        st.info("No grants match the current filters. Try broadening your search.")
        return

    if layout == "List":
        _render_list(grants)
    elif layout == "Table":
        _render_table(grants)
    else:
        _render_kanban(grants)


# ── List view ─────────────────────────────────────────────────────────────────

def _render_list(grants: list):
    for g in grants:
        score    = g.get("weighted_total", 0)
        status   = g.get("status", "triage")
        themes   = g.get("themes_detected", [])
        deadline = g.get("deadline") or "Not specified"
        amount   = _fmt_amount(g)
        geography = _geography(g)
        grant_type = g.get("grant_type", "grant")

        with st.container(border=True):
            # ── Header row ────────────────────────────────────────────────────
            h1, h2, h3 = st.columns([4, 1.3, 1.7])
            with h1:
                st.markdown(
                    f"<div style='font-size:1.05rem;font-weight:700;"
                    f"color:var(--text);line-height:1.3;'>{g.get('title','Untitled')}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='color:var(--text-3);font-size:0.84em;margin-top:2px;'>"
                    f"{icons.svg('users',13,'var(--text-3)')} {g.get('funder','–')}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with h2:
                st.markdown(icons.score_badge(score), unsafe_allow_html=True)
            with h3:
                st.markdown(
                    icons.status_badge(status) + "&nbsp;&nbsp;" +
                    icons.grant_type_badge(grant_type),
                    unsafe_allow_html=True,
                )

            # ── Meta chips row ────────────────────────────────────────────────
            st.markdown(
                icons.meta_chip("calendar", deadline) +
                icons.meta_chip("banknote", amount, "var(--green)") +
                icons.meta_chip("globe", geography, "var(--accent)"),
                unsafe_allow_html=True,
            )

            # ── Theme chips ───────────────────────────────────────────────────
            if themes:
                st.markdown(_themes_html(themes), unsafe_allow_html=True)

            # ── Rationale callout (if available) ──────────────────────────────
            if g.get("rationale"):
                st.markdown(icons.rationale_box(g["rationale"]),
                            unsafe_allow_html=True)

            # ── Detail expander ───────────────────────────────────────────────
            with st.expander("Details & actions"):
                # Eligibility
                if g.get("eligibility"):
                    st.markdown(icons.eligibility_box(g["eligibility"]),
                                unsafe_allow_html=True)

                # Links
                source_url = g.get("url", "")
                apply_url  = g.get("application_url") or source_url
                link_row   = (
                    f"{icons.svg('external-link',13,'var(--text-3)')} "
                    f"[Source page]({source_url})"
                )
                if apply_url and apply_url != source_url:
                    link_row += (
                        f"&nbsp;&nbsp;|&nbsp;&nbsp;"
                        f"{icons.svg('send',13,'var(--green)')} "
                        f"[**Apply here**]({apply_url})"
                    )
                st.markdown(link_row, unsafe_allow_html=True)

                # Score reasoning
                if g.get("reasoning"):
                    st.markdown(
                        f"<div style='color:var(--text-2);font-size:0.87em;"
                        f"margin-top:10px;'><b>Analyst reasoning:</b> {g['reasoning']}</div>",
                        unsafe_allow_html=True,
                    )

                # Evidence
                if g.get("evidence_found"):
                    st.markdown(
                        f"<div style='margin:8px 0;'>"
                        f"{icons.svg('check-circle',13,'var(--green)')} "
                        f"<span style='color:var(--green);font-size:0.85em;font-weight:600;'>"
                        f"Evidence of fit:</span></div>",
                        unsafe_allow_html=True,
                    )
                    for e in g["evidence_found"][:5]:
                        st.markdown(f"  - {e}")

                # Red flags
                if g.get("red_flags"):
                    st.markdown(
                        f"<div style='background:var(--red-bg);border:1px solid var(--red-border);"
                        f"border-radius:8px;padding:10px 12px;margin:8px 0;'>"
                        f"{icons.svg('alert-triangle',14,'var(--red)')} "
                        f"<span style='color:var(--red);font-size:0.85em;'>"
                        + "; ".join(g["red_flags"]) + "</span></div>",
                        unsafe_allow_html=True,
                    )

                a1, a2, a3 = st.columns([2, 2, 1])
                with a1:
                    _move_selectbox(g, "list")
                with a3:
                    _report_popover(g, "list")


# ── Table view ────────────────────────────────────────────────────────────────

def _render_table(grants: list):
    rows = []
    for g in grants:
        rows.append({
            "Title":       g.get("title", "Untitled")[:60],
            "Funder":      g.get("funder", "–"),
            "Type":        (g.get("grant_type") or "–").title(),
            "Score":       round(g.get("weighted_total", 0), 2),
            "Status":      g.get("status", "–"),
            "Geography":   g.get("geography") or "–",
            "Amount":      _fmt_amount(g),
            "Deadline":    g.get("deadline") or "–",
            "Themes":      " · ".join(
                               THEME_LABELS.get(t, t) for t in g.get("themes_detected", [])
                           ),
            "AI Rec":      g.get("recommended_action", "–"),
            "_id":         g["_id"],
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
    icons.section_header("zap", "Grant Actions")
    titles = [f"{r['Title'][:50]}  —  {r['Funder']}" for r in rows]
    sel = st.selectbox("Select a grant to act on", range(len(rows)),
                       format_func=lambda i: titles[i],
                       label_visibility="collapsed")

    if sel is not None:
        g = grants[sel]
        ac1, ac2, ac3 = st.columns([2, 1.5, 1])
        with ac1:
            _move_selectbox(g, "table")
        with ac2:
            if st.button("Mark Passed", key=f"tbl_pass_{g['_id']}",
                         use_container_width=True):
                update_grant_status(g["_id"], "passed")
                st.rerun()
        with ac3:
            _report_popover(g, "table")

        with st.expander(f"Full detail: {g.get('title', '')[:60]}"):
            if g.get("rationale"):
                st.markdown(icons.rationale_box(g["rationale"]),
                            unsafe_allow_html=True)
            if g.get("eligibility"):
                st.markdown(icons.eligibility_box(g["eligibility"]),
                            unsafe_allow_html=True)
            source_url = g.get("url", "")
            apply_url  = g.get("application_url") or source_url
            st.markdown(
                f"{icons.svg('external-link',13,'var(--text-3)')} [Source]({source_url})",
                unsafe_allow_html=True,
            )
            if apply_url and apply_url != source_url:
                st.markdown(
                    f"{icons.svg('send',13,'var(--green)')} [**Apply here**]({apply_url})",
                    unsafe_allow_html=True,
                )
            if g.get("reasoning"):
                st.markdown(f"**Reasoning:** {g['reasoning']}")
            if g.get("red_flags"):
                st.warning("⚠️ " + "  ·  ".join(g["red_flags"]))


# ── Kanban view ───────────────────────────────────────────────────────────────

def _render_kanban(grants: list):
    buckets: dict[str, list] = {s: [] for s in KANBAN_STAGES}
    for g in grants:
        s = g.get("status", "triage")
        buckets[s if s in buckets else "triage"].append(g)

    cols = st.columns(len(KANBAN_STAGES))

    for col, stage in zip(cols, KANBAN_STAGES):
        color, bg, icon_name = icons._STATUS_STYLES.get(
            stage, ("var(--text-3)", "var(--bg-elevated)", "circle")
        )

        with col:
            st.markdown(
                f"<div style='background:{bg};border-radius:8px;padding:8px 10px;"
                f"margin-bottom:8px;display:flex;align-items:center;gap:6px;'>"
                f"{icons.svg(icon_name, 13, color)}"
                f"<span style='color:{color};font-size:0.72em;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:0.06em;'>"
                f"{stage.replace('_',' ')}</span>"
                f"<span style='color:{color};font-size:0.72em;margin-left:auto;'>"
                f"{len(buckets[stage])}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            for g in buckets[stage][:10]:
                score     = g.get("weighted_total", 0)
                deadline  = g.get("deadline") or "–"
                geography = (g.get("geography") or "")[:28]
                grant_type = g.get("grant_type", "grant")

                with st.container(border=True):
                    st.markdown(
                        icons.score_badge(score) + "&nbsp;" +
                        icons.grant_type_badge(grant_type),
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='font-size:0.8em;font-weight:600;"
                        f"color:var(--text);line-height:1.3;margin:4px 0;'>"
                        f"{g.get('title','Untitled')[:44]}</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='font-size:0.72em;color:var(--text-3);'>"
                        f"{g.get('funder','–')[:28]}</div>"
                        f"<div style='font-size:0.72em;color:var(--text-4);margin-top:2px;'>"
                        f"{icons.svg('calendar',11,'var(--text-4)')} {deadline} "
                        f"· {icons.svg('globe',11,'var(--text-4)')} {geography or '–'}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    move_opts = [s for s in KANBAN_STAGES if s != stage]
                    choice = st.selectbox(
                        "Move", move_opts, index=None, placeholder="Move to…",
                        key=f"kb_{g['_id']}_{stage}", label_visibility="collapsed",
                    )
                    if choice:
                        update_grant_status(g["_id"], choice)
                        st.rerun()

            if len(buckets[stage]) > 10:
                st.caption(f"+ {len(buckets[stage]) - 10} more")
