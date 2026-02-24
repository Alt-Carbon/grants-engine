"""Theme toggle component for the AltCarbon sidebar.

Renders a compact dark/light toggle button using st.components.v1.html().
The button writes data-theme="dark" | "light" on the parent window's <html>
element (same-origin Streamlit iframe) and persists the choice in localStorage.

When the user picks a theme via this toggle:
  • Our CSS variables (var(--bg), var(--green), etc.) update immediately
  • Streamlit's own theme must be changed via ⋮ → Settings → Theme for full
    native-component adaption — but our custom HTML elements adapt instantly.
"""
from __future__ import annotations
import streamlit.components.v1 as components

_TOGGLE_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: transparent; font-family: -apple-system, sans-serif; }

  .toggle-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
  }

  .toggle-label {
    font-size: 12px;
    color: #718096;
    flex: 1;
    user-select: none;
  }

  .toggle-btn {
    display: flex;
    align-items: center;
    background: transparent;
    border: 1px solid #2d3748;
    border-radius: 20px;
    padding: 4px 10px;
    gap: 6px;
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    color: #a0aec0;
    transition: all 0.2s;
    white-space: nowrap;
  }

  .toggle-btn:hover {
    border-color: #4299e1;
    color: #4299e1;
  }

  .toggle-btn svg {
    flex-shrink: 0;
  }

  /* Adjust colours for light parent */
  body.light .toggle-btn {
    border-color: #cbd5e0;
    color: #4a5568;
  }
  body.light .toggle-label {
    color: #718096;
  }
</style>
</head>
<body>
<div class="toggle-wrap">
  <span class="toggle-label" id="lbl">Theme</span>
  <button class="toggle-btn" id="btn" onclick="toggle()">
    <span id="icon"></span>
    <span id="mode-text"></span>
  </button>
</div>

<script>
  const DARK_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13"
    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;

  const LIGHT_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13"
    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="4"/>
    <path d="M12 2v2M12 20v2m-7.07-14.07 1.41 1.41M17.66 17.66l1.41 1.41
             M2 12h2M20 12h2m-4.34-7.07-1.41 1.41M6.34 17.66l-1.41 1.41"/></svg>`;

  function getParentTheme() {
    try {
      return window.parent.document.documentElement.getAttribute('data-theme') || 'dark';
    } catch(e) { return localStorage.getItem('alt_theme') || 'dark'; }
  }

  function applyTheme(theme) {
    try {
      window.parent.document.documentElement.setAttribute('data-theme', theme);
    } catch(e) {}
    localStorage.setItem('alt_theme', theme);
    document.getElementById('icon').innerHTML = theme === 'dark' ? DARK_ICON : LIGHT_ICON;
    document.getElementById('mode-text').textContent = theme === 'dark' ? 'Dark' : 'Light';
    document.body.className = theme === 'light' ? 'light' : '';
  }

  function toggle() {
    const current = getParentTheme();
    applyTheme(current === 'dark' ? 'light' : 'dark');
  }

  // On load: restore saved theme
  (function init() {
    const saved = localStorage.getItem('alt_theme') || getParentTheme();
    applyTheme(saved);
  })();
</script>
</body>
</html>
"""


def render_toggle():
    """Render the dark/light theme toggle in the sidebar."""
    components.html(_TOGGLE_HTML, height=40, scrolling=False)


# ── Theme initialiser (run once at app start, height=0) ───────────────────────
_INIT_HTML = """
<script>
  (function() {
    const saved = localStorage.getItem('alt_theme');
    if (saved) {
      try {
        window.parent.document.documentElement.setAttribute('data-theme', saved);
      } catch(e) {}
    }
  })();
</script>
"""


def inject_theme_init():
    """Restore the persisted theme on every page load (height=0, invisible)."""
    import streamlit.components.v1 as components
    components.html(_INIT_HTML, height=0, scrolling=False)
