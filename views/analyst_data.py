"""Analyst > Data & downloads: every table behind the site, and the files to take away."""
import json

import streamlit as st

from webapp import data, mapping, state, ui

ui.page_header("Data & downloads", "The tables behind every page, for the ships and dates you pick.", eyebrow="Analyst")
group = state.param("group", data.GROUPS, "mining")
window = state.param("time", data.WINDOWS, "6m")
c1, c2 = st.columns(2)
g = c1.pills("Ships", list(data.GROUPS), default=group, format_func=data.GROUPS.get, key="data-group")
w = c2.pills("Time", list(data.WINDOWS), default=window, format_func=lambda k: data.WINDOWS[k][0], key="data-time")
if (g or group) != group or (w or window) != window:
    state.set_params(group=g or group, time=w or window)
    st.rerun()

res = ui.results(group, window)
if res is None:
    ui.empty_state("No ship in this group has positions in that time.", [("Try all data", {"time": "all"})])
    ui.footer()
    st.stop()
r, T = res["res"], res["res"]["tables"]

d1, d2, d3, d4 = st.columns(4)
d1.download_button("Everything (ZIP)", r["zip"], "survey_results.zip", "application/zip",
                   help="CSVs and GeoJSON (combined and per layer).")
xlsx_ready = (r["id"], "xlsx") in st.session_state.get("made_files", {})
if xlsx_ready or d2.button("Prepare Excel workbook", help="One sheet per table. Large analyses take a while."):
    with st.spinner("Writing the Excel workbook..."):
        xlsx = data.on_request(r, "xlsx", lambda: data._excel(T))
    d2.download_button("Excel workbook", xlsx, "survey_results.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d3.download_button("GeoJSON (QGIS / ArcGIS)", json.dumps(r["geojson"]), "survey_results.geojson", "application/geo+json")
if d4.button("Prepare map (HTML)", help="The world map as a standalone page to open or share."):
    d4.download_button("Interactive map (HTML)", mapping.map_html(r["geojson"], res["vessels"], None, res["labels"]),
                       "survey_map.html", "text/html")
det = res["intel"]["detections"]
if len(det):
    st.download_button("Findings with priority and reasons (CSV)",
                       det.assign(why=det["why"].map("; ".join),
                                  pri_parts=det["pri_parts"].map(lambda ps: "; ".join(f"{p[1]}={p[2]}" for p in ps)),
                                  conf_parts=det["conf_parts"].map(lambda ps: "; ".join(f"{p[0]}={p[1]}" for p in ps)),
                                  coord=det["coord"].map(" ".join)).to_csv(index=False),
                       "findings.csv", "text/csv")

notes = r.get("notes", [])
if notes:
    with st.expander(f"Notes on the data ({len(notes)})"):
        for note in notes:
            st.warning(note)

SHOW_ROWS = 1000   # every table is sent to the browser on each run: keep big ones short
names = {"survey_areas": "Survey areas", "vessels": "Ships", "nearby_ports": "Nearby ports",
         "survey_hotspots": "Hotspots", "survey_blocks": "Survey blocks", "survey_lines": "Survey lines",
         "rejected_blocks": "Rejected patterns", "predictions": "Predictions", "positions_processed": "Positions"}
extra = {"Stations": res["intel"]["stations"], "Port calls": res["intel"]["calls"], "AIS gaps": res["intel"]["gaps"]}
tabs = st.tabs(list(names.values()) + list(extra) + ["Rare-earth linked ports"])
for tab, (key, df) in zip(tabs, [(k, T[k]) for k in names] + list(extra.items())):
    with tab:
        if len(df):
            show = df.drop(columns=["gfw", "station"], errors="ignore").head(SHOW_ROWS).copy()
            text = show.select_dtypes(include=["object", "string"]).columns
            show[text] = show[text].astype(str).replace({"None": "", "nan": ""})
            if len(df) > SHOW_ROWS:
                st.caption(f"First {SHOW_ROWS:,} of {len(df):,} rows. The full table is in the ZIP.")
            st.dataframe(show, hide_index=True, width="stretch")
        else:
            st.write("Nothing found.")
with tabs[-1]:
    st.caption("Ports within 300 km of a rare-earth processing site or mine, or known to handle rare-earth cargo, "
               "near the surveys found.")
    if len(res["linked"]):
        ui.port_table(res["linked"].sort_values("sea_km").head(SHOW_ROWS), extra=("vessel", "area_id"))
    else:
        st.write("No rare-earth linked ports near the surveys found.")
ui.footer("Compare models", "views/analyst_compare.py")
