"""Analyst > Upload your own track: run the detectors on your own AIS files."""
import re

import streamlit as st

import port_intel
from webapp import data, seatrace_export as sx, state, ui

ui.page_header("Upload your own track", "Run the survey and station detectors on your own AIS position files. "
               "Files stay in this session: they are not stored or shared.", eyebrow="Analyst")
c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
uploads = c1.file_uploader("AIS position files", type=data.UPLOAD_TYPES, accept_multiple_files=True,
                           help="CSV, TSV, TXT or Excel; one ship or many per file. Columns such as Latitude/Longitude, "
                                "Timestamp, MMSI, SOG, COG, ship name and type are recognised automatically.")
if c2.button("Try a sample file", help="Ten synthetic ships, six of them surveying (benchmarks/)."):
    f = data.HERE / "benchmarks" / "synthetic_10_ships.csv"
    st.session_state["upload_files"] = [(f.name, f.read_bytes())]
if uploads:
    st.session_state["upload_files"] = [(u.name, u.getvalue()) for u in uploads]
files = st.session_state.get("upload_files", [])
combine = len(files) > 1 and st.toggle("Combine all files into one dataset",
                                       help="Use this when the files are parts of one export, e.g. one file per day.")
if not files:
    st.info("Choose files above, or try the sample.")
    ui.footer()
    st.stop()

groups = data.groups_from_uploads(files, combine)
given = st.session_state.setdefault("identities", {})
ident = tuple(sorted((k[0], k[1], v["mmsi"], v["flag"], v["name"], "entered", "") for k, v in given.items()))
with st.spinner("Finding surveys and stations in your files..."):
    res, err = data.run_upload(groups, ident, state.results_settings(), state.results_station())
if err:
    st.error(err)
    ui.footer()
    st.stop()
st.session_state["upload_groups"] = groups      # Validation can run models on them

# --- ships whose files carry no identity -----------------------------------------------------------
V = res["vessels"]
need = V[(V["flag"] == "") | V["flag_source"].eq("entered")]
if len(need):
    with st.expander(f"Identify ships with an unknown flag ({int((need['flag'] == '').sum())} unknown)",
                     expanded=bool((need["flag"] == "").any())):
        st.caption("Their files carry no MMSI or flag (MarineTraffic exports, for example). Enter the MMSI and the "
                   "flag follows from its first three digits, or pick the flag. To skip this, put the MMSI in the "
                   "file name, e.g. 413123456_export.csv.")
        flag_names = sorted(set(port_intel.port_countries()) | {re.sub(r"\s*\(.*\)", "", c) for c in port_intel.MID_COUNTRY.values()})
        with st.form("identities_form"):
            typed = {}
            for _, v in need.iterrows():
                key = (v["dataset"], v["vessel"])
                old = given.get(key, {"mmsi": "", "flag": "", "name": ""})
                i1, i2, i3, i4 = st.columns([3, 2, 2, 2])
                i1.markdown(f"**{ui.vessel_label(v)}**{ui.dataset_note(v)}")
                tag = f"{v['dataset']}|{v['vessel']}"
                typed[key] = {"mmsi": i2.text_input("MMSI", value=old["mmsi"], key=f"id_mmsi_{tag}", placeholder="e.g. 413123456"),
                              "flag": i3.selectbox("or flag", [""] + flag_names, key=f"id_flag_{tag}",
                                                   index=([""] + flag_names).index(old["flag"]) if old["flag"] in flag_names else 0),
                              "name": i4.text_input("Name (optional)", value=old["name"], key=f"id_name_{tag}")}
            if st.form_submit_button("Apply and re-run"):
                bad = [k for k, t in typed.items() if t["mmsi"] and not re.fullmatch(r"\d{9}", t["mmsi"].strip())]
                if bad:
                    st.error("An MMSI is 9 digits: check " + ", ".join(vs for _, vs in bad) + ".")
                else:
                    st.session_state["identities"] = {k: {f: t[f].strip() for f in t} for k, t in typed.items() if any(t.values())}
                    st.rerun()

# --- results: open them in SeaTrace -----------------------------------------------------------------
det = res["intel"]["detections"]
ui.stat_tiles([(len(V), "ships", None), (len(res["areas"]), "survey areas", None),
               (int((det["kind"] == "station").sum()) if len(det) else 0, "stations", None),
               (int((det["tier"] == "P1").sum()) if len(det) else 0, "P1 findings", None)])
for note in res["res"].get("notes", []):
    st.warning(note)
c1, c2 = st.columns([1, 1])
if c1.button("Open in SeaTrace →", type="primary", width="stretch"):
    with st.spinner("Preparing your files for the console..."):
        blob = sx.build_blob(res, data.library(), data.isa_zones(), state.results_station(), view=None)
        st.session_state["upload_payload"] = (sx.to_json(blob),) + sx.header_text(blob)
    st.switch_page("views/console.py", query_params={"source": "upload"})
c2.download_button("Download all results (ZIP)", res["res"]["zip"], "survey_results.zip", "application/zip", width="stretch")
for _, d in det.head(12).iterrows():
    head = f"SURVEY AREA {int(d['area_number'])}" if d["kind"] == "survey" else f"STATION · {d['id'].split('-', 1)[1]}"
    st.markdown(f'<div class="tile" style="margin-bottom:6px"><span class="l">{head}</span><br><b>{ui.esc(d["name"])}</b> '
                f'{ui.tier_pill(d["tier"])} {ui.kind_pill(d["kind"])}{ui.why_list(d["why"], 3)}</div>', unsafe_allow_html=True)
ui.footer()
