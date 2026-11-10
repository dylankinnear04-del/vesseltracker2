"""
The Analyst pages' look, matching the SeaTrace console (dark ops theme, IBM Plex, accent #5cc8ff), and the
small pieces they share: header with a way back to SeaTrace, stat tiles, pills, empty states, footer.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from webapp import data, state
from webapp.mapping import dataset_note, vessel_label  # noqa: F401 (re-exported for pages)

TIER_COLORS = {"P1": "#ff5f56", "P2": "#f4a93b", "P3": "#5aa9d6", "P4": "#748797"}     # SeaTrace's tiers
FLAG_CODES = {"China": "CN", "France": "FR", "Japan": "JP", "United States": "US", "Germany": "DE",
              "Russia": "RU", "Denmark": "DK", "Norway": "NO", "South Korea": "KR", "India": "IN",
              "Malta": "MT", "Marshall Islands": "MH", "Saint Kitts and Nevis": "KN", "Taiwan": "TW",
              "United Kingdom": "GB", "Netherlands": "NL", "Belgium": "BE", "Australia": "AU", "Canada": "CA",
              "Singapore": "SG", "Hong Kong": "HK", "Panama": "PA", "Liberia": "LR"}
CREDITS = (
    "Ship tracks, registry and events: Powered by Global Fishing Watch (CC BY-NC 4.0, non-commercial). "
    "US reference tracks: NOAA Marine Cadastre. Ports: NGA World Port Index. EEZs: Marine Regions World EEZ v12 "
    "(CC BY 4.0). Seabed depth: NOAA ETOPO 2022. ISA contract areas: International Seabed Authority, read live, "
    "not stored. Land: Natural Earth. Interface: SeaTrace, a JMU capstone prototype, adapted.")

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600;700&display=swap');
:root { --bg:#07121a; --panel:#0c1a24; --panel-2:#10212d; --line:#1c3141; --line-2:#284457; --ink:#dde8ef; --ink-2:#a1b5c3;
  --ink-3:#6f8797; --accent:#5cc8ff; --f-mono:'IBM Plex Mono',ui-monospace,Menlo,monospace; --f-display:'IBM Plex Sans Condensed',sans-serif; }
.num, .mono, [data-testid="stMetricValue"] { font-family: var(--f-mono); font-variant-numeric: tabular-nums; }
h1, h2, h3, h4 { font-family: var(--f-display); letter-spacing: .01em; }
.st-bar { display:flex; align-items:center; gap:10px; border-bottom:1px solid var(--line); padding:0 0 10px; margin-bottom:14px; }
.st-bar b { font:600 15px var(--f-display); letter-spacing:.06em; color:var(--ink); }
.st-bar span { font:600 10.5px var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--accent); }
.st-head h1 { font:600 26px var(--f-display); margin:0 0 4px; }
.st-head p { color:var(--ink-2); max-width:75ch; margin:0 0 12px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:8px; margin:6px 0 14px; }
.tile { background:var(--panel-2); border:1px solid var(--line); border-radius:6px; padding:9px 12px; }
.tile .v { font:500 22px var(--f-mono); color:var(--ink); } .tile .l { font:600 10px var(--f-mono); letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); }
.pill { display:inline-block; font:600 10px var(--f-mono); letter-spacing:.06em; padding:1px 6px; border-radius:4px; border:1px solid currentColor; }
.empty { border:1px dashed var(--line-2); padding:16px; text-align:center; color:var(--ink-2); border-radius:6px; }
.why { margin:4px 0 0 16px; padding:0; color:var(--ink-2); font-size:12.5px; }
.st-foot { margin-top:28px; padding-top:10px; border-top:1px solid var(--line); font-size:11.5px; color:var(--ink-3); }
</style>"""

LOGO = ('<svg width="24" height="24" viewBox="0 0 30 30" aria-hidden="true"><circle cx="15" cy="15" r="13.5" fill="none" '
        'stroke="#5cc8ff" stroke-width="1.4"/><path d="M4 15c3.5-4 7-4 11 0s7.5 4 11 0" fill="none" stroke="#5cc8ff" '
        'stroke-width="1.4"/><path d="M7 20.5c2.8-2.4 5.4-2.4 8 0s5.2 2.4 8 0" fill="none" stroke="#5cc8ff88" stroke-width="1.2"/>'
        '<circle cx="15" cy="9" r="2" fill="#ffd34d"/></svg>')


def esc(x) -> str:
    return html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


def inject_css() -> None:
    st.html(CSS)


def page_header(title: str, lede: str = "", eyebrow: str = "Analyst") -> None:
    """SeaTrace's slim brand bar with a way back to the console, then the page title."""
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.markdown(f'<div class="st-bar">{LOGO}<b>SEATRACE</b><span>{esc(eyebrow)}</span></div>', unsafe_allow_html=True)
    c2.page_link("views/console.py", label="← Back to SeaTrace")
    st.markdown(f'<div class="st-head"><h1>{esc(title)}</h1>' + (f"<p>{esc(lede)}</p>" if lede else "") + "</div>",
                unsafe_allow_html=True)


def stat_tiles(items: list) -> None:
    cells = "".join(f'<div class="tile" title="{esc(h or "")}"><div class="v">{esc(v)}</div><div class="l">{esc(lab)}</div></div>'
                    for v, lab, h in items)
    st.markdown(f'<div class="tiles">{cells}</div>', unsafe_allow_html=True)


def tier_pill(tier: str) -> str:
    return f'<span class="pill" style="color:{TIER_COLORS.get(tier, "#748797")}">{esc(tier)}</span>'


def kind_pill(kind: str) -> str:
    return f'<span class="pill" style="color:{"#ffd34d" if kind == "survey" else "#a585ff"}">{"SURVEY" if kind == "survey" else "STATION"}</span>'


def why_list(items, limit: int | None = None) -> str:
    items = list(items)[:limit] if limit else list(items)
    return '<ul class="why">' + "".join(f"<li>{esc(w)}</li>" for w in items) + "</ul>" if items else ""


def flag_emoji(country: str) -> str:
    code = FLAG_CODES.get(country)
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code) if code else "🏳️"


def empty_state(message: str, actions: list | None = None) -> None:
    st.markdown(f'<div class="empty">{esc(message)}</div>', unsafe_allow_html=True)
    if actions:
        for col, (label, params) in zip(st.columns(len(actions)), actions):
            if col.button(label, key=f"empty|{label}", width="stretch"):
                state.set_params(**params)
                st.rerun()


def footer(next_label: str | None = None, next_page: str | None = None, params: dict | None = None) -> None:
    if next_label and next_page:
        st.page_link(next_page, label=f"{next_label} →", query_params=params)
    st.markdown(f'<div class="st-foot">{esc(CREDITS)}</div>', unsafe_allow_html=True)


def results(group: str, window: str, countries: tuple = ()) -> dict | None:
    with st.spinner("Reading the ships' tracks and finding surveys: about a minute the first time..."):
        return data.public_results(group, window, tuple(countries), state.results_settings(), state.results_station())


PORT_VIEW = {"category": "List", "rank": "#", "port": "Port", "country": "Country", "harbor_size": "Size",
             "sea_km": st.column_config.NumberColumn("Distance (km)", format="%.0f"),
             "hours_at_10kn": st.column_config.NumberColumn("Hours at 10 kn", format="%.0f"),
             "distance_basis": "Measured by", "ree_link": "Rare-earth link", "ree_site": "Linked site",
             "ree_site_km": st.column_config.NumberColumn("Site distance (km)", format="%.0f"),
             "ree_site_status": "Site status", "solid_bulk": "Bulk cargo", "railway": "Railway",
             "max_vessel_draft_m": "Max draught (m)", "ree_note": "Note"}


def port_table(df: pd.DataFrame, extra: tuple = ()):
    cols = list(extra) + [c for c in PORT_VIEW if c in df]
    st.dataframe(df[cols].reset_index(drop=True), hide_index=True, width="stretch",
                 column_config={k: v for k, v in PORT_VIEW.items() if k in cols})
