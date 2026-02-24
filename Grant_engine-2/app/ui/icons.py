"""Lucide icon helpers for the AltCarbon Grants Intelligence UI.

All icons are sourced from Lucide (MIT licence, lucide.dev).

Key design:
  - svg() emits stroke="currentColor" and sets `color:` in the inline style,
    so CSS variables like `var(--green)` work correctly (SVG `stroke` doesn't
    accept CSS variables directly, but `currentColor` inherits the CSS color).
  - Badge helpers use CSS variables (var(--green), var(--green-bg), etc.) so
    they automatically adapt to the active light/dark theme without any Python
    theme-detection logic.
"""
from __future__ import annotations
import streamlit as st

# ── Raw Lucide SVG path data (viewBox 0 0 24 24) ──────────────────────────────
_ICONS: dict[str, str] = {
    # Navigation
    "layout-dashboard": "<rect width='7' height='9' x='3' y='3' rx='1'/><rect width='7' height='5' x='3' y='15' rx='1'/><rect width='7' height='3' x='14' y='3' rx='1'/><rect width='7' height='11' x='14' y='10' rx='1'/>",
    "search":           "<circle cx='11' cy='11' r='8'/><path d='m21 21-4.3-4.3'/>",
    "zap":              "<path d='M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z'/>",
    "pen-line":         "<path d='M12 20h9'/><path d='M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z'/>",
    "settings":         "<path d='M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z'/><circle cx='12' cy='12' r='3'/>",
    "database":         "<ellipse cx='12' cy='5' rx='9' ry='3'/><path d='M3 5V19A9 3 0 0 0 21 19V5'/><path d='M3 12A9 3 0 0 0 21 12'/>",
    "leaf":             "<path d='M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10z'/><path d='M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12'/>",
    "git-branch":       "<line x1='6' x2='6' y1='3' y2='15'/><circle cx='18' cy='6' r='3'/><circle cx='6' cy='18' r='3'/><path d='M18 9a9 9 0 0 1-9 9'/>",
    # Status / scoring
    "check-circle":     "<circle cx='12' cy='12' r='10'/><path d='m9 12 2 2 4-4'/>",
    "x-circle":         "<circle cx='12' cy='12' r='10'/><path d='m15 9-6 6'/><path d='m9 9 6 6'/>",
    "eye":              "<path d='M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z'/><circle cx='12' cy='12' r='3'/>",
    "target":           "<circle cx='12' cy='12' r='10'/><circle cx='12' cy='12' r='6'/><circle cx='12' cy='12' r='2'/>",
    "trending-up":      "<polyline points='22 7 13.5 15.5 8.5 10.5 2 17'/><polyline points='16 7 22 7 22 13'/>",
    "trending-down":    "<polyline points='22 17 13.5 8.5 8.5 13.5 2 7'/><polyline points='16 17 22 17 22 11'/>",
    "minus":            "<path d='M5 12h14'/>",
    "award":            "<path d='m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1-.81-.469l1.514-8.526'/><circle cx='12' cy='8' r='6'/>",
    "flag":             "<path d='M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z'/><line x1='4' x2='4' y1='22' y2='15'/>",
    "fast-forward":     "<polygon points='13 19 22 12 13 5 13 19'/><polygon points='2 19 11 12 2 5 2 19'/>",
    "send":             "<path d='m22 2-7 20-4-9-9-4Z'/><path d='M22 2 11 13'/>",
    "inbox":            "<polyline points='22 12 16 12 14 15 10 15 8 12 2 12'/><path d='M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'/>",
    # Grant detail
    "dollar-sign":      "<line x1='12' x2='12' y1='2' y2='22'/><path d='M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6'/>",
    "calendar":         "<path d='M8 2v4'/><path d='M16 2v4'/><rect width='18' height='18' x='3' y='4' rx='2'/><path d='M3 10h18'/>",
    "external-link":    "<path d='M15 3h6v6'/><path d='M10 14 21 3'/><path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/>",
    "link":             "<path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71'/><path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'/>",
    "file-text":        "<path d='M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z'/><path d='M14 2v4a2 2 0 0 0 2 2h4'/><path d='M10 9H8'/><path d='M16 13H8'/><path d='M16 17H8'/>",
    # Alerts
    "alert-triangle":   "<path d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3'/><path d='M12 9v4'/><path d='M12 17h.01'/>",
    "alert-circle":     "<circle cx='12' cy='12' r='10'/><line x1='12' x2='12' y1='8' y2='12'/><line x1='12' x2='12.01' y1='16' y2='16'/>",
    "info":             "<circle cx='12' cy='12' r='10'/><path d='M12 16v-4'/><path d='M12 8h.01'/>",
    # Actions
    "refresh-cw":       "<path d='M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8'/><path d='M21 3v5h-5'/><path d='M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16'/><path d='M8 16H3v5'/>",
    "check":            "<path d='M20 6 9 17l-5-5'/>",
    "x":                "<path d='M18 6 6 18'/><path d='m6 6 12 12'/>",
    "download":         "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><polyline points='7 10 12 15 17 10'/><line x1='12' x2='12' y1='15' y2='3'/>",
    "filter":           "<polygon points='22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3'/>",
    "play":             "<polygon points='6 3 20 12 6 21 6 3'/>",
    # Theme
    "sun":              "<circle cx='12' cy='12' r='4'/><path d='M12 2v2'/><path d='M12 20v2'/><path d='m4.93 4.93 1.41 1.41'/><path d='m17.66 17.66 1.41 1.41'/><path d='M2 12h2'/><path d='M20 12h2'/><path d='m6.34 17.66-1.41 1.41'/><path d='m19.07 4.93-1.41 1.41'/>",
    "moon":             "<path d='M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z'/>",
    # System
    "activity":         "<path d='M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2'/>",
    "users":            "<path d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M22 21v-2a4 4 0 0 0-3-3.87'/><path d='M16 3.13a4 4 0 0 1 0 7.75'/>",
    "package":          "<path d='M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z'/><path d='M12 22V12'/><path d='m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7'/><path d='m7.5 4.27 9 5.15'/>",
    "clock":            "<circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/>",
    "loader":           "<line x1='12' x2='12' y1='2' y2='6'/><line x1='12' x2='12' y1='18' y2='22'/><line x1='4.93' x2='7.76' y1='4.93' y2='7.76'/><line x1='16.24' x2='19.07' y1='16.24' y2='19.07'/><line x1='2' x2='6' y1='12' y2='12'/><line x1='18' x2='22' y1='12' y2='12'/><line x1='4.93' x2='7.76' y1='19.07' y2='16.24'/><line x1='16.24' x2='7.76' y1='7.76' y2='16.24'/>",
    "circle":           "<circle cx='12' cy='12' r='10'/>",
    # New — grant detail
    "map-pin":          "<path d='M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0'/><circle cx='12' cy='10' r='3'/>",
    "globe":            "<circle cx='12' cy='12' r='10'/><path d='M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20'/><path d='M2 12h20'/>",
    "trophy":           "<path d='M6 9H4.5a2.5 2.5 0 0 1 0-5H6'/><path d='M18 9h1.5a2.5 2.5 0 0 0 0-5H18'/><path d='M4 22h16'/><path d='M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22'/><path d='M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22'/><path d='M18 2H6v7a6 6 0 0 0 12 0V2Z'/>",
    "banknote":         "<rect width='20' height='12' x='2' y='6' rx='2'/><circle cx='12' cy='12' r='2'/><path d='M6 12h.01M18 12h.01'/>",
    "shield-check":     "<path d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z'/><path d='m9 12 2 2 4-4'/>",
}

# ── Core SVG renderer ──────────────────────────────────────────────────────────

def svg(
    name: str,
    size: int = 16,
    color: str = "currentColor",
    extra_style: str = "",
) -> str:
    """Return a Lucide icon as an inline SVG HTML string.

    Uses stroke="currentColor" so CSS variables (var(--accent), etc.) work
    correctly when passed as `color` — the value is applied to `style.color`
    which is then picked up by currentColor.
    """
    paths = _ICONS.get(name, _ICONS["circle"])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' "
        f"viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
        f"stroke-linecap='round' stroke-linejoin='round' "
        f"style='display:inline-block;vertical-align:middle;flex-shrink:0;"
        f"color:{color};{extra_style}'>"
        f"{paths}</svg>"
    )


# ── Theme-adaptive CSS variable tokens ────────────────────────────────────────
# These map semantic names to our CSS variable names (defined in theme.css).
# Because inline style="" attributes support var(), badges automatically
# adapt to the active light or dark theme with no Python logic needed.

_STATUS_STYLES: dict[str, tuple[str, str, str]] = {
    # status: (text-css-var, bg-css-var, icon-name)
    "triage":         ("var(--accent)",  "var(--accent-bg)",  "inbox"),
    "pursue":         ("var(--green)",   "var(--green-bg)",   "check-circle"),
    "watch":          ("var(--orange)",  "var(--orange-bg)",  "eye"),
    "pursuing":       ("var(--green)",   "var(--green-bg)",   "target"),
    "drafting":       ("var(--purple)",  "var(--purple-bg)",  "pen-line"),
    "draft_complete": ("var(--purple)",  "var(--purple-bg)",  "file-text"),
    "submitted":      ("var(--orange)",  "var(--orange-bg)",  "send"),
    "won":            ("var(--green)",   "var(--green-bg)",   "award"),
    "passed":         ("var(--red)",     "var(--red-bg)",     "x-circle"),
    "auto_pass":      ("var(--text-3)",  "var(--bg-elevated)","fast-forward"),
    "reported":       ("var(--text-3)",  "var(--bg-elevated)","flag"),
}


# ── Compound UI helpers ────────────────────────────────────────────────────────

def page_header(icon_name: str, title: str, subtitle: str = "") -> None:
    """Render a full-width page header with a Lucide icon."""
    sub_html = (
        f"<p style='margin:4px 0 0;font-size:0.9rem;color:var(--text-3);'>{subtitle}</p>"
        if subtitle else ""
    )
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:14px;
                    margin-bottom:24px;padding-bottom:18px;
                    border-bottom:1px solid var(--border);">
            <div style="background:var(--accent-bg);border-radius:12px;padding:11px;
                        display:flex;align-items:center;justify-content:center;
                        border:1px solid var(--accent-border);">
                {svg(icon_name, 26, 'var(--accent)')}
            </div>
            <div>
                <h1 style="margin:0;font-size:1.55rem;font-weight:700;
                           color:var(--text);line-height:1.2;">{title}</h1>
                {sub_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(icon_name: str, title: str, color: str = "var(--accent)") -> None:
    """Render a smaller section header with icon."""
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:8px;
                        margin:16px 0 8px;">
                {svg(icon_name, 18, color)}
                <span style="font-size:1.05rem;font-weight:600;color:{color};">{title}</span>
            </div>""",
        unsafe_allow_html=True,
    )


def score_badge(score: float) -> str:
    """Return HTML for a coloured score badge with trend icon. Theme-adaptive."""
    if score >= 6.5:
        color, bg, icon_name = "var(--green)", "var(--green-bg)", "trending-up"
    elif score >= 5.0:
        color, bg, icon_name = "var(--orange)", "var(--orange-bg)", "minus"
    else:
        color, bg, icon_name = "var(--red)", "var(--red-bg)", "trending-down"
    return (
        f"<span style='display:inline-flex;align-items:center;gap:5px;"
        f"background:{bg};color:{color};padding:3px 10px;"
        f"border-radius:20px;font-size:0.82em;font-weight:700;'>"
        f"{svg(icon_name, 13, color)} {score:.1f}"
        f"</span>"
    )


def status_badge(status: str) -> str:
    """Return HTML for a coloured status pill with icon. Theme-adaptive."""
    color, bg, icon_name = _STATUS_STYLES.get(
        status, ("var(--text-3)", "var(--bg-elevated)", "circle")
    )
    label = status.replace("_", " ").title()
    return (
        f"<span style='display:inline-flex;align-items:center;gap:4px;"
        f"background:{bg};color:{color};padding:3px 11px;"
        f"border-radius:20px;font-size:0.78em;font-weight:600;letter-spacing:0.03em;'>"
        f"{svg(icon_name, 12, color)} {label}"
        f"</span>"
    )


def meta_chip(icon_name: str, text: str, color: str = "var(--text-3)") -> str:
    """Return HTML for a small metadata chip (deadline, funding, etc.)."""
    return (
        f"<span style='display:inline-flex;align-items:center;gap:4px;"
        f"color:{color};font-size:0.82em;margin-right:12px;'>"
        f"{svg(icon_name, 13, color)} {text}"
        f"</span>"
    )


def recommendation_badge(action: str) -> str:
    """Return HTML for the AI recommendation badge. Theme-adaptive."""
    styles = {
        "pursue":    ("var(--green)",  "var(--green-bg)",  "check-circle", "Pursue"),
        "watch":     ("var(--orange)", "var(--orange-bg)", "eye",          "Watch"),
        "auto_pass": ("var(--red)",    "var(--red-bg)",    "x-circle",     "Auto-pass"),
    }
    color, bg, icon_name, label = styles.get(
        action, ("var(--accent)", "var(--accent-bg)", "circle", "Review")
    )
    return (
        f"<span style='display:inline-flex;align-items:center;gap:5px;"
        f"background:{bg};color:{color};padding:4px 12px;"
        f"border-radius:20px;font-size:0.85em;font-weight:700;'>"
        f"{svg(icon_name, 14, color)} {label}"
        f"</span>"
    )


def alert_box(
    icon_name: str,
    message: str,
    color: str = "var(--accent)",
    bg: str = "var(--accent-bg)",
    border: str = "var(--accent-border)",
) -> str:
    """Return HTML for a styled alert/info box."""
    return (
        f"<div style='background:{bg};border:1px solid {border};border-radius:10px;"
        f"padding:14px 18px;display:flex;gap:10px;align-items:flex-start;"
        f"margin-bottom:12px;'>"
        f"{svg(icon_name, 20, color)}"
        f"<span style='color:{color};font-size:0.9em;'>{message}</span>"
        f"</div>"
    )


# ── Grant type badge ───────────────────────────────────────────────────────────

_GRANT_TYPE_STYLES: dict[str, tuple[str, str, str]] = {
    "grant":       ("var(--green)",   "var(--green-bg)",   "award"),
    "prize":       ("var(--orange)",  "var(--orange-bg)",  "trophy"),
    "challenge":   ("var(--orange)",  "var(--orange-bg)",  "zap"),
    "accelerator": ("var(--accent)",  "var(--accent-bg)",  "trending-up"),
    "fellowship":  ("var(--purple)",  "var(--purple-bg)",  "users"),
    "contract":    ("var(--text-3)",  "var(--bg-elevated)","file-text"),
    "loan":        ("var(--text-3)",  "var(--bg-elevated)","banknote"),
    "equity":      ("var(--purple)",  "var(--purple-bg)",  "package"),
    "other":       ("var(--text-3)",  "var(--bg-elevated)","circle"),
}


def grant_type_badge(grant_type: str) -> str:
    """Return HTML for a grant-type pill badge."""
    gt = (grant_type or "grant").lower()
    color, bg, icon_name = _GRANT_TYPE_STYLES.get(gt, _GRANT_TYPE_STYLES["other"])
    label = gt.title()
    return (
        f"<span style='display:inline-flex;align-items:center;gap:4px;"
        f"background:{bg};color:{color};border:1px solid {color}33;"
        f"border-radius:6px;padding:2px 9px;font-size:0.75em;font-weight:600;"
        f"vertical-align:middle;white-space:nowrap;'>"
        f"{svg(icon_name, 11, color)} {label}</span>"
    )


def rationale_box(rationale: str) -> str:
    """Return HTML for the green 'why apply' rationale callout."""
    return (
        f"<div style='background:var(--green-bg);border:1px solid var(--green-border);"
        f"border-radius:10px;padding:14px 16px;margin:10px 0;display:flex;"
        f"gap:10px;align-items:flex-start;'>"
        f"<div style='flex-shrink:0;margin-top:1px;'>"
        f"{svg('shield-check', 18, 'var(--green)')}</div>"
        f"<div>"
        f"<div style='font-size:0.72em;font-weight:700;color:var(--green);"
        f"text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;'>"
        f"Why AltCarbon Should Apply</div>"
        f"<span style='color:var(--green-2);font-size:0.88em;line-height:1.5;'>"
        f"{rationale}</span>"
        f"</div></div>"
    )


def eligibility_box(eligibility: str) -> str:
    """Return HTML for the eligibility info box."""
    return (
        f"<div style='background:var(--accent-bg);border:1px solid var(--accent-border);"
        f"border-radius:8px;padding:12px 14px;margin:8px 0;display:flex;"
        f"gap:8px;align-items:flex-start;'>"
        f"<div style='flex-shrink:0;'>{svg('shield-check', 15, 'var(--accent)')}</div>"
        f"<div>"
        f"<div style='font-size:0.7em;font-weight:700;color:var(--accent);"
        f"text-transform:uppercase;letter-spacing:0.07em;margin-bottom:3px;'>Eligibility</div>"
        f"<span style='color:var(--text-2);font-size:0.85em;line-height:1.5;'>{eligibility}</span>"
        f"</div></div>"
    )
