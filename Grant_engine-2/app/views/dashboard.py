"""View 1 — Dashboard: at-a-glance health of the entire grants engine."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from app.db.queries import (
    get_dashboard_stats,
    get_grants_by_theme,
    get_pipeline_funnel,
    get_recent_activity,
    get_score_distribution,
    get_raw_grants_preview,
    get_raw_stats,
    get_tracker_grants,
    get_tracker_stats,
)
from app.ui import icons
from app.ui.filters import (
    AMOUNT_OPTIONS,
    DEADLINE_OPTIONS,
    amount_bucket_to_range,
    apply_deadline_filter,
    filter_amount_not_specified,
    active_filter_labels,
)

PURSUE_THRESHOLD = 6.5

_ACTIVITY_ICONS: dict[str, str] = {
    "scout":           "search",
    "analyst":         "activity",
    "company_brain":   "database",
    "grant_reader":    "file-text",
    "drafter":         "pen-line",
    "reviewer":        "eye",
    "exporter":        "package",
    "human_triage":    "users",
    "pipeline_update": "refresh-cw",
}

_SOURCE_ICONS: dict[str, str] = {
    "tavily":     "search",
    "exa":        "zap",
    "perplexity": "activity",
    "direct":     "external-link",
}

_SOURCE_COLORS: dict[str, str] = {
    "tavily":     "var(--accent)",
    "exa":        "var(--green)",
    "perplexity": "var(--purple)",
    "direct":     "var(--text-3)",
}

_STATUS_COLORS: dict[str, str] = {
    "pursue":   "var(--green)",
    "pursuing": "var(--green)",
    "watch":    "var(--orange)",
    "triage":   "var(--accent)",
}


def _render_raw_preview():
    """Show scraped raw grants while analyst scoring is pending."""
    icons.section_header("inbox", "Raw Scraped Grants (Pending Scoring)")

    raw_grants = get_raw_grants_preview(limit=50)
    if not raw_grants:
        st.caption("No raw data available.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    rf1, rf2, rf3 = st.columns([2, 1.2, 1.2])
    with rf1:
        raw_search = st.text_input("Search raw", placeholder="Title or funder…",
                                   label_visibility="collapsed", key="raw_search")
    with rf2:
        source_opts = ["All sources", "tavily", "exa", "perplexity", "direct"]
        raw_source = st.selectbox("Source", source_opts,
                                  label_visibility="collapsed", key="raw_source")
    with rf3:
        status_opts = ["All", "Pending", "Scored"]
        raw_status = st.selectbox("Status", status_opts,
                                  label_visibility="collapsed", key="raw_status")

    # Apply filters
    filtered = raw_grants
    if raw_search:
        q = raw_search.lower()
        filtered = [g for g in filtered
                    if q in (g.get("title") or "").lower()
                    or q in (g.get("funder") or "").lower()]
    if raw_source != "All sources":
        filtered = [g for g in filtered if g.get("source") == raw_source]
    if raw_status == "Pending":
        filtered = [g for g in filtered if not g.get("processed")]
    elif raw_status == "Scored":
        filtered = [g for g in filtered if g.get("processed")]

    st.markdown(
        f"<p style='color:var(--text-3);font-size:0.82em;margin-bottom:8px;'>"
        f"{len(filtered)} of {len(raw_grants)} raw grants shown</p>",
        unsafe_allow_html=True,
    )

    for g in filtered[:20]:
        processed = g.get("processed", False)
        src = g.get("source", "")
        icon_name  = _SOURCE_ICONS.get(src, "circle")
        src_color  = _SOURCE_COLORS.get(src, "var(--text-3)")
        themes = " · ".join((g.get("themes_detected") or []))
        scraped = (g.get("scraped_at") or "")[:10]
        status_html = (
            f"<span style='color:var(--green);font-size:0.8em;'>"
            f"{icons.svg('check',12,'var(--green)')} scored</span>"
            if processed
            else f"<span style='color:var(--orange);font-size:0.8em;'>"
                 f"{icons.svg('clock',12,'var(--orange)')} pending</span>"
        )

        with st.expander(f"{g.get('title', 'Untitled')[:80]}"):
            st.markdown(
                f"<div style='display:flex;gap:8px;align-items:center;margin-bottom:8px;'>"
                f"{icons.svg(icon_name,14,src_color)} "
                f"<span style='color:{src_color};font-size:0.82em;font-weight:600;'>{src.upper()}</span>"
                f"&nbsp;·&nbsp;{status_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.markdown(f"**Funder:** {g.get('funder', '–')}")
            col2.markdown(f"**Scraped:** {scraped}")
            col3.markdown(f"**Themes:** {themes or '–'}")
            if g.get("snippet"):
                st.markdown(f"> {g['snippet']}…")
            url = g.get("url", "")
            if url:
                st.markdown(
                    f"{icons.svg('external-link',13,'var(--accent)')} "
                    f"[Open grant page]({url})",
                    unsafe_allow_html=True,
                )

    if len(filtered) > 20:
        st.caption(f"+ {len(filtered) - 20} more (run Scout + Analyst to score all)")


def _render_grant_tracker():
    """Full Grant Tracker table — mirrors the Excel export in the UI."""
    # ── Header ────────────────────────────────────────────────────────────────
    hcol, vcol = st.columns([3, 1])
    with hcol:
        icons.section_header("database", "Grant Tracker")
    with vcol:
        tracker_view = st.radio(
            "Tracker view", ["Table", "Cards"],
            horizontal=True, label_visibility="collapsed",
            key="dash_tracker_view",
        )

    # ── Tracker stats chips ───────────────────────────────────────────────────
    ts = get_tracker_stats()
    capital = ts.get("capital_targeted", 0)
    capital_str = f"${capital:,.0f}" if capital else "–"

    st.markdown(
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;'>"
        f"<span style='background:var(--bg-card);border:1px solid var(--border);"
        f"border-radius:20px;padding:4px 12px;font-size:0.82em;color:var(--text);'>"
        f"{icons.svg('database',13,'var(--text-3)')} <b>{ts.get('total',0)}</b> total</span>"
        f"<span style='background:var(--green-bg);border:1px solid var(--green-border);"
        f"border-radius:20px;padding:4px 12px;font-size:0.82em;color:var(--green);'>"
        f"{icons.svg('check-circle',13,'var(--green)')} <b>{ts.get('pursuing',0)}</b> pursuing</span>"
        f"<span style='background:var(--orange-bg);border:1px solid var(--orange-border);"
        f"border-radius:20px;padding:4px 12px;font-size:0.82em;color:var(--orange);'>"
        f"{icons.svg('eye',13,'var(--orange)')} <b>{ts.get('watching',0)}</b> watching</span>"
        f"<span style='background:#1a2744;border:1px solid var(--border);"
        f"border-radius:20px;padding:4px 12px;font-size:0.82em;color:var(--accent);'>"
        f"{icons.svg('inbox',13,'var(--accent)')} <b>{ts.get('in_triage',0)}</b> in triage</span>"
        f"<span style='background:var(--bg-card);border:1px solid var(--border);"
        f"border-radius:20px;padding:4px 12px;font-size:0.82em;color:var(--green);'>"
        f"{icons.svg('banknote',13,'var(--green)')} <b>{capital_str}</b> targeted</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Filter row 1 ─────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2.5, 1.2, 1.2, 1.2])
    with f1:
        trk_search = st.text_input(
            "Search", placeholder="Grant name, funder, geography…",
            label_visibility="collapsed", key="trk_search",
        )
    with f2:
        trk_status = st.selectbox(
            "Status", ["All statuses", "triage", "pursue", "pursuing", "watch"],
            label_visibility="collapsed", key="trk_status",
        )
    with f3:
        trk_type = st.selectbox(
            "Type", ["All types", "grant", "prize", "rfp", "fellowship", "loan"],
            label_visibility="collapsed", key="trk_type",
        )
    with f4:
        trk_amount = st.selectbox(
            "Amount", AMOUNT_OPTIONS,
            label_visibility="collapsed", key="trk_amount",
        )

    # ── Filter row 2 ─────────────────────────────────────────────────────────
    f5, f6, _ = st.columns([1.8, 1.8, 2])
    with f5:
        trk_deadline = st.selectbox(
            "Deadline", DEADLINE_OPTIONS,
            label_visibility="collapsed", key="trk_deadline",
        )
    with f6:
        trk_theme = st.selectbox(
            "Theme", ["All themes", "biochar", "dac", "enhanced_weathering",
                      "soil_carbon", "blue_carbon", "afforestation", "general_cdr",
                      "climate_tech", "sustainability", "carbon_markets"],
            format_func=lambda x: x.replace("_", " ").title() if x != "All themes" else x,
            label_visibility="collapsed", key="trk_theme",
        )

    # ── Resolve filters ───────────────────────────────────────────────────────
    status_filter = "" if trk_status == "All statuses" else trk_status
    type_filter   = "" if trk_type == "All types" else trk_type
    theme_filter  = "" if trk_theme == "All themes" else trk_theme
    min_fund, max_fund = amount_bucket_to_range(trk_amount)

    grants = get_tracker_grants(
        search=trk_search,
        theme_filter=theme_filter,
        grant_type_filter=type_filter,
        status_filter=status_filter,
        min_funding=min_fund,
        max_funding=max_fund,
    )
    # Client-side post-filters
    grants = filter_amount_not_specified(grants, trk_amount)
    grants = apply_deadline_filter(grants, trk_deadline)

    # ── Active filter chips ───────────────────────────────────────────────────
    chip_labels = active_filter_labels(
        search=trk_search, theme=theme_filter, status=status_filter,
        grant_type=type_filter, amount=trk_amount, deadline=trk_deadline,
    )
    count_txt = f"<b>{len(grants)}</b> grants"
    if chip_labels:
        chips_html = " ".join(
            f"<span style='background:var(--accent-bg,#1a2744);color:var(--accent);"
            f"border:1px solid var(--accent);border-radius:12px;"
            f"padding:2px 10px;font-size:0.78em;'>{lbl}</span>"
            for lbl in chip_labels
        )
        st.markdown(
            f"<div style='margin-bottom:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;'>"
            f"<span style='color:var(--text-3);font-size:0.82em;'>{count_txt} matching</span>"
            f"{chips_html}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<p style='color:var(--text-3);font-size:0.82em;margin-bottom:8px;'>"
            f"Showing {count_txt}</p>",
            unsafe_allow_html=True,
        )

    if not grants:
        st.info("No grants match the current filters.")
        return

    # ── TABLE VIEW ────────────────────────────────────────────────────────────
    if tracker_view == "Table":
        rows = []
        for g in grants:
            status = g.get("status", "triage")
            score  = g.get("weighted_total") or 0
            amount_val = g.get("amount") or (
                f"${g.get('max_funding_usd') or g.get('max_funding') or 0:,}"
                if g.get("max_funding_usd") or g.get("max_funding") else "–"
            )
            themes_raw = g.get("themes_detected") or g.get("themes") or []
            themes_str = " | ".join(themes_raw) if isinstance(themes_raw, list) else str(themes_raw)
            apply_url  = g.get("application_url") or g.get("url") or ""

            rows.append({
                "Grant Name":  g.get("grant_name") or g.get("title") or "Untitled",
                "Funder":      g.get("funder") or "–",
                "Type":        (g.get("grant_type") or "grant").title(),
                "Geography":   g.get("geography") or "–",
                "Ticket Size": amount_val,
                "Deadline":    g.get("deadline") or "–",
                "Score":       round(score, 2),
                "Status":      status.title(),
                "Themes":      themes_str or "–",
                "Rationale":   (g.get("rationale") or g.get("reasoning") or "")[:120],
                "Apply":       apply_url,
            })

        df = pd.DataFrame(rows)

        def _score_color(val):
            if val >= 7.5: return "background:#0d2e1a;color:#68d391;font-weight:700"
            if val >= 6.5: return "background:#0d2e1a;color:#48bb78;font-weight:700"
            if val >= 5.0: return "background:#2d1f0a;color:#f6ad55;font-weight:700"
            return "background:#2d0a0a;color:#fc8181;font-weight:700"

        def _status_color(val):
            v = val.lower()
            if v in ("pursue", "pursuing"):
                return "color:#68d391;font-weight:600"
            if v == "watch":
                return "color:#f6ad55;font-weight:600"
            if v == "triage":
                return "color:#63b3ed;font-weight:600"
            return ""

        styled = (
            df.style
            .applymap(_score_color, subset=["Score"])
            .applymap(_status_color, subset=["Status"])
        )
        st.dataframe(
            styled,
            use_container_width=True,
            height=min(80 + len(rows) * 36, 600),
            column_config={
                "Apply": st.column_config.LinkColumn("Apply", display_text="Open"),
                "Rationale": st.column_config.TextColumn("Rationale", width="large"),
                "Grant Name": st.column_config.TextColumn("Grant Name", width="large"),
            },
        )

        # ── CSV export ────────────────────────────────────────────────────────
        csv_bytes = df.to_csv(index=False).encode()
        st.download_button(
            "Export CSV",
            data=csv_bytes,
            file_name="altcarbon_grant_tracker.csv",
            mime="text/csv",
            key="trk_csv",
        )

    # ── CARDS VIEW ────────────────────────────────────────────────────────────
    else:
        for g in grants[:50]:
            status     = g.get("status", "triage")
            score      = g.get("weighted_total") or 0
            grant_type = g.get("grant_type", "grant")
            deadline   = g.get("deadline") or "–"
            geography  = g.get("geography") or "–"
            amount_val = g.get("amount") or (
                f"${g.get('max_funding_usd') or g.get('max_funding') or 0:,}"
                if g.get("max_funding_usd") or g.get("max_funding") else "–"
            )
            themes_raw = g.get("themes_detected") or g.get("themes") or []
            themes_str = ", ".join(themes_raw) if isinstance(themes_raw, list) else str(themes_raw)
            apply_url  = g.get("application_url") or g.get("url") or ""
            status_color = _STATUS_COLORS.get(status, "var(--text-3)")

            with st.container(border=True):
                row1, row2, row3 = st.columns([3.5, 1, 1.5])
                with row1:
                    st.markdown(
                        f"<div style='font-weight:700;color:var(--text);font-size:0.97rem;'>"
                        f"{g.get('grant_name') or g.get('title') or 'Untitled'}</div>"
                        f"<div style='color:var(--text-3);font-size:0.83em;margin-top:2px;'>"
                        f"{icons.svg('users',12,'var(--text-3)')} {g.get('funder','–')}"
                        f"&nbsp;&nbsp;{icons.grant_type_badge(grant_type)}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with row2:
                    st.markdown(icons.score_badge(score), unsafe_allow_html=True)
                with row3:
                    st.markdown(
                        f"<span style='background:var(--bg-card);border:1px solid {status_color};"
                        f"color:{status_color};border-radius:12px;padding:3px 10px;"
                        f"font-size:0.8em;font-weight:600;'>{status.upper()}</span>",
                        unsafe_allow_html=True,
                    )

                st.markdown(
                    icons.meta_chip("calendar", deadline) +
                    icons.meta_chip("banknote", amount_val, "var(--green)") +
                    icons.meta_chip("globe", geography, "var(--accent)"),
                    unsafe_allow_html=True,
                )

                rationale = g.get("rationale") or g.get("reasoning") or ""
                if rationale:
                    st.markdown(icons.rationale_box(rationale), unsafe_allow_html=True)

                if themes_str:
                    st.caption(themes_str)

                if apply_url:
                    st.markdown(
                        f"{icons.svg('external-link',13,'var(--accent)')} "
                        f"[Apply / View Grant]({apply_url})",
                        unsafe_allow_html=True,
                    )

        if len(grants) > 50:
            st.caption(f"+ {len(grants) - 50} more grants — switch to Table view to see all")


def render():
    icons.page_header("layout-dashboard", "Dashboard", "At-a-glance health of the grants engine")

    stats = get_dashboard_stats()

    # ── Empty state ───────────────────────────────────────────────────────────
    raw = get_raw_stats()
    if stats["total_discovered"] == 0:
        if raw["total_raw"] > 0:
            st.warning(
                f"**{raw['total_raw']} grants scraped, {raw['unprocessed']} pending analyst scoring.**\n\n"
                "Click **Run Scout Now** to run the analyst and score all waiting grants."
            )
            _render_raw_preview()
        else:
            st.info(
                "**No grants discovered yet.**\n\n"
                "Click **Run Scout Now** in the sidebar to start discovering grant opportunities."
            )
        return

    # ── Top metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Grants Discovered", stats["total_discovered"])
    c2.metric("In Triage", stats["in_triage"])
    c3.metric("Pursuing", stats["pursuing"])
    c4.metric("Drafts Complete", stats["draft_complete"])
    capital = stats["capital_targeted"]
    c5.metric("Capital Targeted", f"${capital:,.0f}" if capital else "–")

    st.divider()

    col_left, col_right = st.columns([1.6, 1])

    # ── Pipeline funnel ───────────────────────────────────────────────────────
    with col_left:
        icons.section_header("git-branch", "Pipeline Funnel")
        funnel_data = get_pipeline_funnel()
        if funnel_data:
            labels = [f["stage"] for f in funnel_data]
            values = [f["count"] for f in funnel_data]
            fig = go.Figure(go.Funnel(
                y=labels,
                x=values,
                textposition="inside",
                textinfo="value+percent initial",
                marker={"color": ["#4299e1", "#63b3ed", "#48bb78", "#b794f4", "#f6ad55"]},
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "var(--text)"},
                margin={"l": 20, "r": 20, "t": 20, "b": 20},
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No grant data yet — run Scout to start discovering.")

    # ── Theme distribution ────────────────────────────────────────────────────
    with col_right:
        icons.section_header("filter", "Grants by Theme")
        theme_data = get_grants_by_theme()
        if theme_data:
            fig = px.pie(
                names=list(theme_data.keys()),
                values=list(theme_data.values()),
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font={"color": "var(--text)"},
                margin={"l": 0, "r": 0, "t": 20, "b": 0},
                height=280,
                showlegend=True,
                legend={"font": {"size": 10}},
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No theme data yet.")

    st.divider()

    col_score, col_activity = st.columns([1.5, 1])

    # ── Score distribution ────────────────────────────────────────────────────
    with col_score:
        icons.section_header("activity", "Score Distribution")
        scores = get_score_distribution()
        if scores:
            fig = go.Figure()
            fig.add_trace(go.Histogram(
                x=scores, nbinsx=20,
                marker_color="#4299e1", opacity=0.8, name="Grants",
            ))
            fig.add_vline(
                x=PURSUE_THRESHOLD, line_dash="dash", line_color="#48bb78",
                annotation_text="Pursue threshold", annotation_position="top right",
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "var(--text)"},
                xaxis={"title": "Score", "gridcolor": "var(--border)"},
                yaxis={"title": "Count", "gridcolor": "var(--border)"},
                margin={"l": 20, "r": 20, "t": 20, "b": 40},
                height=220,
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No scored grants yet.")

    # ── Recent activity ───────────────────────────────────────────────────────
    with col_activity:
        icons.section_header("clock", "Recent Activity")
        activity = get_recent_activity(8)
        if activity:
            for event in activity:
                node = event.get("node", "system")
                icon_name = _ACTIVITY_ICONS.get(node, "circle")
                ts = event.get("ts", event.get("created_at", ""))[:16]
                action = event.get("action", event.get("message", node))
                st.markdown(
                    f"<div class='activity-item'>"
                    f"<div class='activity-icon'>{icons.svg(icon_name, 14, 'var(--accent)')}</div>"
                    f"<div><span style='color:var(--text);font-weight:500;'>{action}</span>"
                    f"<br><span style='color:var(--text-4);font-size:0.8em;'>{ts}</span></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("No activity yet.")

    st.divider()

    # ── Grant Tracker ─────────────────────────────────────────────────────────
    _render_grant_tracker()

    st.divider()

    # ── Raw grants (if any pending) ───────────────────────────────────────────
    if raw["total_raw"] > 0:
        _render_raw_preview()
