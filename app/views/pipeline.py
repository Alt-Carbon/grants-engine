"""View 2 — Grants Pipeline: List · Table · Kanban with full new field display."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.db.queries import (
    export_grants_csv,
    get_all_pipeline_grants,
    report_grant,
    save_manual_grant,
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


# ── Manual grant entry ────────────────────────────────────────────────────────

def _render_manual_entry():
    """Expandable form — paste a URL, we fetch + save it for the analyst to score."""
    with st.expander("➕  Add a grant manually", expanded=False):
        st.caption(
            "Scout didn't find it? Paste the grant URL below. "
            "We'll fetch the page content and queue it for analyst scoring."
        )

        col_url, col_funder = st.columns([3, 1])
        with col_url:
            url = st.text_input(
                "Grant URL",
                placeholder="https://example.org/grant-call-2026",
                key="manual_url",
                label_visibility="collapsed",
            )
        with col_funder:
            funder_override = st.text_input(
                "Funder (optional)",
                placeholder="e.g. EU EIC",
                key="manual_funder",
                label_visibility="collapsed",
            )

        col_title, col_notes = st.columns([2, 2])
        with col_title:
            title_override = st.text_input(
                "Title override (optional)",
                placeholder="Leave blank to auto-detect from page",
                key="manual_title",
                label_visibility="collapsed",
            )
        with col_notes:
            notes = st.text_input(
                "Notes (optional)",
                placeholder="Why you're adding this…",
                key="manual_notes",
                label_visibility="collapsed",
            )

        if st.button("Fetch & Queue for Analyst", type="primary", key="manual_submit",
                     disabled=not url):
            import os
            cf_account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
            cf_token = os.environ.get("CLOUDFLARE_BROWSER_TOKEN", "")
            with st.spinner("Fetching page content…"):
                ok, msg = save_manual_grant(
                    url=url,
                    title_override=title_override,
                    funder_override=funder_override,
                    notes=notes,
                    cf_account_id=cf_account_id,
                    cf_token=cf_token,
                )
            if ok:
                st.success(f"✅ {msg}\n\nRun the Analyst from the sidebar to score it.")
            else:
                st.error(f"❌ {msg}")


# ── Page ──────────────────────────────────────────────────────────────────────

def render():
    icons.page_header("git-branch", "Grants Pipeline",
                      "Full visibility across all tracked opportunities")

    _render_manual_entry()
    st.markdown("")

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

_KANBAN_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:transparent; font-size:13px;
}
#kb-bar {
  display:flex; align-items:center; justify-content:space-between;
  padding:0 2px 8px; gap:8px;
}
.kb-hint { color:#94a3b8; font-size:0.76em; display:flex; align-items:center; gap:5px; }
.kb-btn {
  background:#f8fafc; border:1px solid #e2e8f0; color:#475569;
  border-radius:6px; padding:4px 12px; cursor:pointer; font-size:0.8em;
  transition:all 0.15s; white-space:nowrap;
}
.kb-btn:hover { border-color:#16a34a; color:#16a34a; background:#f0fdf4; }
#kb-wrap { width:100%; overflow-x:auto; overflow-y:hidden; padding-bottom:8px; }
#kb-board { display:flex; gap:10px; min-width:max-content; padding:0 2px; }

.kb-col { width:190px; flex-shrink:0; display:flex; flex-direction:column; }
.kb-hdr {
  display:flex; align-items:center; justify-content:space-between;
  padding:6px 10px; border-radius:8px; margin-bottom:8px;
  font-size:0.68em; font-weight:700; text-transform:uppercase; letter-spacing:0.05em;
}
.kb-cnt {
  background:rgba(255,255,255,0.55); border-radius:10px;
  padding:1px 7px; font-size:1.05em; font-weight:800; min-width:18px; text-align:center;
}
.kb-cards {
  overflow-y:auto; overflow-x:hidden; max-height:560px; min-height:64px; padding:1px;
  border-radius:8px; transition:background 0.15s, outline 0.15s;
}
.kb-cards::-webkit-scrollbar { width:3px; }
.kb-cards::-webkit-scrollbar-thumb { background:#e2e8f0; border-radius:3px; }
.kb-col.drag-over .kb-cards {
  background:rgba(22,163,74,0.05);
  outline:2px dashed #16a34a; outline-offset:-2px;
}
.card {
  background:#fff; border:1.5px solid #e8eef4; border-radius:10px;
  padding:9px 10px 8px; margin-bottom:6px; cursor:grab;
  transition:box-shadow 0.15s, border-color 0.15s, opacity 0.12s, transform 0.12s;
  user-select:none;
}
.card:hover { box-shadow:0 3px 10px rgba(0,0,0,0.08); border-color:#c8d8e8; }
.card.dragging { opacity:0.35; cursor:grabbing; transform:scale(0.97); }
.c-badges { display:flex; align-items:center; gap:4px; margin-bottom:5px; flex-wrap:wrap; }
.c-score {
  font-size:0.69em; font-weight:800; padding:2px 7px;
  border-radius:5px; letter-spacing:0.01em;
}
.c-type {
  font-size:0.64em; font-weight:600; padding:2px 6px;
  border-radius:5px; background:#f1f5f9; color:#64748b;
}
.c-title { font-size:0.8em; font-weight:700; color:#1e293b; line-height:1.35; margin-bottom:3px; }
.c-funder { font-size:0.7em; color:#64748b; margin-bottom:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.c-meta { font-size:0.65em; color:#94a3b8; }
.kb-extra { font-size:0.68em; color:#94a3b8; text-align:center; padding:5px 0; font-style:italic; }
#toast {
  position:fixed; bottom:12px; right:12px; z-index:9999;
  padding:8px 14px; border-radius:8px; font-size:0.8em; font-weight:600;
  color:#fff; opacity:0; transform:translateY(6px);
  transition:opacity 0.2s, transform 0.2s; pointer-events:none; white-space:nowrap;
}
#toast.show { opacity:1; transform:translateY(0); }
#toast.s-info    { background:#3b82f6; }
#toast.s-success { background:#16a34a; }
#toast.s-error   { background:#dc2626; }
"""

_KANBAN_JS = """
const SC = {
  triage:         {bg:'#fffbeb', color:'#b45309'},
  pursue:         {bg:'#eff6ff', color:'#2563eb'},
  pursuing:       {bg:'#f5f3ff', color:'#7c3aed'},
  drafting:       {bg:'#ecfeff', color:'#0891b2'},
  draft_complete: {bg:'#f0fdf4', color:'#16a34a'},
  submitted:      {bg:'#eef2ff', color:'#4338ca'},
  won:            {bg:'#dcfce7', color:'#166534'},
  passed:         {bg:'#f8fafc', color:'#64748b'},
};

function esc(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function scoreStyle(s) {
  if (s >= 7.5) return 'background:#dcfce7;color:#15803d';
  if (s >= 6.5) return 'background:#f0fdf4;color:#16a34a';
  if (s >= 5.0) return 'background:#fff7ed;color:#ea580c';
  return 'background:#fef2f2;color:#dc2626';
}

let dragged = null, fromStage = null;

function buildBoard() {
  const board = document.getElementById('kb-board');
  DATA.forEach(col => {
    const sc = SC[col.stage] || {bg:'#f8fafc', color:'#64748b'};
    const colEl = document.createElement('div');
    colEl.className = 'kb-col';
    colEl.dataset.stage = col.stage;
    colEl.innerHTML =
      '<div class="kb-hdr" style="background:' + sc.bg + ';color:' + sc.color + '">'
      + '<span>' + esc(col.label) + '</span>'
      + '<span class="kb-cnt" id="cnt-' + col.stage + '">' + col.count + '</span>'
      + '</div>'
      + '<div class="kb-cards" id="cards-' + col.stage + '"></div>';

    const cardsEl = colEl.querySelector('.kb-cards');
    col.cards.forEach(c => cardsEl.appendChild(mkCard(c, col.stage)));
    if (col.extra > 0) {
      const d = document.createElement('div');
      d.className = 'kb-extra';
      d.textContent = '+ ' + col.extra + ' more';
      cardsEl.appendChild(d);
    }

    colEl.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      colEl.classList.add('drag-over');
    });
    colEl.addEventListener('dragleave', e => {
      if (!colEl.contains(e.relatedTarget)) colEl.classList.remove('drag-over');
    });
    colEl.addEventListener('drop', e => onDrop(e, col.stage, colEl));
    board.appendChild(colEl);
  });
}

function mkCard(c, stage) {
  const el = document.createElement('div');
  el.className = 'card';
  el.draggable = true;
  el.dataset.id = c.id;
  el.dataset.stage = stage;
  el.innerHTML =
    '<div class="c-badges">'
    + '<span class="c-score" style="' + scoreStyle(c.score) + '">' + c.score + '</span>'
    + '<span class="c-type">' + esc(c.grant_type) + '</span>'
    + '</div>'
    + '<div class="c-title">' + esc(c.title) + '</div>'
    + '<div class="c-funder">' + esc(c.funder) + '</div>'
    + '<div class="c-meta">📅 ' + esc(c.deadline) + ' · 🌍 ' + esc(c.geography || '–') + '</div>';

  el.addEventListener('dragstart', e => {
    dragged = el; fromStage = stage;
    el.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', c.id);
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    document.querySelectorAll('.kb-col').forEach(x => x.classList.remove('drag-over'));
  });
  return el;
}

function onDrop(e, toStage, colEl) {
  e.preventDefault();
  colEl.classList.remove('drag-over');
  const id = e.dataTransfer.getData('text/plain');
  if (!dragged || !id || fromStage === toStage) return;

  // Optimistic: move card in the DOM
  const cardsEl = colEl.querySelector('.kb-cards');
  cardsEl.insertBefore(dragged, cardsEl.firstChild);
  const prev = fromStage;
  dragged.dataset.stage = toStage;
  fromStage = toStage;
  bump('cnt-' + prev, -1);
  bump('cnt-' + toStage, +1);
  toast('Moving to ' + toStage.replace(/_/g, ' ') + '...', 'info');

  fetch(API_URL, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'x-internal-secret': API_KEY},
    body: JSON.stringify({grant_id: id, status: toStage})
  })
  .then(r => r.ok ? r.json() : Promise.reject(r.status))
  .then(() => {
    toast('Moved to ' + toStage.replace(/_/g, ' '), 'success');
    setTimeout(() => { try { window.parent.location.reload(); } catch(err) {} }, 1600);
  })
  .catch(err => toast('Update failed (' + err + ')', 'error'));
}

function bump(id, d) {
  const el = document.getElementById(id);
  if (el) el.textContent = Math.max(0, parseInt(el.textContent || '0') + d);
}

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show s-' + type;
  clearTimeout(window._tt);
  window._tt = setTimeout(() => { t.className = ''; }, 2600);
}

buildBoard();
"""


def _render_kanban(grants: list):
    import json
    import os
    import streamlit.components.v1 as components

    RAILWAY_URL = os.environ.get("RAILWAY_URL", "http://localhost:8000")
    INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")

    buckets: dict[str, list] = {s: [] for s in KANBAN_STAGES}
    for g in grants:
        s = g.get("status", "triage")
        buckets[s if s in buckets else "triage"].append(g)

    columns_data = []
    for stage in KANBAN_STAGES:
        cards = []
        for g in buckets[stage][:10]:
            cards.append({
                "id":         str(g["_id"]),
                "title":      (g.get("title") or "Untitled")[:52],
                "funder":     (g.get("funder") or "–")[:30],
                "deadline":   (g.get("deadline") or "–")[:16],
                "score":      round(g.get("weighted_total", 0), 1),
                "geography":  (g.get("geography") or "")[:22],
                "grant_type": (g.get("grant_type") or "grant")[:10],
            })
        columns_data.append({
            "stage": stage,
            "label": stage.replace("_", " ").title(),
            "count": len(buckets[stage]),
            "extra": max(0, len(buckets[stage]) - 10),
            "cards": cards,
        })

    # Inject dynamic data as JS constants; keep CSS/JS as plain strings (no f-string escaping needed)
    data_block = (
        "const DATA="    + json.dumps(columns_data) + ";"
        "const API_URL=" + json.dumps(f"{RAILWAY_URL}/update/grant-status") + ";"
        "const API_KEY=" + json.dumps(INTERNAL_SECRET) + ";"
    )

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>" + _KANBAN_CSS + "</style>"
        "<script>" + data_block + "</script>"
        "</head><body>"
        "<div id='kb-bar'>"
        "  <span class='kb-hint'>&#9776;&nbsp;Drag cards between columns to move stages</span>"
        "  <button class='kb-btn' onclick='try{window.parent.location.reload()}catch(e){}'>&#8635; Refresh</button>"
        "</div>"
        "<div id='kb-wrap'><div id='kb-board'></div></div>"
        "<div id='toast'></div>"
        "<script>" + _KANBAN_JS + "</script>"
        "</body></html>"
    )

    components.html(html, height=670, scrolling=False)
