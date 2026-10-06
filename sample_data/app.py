"""
SURVEY DETECTOR WEB APP  (v3)
=============================

Upload AIS exports; every file is a dataset. All datasets are drawn on one
interactive world map with switchable layers (tracks, survey patterns,
predicted lines and vessel positions per dataset, plus ports and rare-earth
sites), and each vessel gets an information panel with the ports nearest its
survey, highlighting those linked to rare-earth processing.

    streamlit run app.py            # run locally at http://localhost:8501

Detection: survey_pattern_detector.py. Ports and rare-earth sites:
port_intel.py with reference_data/.
"""

from __future__ import annotations

import html
import io
import json
import tempfile
import warnings
import zipfile
from dataclasses import asdict
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from folium.plugins import FastMarkerCluster, GroupedLayerControl

import port_intel
import survey_pattern_detector as spd

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample_data" / "synthetic_10_ships.csv"
UPLOAD_TYPES = ["csv", "txt", "tsv", "xlsx", "xlsm"]
TABLES = ["vessels", "nearby_ports", "survey_areas", "survey_blocks", "survey_lines",
          "predictions", "positions_processed"]

SETTINGS = {
    "Cleaning": {
        "min_speed_kn": "Points slower than this are loitering/drifting and dropped (knots).",
        "min_step_km": "A point closer than this to the previous one counts as stationary.",
        "max_implied_speed_kn": "Faster than this between fixes = bad position.",
        "max_gap_hours": "Split the track at reporting gaps longer than this.",
        "max_gap_km_no_time": "Without timestamps, split the track at jumps longer than this.",
    },
    "Straight lines": {
        "rdp_tolerance_km": "How far a track may wander and still count as straight.",
        "min_segment_km": "Shorter pieces are treated as turns.",
        "merge_heading_tol_deg": "Pieces within this heading of each other can join into one line.",
        "merge_offset_km": "Pieces this close to one line get merged.",
        "merge_gap_km": "...across at most this much turn or dog-leg.",
        "min_line_km": "Shortest straight line counted as a survey line.",
        "min_points_per_line": "Fewest position reports a line may have.",
    },
    "Lawnmower pattern": {
        "antiparallel_tol_deg": "Next line must run within this of the opposite direction.",
        "block_axis_tol_deg": "Every line must stay within this of the block's axis.",
        "min_spacing_km": "Narrowest gap between adjacent lines.",
        "max_spacing_km": "Widest gap between adjacent lines.",
        "min_overlap_frac": "Adjacent lines must cover at least this share of the same stretch.",
        "min_length_ratio": "Shorter line / longer line, for adjacent lines.",
        "max_connector_km": "Longest turn between the end of one line and the next.",
        "max_skip_lines": "Odd lines (cross-lines, turn pieces) tolerated inside a block.",
        "min_lines_per_block": "Fewest lines that make a survey block.",
        "area_join_km": "Blocks this close with the same axis form one survey area.",
    },
    "Prediction": {
        "predict_lines": "How many upcoming lines to project.",
        "min_progression_for_prediction": "Only predict when at least this share of steps advance the same way.",
    },
}

# one colour per dataset; red/orange/gold are kept for rare-earth ports, magenta for predictions
DATASET_COLORS = ["#2f6fdf", "#16a34a", "#8e44ad", "#0e9aa7", "#8d5a3b", "#d63384",
                  "#5c6f82", "#9aa20f"]
PREDICTION_COLOR = "#ff2fb3"
LINK_COLORS = {"Known rare-earth cargo port": "#d62728",
               "Near rare-earth processing site": "#f28e2b",
               "Near rare-earth mine": "#c9a227"}
PLAIN_PORT_COLOR = "#3b5b7d"
FLAG_PORT_COLOR = "#ffc400"     # ring around ports of the vessel's flag state / chosen country
FLAG_CATEGORIES = ("flag-state port", "flag-state rare-earth linked port")
SITE_STYLES = {  # type -> (colour, marker sides (0 = area circle), layer name)
    "processing": ("#7b1fa2", 4, "Processing & separation plants"),
    "magnet": ("#c2185b", 4, "Magnet & metal plants"),
    "mine": ("#6d4c41", 3, "Mines & deposits"),
    "logistics port": ("#d62728", 4, "Rare-earth cargo ports"),
    "seabed area": ("#00838f", 0, "Seabed mineral areas (approx.)"),
}


# ============================================================
# RUNNING THE DETECTOR
# ============================================================

@st.cache_data(show_spinner=False, max_entries=6)
def analyse(files: tuple, settings: dict, separate: bool) -> dict:
    """Run the detector on uploaded (name, bytes) pairs and collect everything the page shows."""
    cfg = spd.Config(**settings)
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "input", Path(tmp) / "results"
        src.mkdir()
        paths = []
        for i, (name, data) in enumerate(files):
            path = src / f"{i:03d}" / Path(name).name    # each file keeps its own name
            path.parent.mkdir()
            path.write_bytes(data)
            paths.append(str(path))
        sources = paths if separate else {"Combined upload": paths}

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results, notes, n_rows = spd.run(sources, cfg, out, workers=1, make_maps=True)

        tables = {}
        for key in TABLES:
            try:
                tables[key] = pd.read_csv(out / f"{key}.csv", low_memory=False)
            except (FileNotFoundError, pd.errors.EmptyDataError):
                tables[key] = pd.DataFrame()
        maps = {p.name: p.read_bytes() for p in sorted((out / "maps").glob("*.png"))}
        geojson = json.loads((out / "survey_results.geojson").read_text())
        xlsx = _excel(tables)
        zip_bytes = _zip_folder(out, extra={"survey_results.xlsx": xlsx})
    return {"notes": notes, "n_rows": n_rows, "tables": tables, "maps": maps,
            "geojson": geojson, "zip": zip_bytes, "xlsx": xlsx}


def _excel(tables: dict) -> bytes:
    names = {"vessels": "Vessels", "nearby_ports": "Nearby Ports", "survey_areas": "Survey Areas",
             "survey_blocks": "Survey Blocks", "survey_lines": "Survey Lines",
             "predictions": "Predictions", "positions_processed": "Positions"}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for key, sheet in names.items():
            tables[key].to_excel(xl, sheet_name=sheet, index=False)
    return buf.getvalue()


def _zip_folder(folder: Path, extra: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path("survey_results") / p.relative_to(folder))
        for name, data in extra.items():
            z.writestr(f"survey_results/{name}", data)
    return buf.getvalue()


# ============================================================
# MAP
# ============================================================

def _latlon_parts(coords):
    """[[lon, lat], ...] -> pieces of [[lat, lon], ...], split where the line crosses 180°."""
    parts, cur = [], []
    for lon, lat in coords:
        if cur and abs(lon - cur[-1][1]) > 180:
            parts.append(cur)
            cur = []
        cur.append([lat, lon])
    parts.append(cur)
    return [p for p in parts if len(p) > 1]


def _polyline(coords, group, **style):
    for part in _latlon_parts(coords):
        folium.PolyLine(part, **style).add_to(group)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan")


def _rows(pairs) -> str:
    """Popup table from (label, value) pairs, skipping empty values."""
    cells = "".join(f"<tr><td style='color:#666;padding-right:8px;vertical-align:top'>"
                    f"{html.escape(str(k))}</td><td>{v}</td></tr>" for k, v in pairs if not _blank(v))
    return f"<table style='font-size:12px'>{cells}</table>"


def _km(x) -> str:
    return "" if _blank(x) else f"{float(x):,.0f} km"


def vessel_label(row) -> str:
    name = row.get("name") or ""
    return f"{name} ({row['vessel']})" if name and name != str(row["vessel"]) else str(row["vessel"])


def _vessel_popup(v) -> str:
    link = (f"<a href='{html.escape(v['marinetraffic_url'])}' target='_blank'>MarineTraffic</a>"
            if v["marinetraffic_url"] else "")
    return _rows([
        ("Vessel", f"<b>{html.escape(vessel_label(v))}</b>"), ("Dataset", html.escape(v["dataset"])),
        ("MMSI", v["mmsi"]), ("IMO", v["imo"]), ("Flag", v["flag"]), ("Type", v["ship_type"]),
        ("Status", f"<b>{v['survey_status']}</b>"),
        ("Last position", f"{v['last_lat']:.4f}, {v['last_lon']:.4f}"),
        ("Last report", v.get("last_time")), ("Track", _km(v.get("track_km"))), ("Links", link)])


def _match(f, ds, vessel=None) -> bool:
    p = f["properties"]
    return str(p.get("dataset")) == ds and (vessel is None or str(p.get("vessel")) == vessel)


def build_map(geojson: dict, vessels: pd.DataFrame, focus: tuple | None) -> folium.Map:
    feats = geojson["features"]

    keep = set(zip(vessels["dataset"], vessels["vessel"]))   # vessels passing the flag filter

    def layer(name):
        return [f for f in feats if f["properties"]["layer"] == name
                and (name == "ree_site" or (str(f["properties"].get("dataset")),
                                            str(f["properties"].get("vessel"))) in keep)]

    m = folium.Map(location=[15, 0], zoom_start=2, min_zoom=2, tiles=None,
                   world_copy_jump=True, control_scale=True, prefer_canvas=True)
    # Esri basemaps need no API key (Carto's now do)
    esri = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    for service, name, attr, native in (
            ("Ocean/World_Ocean_Base", "Ocean", "Esri, GEBCO, NOAA, Garmin, HERE", 10),
            ("World_Imagery", "Satellite", "Esri, Maxar, Earthstar Geographics", 18),
            ("Canvas/World_Light_Gray_Base", "Light", "Esri, HERE, Garmin", 16),
            ("Canvas/World_Dark_Gray_Base", "Dark", "Esri, HERE, Garmin", 16)):
        folium.TileLayer(esri.format(service), name=name, attr=f"Tiles &copy; {attr}",
                         max_native_zoom=native, max_zoom=18, show=name == "Ocean").add_to(m)

    groups, bounds = {}, []
    for i, ds in enumerate(dict.fromkeys(vessels["dataset"])):
        color = DATASET_COLORS[i % len(DATASET_COLORS)]
        survey = folium.FeatureGroup("Survey patterns")
        preds = folium.FeatureGroup("Predicted next lines")
        tracks = folium.FeatureGroup("Vessel tracks")
        boats = folium.FeatureGroup("Vessel positions")

        for f in layer("track"):
            if _match(f, ds):
                _polyline(f["geometry"]["coordinates"], tracks, color=color, weight=1.5, opacity=0.55,
                          tooltip=f"{f['properties']['vessel']} track")
        for f in layer("survey_block"):
            if not _match(f, ds):
                continue
            p = f["properties"]
            ring = [[lat, lon] for lon, lat in f["geometry"]["coordinates"][0]]
            folium.Polygon(ring, color=color, weight=1, fill=True, fill_opacity=0.18,
                           tooltip=f"{p['vessel']} · block {p['block_id']} · {p['confidence']} confidence",
                           popup=folium.Popup(_rows([
                               ("Vessel", p["vessel"]), ("Block", p["block_id"]), ("Status", p["status"]),
                               ("Confidence", f"{p['confidence']} ({p['score']})"), ("Lines", p["n_lines"]),
                               ("Line direction", p["line_axis_compass"]),
                               ("Spacing", f"{p['median_spacing_km']} km"),
                               ("Area", f"{p['area_km2']} km²")]), max_width=320)).add_to(survey)
        for f in layer("survey_area"):
            if not _match(f, ds):
                continue
            p = f["properties"]
            ring = [[lat, lon] for lon, lat in f["geometry"]["coordinates"][0]]
            bounds += ring
            folium.Polygon(ring, color=color, weight=2.5, dash_array="6 4", fill=False,
                           tooltip=f"{p['vessel']} · survey area {p['area_id']} · {p['status']}").add_to(survey)
        for f in layer("line"):
            if _match(f, ds) and (f["properties"].get("block_id") or -1) > 0:
                _polyline(f["geometry"]["coordinates"], survey, color=color, weight=3, opacity=0.95)
        has_preds = False
        for f in layer("predicted_line"):
            if _match(f, ds):
                has_preds = True
                p = f["properties"]
                _polyline(f["geometry"]["coordinates"], preds, color=PREDICTION_COLOR, weight=4,
                          dash_array="8 6",
                          tooltip=f"{p['vessel']}: {p['kind']} (+{p['hours_after_last_fix_start']} h)")

        for _, v in vessels[vessels["dataset"] == ds].iterrows():
            if pd.isna(v["last_lat"]):
                continue
            live = v["survey_status"] == "Surveying now"
            folium.Marker([v["last_lat"], v["last_lon"]],
                          tooltip=f"{vessel_label(v)} · {v['survey_status']}",
                          popup=folium.Popup(_vessel_popup(v), max_width=340),
                          icon=folium.Icon(color="red" if live else "blue" if v["survey_areas"] else "gray",
                                           icon="ship", prefix="fa")).add_to(boats)
            if not v["survey_areas"]:
                bounds.append([v["last_lat"], v["last_lon"]])

        groups[f"Dataset: {ds}"] = [survey] + ([preds] if has_preds else []) + [tracks, boats]

    # --- ports near surveys and the routes to them ---------------------------
    linked_ports = folium.FeatureGroup("Rare-earth linked ports")
    plain_ports = folium.FeatureGroup("Other nearby ports")
    flag_ports = folium.FeatureGroup("Ports in flag state / chosen country")
    linked_routes = folium.FeatureGroup("Routes to rare-earth linked ports")
    flag_routes = folium.FeatureGroup("Routes to flag-state / chosen-country ports")
    plain_routes = folium.FeatureGroup("Routes to other nearby ports", show=False)
    by_port = {}
    for f in layer("nearby_port"):
        p = f["properties"]
        by_port.setdefault((p["port"], p["country"], p["lat"], p["lon"]), []).append(p)
    for (name, country, lat, lon), rows in by_port.items():
        p = rows[0]
        link = "" if _blank(p.get("ree_link")) else p["ree_link"]
        surveys = "<br>".join(f"{html.escape(str(r['vessel']))} area {r['area_id']}: "
                              f"{_km(r['sea_km'])} ({r['distance_basis']})" for r in rows)
        folium.CircleMarker(
            [lat, lon], radius=8 if link else 5, color="#222", weight=1, fill=True,
            fill_color=LINK_COLORS.get(link, PLAIN_PORT_COLOR), fill_opacity=0.95,
            tooltip=f"{name} ({country})" + (f" · {link}" if link else ""),
            popup=folium.Popup(_rows([
                ("Port", f"<b>{html.escape(name)}</b>"), ("Country", country),
                ("Harbour size", p["harbor_size"]), ("Rare-earth link", f"<b>{link}</b>" if link else ""),
                ("Linked site", p.get("ree_site")),
                ("Site distance", _km(p.get("ree_site_km")) if link else ""),
                ("Note", p.get("ree_note")), ("Max draught (m)", p.get("max_vessel_draft_m")),
                ("Bulk cargo", p.get("solid_bulk")), ("Railway", p.get("railway")),
                ("Distance from surveys", surveys)]), max_width=380),
        ).add_to(linked_ports if link else plain_ports)
        home = sorted({r["match_country"] for r in rows if r["category"] in FLAG_CATEGORIES})
        if home:   # a ring marks ports of the matched country
            folium.CircleMarker([lat, lon], radius=12, color=FLAG_PORT_COLOR, weight=3, fill=False,
                                tooltip=f"{name}: port in {', '.join(home)}").add_to(flag_ports)
    for f in layer("port_route"):
        p = f["properties"]
        linked = not _blank(p.get("ree_link"))
        home = p.get("category") in FLAG_CATEGORIES
        _polyline(f["geometry"]["coordinates"],
                  flag_routes if home else linked_routes if linked else plain_routes,
                  color=FLAG_PORT_COLOR if home else
                  LINK_COLORS["Known rare-earth cargo port"] if linked else PLAIN_PORT_COLOR,
                  weight=1.5, opacity=0.6, dash_array="4 6",
                  tooltip=f"{p['vessel']} area {p['area_id']} → {p['port']}: {_km(p['sea_km'])} "
                          f"({p['distance_basis']})")

    # --- rare-earth sites ------------------------------------------------------
    site_groups = {t: folium.FeatureGroup(name) for t, (_, _, name) in SITE_STYLES.items()}
    for f in layer("ree_site"):
        p = f["properties"]
        if p["type"] not in site_groups:
            continue
        color, sides, _ = SITE_STYLES[p["type"]]
        tip = f"{p['name']} · {p['type']} ({p['status']})"
        popup = folium.Popup(_rows([("Site", f"<b>{html.escape(p['name'])}</b>"), ("Type", p["type"]),
                                    ("Status", p["status"]), ("Operator", p.get("operator")),
                                    ("Country", p["country"]), ("Note", p.get("notes"))]), max_width=340)
        if sides == 0:   # an area: mark its approximate extent
            folium.Circle([p["lat"], p["lon"]], radius=250_000, color=color, weight=1.5, dash_array="5 5",
                          fill=True, fill_opacity=0.08, tooltip=tip, popup=popup).add_to(site_groups[p["type"]])
        else:   # HTML shapes: RegularPolygonMarker breaks on the canvas renderer
            shape = (f"<div style='width:11px;height:11px;margin:2px;background:{color};"
                     f"border:1px solid #222;transform:rotate(45deg)'></div>" if sides == 4 else
                     f"<div style='width:0;height:0;border-left:8px solid transparent;"
                     f"border-right:8px solid transparent;border-bottom:14px solid {color}'></div>")
            folium.Marker([p["lat"], p["lon"]], tooltip=tip, popup=popup,
                          icon=folium.DivIcon(html=shape, icon_size=(16, 16), icon_anchor=(8, 8),
                                              class_name="ree-site")).add_to(site_groups[p["type"]])

    world_ports = folium.FeatureGroup("All world ports (3,800)", show=False)
    ports = port_intel.load_ports()
    if len(ports):
        FastMarkerCluster(ports[["lat", "lon", "port"]].values.tolist(),
                          callback=("function (row) { return L.circleMarker(new L.LatLng(row[0], row[1]),"
                                    " {radius: 4, color: '#3b5b7d', fillOpacity: 0.8})"
                                    ".bindTooltip(row[2]); }")).add_to(world_ports)

    groups["Ports near surveys"] = [linked_ports, plain_ports, flag_ports, linked_routes,
                                    flag_routes, plain_routes]
    groups["Rare-earth sites"] = list(site_groups.values())
    groups["Reference"] = [world_ports]
    for members in groups.values():
        for g in members:
            g.add_to(m)
    GroupedLayerControl(groups, exclusive_groups=False, collapsed=False).add_to(m)
    folium.LayerControl(position="bottomleft", collapsed=True).add_to(m)   # basemaps

    if focus is not None:
        ds, vessel = focus
        fb = []
        for f in feats:
            if not _match(f, ds, vessel):
                continue
            kind, coords = f["properties"]["layer"], f["geometry"]["coordinates"]
            if kind == "survey_area":
                fb += [[lat, lon] for lon, lat in coords[0]]
            elif kind == "predicted_line":
                fb += [[lat, lon] for lon, lat in coords]
        v = vessels[(vessels["dataset"] == ds) & (vessels["vessel"] == vessel)]
        if len(v) and not pd.isna(v.iloc[0]["last_lat"]):
            fb.append([v.iloc[0]["last_lat"], v.iloc[0]["last_lon"]])
        if len(fb) <= 1:   # no survey: frame the whole track
            fb += [[lat, lon] for f in layer("track") if _match(f, ds, vessel)
                   for lon, lat in f["geometry"]["coordinates"]]
        bounds = fb or bounds
    if bounds:
        lats, lons = [b[0] for b in bounds], [b[1] for b in bounds]
        pad = max(0.3, (max(lats) - min(lats)) * 0.15, (max(lons) - min(lons)) * 0.15)
        m.fit_bounds([[min(lats) - pad, min(lons) - pad], [max(lats) + pad, max(lons) + pad]])
    return m


@st.cache_data(show_spinner=False, max_entries=24)
def map_html(geojson: dict, vessels: pd.DataFrame, focus: tuple | None) -> str:
    return build_map(geojson, vessels, focus).get_root().render()


# ============================================================
# PAGE
# ============================================================

st.set_page_config(page_title="Survey Pattern Detector", page_icon=":ship:", layout="wide")

with st.sidebar:
    st.header("Settings")
    st.caption("The defaults suit most survey vessels. Changes re-run the analysis.")
    defaults = asdict(spd.Config())
    if st.button("Reset to defaults"):
        for name in defaults:
            st.session_state.pop(f"cfg_{name}", None)
    settings = {}
    for group, items in SETTINGS.items():
        with st.expander(group):
            for name, help_text in items.items():
                default = defaults[name]
                label = (name.replace("_", " ").replace(" kn", " (kn)").replace(" km", " (km)")
                         .replace(" deg", " (°)"))
                if isinstance(default, int):
                    settings[name] = int(st.number_input(label, value=default, min_value=0, step=1,
                                                         help=help_text, key=f"cfg_{name}"))
                else:
                    settings[name] = float(st.number_input(label, value=float(default), min_value=0.0,
                                                           format="%g", help=help_text, key=f"cfg_{name}"))
    settings = {**defaults, **settings}   # anything not listed above keeps its default

    st.header("Port matching")
    port_mode = st.radio("Also list the nearest ports of", ["Each vessel's flag state",
                                                             "One country for every vessel", "Nobody"],
                         key="port_mode",
                         help="Matches each survey to ports of a country: its vessel's flag state "
                              "(Chinese ships to Chinese ports, American ships to American ports...), "
                              "or one country you pick for every vessel.")
    if port_mode == "One country for every vessel":
        countries = port_intel.port_countries()
        settings["port_country"] = st.selectbox(
            "Country", countries, index=countries.index("China") if "China" in countries else 0,
            key="port_country_pick")
    else:
        settings["port_country"] = "flag" if port_mode.startswith("Each") else "none"
    st.caption("Flags come from a flag column or, failing that, from the MMSI. China includes Hong "
               "Kong and Macau; the United States includes its territories.")

st.title("Survey Pattern Detector")
st.write("Finds lawnmower seafloor-survey patterns in AIS vessel tracks, draws every dataset on one "
         "world map, and lists the ports near each survey, highlighting those linked to rare-earth "
         "processing. Upload one or more exports: each file becomes its own dataset and map layer.")

uploads = st.file_uploader("AIS position files", type=UPLOAD_TYPES, accept_multiple_files=True,
                           help="CSV, TSV, TXT or Excel; one ship or many per file. Columns such as "
                                "Latitude/Longitude, Timestamp, MMSI, SOG, COG, ship name and type "
                                "are recognised automatically. Up to 200 MB per file.")
separate = True
if uploads and len(uploads) > 1:
    separate = not st.toggle("Combine all files into one dataset", value=False,
                             help="Use this when the files are parts of one export, e.g. one file per day.")
use_sample = False
if not uploads:
    use_sample = st.toggle("Show the example (10 synthetic ships)", value=True)
    if not use_sample:
        st.info("Upload AIS files above to analyse them.")
        st.stop()

files = (tuple((u.name, u.getvalue()) for u in uploads) if uploads
         else ((SAMPLE.name, SAMPLE.read_bytes()),))

with st.spinner("Detecting survey patterns and searching nearby ports..."):
    try:
        res = analyse(files, settings, separate)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        st.error(f"Could not read the data: {exc}")
        st.stop()

if use_sample:
    st.caption("Showing example data: synthetic tracks, not real vessels.")

T = res["tables"]
vessels, ports_tbl, areas, preds = (T["vessels"].copy(), T["nearby_ports"].copy(),
                                    T["survey_areas"], T["predictions"])
for col in ("dataset", "vessel", "name", "mmsi", "imo", "callsign", "flag", "flag_source",
            "ship_type", "destination", "marinetraffic_url", "port_country", "port_country_basis"):
    vessels[col] = (vessels[col].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
                    if col in vessels else "")
if len(ports_tbl):
    text_cols = ports_tbl.select_dtypes(include="object").columns
    ports_tbl[text_cols] = ports_tbl[text_cols].fillna("")     # blank, not "None", in tables
    ports_tbl["ree_link"] = ports_tbl["ree_link"].fillna("").astype(str)   # all-empty reads as float
    ports_tbl[["dataset", "vessel"]] = ports_tbl[["dataset", "vessel"]].astype(str)
if len(ports_tbl) and "match_country" not in ports_tbl:
    ports_tbl["match_country"] = ""
linked_tbl = ports_tbl[ports_tbl["ree_link"] != ""] if len(ports_tbl) else ports_tbl
home_tbl = ports_tbl[ports_tbl["match_country"] != ""] if len(ports_tbl) else ports_tbl

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Datasets", vessels["dataset"].nunique())
c2.metric("Vessels", len(vessels))
c3.metric("Survey areas", len(areas))
c4.metric("Surveying now", int((vessels["survey_status"] == "Surveying now").sum()))
c5.metric("Rare-earth linked ports nearby", linked_tbl["port"].nunique() if len(linked_tbl) else 0)
for note in res["notes"]:
    st.warning(note)

# --- flag filter and vessel picker: they drive the map and the panels below -----
vessels["flag_shown"] = vessels["flag"].replace("", "Unknown")
counts = vessels["flag_shown"].value_counts()
f_col, v_col = st.columns([2, 3])
with f_col:
    flags = st.multiselect("Vessel flags", list(counts.index), default=list(counts.index),
                           format_func=lambda f: f"{f} ({counts[f]})",
                           help="Show only vessels flying these flags, e.g. just China.")
shown = vessels[vessels["flag_shown"].isin(flags)]
order = shown.assign(rank=shown["survey_status"].map({"Surveying now": 0, "Survey found": 1}).fillna(2))
choices = {"All vessels shown": None}
for _, v in order.sort_values(["rank", "dataset", "vessel"]).iterrows():
    where = "" if v["dataset"] == v["vessel"] else f" · {v['dataset']}"   # one unnamed ship per file
    flag = f" · {v['flag']}" if v["flag"] else ""
    choices[f"{vessel_label(v)}{where}{flag} · {v['survey_status']}"] = (v["dataset"], v["vessel"])
with v_col:
    pick = st.selectbox("Vessel", list(choices), help="Zooms the map to the vessel and shows its details below.")
focus = choices[pick]
if not len(shown):
    st.info("No vessels have the chosen flags.")

st.subheader("World map")
page_map = map_html(res["geojson"], shown, focus)
components.html(page_map, height=640)
legend = [f"<span style='color:{c}'>●</span> {k}" for k, c in LINK_COLORS.items()]
legend += [f"<span style='color:{PLAIN_PORT_COLOR}'>●</span> other port",
           f"<span style='color:{FLAG_PORT_COLOR}'>◯</span> port in flag state / chosen country",
           f"<span style='color:{PREDICTION_COLOR}'>╍╍</span> predicted next lines",
           f"<span style='color:{SITE_STYLES['processing'][0]}'>◆</span> processing plant",
           f"<span style='color:{SITE_STYLES['magnet'][0]}'>◆</span> magnet / metal plant",
           f"<span style='color:{SITE_STYLES['mine'][0]}'>▲</span> mine / deposit",
           f"<span style='color:{SITE_STYLES['seabed area'][0]}'>◯</span> seabed mineral area"]
st.markdown("<div style='font-size:0.85rem;line-height:1.8'>" + " &nbsp; ".join(legend) +
            "<br>Layer switches are at the top right of the map, basemaps at the bottom left. Each "
            "dataset has its own colour. Ship icons: red = surveying now, blue = survey found, "
            "grey = no survey. Click anything for details.</div>", unsafe_allow_html=True)

# --- details -------------------------------------------------------------------
PORT_VIEW = {"category": "List", "rank": "#", "port": "Port", "country": "Country", "harbor_size": "Size",
             "sea_km": st.column_config.NumberColumn("Distance (km)", format="%.0f"),
             "hours_at_10kn": st.column_config.NumberColumn("Hours at 10 kn", format="%.0f"),
             "distance_basis": "Measured by", "ree_link": "Rare-earth link", "ree_site": "Linked site",
             "ree_site_km": st.column_config.NumberColumn("Site distance (km)", format="%.0f"),
             "ree_site_status": "Site status", "solid_bulk": "Bulk cargo", "railway": "Railway",
             "max_vessel_draft_m": "Max draught (m)", "ree_note": "Note"}


def list_name(row) -> str:
    country = row.get("match_country") or ""
    return {"flag-state port": f"nearest port in {country}",
            "flag-state rare-earth linked port": f"rare-earth linked port in {country}"
            }.get(row["category"], row["category"])


def port_table(df: pd.DataFrame, extra: tuple = ()):
    cols = list(extra) + [c for c in PORT_VIEW if c in df]
    view = df.assign(category=df.apply(list_name, axis=1))[cols].reset_index(drop=True)
    home = df["match_country"].ne("").to_numpy() if "match_country" in df else [False] * len(df)

    def tint(r):
        color = ("rgba(214, 39, 40, 0.14)" if r["ree_link"] else
                 "rgba(255, 196, 0, 0.16)" if home[r.name] else "")
        return [f"background-color: {color}" if color else ""] * len(r)
    styled = view.style.apply(tint, axis=1)
    st.dataframe(styled, hide_index=True, width="stretch",
                 column_config={k: v for k, v in PORT_VIEW.items() if k in cols})


if focus is None:
    st.subheader("Vessels")

    def first_port(tbl: pd.DataFrame) -> dict:
        out = {}
        for (ds, vs), g in tbl.sort_values("sea_km").groupby(["dataset", "vessel"]) if len(tbl) else []:
            r = g.iloc[0]
            out[(ds, vs)] = f"{r['port']} ({r['country']}), {r['sea_km']:,.0f} km"
        return out
    keys = list(zip(shown["dataset"], shown["vessel"]))
    best, home, home_ree = (first_port(linked_tbl),
                            first_port(home_tbl[home_tbl["category"] == "flag-state port"] if len(home_tbl) else home_tbl),
                            first_port(home_tbl[home_tbl["ree_link"] != ""] if len(home_tbl) else home_tbl))
    overview = shown.assign(nearest_ree_port=[best.get(k, "") for k in keys],
                            home_port=[home.get(k, "") for k in keys],
                            home_ree_port=[home_ree.get(k, "") for k in keys])
    st.dataframe(overview[["dataset", "vessel", "name", "flag", "ship_type", "survey_status", "survey_areas",
                           "nearest_ree_port", "port_country", "home_port", "home_ree_port",
                           "positions_used", "track_km", "marinetraffic_url"]],
                 hide_index=True, width="stretch",
                 column_config={"dataset": "Dataset", "vessel": "Vessel", "name": "Name", "flag": "Flag",
                                "ship_type": "Type", "survey_status": "Status", "survey_areas": "Areas",
                                "nearest_ree_port": "Nearest rare-earth linked port",
                                "port_country": "Matched country",
                                "home_port": "Nearest port there",
                                "home_ree_port": "Nearest rare-earth linked port there",
                                "positions_used": "Positions",
                                "track_km": st.column_config.NumberColumn("Track (km)", format="%.0f"),
                                "marinetraffic_url": st.column_config.LinkColumn("MarineTraffic",
                                                                                 display_text="open")})
    shown_keys = set(keys)
    if len(linked_tbl):   # only vessels passing the flag filter
        linked_tbl = linked_tbl[[k in shown_keys for k in zip(linked_tbl["dataset"], linked_tbl["vessel"])]]
    if len(linked_tbl):
        st.subheader("Rare-earth linked ports near detected surveys")
        st.caption("Ports within 300 km of a rare-earth processing site or mine, or known to handle "
                   "rare-earth cargo. Pick a vessel above for its full port list.")
        port_table(linked_tbl.sort_values("sea_km"), extra=("dataset", "vessel", "area_id"))
else:
    ds, vs = focus
    v = vessels[(vessels["dataset"] == ds) & (vessels["vessel"] == vs)].iloc[0]
    st.subheader(vessel_label(v))
    left, right = st.columns(2)
    with left:
        size = " × ".join(f"{v[c]} m" for c in ("length_m", "width_m") if c in v and not _blank(v[c]))
        ident = [("Dataset", v["dataset"]), ("Name", v["name"]), ("MMSI", v["mmsi"]), ("IMO", v["imo"]),
                 ("Call sign", v["callsign"]),
                 ("Flag", f"{v['flag']} (from {v['flag_source']})" if v["flag"] else ""),
                 ("Ship type", v["ship_type"]), ("Size", size), ("Destination", v["destination"]),
                 ("Ports matched to", f"{v['port_country']} ({v['port_country_basis']})"
                                      if v["port_country"] else "")]
        st.markdown("**Identity**")
        st.markdown("  \n".join(f"{k}: **{val}**" for k, val in ident if not _blank(val)))
        if v["marinetraffic_url"]:
            st.link_button("Open on MarineTraffic", v["marinetraffic_url"])
        elif not v["mmsi"]:
            st.caption("No MMSI in the data, so there is no MarineTraffic link"
                       + ("." if v["flag"] else " and the flag is unknown."))
    with right:
        period = (f"{str(v['first_time'])[:16]} → {str(v['last_time'])[:16]} UTC"
                  if "first_time" in v and not _blank(v["first_time"]) else "no timestamps (file order used)")
        st.markdown("**Track**")
        st.markdown(f"Status: **{v['survey_status']}**  \n"
                    f"Positions used: **{int(v['positions_used']):,}** of {int(v['positions']):,}  \n"
                    f"Distance covered: **{v['track_km']:,.0f} km**  \n"
                    f"Period: {period}  \n"
                    f"Last position: **{v['last_lat']:.4f}, {v['last_lon']:.4f}**")

    v_areas = (areas[(areas["dataset"].astype(str) == ds) & (areas["vessel"].astype(str) == vs)]
               if len(areas) else areas)
    if not len(v_areas):
        st.info("No lawnmower survey pattern found for this vessel, so no port search was made.")
    for _, a in v_areas.iterrows():
        live = str(a["status"]).startswith("IN")
        st.markdown(f"#### Survey area {a['area_id']} " + (":orange[IN PROGRESS]" if live else ":green[completed]"))
        st.markdown(f"{a['n_lines']} lines in {a['n_blocks']} block(s), best confidence {a['best_confidence']}. "
                    f"Lines run {a['line_axis_compass']}, ~{a['median_spacing_km']} km apart; "
                    f"{a['total_line_km']} line-km over ~{a['area_km2']} km², centred at "
                    f"{a['centroid_lat']}, {a['centroid_lon']}.")
        near = (ports_tbl[(ports_tbl["dataset"] == ds) & (ports_tbl["vessel"] == vs)
                          & (ports_tbl["area_id"] == a["area_id"])] if len(ports_tbl) else ports_tbl)
        if len(near):
            top = near[near["ree_link"] != ""].sort_values("sea_km").head(1)
            if len(top):
                t = top.iloc[0]
                site = (f" {t['ree_site']} ({t['ree_site_status']}) is {t['ree_site_km']:,.0f} km from the port."
                        if not _blank(t["ree_site"]) else "")
                st.error(f"Closest rare-earth linked port: **{t['port']} ({t['country']})**, "
                         f"~{t['sea_km']:,.0f} km by {t['distance_basis']}. {t['ree_link']}.{site}")
            home_rows = near[near["match_country"] != ""]
            if len(home_rows):
                country = home_rows.iloc[0]["match_country"]
                first = home_rows[home_rows["category"] == "flag-state port"].sort_values("sea_km").head(1)
                h_ree = home_rows[home_rows["ree_link"] != ""].sort_values("sea_km").head(1)
                msg = f"Ports in **{country}** ({v['port_country_basis']})"
                if len(first):
                    f0 = first.iloc[0]
                    msg += f": nearest is **{f0['port']}**, ~{f0['sea_km']:,.0f} km by {f0['distance_basis']}"
                if len(h_ree):
                    h0 = h_ree.iloc[0]
                    msg += (f"; nearest rare-earth linked is **{h0['port']}**, ~{h0['sea_km']:,.0f} km "
                            f"({h0['ree_link'].lower()}"
                            + (f": {h0['ree_site']}" if not _blank(h0["ree_site"]) else "") + ")")
                else:
                    msg += f"; no rare-earth linked port in {country} is listed."
                st.warning(msg + ".")
            elif settings["port_country"] == "flag" and not v["port_country"]:
                st.info("This vessel's flag is unknown (no flag column or MMSI), so no flag-state ports "
                        "are listed. Choose a country under Port matching in the sidebar instead.")
            st.markdown("**Ports near this survey** (red rows: rare-earth linked; gold rows: matched country)")
            first = {"flag-state port": 0, "flag-state rare-earth linked port": 1}   # matched country on top
            port_table(near.sort_values(["category", "rank"],
                                        key=lambda c: c.map(first).fillna(2) if c.name == "category" else c))
        sites = pd.DataFrame(port_intel.nearby_ree_sites(a["centroid_lat"], a["centroid_lon"], 5))
        if len(sites):
            st.markdown("**Closest rare-earth sites** (straight-line distance)")
            st.dataframe(sites[["name", "type", "status", "country", "distance_km", "notes"]],
                         hide_index=True, width="stretch",
                         column_config={"distance_km": st.column_config.NumberColumn("Distance (km)",
                                                                                     format="%.0f")})

    v_preds = (preds[(preds["dataset"].astype(str) == ds) & (preds["vessel"].astype(str) == vs)]
               if len(preds) else preds)
    if len(v_preds):
        st.markdown("**Predicted next lines**")
        cols = [c for c in ["line_ahead", "kind", "start_lat", "start_lon", "end_lat", "end_lon",
                            "heading_deg", "hours_after_last_fix_start", "est_start_utc"] if c in v_preds]
        st.dataframe(v_preds[cols], hide_index=True, width="stretch")
    png = res["maps"].get(spd.map_filename(ds, vs))
    if png:
        with st.expander("Detector map (PNG)"):
            st.image(png, width="stretch")

st.caption("Ports: NGA World Port Index (public domain). Sea distances follow a shipping-lane network "
           "(searoute package) and are straight-line where no reliable route exists. Rare-earth sites "
           "are a curated list with approximate locations (reference_data/ree_sites.csv); verify "
           "before relying on them.")

st.subheader("All results")
tabs = st.tabs(["Vessels", "Nearby ports", "Survey areas", "Survey blocks", "Survey lines",
                "Predictions", "Positions"])
for tab, key in zip(tabs, TABLES):
    with tab:
        if len(T[key]):
            df = T[key].copy()
            text = df.select_dtypes(include="object").columns
            df[text] = df[text].fillna("")
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.write("Nothing found.")

st.subheader("Download")
d1, d2, d3, d4 = st.columns(4)
d1.download_button("Everything (ZIP)", res["zip"], "survey_results.zip", "application/zip",
                   help="CSVs, Excel workbook, GeoJSON (combined and per layer) and map images.")
d2.download_button("Excel workbook", res["xlsx"], "survey_results.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d3.download_button("GeoJSON (QGIS / ArcGIS)", json.dumps(res["geojson"]), "survey_results.geojson",
                   "application/geo+json")
d4.download_button("Interactive map (HTML)", map_html(res["geojson"], vessels, None), "survey_map.html",
                   "text/html", help="The world map with all datasets as a standalone page to open or share.")
