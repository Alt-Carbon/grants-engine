"""View 5 — Agent Config: configure all agent behaviour without touching code."""
from __future__ import annotations

import streamlit as st

from app.db.queries import get_agent_config, save_agent_config
from app.ui import icons


def render():
    icons.page_header("settings", "Agent Config", "Configure all agent behaviour without touching code")

    configs = get_agent_config()
    scout_cfg = configs.get("scout", {})
    analyst_cfg = configs.get("analyst", {})
    drafter_cfg = configs.get("drafter", {})

    tab_scout, tab_analyst, tab_drafter, tab_system = st.tabs(
        ["Scout", "Analyst", "Drafter", "System"]
    )

    # ── Scout tab ─────────────────────────────────────────────────────────────
    with tab_scout:
        st.subheader("Scout Configuration")
        scout_enabled = st.toggle("Enable automated scouting", value=scout_cfg.get("enabled", True))
        freq = st.slider("Run frequency (hours)", 12, 168, int(scout_cfg.get("run_frequency_hours", 48)), step=12)
        max_results = st.slider("Max results per query", 5, 30, int(scout_cfg.get("max_results_per_query", 10)))

        st.markdown("**Search Tools**")
        use_tavily = st.checkbox("Tavily (keyword search)", value="tavily" in scout_cfg.get("search_tools", ["tavily", "exa"]))
        use_exa = st.checkbox("Exa (semantic search)", value="exa" in scout_cfg.get("search_tools", ["tavily", "exa"]))

        st.markdown("**Themes to scout**")
        theme_options = ["climatetech", "agritech", "ai_for_sciences", "applied_earth_sciences", "social_impact"]
        active_themes = st.multiselect("Themes", theme_options, default=scout_cfg.get("themes", theme_options))

        st.markdown("**Custom Queries** (one per line, leave blank to use defaults)")
        custom_q_text = st.text_area(
            "Custom Tavily queries",
            value="\n".join(scout_cfg.get("custom_queries", [])),
            height=120,
            placeholder="climatetech grant open call 2026\nagritech India funding 2026",
        )

        if st.button("Save Scout Config", type="primary"):
            tools = []
            if use_tavily:
                tools.append("tavily")
            if use_exa:
                tools.append("exa")
            new_cfg = {
                "enabled": scout_enabled,
                "run_frequency_hours": freq,
                "max_results_per_query": max_results,
                "search_tools": tools,
                "themes": active_themes,
                "custom_queries": [q.strip() for q in custom_q_text.splitlines() if q.strip()],
            }
            save_agent_config("scout", new_cfg)
            st.success("Scout config saved!")

    # ── Analyst tab ───────────────────────────────────────────────────────────
    with tab_analyst:
        st.subheader("Analyst Scoring Configuration")

        st.markdown("**Scoring Weights** (must sum to 100%)")
        weights = analyst_cfg.get("scoring_weights", {
            "theme_alignment": 0.25,
            "eligibility_confidence": 0.20,
            "funding_amount": 0.20,
            "deadline_urgency": 0.15,
            "geography_fit": 0.10,
            "competition_level": 0.10,
        })

        w_theme = st.slider("Theme Alignment", 0, 50, int(weights.get("theme_alignment", 0.25) * 100))
        w_elig = st.slider("Eligibility Confidence", 0, 50, int(weights.get("eligibility_confidence", 0.20) * 100))
        w_fund = st.slider("Funding Amount", 0, 50, int(weights.get("funding_amount", 0.20) * 100))
        w_dead = st.slider("Deadline Urgency", 0, 40, int(weights.get("deadline_urgency", 0.15) * 100))
        w_geo = st.slider("Geography Fit", 0, 30, int(weights.get("geography_fit", 0.10) * 100))
        w_comp = st.slider("Competition Level", 0, 30, int(weights.get("competition_level", 0.10) * 100))

        total_weight = w_theme + w_elig + w_fund + w_dead + w_geo + w_comp
        if total_weight != 100:
            st.markdown(
                f"<div style='background:var(--orange-bg);border:1px solid var(--orange-border);border-radius:8px;"
                f"padding:10px 12px;display:flex;gap:8px;align-items:center;margin:8px 0;'>"
                f"{icons.svg('alert-triangle',15,'var(--orange)')}"
                f"<span style='color:var(--orange-2);font-size:0.88em;'>Weights sum to {total_weight}% — must be exactly 100%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.divider()
        pursue_t = st.slider("Pursue threshold (score ≥)", 5.0, 9.0, float(analyst_cfg.get("pursue_threshold", 6.5)), step=0.1)
        watch_t = st.slider("Watch threshold (score ≥)", 3.0, 7.0, float(analyst_cfg.get("watch_threshold", 5.0)), step=0.1)
        min_funding = st.number_input("Minimum grant size ($)", value=int(analyst_cfg.get("min_funding", 3000)), step=500)
        perplexity_on = st.toggle("Enable Perplexity funder enrichment", value=analyst_cfg.get("perplexity_enrichment", True))

        if st.button("Save Analyst Config", type="primary"):
            if total_weight == 100:
                new_cfg = {
                    "scoring_weights": {
                        "theme_alignment": w_theme / 100,
                        "eligibility_confidence": w_elig / 100,
                        "funding_amount": w_fund / 100,
                        "deadline_urgency": w_dead / 100,
                        "geography_fit": w_geo / 100,
                        "competition_level": w_comp / 100,
                    },
                    "pursue_threshold": pursue_t,
                    "watch_threshold": watch_t,
                    "min_funding": min_funding,
                    "perplexity_enrichment": perplexity_on,
                }
                save_agent_config("analyst", new_cfg)
                st.success("Analyst config saved!")
            else:
                st.error("Fix weights to sum to 100% before saving.")

    # ── Drafter tab ───────────────────────────────────────────────────────────
    with tab_drafter:
        st.subheader("Drafter Configuration")

        writing_style = st.selectbox(
            "Writing style",
            ["professional", "technical", "concise", "narrative"],
            index=["professional", "technical", "concise", "narrative"].index(
                drafter_cfg.get("writing_style", "professional")
            ),
        )
        word_buffer = st.slider("Word limit buffer (%)", 0, 20, int(drafter_cfg.get("word_limit_buffer_pct", 10)),
                                help="Write this % under the limit to stay safe")
        context_chunks = st.slider("Company Brain chunks per section", 2, 12, int(drafter_cfg.get("context_chunks_per_section", 6)))
        custom_instructions = st.text_area(
            "Custom writing instructions",
            value=drafter_cfg.get("custom_instructions", ""),
            placeholder="e.g. Always mention AltCarbon's carbon credit verification methodology. Avoid jargon.",
            height=100,
        )

        if st.button("Save Drafter Config", type="primary"):
            save_agent_config("drafter", {
                "writing_style": writing_style,
                "word_limit_buffer_pct": word_buffer,
                "context_chunks_per_section": context_chunks,
                "custom_instructions": custom_instructions,
            })
            st.success("Drafter config saved!")

    # ── System tab ────────────────────────────────────────────────────────────
    with tab_system:
        st.subheader("System Status")
        import os
        checks = [
            ("ANTHROPIC_API_KEY", "Anthropic"),
            ("OPENAI_API_KEY", "OpenAI Embeddings"),
            ("TAVILY_API_KEY", "Tavily"),
            ("EXA_API_KEY", "Exa"),
            ("PERPLEXITY_API_KEY", "Perplexity"),
            ("NOTION_TOKEN", "Notion"),
            ("MONGODB_URI", "MongoDB"),
            ("RAILWAY_URL", "Railway Backend"),
        ]
        for env_key, label in checks:
            val = os.environ.get(env_key, "")
            if val:
                st.markdown(
                    f"{icons.svg('check-circle', 14, 'var(--green)')} "
                    f"<span style='color:var(--text);font-weight:500;'>{label}</span> "
                    f"<span style='color:var(--green);font-size:0.82em;'>configured</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"{icons.svg('x-circle', 14, 'var(--red)')} "
                    f"<span style='color:var(--text);font-weight:500;'>{label}</span> "
                    f"<span style='color:var(--red);font-size:0.82em;'>not set</span>",
                    unsafe_allow_html=True,
                )

        st.divider()
        st.markdown("**Cron Schedules**")
        st.code("Scout: 0 2 */2 * *   (2am every 2 days)\nKnowledge sync: 0 0 * * *   (midnight daily)")

        st.divider()
        st.markdown("**Data Management**")
        col1, col2 = st.columns(2)
        if col1.button("Clear triage queue"):
            from app.db.queries import _db
            _db()["grants_scored"].update_many({"status": "triage"}, {"$set": {"status": "auto_pass"}})
            st.success("Triage queue cleared")

        from app.db.queries import export_grants_csv
        csv_data = export_grants_csv()
        col2.download_button(
            "Export CSV",
            data=csv_data,
            file_name="altcarbon_grants.csv",
            mime="text/csv",
        )
