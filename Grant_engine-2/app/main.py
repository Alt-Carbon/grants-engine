"""AltCarbon Grants Intelligence — Streamlit App entry point."""
from __future__ import annotations

import os
import sys
import time

# Ensure project root is on sys.path so `app.*` imports resolve correctly
# when Streamlit runs this file directly.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# Load .env so MONGODB_URI and other secrets are available before any DB calls.
from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

import httpx
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AltCarbon Grants Intelligence",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load CSS ──────────────────────────────────────────────────────────────────
css_path = os.path.join(os.path.dirname(__file__), "styles", "theme.css")
if os.path.exists(css_path):
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ── Views + Icons + Theme ──────────────────────────────────────────────────────
from app.views import dashboard, pipeline, triage, drafter, agent_config, knowledge_health
from app.ui import icons
from app.ui.theme_toggle import inject_theme_init, render_toggle
from app.db.queries import get_quick_stats

# Restore persisted theme on every render (writes data-theme on parent html)
inject_theme_init()

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS = {
    "scout_running": False,
    "scout_started_at": None,
    "scout_elapsed": "",
    "scout_banner": None,   # None | "running" | "done"
    "scout_done_msg": "",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

RAILWAY_URL = os.environ.get("RAILWAY_URL", "http://localhost:8000")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")


# ── Backend poll helper ────────────────────────────────────────────────────────
def _fetch_scout_status() -> dict:
    try:
        r = httpx.get(f"{RAILWAY_URL}/status/scout", timeout=3.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


# ── Scout polling fragment ─────────────────────────────────────────────────────
# Fragment only updates st.session_state — never writes to st.sidebar.
# The sidebar reads from session_state outside this fragment.
@st.fragment(run_every="3s")
def _scout_poll():
    status = _fetch_scout_status()
    running = status.get("running", False)

    if running:
        st.session_state.scout_running = True
        st.session_state.scout_banner = "running"
        if status.get("started_at"):
            from datetime import datetime, timezone
            try:
                started = datetime.fromisoformat(
                    status["started_at"].replace("Z", "+00:00")
                )
                secs = int((datetime.now(timezone.utc) - started).total_seconds())
                st.session_state.scout_elapsed = f"{secs}s"
            except Exception:
                st.session_state.scout_elapsed = ""

    elif st.session_state.scout_running:
        new_grants = status.get("last_run_new_grants", 0)
        total_found = status.get("last_run_total_found", 0)
        st.session_state.scout_running = False
        st.session_state.scout_banner = "done"
        st.session_state.scout_elapsed = ""
        st.session_state.scout_done_msg = (
            f"Scout complete — {new_grants} new grants scored ({total_found} found)"
        )
        st.rerun(scope="app")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # Branding
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;padding:4px 0 12px;">
            <div style="background:#1a3a2a;border-radius:10px;padding:8px;display:flex;">
                {icons.svg('leaf', 22, '#48bb78')}
            </div>
            <div>
                <div style="font-size:1.05rem;font-weight:700;color:#e2e8f0;line-height:1.1;">AltCarbon</div>
                <div style="font-size:0.75rem;color:#718096;letter-spacing:0.04em;">Grants Intelligence</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Live scout banner ─────────────────────────────────────────────────────
    if st.session_state.scout_banner == "running":
        elapsed = st.session_state.scout_elapsed
        st.markdown(
            f"""<div style="display:flex;align-items:center;gap:8px;background:#1a2340;
                            border:1px solid #2d5a8a;border-radius:8px;padding:10px 12px;margin-bottom:8px;">
                    {icons.svg('loader', 16, '#4299e1')}
                    <span style="font-size:0.85em;color:#90cdf4;font-weight:500;">
                        Scout running… {elapsed}
                    </span>
                </div>""",
            unsafe_allow_html=True,
        )
    elif st.session_state.scout_banner == "done":
        st.markdown(
            f"""<div style="display:flex;align-items:center;gap:8px;background:#1a4731;
                            border:1px solid #276749;border-radius:8px;padding:10px 12px;margin-bottom:8px;">
                    {icons.svg('check-circle', 16, '#48bb78')}
                    <span style="font-size:0.82em;color:#9ae6b4;font-weight:500;">
                        {st.session_state.scout_done_msg}
                    </span>
                </div>""",
            unsafe_allow_html=True,
        )
        if st.button("Dismiss", key="dismiss_banner"):
            st.session_state.scout_banner = None
            st.session_state.scout_done_msg = ""
            st.rerun()

    # ── Quick stats ───────────────────────────────────────────────────────────
    try:
        stats = get_quick_stats()
        col1, col2 = st.columns(2)
        col1.metric("Discovered", stats["total_grants"])
        col2.metric("In Triage", stats["in_triage"])
        col1.metric("Pursuing", stats["pursuing"])
        last_scout = stats["last_scout"]
        if last_scout and last_scout != "Never":
            last_scout = str(last_scout)[:10]
        col2.metric("Last Scout", last_scout)
    except Exception:
        st.caption("Connecting to database...")

    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────────
    # Nav items: (radio_label, icon_name, display_label)
    _NAV = [
        ("Dashboard",       "layout-dashboard", "Dashboard"),
        ("Grants Pipeline", "git-branch",        "Grants Pipeline"),
        ("Triage Queue",    "zap",               "Triage Queue"),
        ("Drafter",         "pen-line",          "Drafter"),
        ("Agent Config",    "settings",          "Agent Config"),
        ("Knowledge Health","database",          "Knowledge Health"),
    ]

    # Build the nav label list with inline SVG icons using HTML
    # Streamlit radio doesn't support HTML in labels, so we add icons via
    # a CSS trick: inject icon SVGs into a custom HTML block above the radio
    # and use CSS to overlay them on each label using flexbox + order.
    nav_icons_html = "".join(
        f"<div style='display:flex;align-items:center;gap:9px;padding:9px 14px;"
        f"color:#718096;font-size:0.9em;'>"
        f"{icons.svg(icon, 16, '#718096')}"
        f"<span>{label}</span></div>"
        for _, icon, label in _NAV
    )

    # We render the nav as pure HTML buttons backed by session state
    # to get proper icon support.
    _active = st.session_state.get("_nav_page", "Dashboard")

    for radio_key, icon_name, display_label in _NAV:
        is_active = _active == radio_key
        bg      = "#1a2340" if is_active else "transparent"
        color   = "#4299e1" if is_active else "#718096"
        border  = "1px solid #2d5a8a" if is_active else "1px solid transparent"
        weight  = "600" if is_active else "400"

        col_icon, col_btn = st.columns([0.13, 0.87])
        with col_icon:
            st.markdown(
                f"<div style='padding-top:6px;'>{icons.svg(icon_name, 17, color)}</div>",
                unsafe_allow_html=True,
            )
        with col_btn:
            # Style the button via CSS based on active state
            btn_style = f"""
            <style>
            div[data-testid="stButton"]:has(button[kind="{'primary' if is_active else 'secondary'}"]) {{
                margin: 0;
            }}
            </style>
            """
            if st.button(
                display_label,
                key=f"nav_{radio_key}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["_nav_page"] = radio_key
                st.rerun()

    page = st.session_state.get("_nav_page", "Dashboard")

    st.divider()

    # ── Run Scout button ──────────────────────────────────────────────────────
    if st.session_state.scout_running:
        st.markdown(
            f"""<div style="display:flex;align-items:center;justify-content:center;gap:8px;
                            background:#1a2340;border:1px solid #2d3748;border-radius:8px;
                            padding:10px;color:#718096;font-size:0.88em;margin-bottom:8px;">
                    {icons.svg('loader', 15, '#718096')} Scout running…
                </div>""",
            unsafe_allow_html=True,
        )
    else:
        if st.button(
            "Run Scout Now",
            use_container_width=True,
            type="primary",
            key="run_scout_btn",
        ):
            try:
                r = httpx.post(
                    f"{RAILWAY_URL}/run/scout",
                    headers={"x-internal-secret": INTERNAL_SECRET},
                    timeout=10.0,
                )
                data = r.json()
                if r.status_code == 200:
                    if data.get("status") == "scout_already_running":
                        st.warning("Scout is already running.")
                    else:
                        st.session_state.scout_running = True
                        st.session_state.scout_banner = "running"
                        st.session_state.scout_started_at = data.get("started_at")
                        st.session_state.scout_elapsed = "0s"
                        st.rerun()
                else:
                    st.error(f"Error {r.status_code}: {r.text}")
            except Exception as e:
                st.error(f"Cannot reach backend: {e}")

    col_sync, col_refresh = st.columns(2)
    with col_sync:
        if st.button("Sync KB", use_container_width=True, key="sync_kb_btn"):
            try:
                r = httpx.post(
                    f"{RAILWAY_URL}/run/knowledge-sync",
                    headers={"x-internal-secret": INTERNAL_SECRET},
                    timeout=10.0,
                )
                st.success("Sync started!") if r.status_code == 200 else st.error(f"Error: {r.status_code}")
            except Exception as e:
                st.error(f"Cannot reach backend: {e}")
    with col_refresh:
        if st.button("Refresh", use_container_width=True, key="refresh_btn"):
            st.rerun(scope="app")

    # ── DB maintenance row ────────────────────────────────────────────────────
    col_bf, col_dd = st.columns(2)
    with col_bf:
        if st.button("Backfill Fields", use_container_width=True, key="backfill_btn",
                     help="Extract grant_type, geography, eligibility, amount, deadline, rationale on existing grants"):
            try:
                r = httpx.post(
                    f"{RAILWAY_URL}/admin/backfill-fields",
                    headers={"x-internal-secret": INTERNAL_SECRET},
                    timeout=10.0,
                )
                st.success("Backfill started!") if r.status_code == 200 else st.error(f"Error: {r.status_code}")
            except Exception as e:
                st.error(f"Cannot reach backend: {e}")
    with col_dd:
        if st.button("Deduplicate", use_container_width=True, key="dedup_btn",
                     help="Remove duplicate grants from the database"):
            try:
                r = httpx.post(
                    f"{RAILWAY_URL}/admin/deduplicate",
                    headers={"x-internal-secret": INTERNAL_SECRET},
                    timeout=10.0,
                )
                st.success("Dedup started!") if r.status_code == 200 else st.error(f"Error: {r.status_code}")
            except Exception as e:
                st.error(f"Cannot reach backend: {e}")

    st.divider()
    render_toggle()
    st.markdown(
        f"<div style='color:#4a5568;font-size:0.72em;text-align:center;margin-top:4px;'>"
        f"AltCarbon Grants Intelligence v2.0</div>",
        unsafe_allow_html=True,
    )

# ── Start polling fragment ─────────────────────────────────────────────────────
_scout_poll()

# ── Render active view ────────────────────────────────────────────────────────
if page == "Dashboard":
    dashboard.render()
elif page == "Grants Pipeline":
    pipeline.render()
elif page == "Triage Queue":
    triage.render()
elif page == "Drafter":
    drafter.render()
elif page == "Agent Config":
    agent_config.render()
elif page == "Knowledge Health":
    knowledge_health.render()
