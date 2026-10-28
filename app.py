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

import datetime
import gc
import html
import io
import json
import re
import tempfile
import uuid
import warnings
import zipfile
from dataclasses import asdict
from pathlib import Path

import folium
from branca.element import MacroElement
from jinja2 import Template
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from folium.plugins import FastMarkerCluster, GroupedLayerControl

import port_intel
import survey_pattern_detector as spd

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "library"          # vessels.csv catalog + tracks/ position files
UPLOAD_TYPES = ["csv", "txt", "tsv", "xlsx", "xlsm"]
TABLES = ["vessels", "nearby_ports", "survey_hotspots", "survey_areas", "survey_blocks", "survey_lines",
          "rejected_blocks", "predictions", "positions_processed"]

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
        "max_turn_hours": "Longest time between one line and the next: legs days apart are repeat trips, not a survey.",
        "max_skip_lines": "Odd lines (cross-lines, turn pieces) tolerated inside a block.",
        "min_lines_per_block": "Fewest lines that make a survey block.",
        "area_join_km": "Blocks this close with the same axis form one survey area.",
    },
    "Is it a real survey?": {
        "min_score": "Drop blocks scoring below this (0-1): they only loosely fit the pattern.",
        "max_spacing_cv": "Lawnmower line spacing must be this regular (spread / mean).",
        "min_new_track_frac": "Share of lines on new ground, not re-running an earlier line (shuttles, patrols).",
        "min_progression": "Lawnmower: share of steps that advance the same way across the block.",
        "min_interleaved_lines": "Interleaved / racetrack surveys (3D seismic) need at least this many lines...",
        "min_coverage": "...filling this share of the block's width (1 km strips)...",
        "min_width_km": "...which is at least this wide (km)...",
        "interleaved_max_speed_kn": "...run at towed-seismic speed or slower (kn)...",
        "interleaved_max_turn_hours": "...turning straight onto the next line (hours).",
        "min_survey_speed_kn": "Slowest median speed on the lines that counts as surveying.",
        "max_survey_speed_kn": "Fastest: ferries and patrols run faster than survey ships.",
        "min_offshore_km": "Survey lines must lie at least this far from the coast (median).",
        "shore_turn_km": "A line ending this close to the coast turns at the shore...",
        "max_shore_turn_frac": "...and no more than this share of line ends may do that.",
    },
    "Survey hotspots": {
        "hotspot_join_km": "Survey areas this close, by any ships, count as one hotspot.",
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
HOTSPOT_COLORS = {1: "#ffb300", 2: "#f4511e", 3: "#8e0038"}   # by ships surveying it (3 = 3 or more)
AREA_COLOR, AREA_EDGE = "#ffe500", "#1b1b1b"   # survey areas: bright yellow, outlined in near-black
LINK_COLORS = {"Known rare-earth cargo port": "#d62728",
               "Near rare-earth processing site": "#f28e2b",
               "Near rare-earth mine": "#c9a227"}
PLAIN_PORT_COLOR = "#3b5b7d"
FLAG_PORT_COLOR = "#ffc400"     # ring around ports of the vessel's flag state / chosen country
FLAG_CATEGORIES = ("flag-state port", "flag-state rare-earth linked port")
SITE_STYLES = {  # type -> (colour, marker sides (4 diamond, 3 triangle), layer name)
    "processing": ("#7b1fa2", 4, "Processing & separation plants"),
    "magnet": ("#c2185b", 4, "Magnet & metal plants"),
    "mine": ("#6d4c41", 3, "Mines & deposits"),
    "logistics port": ("#d62728", 4, "Rare-earth cargo ports"),
}


# Seabed mining areas. ISA boundaries are not stored in this project: the map loads
# them in the viewer's browser from the ISA's own public map service (the data
# behind isa.org.jm/deepdata-database/maps), credited to the ISA; its terms allow
# personal, non-commercial use and ask for written permission for republishing.
ISA_SERVICE = ("https://services5.arcgis.com/VcAAb5oBhdAAnFj2/arcgis/rest/services/"
               "fclContractAreas_20240724/FeatureServer")
ISA_LAYERS = {"active": 32, "reserved": 33, "relinquished": 34, "apei": 35}
CCZ_OUTLINE = ("https://geo.vliz.be/geoserver/MarineRegions/wfs?service=WFS&version=1.0.0"
               "&request=GetFeature&typeName=MarineRegions:isa_ccz_managementarea"
               "&outputFormat=application/json")
NATIONAL_SEABED = HERE / "reference_data" / "national_seabed_areas.geojson"
# ContractID -> (contractor, sponsoring state), from the ISA's per-contractor layers
ISA_CONTRACTORS = {
    "UKSRLPMN1": ("Loke CCZ (formerly UK Seabed Resources)", "United Kingdom"),
    "UKSRLPMN2": ("Loke CCZ (formerly UK Seabed Resources)", "United Kingdom"),
    "CIICPMN1": ("Cook Islands Investment Corporation (CIIC)", "Cook Islands"),
    "COMRAPMN1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "COMRAPMS1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "COMRACRFC1": ("China Ocean Mineral Resources R&D Association (COMRA)", "China"),
    "BPHDCPMN1": ("Beijing Pioneer Hi-Tech Development Corporation", "China"),
    "CMMPMN1": ("China Minmetals Corporation", "China"),
    "BrazilCRFC1": ("Companhia de Pesquisa de Recursos Minerais (CPRM)", "Brazil"),
    "IOMPMN1": ("Interoceanmetal Joint Organization (IOM)",
                "Bulgaria, Cuba, Czechia, Poland, Russia, Slovakia"),
    "POLPMS1": ("Government of the Republic of Poland", "Poland"),
    "BMJPMN1": ("Blue Minerals Jamaica Ltd", "Jamaica"),
    "GSRPMN1": ("Global Sea Mineral Resources NV (GSR)", "Belgium"),
    "IFREMERPMN1": ("IFREMER", "France"), "IFREMERPMS1": ("IFREMER", "France"),
    "KOREAPMN1": ("Government of the Republic of Korea", "South Korea"),
    "KOREAPMS1": ("Government of the Republic of Korea", "South Korea"),
    "KOREACRFC1": ("Government of the Republic of Korea", "South Korea"),
    "OMSPMN1": ("Ocean Mineral Singapore Pte Ltd", "Singapore"),
    "RUSFEDPMS1": ("Government of the Russian Federation", "Russia"),
    "RUSMNRCRFC1": ("Ministry of Natural Resources and Environment of Russia", "Russia"),
    "RUSMNCRFC1": ("Ministry of Natural Resources and Environment of Russia", "Russia"),
    "YUZHPMN1": ("JSC Yuzhmorgeologiya", "Russia"),
    "TOMLPMN1": ("Tonga Offshore Mining Limited", "Tonga"),
    "NORIPMN1": ("Nauru Ocean Resources Inc. (NORI)", "Nauru"),
    "MARAWAPMN1": ("Marawa Research and Exploration Ltd", "Kiribati"),
    "JOGMECCRFC1": ("Japan Organization for Metals and Energy Security (JOGMEC)", "Japan"),
    "DORDPMN1": ("Deep Ocean Resources Development Co. (DORD)", "Japan"),
    "IndiaPMN1": ("Government of India", "India"), "IndiaPMS1": ("Government of India", "India"),
    "BGRPMN1": ("Federal Institute for Geosciences and Natural Resources (BGR)", "Germany"),
    "BGRPMS1": ("Federal Institute for Geosciences and Natural Resources (BGR)", "Germany"),
}
MINERAL_COLORS = {"nodules": "#1e88e5", "sulphides": "#ef6c00", "crusts": "#8d6e63"}
CHINA_OUTLINE = "#d50000"


class LiveSeabedAreas(MacroElement):
    """
    Fills the given (empty) feature groups in the viewer's browser from the ISA
    service and the Marine Regions CCZ outline, re-centred on longitude c like
    everything else on the map. A layer is fetched the first time it is shown.
    """
    _template = Template("""
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var c = {{ this.c }};
  var G = {{ this.groups_js }};
  var SERVICE = {{ this.service|tojson }}, LAYERS = {{ this.layers|tojson }};
  var CCZ = {{ this.ccz|tojson }};
  var WHO = {{ this.contractors|tojson }}, COLORS = {{ this.colors|tojson }};
  var CHINA = {{ this.china|tojson }};
  map.attributionControl.addAttribution(
    'Seabed mining areas: <a href="https://www.isa.org.jm/deepdata-database/maps/" target="_blank">' +
    'International Seabed Authority</a>; EEZs: <a href="https://www.marineregions.org" target="_blank">' +
    'Marine Regions</a> (CC BY 4.0)');

  function wrap(lon, ref) { return ref + ((((lon - ref + 180) % 360) + 360) % 360) - 180; }
  function ring(r) {
    var out = [], prev = null;
    for (var i = 0; i < r.length; i++) {
      var lon = wrap(r[i][0], prev === null ? c : prev);
      out.push([lon, r[i][1]]); prev = lon;
    }
    return out;
  }
  function recentre(g) {
    if (!g) return g;
    if (g.type === 'Polygon') g.coordinates = g.coordinates.map(ring);
    else if (g.type === 'MultiPolygon') g.coordinates = g.coordinates.map(function (p) { return p.map(ring); });
    return g;
  }
  function mineral(id) {
    id = String(id || '');
    return /CRFC/i.test(id) ? 'crusts' : /PMS/i.test(id) ? 'sulphides' : 'nodules';
  }
  var NAMES = {nodules: 'Polymetallic nodules', sulphides: 'Polymetallic sulphides',
               crusts: 'Cobalt-rich ferromanganese crusts'};
  function row(k, v) { return (v === undefined || v === null || v === '' || v === ' ' || v === 'NA') ? '' :
    '<tr><td style="color:#666;padding-right:8px">' + k + '</td><td>' + v + '</td></tr>'; }
  function contractPopup(p, kind) {
    var w = WHO[p.ContractID] || [p.ContractID, ''];
    var year = p.ActDate ? new Date(p.ActDate).getUTCFullYear() : '';
    return '<table style="font-size:12px">' + row('Area', '<b>' + kind + '</b>') +
      row('Contractor', w[0]) + row('Sponsoring state', w[1]) + row('Mineral', NAMES[mineral(p.ContractID)]) +
      row('Contract', p.ContractID) + row('Sub-area', p.SubArea) + row('Block', p.BlkCell) +
      row('Size', p.AreaKM2 ? Math.round(Number(p.AreaKM2)).toLocaleString() + ' km²' : '') + row('Since', year) +
      row('Status', p.Status) + row('Source', 'International Seabed Authority') + '</table>';
  }
  function style(kind, p) {
    if (kind === 'apei') return {color: '#2e7d32', weight: 1.5, fillColor: '#66bb6a', fillOpacity: 0.25};
    if (kind === 'relinquished') return {color: '#9e9e9e', weight: 0.8, dashArray: '3 4', fillOpacity: 0.05};
    var col = COLORS[mineral(p.ContractID)], china = (WHO[p.ContractID] || [])[1] === 'China';
    if (kind === 'reserved') return {color: col, weight: 1.2, dashArray: '6 4', fillColor: col, fillOpacity: 0.08};
    return {color: china ? CHINA : col, weight: china ? 2.5 : 1, fillColor: col, fillOpacity: 0.3};
  }

  function fetchAll(url, done, offset, acc) {
    offset = offset || 0; acc = acc || [];
    var page = url.indexOf('/query?') < 0 ? url :
      url + '&resultOffset=' + offset + '&resultRecordCount=1000';
    fetch(page).then(function (r) { return r.json(); }).then(function (d) {
      var f = d.features || [];
      acc = acc.concat(f);
      var more = d.exceededTransferLimit || (d.properties && d.properties.exceededTransferLimit);
      if (url.indexOf('/query?') >= 0 && more && f.length) fetchAll(url, done, offset + f.length, acc);
      else done(acc);
    }).catch(function (e) { console.warn('Seabed layer failed to load', e); done(acc); });
  }
  function isaQuery(id, fields) {   // the APEI layer has no contract fields: asking for them fails
    return SERVICE + '/' + id + '/query?where=1%3D1&outSR=4326&f=geojson&returnGeometry=true' +
      '&maxAllowableOffset=0.01&geometryPrecision=3' +
      '&outFields=' + (fields || 'ContractID,SubArea,BlkCell,AreaType,AreaKM2,ActDate,Status');
  }
  function draw(features, kind, target) {
    features.forEach(function (f) {
      if (!f.geometry) return;
      f.geometry = recentre(f.geometry);
      var p = f.properties || {};
      var tip = kind === 'apei' ? (p.Remarks || 'APEI') + ': protected from mining' :
        ((WHO[p.ContractID] || [p.ContractID])[0] + ' · ' + NAMES[mineral(p.ContractID)] +
         (kind === 'reserved' ? ' (reserved area)' : kind === 'relinquished' ? ' (relinquished)' : ''));
      L.geoJSON(f, {style: function () { return style(kind, p); }})
        .bindTooltip(tip, {sticky: true})
        .bindPopup(kind === 'apei' ?
          '<table style="font-size:12px">' + row('Area', '<b>Area of Particular Environmental Interest</b>') +
          row('Name', p.Remarks) +
          row('Purpose', 'Protected from mining under the CCZ environmental management plan') +
          row('Size', p.AreaKM2 ? Math.round(Number(p.AreaKM2)).toLocaleString() + ' km²' : '') +
          row('Source', 'International Seabed Authority') + '</table>' :
          contractPopup(p, kind === 'reserved' ? 'ISA reserved area' :
                        kind === 'relinquished' ? 'Relinquished area' : 'ISA exploration contract'))
        .addTo(typeof target === 'function' ? target(p) : target);
    });
  }
  function whenShown(groups, load) {   // fetch the first time any of the groups is on the map
    var done = false;
    function go() { if (!done) { done = true; load(); } }
    groups.forEach(function (g) { if (map.hasLayer(g)) go(); else g.once('add', go); });
  }

  whenShown([G.nodules, G.sulphides, G.crusts], function () {
    fetchAll(isaQuery(LAYERS.active), function (f) {
      draw(f, 'active', function (p) { return G[mineral(p.ContractID)]; });
    });
  });
  whenShown([G.reserved], function () { fetchAll(isaQuery(LAYERS.reserved), function (f) { draw(f, 'reserved', G.reserved); }); });
  whenShown([G.apei], function () { fetchAll(isaQuery(LAYERS.apei, 'AreaKM2,Status,Remarks'), function (f) { draw(f, 'apei', G.apei); }); });
  whenShown([G.relinquished], function () {
    fetchAll(isaQuery(LAYERS.relinquished), function (f) { draw(f, 'relinquished', G.relinquished); });
  });
  whenShown([G.ccz], function () {
    fetchAll(CCZ, function (f) {
      f.forEach(function (x) {
        x.geometry = recentre(x.geometry);
        L.geoJSON(x, {style: {color: '#1565c0', weight: 2, dashArray: '10 6', fill: false}})
          .bindTooltip('Clarion-Clipperton Zone management area (ISA)', {sticky: true}).addTo(G.ccz);
      });
    });
  });
})();
{% endmacro %}
""")

    def __init__(self, c: float, groups: dict):
        super().__init__()
        self._name = "LiveSeabedAreas"
        self.c = round(float(c), 6)
        self.groups_js = "{" + ", ".join(f"{k}: {g.get_name()}" for k, g in groups.items()) + "}"
        self.service, self.layers, self.ccz = ISA_SERVICE, ISA_LAYERS, CCZ_OUTLINE
        self.contractors = {k: list(v) for k, v in ISA_CONTRACTORS.items()}
        self.colors, self.china = MINERAL_COLORS, CHINA_OUTLINE


# ============================================================
# RUNNING THE DETECTOR
# ============================================================

# Streamlit Community Cloud gives an app about 1 GB: keep few big results cached
@st.cache_data(show_spinner=False, max_entries=2)
def analyse(groups: tuple, settings: dict, identities: tuple = ()) -> dict:
    """
    Run the detector and collect everything the page shows.
    groups: ((dataset name, ((file name, bytes), ...)), ...), one per dataset.
    identities: ((dataset, vessel or None, mmsi, flag, name, source, imo), ...) for vessels
    whose files carry no identity (library catalog entries, the identity form).
    """
    cfg = spd.Config(**settings)
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "input", Path(tmp) / "results"
        src.mkdir()
        sources, i = {}, 0
        for dataset, files in groups:
            for name, data in files:
                path = src / f"{i:03d}" / Path(name).name    # each file keeps its own name
                path.parent.mkdir()
                path.write_bytes(data)
                sources.setdefault(dataset, []).append(str(path))
                i += 1

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # quick-look PNGs and the Excel workbook are slow (about two thirds of the time
            # for many ships) and rarely opened: they are made on request instead (see below)
            results, notes, n_rows = spd.run(
                sources, cfg, out, workers=1, make_maps=False,
                identities={(ds, vs): {"mmsi": m, "flag": f, "name": n, "source": how, "imo": imo}
                            for ds, vs, m, f, n, how, imo in identities})

        tables = {}
        for key in TABLES:
            try:
                tables[key] = pd.read_csv(out / f"{key}.csv", low_memory=False)
            except (FileNotFoundError, pd.errors.EmptyDataError):
                tables[key] = pd.DataFrame()
        maps = {spd.map_filename(r["dataset"], r["vessel"]): {k: r[k] for k in spd.MAP_KEYS}
                for r in results}
        geojson = json.loads((out / "survey_results.geojson").read_text())
        zip_bytes = _zip_folder(out, extra={})
    del results
    gc.collect()                           # hand the detector's working memory back before the page is built
    return {"notes": notes, "n_rows": n_rows, "tables": tables, "maps": maps,
            "geojson": geojson, "zip": zip_bytes, "id": uuid.uuid4().hex}


def on_request(res: dict, what: str, make):
    """A file made only when asked for, once per analysis result (kept for the session)."""
    made = st.session_state.setdefault("made_files", {})
    key = (res["id"], what)
    if key not in made:
        if len(made) > 40:                 # keep the session small
            made.clear()
        made[key] = make()
    return made[key]


def _excel(tables: dict) -> bytes:
    names = {"vessels": "Vessels", "nearby_ports": "Nearby Ports", "survey_hotspots": "Survey Hotspots",
             "survey_areas": "Survey Areas", "survey_blocks": "Survey Blocks", "survey_lines": "Survey Lines",
             "rejected_blocks": "Rejected Patterns", "predictions": "Predictions",
             "positions_processed": "Positions"}
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

def _wrap(lon: float, c: float) -> float:
    """Longitude moved into [c - 180, c + 180), the frame the map is drawn in."""
    return c + ((lon - c + 180) % 360) - 180


def _unwrap(coords, c: float):
    """
    [[lon, lat], ...] -> [[lat, lon], ...] for Leaflet, continuous around central
    longitude c: a line or area crossing the 180° line stays in one piece, on the
    same copy of the world as everything else drawn.
    """
    out = []
    for lon, lat in coords:
        lon = _wrap(lon, out[-1][1] if out else c)
        out.append([lat, lon])
    return out


def _polyline(coords, group, c: float, **style):
    pts = _unwrap(coords, c)
    if len(pts) > 1:
        folium.PolyLine(pts, **style).add_to(group)


def _central_lon(lons) -> float:
    """Circular mean longitude: the middle of a set that may straddle 180°."""
    if not lons:
        return 0.0
    r = np.radians(np.asarray(lons, float))
    return float(np.degrees(np.arctan2(np.sin(r).mean(), np.cos(r).mean())))


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
    name, vessel = row.get("name") or "", str(row["vessel"])
    if not name or name.lower() == vessel.lower() or safe_name(name) == vessel:   # id is the name
        return name or vessel
    return f"{name} ({vessel})"


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


def build_map(geojson: dict, vessels: pd.DataFrame, focus: tuple | None, labels: tuple = (),
              focus_area: tuple | None = None) -> folium.Map:
    """
    The world map. focus: (dataset, vessel) to zoom to; focus_area: (dataset, vessel, area_id)
    to zoom to one survey area; labels: ((dataset, vessel, area_id), number) for the numbered
    survey-area badges, matching the list beside the map.
    """
    number = {k: n for k, n in labels}
    zoomed = focus is not None or focus_area is not None
    matched = any(f["properties"]["layer"] == "port_route" and f["properties"].get("category") in FLAG_CATEGORIES
                  for f in geojson["features"])
    feats = geojson["features"]

    keep = set(zip(vessels["dataset"], vessels["vessel"]))   # vessels passing the flag filter

    def layer(name):
        return [f for f in feats if f["properties"]["layer"] == name
                and (name == "ree_site" or (str(f["properties"].get("dataset")),
                                            str(f["properties"].get("vessel"))) in keep)]

    # central longitude: the focused vessel's survey, else all surveys and vessels
    anchor = []
    for f in feats:
        p = f["properties"]
        if p["layer"] not in ("survey_area", "track") or (str(p.get("dataset")), str(p.get("vessel"))) not in keep:
            continue
        if focus is not None and not _match(f, *focus):
            continue
        if focus_area is not None and not (p["layer"] == "survey_area" and _match(f, *focus_area[:2])
                                           and p.get("area_id") == focus_area[2]):
            continue
        coords = f["geometry"]["coordinates"]
        anchor += [lon for lon, _ in (coords[0] if p["layer"] == "survey_area" else coords[-1:])]
    c = _central_lon(anchor)

    m = folium.Map(location=[15, c], zoom_start=2, min_zoom=2, tiles=None,
                   control_scale=True, prefer_canvas=True,
                   # everything is drawn within 180° of longitude c, so panning is held to
                   # that one copy of the world; on any other copy the data would vanish
                   world_copy_jump=False, max_bounds=True, min_lat=-85, max_lat=85,
                   min_lon=c - 180, max_lon=c + 180, max_bounds_viscosity=1.0)
    # Esri basemaps need no API key (Carto's now do)
    esri = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    for service, name, attr, native in (
            ("Ocean/World_Ocean_Base", "Ocean", "Esri, GEBCO, NOAA, Garmin, HERE", 10),
            ("World_Imagery", "Satellite", "Esri, Maxar, Earthstar Geographics", 18),
            ("Canvas/World_Light_Gray_Base", "Light", "Esri, HERE, Garmin", 16),
            ("Canvas/World_Dark_Gray_Base", "Dark", "Esri, HERE, Garmin", 16)):
        folium.TileLayer(esri.format(service), name=name, attr=f"Tiles &copy; {attr}",
                         max_native_zoom=native, max_zoom=18, show=name == "Ocean").add_to(m)

    groups, bounds, track_bounds = {}, [], []
    # the survey areas are the point of the map: one layer on top of everything, bright and numbered
    highlight = folium.FeatureGroup("Survey areas (numbered)")
    for i, ds in enumerate(dict.fromkeys(vessels["dataset"])):
        color = DATASET_COLORS[i % len(DATASET_COLORS)]
        survey = folium.FeatureGroup("Survey patterns")
        preds = folium.FeatureGroup("Predicted next lines")
        tracks = folium.FeatureGroup("Vessel tracks")
        boats = folium.FeatureGroup("Vessel positions")

        for f in layer("track"):
            if _match(f, ds):
                _polyline(f["geometry"]["coordinates"], tracks, c, color=color, weight=1.2, opacity=0.35,
                          tooltip=f"{f['properties']['vessel']} track")
        for f in layer("survey_block"):
            if not _match(f, ds):
                continue
            p = f["properties"]
            ring = _unwrap(f["geometry"]["coordinates"][0], c)
            folium.Polygon(ring, color=color, weight=1, dash_array="3 3", fill=False,
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
            ring = _unwrap(f["geometry"]["coordinates"][0], c)
            bounds += ring
            n = number.get((str(p["dataset"]), str(p["vessel"]), p["area_id"]))
            when = (f"{str(p.get('start_time'))[:10]} → {str(p.get('end_time'))[:10]}"
                    if p.get("start_time") else "")
            tip = (f"Survey area {('#' + str(n) + ' · ') if n else ''}{p['vessel']} · {p['n_lines']} lines"
                   + (f" · {when}" if when else "")
                   + (" · SURVEYING NOW" if str(p["status"]).startswith("IN") else ""))
            folium.Polygon(ring, color=AREA_EDGE, weight=3, fill=True, fill_color=AREA_COLOR,
                           fill_opacity=0.55, tooltip=tip,
                           popup=folium.Popup(_rows([
                               ("Survey area", f"<b>{'#' + str(n) if n else p['area_id']}</b>"),
                               ("Ship", f"<b>{html.escape(str(p['vessel']))}</b>"), ("Status", p["status"]),
                               ("Dates", when), ("Lines", p["n_lines"]),
                               ("Line direction", p["line_axis_compass"]),
                               ("Spacing", f"{p['median_spacing_km']} km"),
                               ("Line-km", p["total_line_km"]), ("Area", f"{p['area_km2']} km²"),
                               ("Centre", f"{p['centroid_lat']}, {p['centroid_lon']}")]),
                               max_width=340)).add_to(highlight)
            if n:
                folium.Marker([p["centroid_lat"], _wrap(p["centroid_lon"], c)], tooltip=tip,
                              icon=folium.DivIcon(
                                  html=(f"<div style='background:{AREA_EDGE};color:{AREA_COLOR};"
                                        "border:2px solid #fff;border-radius:6px;min-width:22px;height:22px;"
                                        "padding:0 4px;line-height:18px;text-align:center;"
                                        f"font:700 12px sans-serif;box-shadow:0 0 3px #0008'>{n}</div>"),
                                  icon_size=(26, 22), icon_anchor=(13, 11))).add_to(highlight)
        for f in layer("line"):
            if _match(f, ds) and (f["properties"].get("block_id") or -1) > 0:
                _polyline(f["geometry"]["coordinates"], survey, c, color=color, weight=3, opacity=0.95)
        has_preds, flagged = False, set()
        for f in layer("predicted_line"):
            if _match(f, ds):
                has_preds = True
                p = f["properties"]
                _polyline(f["geometry"]["coordinates"], preds, c, color=PREDICTION_COLOR, weight=4,
                          dash_array="8 6",
                          tooltip=f"{p['vessel']}: {p['kind']} (+{p['hours_after_last_fix_start']} h)")
                if p["vessel"] not in flagged:   # the lines are small at world scale: a label finds them
                    flagged.add(p["vessel"])
                    lon0, lat0 = f["geometry"]["coordinates"][0]
                    folium.Marker([lat0, _wrap(lon0, c)],
                                  tooltip=f"{p['vessel']} is surveying now: pink dashed lines are its "
                                          "predicted next survey lines",
                                  icon=folium.DivIcon(
                                      html=(f"<div style='background:{PREDICTION_COLOR};color:#fff;"
                                            "border:2px solid #fff;border-radius:10px;padding:1px 7px;"
                                            "font:700 11px sans-serif;white-space:nowrap;"
                                            "box-shadow:0 0 3px #0008'>next lines ▸</div>"),
                                      icon_size=(84, 20), icon_anchor=(0, 10))).add_to(preds)

        for _, v in vessels[vessels["dataset"] == ds].iterrows():
            if pd.isna(v["last_lat"]):
                continue
            live = v["survey_status"] == "Surveying now"
            # last position as a small dot (pins hid the survey areas): red = surveying now
            folium.CircleMarker([v["last_lat"], _wrap(v["last_lon"], c)], radius=6 if live else 4,
                                color="#ffffff", weight=1.5, fill=True, fill_opacity=1,
                                fill_color="#e53935" if live else color,
                                tooltip=f"{vessel_label(v)} · last position · {v['survey_status']}",
                                popup=folium.Popup(_vessel_popup(v), max_width=340)).add_to(boats)
            track_bounds.append([v["last_lat"], _wrap(v["last_lon"], c)])

        groups[f"Dataset: {ds}"] = [tracks, survey] + ([preds] if has_preds else []) + [boats]

    # --- survey hotspots: seabed surveyed more than once, by one ship or several --
    multi = folium.FeatureGroup("Surveyed by several ships")
    repeat = folium.FeatureGroup("Surveyed again by the same ship", show=False)
    for f in feats:
        p = f["properties"]
        if p["layer"] != "hotspot":
            continue
        ships = int(p["n_vessels"])
        color = HOTSPOT_COLORS[min(ships, 3)]
        ring = _unwrap(f["geometry"]["coordinates"][0], c)
        together = p.get("surveyed_together") or ""
        when = (f"{str(p.get('first_time'))[:10]} → {str(p.get('last_time'))[:10]}"
                if p.get("first_time") else "")
        folium.Polygon(ring, color=color, weight=4 if ships > 1 else 2, fill=True,
                       fill_color=color, fill_opacity=0.22 if ships > 1 else 0.1,
                       tooltip=(f"Survey hotspot {p['hotspot_id']} · {ships} ships"
                                + (" · at the same time" if together else "")
                                if ships > 1 else f"Survey hotspot {p['hotspot_id']} · surveyed "
                                                  f"{p['n_survey_areas']} times by one ship"),
                       popup=folium.Popup(_rows([
                           ("Hotspot", f"<b>{p['hotspot_id']}</b>"),
                           ("Ships", f"<b>{ships}</b>: " + html.escape(str(p["vessels"]))),
                           ("Flags", p.get("flags")),
                           ("Survey areas", p["n_survey_areas"]), ("Lines", p["n_lines"]),
                           ("Line-km", f"{p['total_line_km']:,.0f}"),
                           ("Area", f"{p['area_km2']:,.0f} km²"), ("Period", when),
                           ("Most ships at once", p.get("max_vessels_at_once")),
                           ("Surveying together", html.escape(together)),
                           ("Surveying now", "yes" if p.get("surveying_now") else "")]),
                           max_width=380)).add_to(multi if ships > 1 else repeat)
        if ships > 1:   # count badge in the middle
            folium.Marker([p["centroid_lat"], _wrap(p["centroid_lon"], c)],
                          tooltip=f"Survey hotspot {p['hotspot_id']}: {ships} ships",
                          icon=folium.DivIcon(
                              html=(f"<div style='background:{color};color:#fff;border:2px solid #fff;"
                                    "border-radius:50%;width:26px;height:26px;line-height:22px;"
                                    "text-align:center;font:700 13px sans-serif;"
                                    f"box-shadow:0 0 3px #0008'>{ships}</div>"),
                              icon_size=(26, 26), icon_anchor=(13, 13))).add_to(multi)
    groups["Survey hotspots"] = [multi, repeat]

    # --- ports near surveys and the routes to them ---------------------------
    # ports, like their routes, only once zoomed to a ship or an area (layers menu otherwise)
    linked_ports = folium.FeatureGroup("Rare-earth linked ports", show=zoomed)
    plain_ports = folium.FeatureGroup("Other nearby ports", show=zoomed)
    # the ship's own country's ports are the point of the port search: the nearest one and the
    # nearest rare-earth linked one per survey always show; the longer lists when zoomed
    flag_ports = folium.FeatureGroup("Nearest ports in the ship's own country")
    flag_more = folium.FeatureGroup("Other ports in the ship's own country", show=zoomed)
    # routes only when zoomed to a ship or an area: on the world view they hide the surveys
    linked_routes = folium.FeatureGroup("Routes to rare-earth linked ports (any country)",
                                        show=zoomed and not matched)
    flag_routes = folium.FeatureGroup("Routes to the nearest ports in the ship's own country")
    flag_routes_more = folium.FeatureGroup("Routes to other ports in the ship's own country", show=zoomed)
    headline = {(str(p["dataset"]), str(p["vessel"]), p["area_id"], p["port"])
                for p in (f["properties"] for f in layer("nearby_port"))
                if p.get("category") in FLAG_CATEGORIES and p.get("rank") == 1}
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
            [lat, _wrap(lon, c)], radius=8 if link else 5, color="#222", weight=1, fill=True,
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
            top = any((str(r["dataset"]), str(r["vessel"]), r["area_id"], r["port"]) in headline for r in rows)
            folium.CircleMarker([lat, _wrap(lon, c)], radius=12 if top else 10, color=FLAG_PORT_COLOR,
                                weight=3, fill=top, fill_color=FLAG_PORT_COLOR, fill_opacity=0.35,
                                tooltip=f"{name}: port in {', '.join(home)}"
                                        + (f" · {link}" if link else ""),
                                popup=folium.Popup(_rows([
                                    ("Port", f"<b>{html.escape(name)}</b>"), ("Country", country),
                                    ("Rare-earth link", f"<b>{link}</b>" if link else ""),
                                    ("Distance from surveys", surveys)]), max_width=380),
                                ).add_to(flag_ports if top else flag_more)
    for f in layer("port_route"):
        p = f["properties"]
        linked = not _blank(p.get("ree_link"))
        home = p.get("category") in FLAG_CATEGORIES
        top = (str(p["dataset"]), str(p["vessel"]), p["area_id"], p["port"]) in headline
        _polyline(f["geometry"]["coordinates"], c=c, group=
                  (flag_routes if top else flag_routes_more) if home else
                  linked_routes if linked else plain_routes,
                  color=FLAG_PORT_COLOR if home else
                  LINK_COLORS["Known rare-earth cargo port"] if linked else PLAIN_PORT_COLOR,
                  weight=3 if home else 1.5, opacity=0.9 if home else 0.6, dash_array="4 6",
                  tooltip=f"{p['vessel']} area {p['area_id']} → {p['port']}: {_km(p['sea_km'])} "
                          f"({p['distance_basis']})")

    # --- rare-earth sites ------------------------------------------------------
    site_groups = {t: folium.FeatureGroup(name, show=False) for t, (_, _, name) in SITE_STYLES.items()}
    for f in layer("ree_site"):
        p = f["properties"]
        if p["type"] not in site_groups:
            continue
        color, sides, _ = SITE_STYLES[p["type"]]
        tip = f"{p['name']} · {p['type']} ({p['status']})"
        popup = folium.Popup(_rows([("Site", f"<b>{html.escape(p['name'])}</b>"), ("Type", p["type"]),
                                    ("Status", p["status"]), ("Operator", p.get("operator")),
                                    ("Country", p["country"]), ("Note", p.get("notes"))]), max_width=340)
        # HTML shapes: RegularPolygonMarker breaks on the canvas renderer
        shape = (f"<div style='width:11px;height:11px;margin:2px;background:{color};"
                 f"border:1px solid #222;transform:rotate(45deg)'></div>" if sides == 4 else
                 f"<div style='width:0;height:0;border-left:8px solid transparent;"
                 f"border-right:8px solid transparent;border-bottom:14px solid {color}'></div>")
        folium.Marker([p["lat"], _wrap(p["lon"], c)], tooltip=tip, popup=popup,
                      icon=folium.DivIcon(html=shape, icon_size=(16, 16), icon_anchor=(8, 8),
                                          class_name="ree-site")).add_to(site_groups[p["type"]])

    # --- seabed mining areas ------------------------------------------------------
    seabed = {
        "ccz": folium.FeatureGroup("Clarion-Clipperton Zone outline"),
        "nodules": folium.FeatureGroup("ISA contracts: polymetallic nodules"),
        "sulphides": folium.FeatureGroup("ISA contracts: polymetallic sulphides"),
        "crusts": folium.FeatureGroup("ISA contracts: cobalt-rich crusts"),
        "reserved": folium.FeatureGroup("ISA reserved areas"),
        "apei": folium.FeatureGroup("Protected areas (APEIs)"),
        "relinquished": folium.FeatureGroup("Relinquished areas", show=False),
    }
    national = folium.FeatureGroup("National seabed mineral zones (EEZ)")
    if NATIONAL_SEABED.exists():
        for f in json.loads(NATIONAL_SEABED.read_text())["features"]:
            p, geom = f["properties"], f["geometry"]
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            for poly in polys:
                folium.Polygon([_unwrap(r, c) for r in poly], color="#00838f", weight=2, dash_array="8 5",
                               fill=True, fill_opacity=0.06,
                               tooltip=f"{p['name']} ({p['country']})",
                               popup=folium.Popup(_rows([("Zone", f"<b>{html.escape(p['name'])}</b>"),
                                                         ("Country", p["country"]), ("Mineral", p["mineral"]),
                                                         ("Note", p["note"]), ("Outline", p["source"])]),
                                                  max_width=360)).add_to(national)

    world_ports = folium.FeatureGroup("All world ports (3,800)", show=False)
    ports = port_intel.load_ports()
    if len(ports):
        FastMarkerCluster([[la, _wrap(lo, c), name] for la, lo, name in ports[["lat", "lon", "port"]].values],
                          callback=("function (row) { return L.circleMarker(new L.LatLng(row[0], row[1]),"
                                    " {radius: 4, color: '#3b5b7d', fillOpacity: 0.8})"
                                    ".bindTooltip(row[2]); }")).add_to(world_ports)

    groups["Ports near surveys"] = [flag_ports, flag_routes, flag_more, flag_routes_more, linked_ports,
                                    plain_ports, linked_routes, plain_routes]
    groups["Seabed mining areas"] = list(seabed.values()) + [national]
    groups["Rare-earth sites"] = list(site_groups.values())
    groups["Reference"] = [world_ports]
    for members in groups.values():
        for g in members:
            g.add_to(m)
    highlight.add_to(m)                    # added last: drawn above everything else
    GroupedLayerControl({"Survey areas": [highlight], **groups},
                        exclusive_groups=False, collapsed=True).add_to(m)   # opens on hover / tap
    LiveSeabedAreas(c, seabed).add_to(m)
    folium.LayerControl(position="bottomleft", collapsed=True).add_to(m)   # basemaps

    if focus_area is not None:
        ds, vessel, area_id = focus_area
        bounds = [pt for f in feats if f["properties"]["layer"] in ("survey_area", "predicted_line")
                  and _match(f, ds, vessel) and f["properties"].get("area_id", area_id) == area_id
                  for pt in _unwrap(f["geometry"]["coordinates"][0]
                                    if f["properties"]["layer"] == "survey_area" else f["geometry"]["coordinates"], c)]
    elif focus is not None:
        ds, vessel = focus
        fb = []
        for f in feats:
            if not _match(f, ds, vessel):
                continue
            kind, coords = f["properties"]["layer"], f["geometry"]["coordinates"]
            if kind == "survey_area":
                fb += _unwrap(coords[0], c)
            elif kind == "predicted_line":
                fb += _unwrap(coords, c)
        v = vessels[(vessels["dataset"] == ds) & (vessels["vessel"] == vessel)]
        if len(v) and not pd.isna(v.iloc[0]["last_lat"]):
            fb.append([v.iloc[0]["last_lat"], _wrap(v.iloc[0]["last_lon"], c)])
        # include the matched country's nearest port and nearest rare-earth linked port
        fb += [[f["properties"]["lat"], _wrap(f["properties"]["lon"], c)] for f in layer("nearby_port")
               if _match(f, ds, vessel) and f["properties"].get("category") in FLAG_CATEGORIES
               and f["properties"].get("rank") == 1]
        if len(fb) <= 1:   # no survey: frame the whole track
            fb += [pt for f in layer("track") if _match(f, ds, vessel)
                   for pt in _unwrap(f["geometry"]["coordinates"], c)]
        bounds = fb or bounds
    bounds = bounds or track_bounds        # no survey areas: frame the ships instead
    if bounds:
        lats, lons = [b[0] for b in bounds], [b[1] for b in bounds]
        pad_lat = max(0.3, (max(lats) - min(lats)) * 0.15)
        pad_lon = max(0.3, (max(lons) - min(lons)) * 0.15)
        # the web map stretches without limit toward the poles: keep the frame inside ±82°
        m.fit_bounds([[max(min(lats) - pad_lat, -82), min(lons) - pad_lon],
                      [min(max(lats) + pad_lat, 82), max(lons) + pad_lon]])
    return m


MAP_STYLE = 5   # bump when build_map changes: the cache below only sees its own code, not build_map's


@st.cache_data(show_spinner=False, max_entries=4)
def map_html(geojson: dict, vessels: pd.DataFrame, focus: tuple | None, labels: tuple = (),
             focus_area: tuple | None = None, style: int = MAP_STYLE) -> str:
    return build_map(geojson, vessels, focus, labels, focus_area).get_root().render()


# ============================================================
# SHIP LIBRARY
# ============================================================

def library_files() -> tuple:
    """(file, modified time) for the catalog and every track: the cache key for the library."""
    files = [LIBRARY / "vessels.csv"] + sorted((LIBRARY / "tracks").glob("*"))
    return tuple((str(f), f.stat().st_mtime) for f in files if f.is_file())


@st.cache_data(show_spinner=False)
def load_library(stamp: tuple) -> pd.DataFrame:
    """The catalog, with each track's date span and number of positions added."""
    path = LIBRARY / "vessels.csv"
    if not path.exists():
        return pd.DataFrame()
    cat = pd.read_csv(path, dtype=str).fillna("")
    first, last, count = [], [], []
    for track in cat.get("track_file", pd.Series([""] * len(cat))):
        f = LIBRARY / "tracks" / track
        if not track or not f.is_file():
            first.append(None); last.append(None); count.append(0)
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            std, _ = spd.standardize(spd.read_any(f), f.stem)
        times = std["time"].dropna()
        first.append(times.min().date() if len(times) else None)
        last.append(times.max().date() if len(times) else None)
        count.append(len(std))
    return cat.assign(data_from=first, data_to=last, positions=count,
                      has_data=[n > 0 for n in count])


@st.cache_data(show_spinner=False, max_entries=16)
def library_track(track: str, stamp: float, start, end) -> bytes:
    """A library track cut to [start, end] (dates), as CSV bytes in its original columns."""
    f = LIBRARY / "tracks" / track
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = spd.read_any(f)
        std, _ = spd.standardize(raw, f.stem)
    if std["time"].notna().any() and start and end:
        day = std["time"].dt.date
        raw = raw.iloc[std.loc[(day >= start) & (day <= end), "row_in_file"]]
    return raw.to_csv(index=False).encode()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "vessel"


# the deep-sea mining watchlist (the GFW export the weekly update also pulls): a quick pick
WATCHLIST = LIBRARY / "watchlist_deep_sea_mining.csv"


@st.cache_data(show_spinner=False)
def watchlist_mmsi(stamp: float) -> frozenset:
    """MMSIs on the deep-sea mining watchlist (stamp: the file's modified time, for the cache)."""
    try:
        w = pd.read_csv(WATCHLIST, dtype=str)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return frozenset()
    col = next((c for c in w.columns if c.strip().lower() == "mmsi"), None)
    return frozenset(w[col].dropna().str.strip()) if col else frozenset()
FLAG_CODES = {"China": "CN", "France": "FR", "Japan": "JP", "United States": "US", "Germany": "DE",
              "Russia": "RU", "Denmark": "DK", "Norway": "NO", "South Korea": "KR", "India": "IN",
              "Malta": "MT", "Marshall Islands": "MH", "Saint Kitts and Nevis": "KN", "Taiwan": "TW",
              "United Kingdom": "GB", "Netherlands": "NL", "Belgium": "BE", "Australia": "AU",
              "Canada": "CA", "Singapore": "SG", "Hong Kong": "HK", "Panama": "PA", "Liberia": "LR",
              "Bahamas": "BS", "Cyprus": "CY", "Italy": "IT", "Spain": "ES", "Brazil": "BR",
              "Philippines": "PH", "Vietnam": "VN", "Indonesia": "ID", "Malaysia": "MY"}


def flag_emoji(country: str) -> str:
    code = FLAG_CODES.get(country)
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code) if code else "🏳️"


KIND_ORDER = ["Research / survey ship", "Seismic ship (oil & gas)", "Other ship", "Coast guard"]


def ship_kind(ship_type: str) -> str:
    """The catalog's ship type in plain words, for grouping and filtering."""
    t = str(ship_type).lower()
    if "coast guard" in t:
        return "Coast guard"
    if "seismic" in t and "research" not in t:
        return "Seismic ship (oil & gas)"
    if re.search(r"research|survey|hydrographic|geolog|icebreaker", t):
        return "Research / survey ship"
    return "Other ship"


# ============================================================
# PAGE
# ============================================================

st.set_page_config(page_title="Survey Pattern Detector", page_icon=":ship:", layout="wide")

# Colours and fonts live in .streamlit/config.toml; this adds the masthead, the metrics band and
# the legend. Headings are italic like the water names on a nautical chart.
st.markdown("""<style>
h1, h2, h3, h4 { font-style: italic; letter-spacing: -0.01em; }
h3 { margin-top: 1.6rem !important; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
.st-key-metrics { background: rgba(120, 175, 205, 0.16); border-left: 3px solid #A3166E;
  padding: 0.9rem 1.2rem 0.4rem; border-radius: 0.2rem; }
.st-key-legend { font-size: 0.85rem; line-height: 1.5; }
.legend-keys { display: flex; flex-wrap: wrap; gap: 0.3rem 1.2rem; margin-bottom: 0.5rem; }
.legend-keys span { white-space: nowrap; }
.legend-keys b { display: inline-block; width: 1.1em; font-weight: 400; }
.legend-help { opacity: 0.75; max-width: 80ch; }
.masthead { display: grid; grid-template-columns: minmax(0, 40rem) minmax(0, 1fr); gap: 1.5rem;
  align-items: center; padding: 0 0 0.8rem; border-bottom: 1px solid rgba(120, 160, 185, 0.45);
  margin-bottom: 0.6rem; }
.masthead h1 { font-size: clamp(1.8rem, 3.4vw, 2.5rem); line-height: 1.05; margin: 0 0 0.4rem;
  padding: 0; font-weight: 500; }
.masthead p { max-width: 70ch; line-height: 1.5; margin: 0; opacity: 0.85; }
.masthead svg { width: 100%; max-width: 15rem; height: auto; justify-self: end; overflow: visible; }
[data-testid="stSidebar"] [data-testid="stExpander"] details summary p { font-size: 0.95rem; }
[data-testid="stSidebar"] .stCheckbox { margin-bottom: -0.45rem; }
.masthead .run { fill: none; stroke: #C02C86; stroke-width: 2.2; stroke-linecap: round;
  stroke-linejoin: round; stroke-dasharray: 2400; stroke-dashoffset: 2400;
  animation: sweep 3.2s cubic-bezier(.45, .05, .35, 1) .2s forwards; }
.masthead .transit { fill: none; stroke: currentColor; stroke-width: 1.2; stroke-dasharray: 2 5;
  opacity: 0.45; }
.masthead .contour { fill: none; stroke: #5D93B5; stroke-width: 1; opacity: 0.5; }
.masthead .sounding { font: italic 11px "Newsreader", serif; fill: currentColor; opacity: 0.45; }
.masthead .ship { fill: #C02C86; opacity: 0; animation: arrive .3s ease-out 3.3s forwards; }
@keyframes sweep { to { stroke-dashoffset: 0; } }
@keyframes arrive { to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .masthead .run { animation: none; stroke-dashoffset: 0; }
  .masthead .ship { animation: none; opacity: 1; }
}
@media (max-width: 760px) {
  .masthead { grid-template-columns: 1fr; gap: 1rem; }
  .masthead svg { order: -1; justify-self: start; max-width: 18rem; }
}
</style>""", unsafe_allow_html=True)

def _masthead_svg() -> str:
    """A survey ship's lawnmower run, drawn once as the page loads."""
    left, right, top, gap, n = 170, 440, 46, 17, 7
    run = f"M{left} {top}"
    for i in range(n):
        y = top + i * gap
        end = right if i % 2 == 0 else left
        run += f" H{end}"
        if i < n - 1:
            run += f" A{gap / 2} {gap / 2} 0 0 {1 if i % 2 == 0 else 0} {end} {y + gap}"
    last = top + (n - 1) * gap
    soundings = [(40, 40, "1987"), (96, 92, "2140"), (30, 128, "2215"), (470, 24, "2302"),
                 (300, 190, "2418"), (120, 186, "2266")]
    return (
        '<svg viewBox="0 0 480 200" role="img" aria-label="A survey vessel sailing a lawnmower pattern">'
        '<path class="contour" d="M140 30 C220 4 380 8 462 32 C486 70 478 150 456 170 '
        'C360 186 210 184 148 166 C126 120 124 64 140 30 Z"/>'
        + "".join(f'<text class="sounding" x="{x}" y="{y}">{d}</text>' for x, y, d in soundings)
        + f'<path class="transit" d="M8 196 C60 150 110 70 {left} {top}"/>'
        f'<path class="run" d="{run}"/>'
        f'<path class="ship" d="M{right + 4} {last - 5} L{right + 15} {last} L{right + 4} {last + 5} Z"/>'
        "</svg>")


WHAT_IS_IT = (
    "Ships that map the seabed sail a **lawnmower pattern**: long straight lines side by side, "
    "turning at the end of each line and coming back the other way a little to one side, so that "
    "together the lines cover the whole area. This site looks for that pattern in ships' position "
    "reports (AIS). Ferries, patrol boats and ships going back and forth along a coast can look "
    "similar, so those are filtered out: a survey has to run line after line without long breaks, "
    "keep covering new ground, stay offshore and move at survey speed.\n\n"
    "- **Survey area** (bright yellow, numbered): where one ship surveyed.\n"
    "- **Hotspot**: a place surveyed by several ships, or more than once. Several ships at the "
    "same time suggests a coordinated campaign.\n"
    "- **Ports**: for each survey, the nearest ports, the nearest ports of the ship's own country, "
    "and ports linked to rare-earth minerals (near a processing plant or mine, or known to handle "
    "rare-earth cargo). Routes follow shipping lanes and go around land.\n"
    "- **Surveying now**: the ship was still running survey lines at its last position; pink "
    "dashed lines show where its next lines would fall.")

CREDITS = (
    "Library tracks: [Powered by Global Fishing Watch](https://globalfishingwatch.org) (CC BY-NC 4.0; "
    "hourly positions on a ~1 km grid); US reference tracks: NOAA Marine Cadastre (public domain). "
    "Ports: NGA World Port Index (public domain). Sea distances follow a shipping-lane network "
    "(searoute package) and go around land (Natural Earth 1:10m land, public domain). Rare-earth "
    "sites are a curated list with approximate locations (reference_data/ree_sites.csv); verify "
    "before relying on them.")

# ============================================================
# SIDEBAR: ships, timeframe, own files, advanced settings
# ============================================================

lib = load_library(library_files())
groups, lib_ids = [], []
with st.sidebar:
    st.header("Ships")
    if not len(lib):
        st.info("No ship library found (library/vessels.csv). Upload AIS files below instead.")
        chosen = lib
    else:
        mining = watchlist_mmsi(WATCHLIST.stat().st_mtime if WATCHLIST.exists() else 0.0)
        lib = lib.assign(kind=lib["ship_type"].map(ship_kind), flag=lib["flag"].replace("", "Unknown"),
                         mining=lib["mmsi"].isin(mining))
        selected = st.session_state.setdefault("lib_selected", set())     # empty until you pick
        st.session_state.setdefault("lib_ver", 0)
        st.caption("Open a country, tick ships and press **Show on map**. "
                   "⛏️ marks the deep-sea mining watchlist.")

        query = st.text_input("Find a ship", placeholder="Find a ship: name, MMSI, operator...",
                              key="lib_query", label_visibility="collapsed")
        kinds = [k for k in KIND_ORDER if k in set(lib["kind"])]
        kind = st.selectbox("Kind of ship", ["All kinds of ship"] + kinds, key="lib_kind",
                            label_visibility="collapsed")
        with_data = st.toggle("Only ships with position data", value=True, key="lib_with_data",
                              help="Ships without data are on the watchlist but cannot be analysed yet.")
        view = lib
        if query:
            cols = [c for c in ("name", "mmsi", "imo", "callsign", "operator", "ship_type", "notes") if c in lib]
            view = view[view[cols].agg(" ".join, axis=1).str.contains(re.escape(query), case=False)]
        if kind != "All kinds of ship":
            view = view[view["kind"] == kind]
        if with_data:
            view = view[view["has_data"]]

        b1, b2 = st.columns(2)
        if b1.button("Mining ships", width="stretch", disabled=not lib["mining"].any(),
                     help="Choose just the deep-sea mining watchlist ships (replaces the current choice)."):
            selected.clear()
            selected |= set(lib[lib["mining"] & lib["has_data"]]["name"])
            st.session_state["lib_ver"] += 1
        if b2.button("Clear", width="stretch", disabled=not selected, help="Untick every ship."):
            selected.clear()
            st.session_state["lib_ver"] += 1

        # countries start closed; a version number in the keys starts the boxes afresh after the
        # buttons above or a submit, and the filters in the keys keep boxes and ships matched
        tag = f"{st.session_state['lib_ver']}|{query}|{kind}|{with_data}"
        by_country = view.groupby("flag", sort=False).size().sort_values(ascending=False)
        ticks, all_of = {}, {}
        with st.form("lib_form", border=False):
            if not len(view):
                st.info("No ships match. Clear the search or the filters.")
            for country, n in by_country.items():
                rows = view[view["flag"] == country]
                rows = rows.assign(_off=~rows["name"].isin(selected), _nodata=~rows["has_data"],
                                   _kind=rows["kind"].map(KIND_ORDER.index)).sort_values(
                    ["_off", "_nodata", "_kind", "name"])             # chosen ships first
                n_on = int(rows["name"].isin(selected).sum())
                label = (f"{flag_emoji(country)} {country} · {n}" + (f" · **{n_on} chosen**" if n_on else ""))
                with st.expander(label, expanded=bool(query)):
                    with_tracks = int(rows["has_data"].sum())
                    if with_tracks > 1:
                        all_of[country] = st.checkbox(f"All {with_tracks} ships from {country}",
                                                      key=f"all|{country}|{tag}")
                    for _, r in rows.iterrows():
                        dates = f"{r['data_from']} → {r['data_to']}" if r["has_data"] else "no position data yet"
                        ticks[r["name"]] = (st.checkbox(
                            ("⛏️ " if r["mining"] else "") + r["name"], value=r["name"] in selected,
                            key=f"pick|{r['name']}|{tag}", disabled=not r["has_data"],
                            help=f"{r['kind']}" + (f" · {r['operator']}" if r.get("operator") else "")
                                 + f" · {dates}"), r["has_data"], country)
            go = st.form_submit_button("Show on map", type="primary", width="stretch")
        if go:
            for name, (on, has, country) in ticks.items():
                if has and (on or all_of.get(country)):
                    selected.add(name)
                else:
                    selected.discard(name)
            st.session_state["lib_ver"] += 1
            st.rerun()

        chosen = lib[lib["name"].isin(selected) & lib["has_data"]]
        if len(chosen):
            st.caption(f"**{len(chosen)} ship{'s' if len(chosen) != 1 else ''} chosen**"
                       + (" (many ships take a minute or two)" if len(chosen) > 20 else ""))

    # --- timeframe ------------------------------------------------------------------
    if len(chosen):
        span_from = min(d for d in chosen["data_from"] if d)
        span_to = max(d for d in chosen["data_to"] if d)
        start, end = span_from, span_to
        st.header("Timeframe")
        frame = st.selectbox("Timeframe", ["Last 6 months", "Latest week", "All data", "Last 30 days",
                                           "Last 90 days", "Last 365 days", "Custom range"],
                             key="lib_frame", label_visibility="collapsed",
                             help="'Last 6 months' and 'Latest week' end at the newest position of the "
                                  "chosen ships (Global Fishing Watch data arrives about 4 days late). "
                                  "Six months is about what it takes to catch ships surveying; a single "
                                  "week rarely holds a whole survey. 'Last N days' counts back from each "
                                  "ship's own newest position.")
        last_n = int(frame.split()[1]) if frame.startswith("Last") and frame.endswith("days") else None
        shared = {"Latest week": 7, "Last 6 months": 182}.get(frame)   # one window for all ships
        if shared:
            start, end = max(span_from, span_to - datetime.timedelta(days=shared - 1)), span_to
        if frame == "Custom range":
            picked = st.date_input("Dates", value=(span_from, span_to), min_value=span_from,
                                   max_value=span_to, key="lib_dates")
            if isinstance(picked, (tuple, list)) and len(picked) == 2:
                start, end = picked
        st.caption(f"Data available {span_from} to {span_to}. " + (
            f"Using the **last {last_n} days of each ship's track**." if last_n else
            f"Using **{start} to {end}**."))
        quiet = []
        for _, row in chosen.iterrows():
            f = LIBRARY / "tracks" / row["track_file"]
            s_i, e_i = start, end
            if not last_n and row["data_to"] and (row["data_to"] < start or row["data_from"] > end):
                quiet.append(row["name"])            # no positions in the chosen dates
                continue
            if last_n and row["data_to"]:   # per ship: its own newest position
                e_i = row["data_to"]
                s_i = max(row["data_from"], e_i - pd.Timedelta(days=last_n - 1))
            data = library_track(row["track_file"], f.stat().st_mtime, s_i, e_i)
            groups.append((row["name"], ((f"{safe_name(row['name'])}.csv", data),)))
            lib_ids.append((row["name"], None, row["mmsi"], row["flag"], row["name"], "library",
                            row.get("imo", "")))
        if quiet:
            st.caption("Not in these dates (in port, or AIS off): " + ", ".join(sorted(quiet)) + ".")

    # --- own files and advanced settings, out of the way ---------------------------------
    st.divider()
    with st.expander("Your own AIS files"):
        uploads = st.file_uploader("AIS position files", type=UPLOAD_TYPES, accept_multiple_files=True,
                                   help="CSV, TSV, TXT or Excel; one ship or many per file. Columns such as "
                                        "Latitude/Longitude, Timestamp, MMSI, SOG, COG, ship name and type "
                                        "are recognised automatically. Up to 200 MB per file.")
        separate = True
        if uploads and len(uploads) > 1:
            separate = not st.toggle("Combine all files into one dataset", value=False,
                                     help="Use this when the files are parts of one export, e.g. one file per day.")
    with st.expander("Advanced settings"):
        st.caption("You don't need to change these: the defaults suit most survey ships.")
        defaults = asdict(spd.Config())
        if st.button("Reset to defaults"):
            for name in defaults:
                st.session_state.pop(f"cfg_{name}", None)
        settings = {}
        for group, items in SETTINGS.items():
            st.markdown(f"**{group}**")
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
        st.markdown("**Port matching**")
        port_mode = st.radio("Also list the nearest ports of", ["Each vessel's flag state",
                                                                 "One country for every vessel", "Nobody"],
                             key="port_mode",
                             help="Matches each survey to ports of a country: its vessel's flag state "
                                  "(Chinese ships to Chinese ports...), or one country you pick for every vessel.")
        if port_mode == "One country for every vessel":
            countries = port_intel.port_countries()
            settings["port_country"] = st.selectbox(
                "Country", countries, index=countries.index("China") if "China" in countries else 0,
                key="port_country_pick")
        else:
            settings["port_country"] = "flag" if port_mode.startswith("Each") else "none"

if uploads:
    taken = {g[0] for g in groups}
    if separate:
        for u in uploads:
            name, n = Path(u.name).stem, 2
            while name in taken:
                name, n = f"{Path(u.name).stem} ({n})", n + 1
            taken.add(name)
            groups.append((name, ((u.name, u.getvalue()),)))
    else:
        groups.append(("Combined upload", tuple((u.name, u.getvalue()) for u in uploads)))

# ============================================================
# MAIN PAGE
# ============================================================

st.markdown(
    '<header class="masthead"><div><h1>Survey Pattern Detector</h1>'
    "<p>Where ships have been mapping the seabed: each survey is found in the ships' position "
    "reports and highlighted on the map, with the places several ships surveyed and the ports "
    f"they would sail back to.</p></div>{_masthead_svg()}</header>", unsafe_allow_html=True)

if not groups:
    st.info("**Start here:** choose ships in the menu on the left (open it with the **»** arrow at "
            "the top left if it is hidden): open a country, tick the ships you want and press "
            "**Show on map**. Their survey areas then appear on the map, highlighted in yellow.")
    with st.container(border=True):
        st.markdown("**What am I looking at?**\n\n" + WHAT_IS_IT)
    st.stop()

given = st.session_state.setdefault("identities", {})   # (dataset, vessel) -> {mmsi, flag, name}
with st.spinner("Finding survey patterns and the ports near them..."):
    try:
        res = analyse(tuple(groups), settings,
                      tuple(lib_ids) + tuple(sorted((k[0], k[1], v["mmsi"], v["flag"], v["name"], "entered", "")
                                                    for k, v in given.items())))
    except (ValueError, FileNotFoundError, ImportError) as exc:
        st.error(f"Could not read the data: {exc}")
        st.stop()

T = res["tables"]
vessels, ports_tbl, areas, preds = (T["vessels"].copy(), T["nearby_ports"].copy(),
                                    T["survey_areas"], T["predictions"])
hotspots = T["survey_hotspots"]
for col in ("dataset", "vessel", "name", "mmsi", "imo", "callsign", "flag", "flag_source",
            "ship_type", "destination", "marinetraffic_url", "port_country", "port_country_basis"):
    vessels[col] = (vessels[col].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
                    if col in vessels else "")
if len(ports_tbl):
    text_cols = ports_tbl.select_dtypes(include=["object", "string"]).columns
    ports_tbl[text_cols] = ports_tbl[text_cols].fillna("")     # blank, not "None", in tables
    ports_tbl["ree_link"] = ports_tbl["ree_link"].fillna("").astype(str)   # all-empty reads as float
    ports_tbl[["dataset", "vessel"]] = ports_tbl[["dataset", "vessel"]].astype(str)
if len(ports_tbl) and "match_country" not in ports_tbl:
    ports_tbl["match_country"] = ""
linked_tbl = ports_tbl[ports_tbl["ree_link"] != ""] if len(ports_tbl) else ports_tbl
home_tbl = ports_tbl[ports_tbl["match_country"] != ""] if len(ports_tbl) else ports_tbl

c1, c2, c3, c4, c5 = st.container(key="metrics").columns(5)
c1.metric("Ships", len(vessels))
c2.metric("Survey areas", len(areas), help="Highlighted in yellow and numbered on the map.")
c3.metric("Surveying now", int((vessels["survey_status"] == "Surveying now").sum()),
          help="Still running survey lines at their last position.")
c4.metric("Multi-ship hotspots", int((hotspots["n_vessels"] > 1).sum()) if len(hotspots) else 0,
          help="Places surveyed by more than one ship (Hotspots tab).")
c5.metric("Rare-earth ports nearby", linked_tbl["port"].nunique() if len(linked_tbl) else 0,
          help="Ports linked to rare-earth minerals near the surveys (Ports tab).")

lib_files = {safe_name(name) for name, *_ in lib_ids}
notes = [n for n in res["notes"]
         if not (n.split(":")[0] in lib_files and "no vessel ID column" in n)]   # the catalog says who
if notes:
    with st.expander(f"Notes on the data ({len(notes)})"):
        for note in notes:
            st.warning(note)

# --- survey areas, numbered newest first (surveys still running on top) ----------
vessels["flag_shown"] = vessels["flag"].replace("", "Unknown")
names = {(r["dataset"], r["vessel"]): (r["name"] or r["vessel"], r["flag"]) for _, r in vessels.iterrows()}
area_list = areas.copy()
if len(area_list):
    area_list[["dataset", "vessel"]] = area_list[["dataset", "vessel"]].astype(str)
    area_list["live"] = area_list["status"].astype(str).str.startswith("IN")
    area_list["_end"] = (area_list["end_time"].astype(str) if "end_time" in area_list else "")
    area_list = area_list.sort_values(["live", "_end"], ascending=[False, False]).reset_index(drop=True)
    area_list["number"] = np.arange(1, len(area_list) + 1)
labels = tuple(((r["dataset"], r["vessel"], int(r["area_id"])), int(r["number"]))
               for _, r in area_list.iterrows()) if len(area_list) else ()

ALL_SHIPS = "All ships"


def zoom_to_area(key):
    st.session_state["focus_area"] = key
    st.session_state["zoom_ship"] = ALL_SHIPS


def show_everything():
    st.session_state["focus_area"] = None
    st.session_state["zoom_ship"] = ALL_SHIPS


tab_map, tab_ships, tab_hot, tab_ports, tab_data, tab_help = st.tabs(
    ["🗺️ Map", "🚢 Ships", "🔁 Hotspots", "⚓ Ports", "📄 Data & downloads", "❓ Help"])

# ============================================================
# MAP TAB
# ============================================================
with tab_map:
    v_col, a_col, _ = st.columns([3, 1, 2])
    shown = vessels                        # ships are chosen by country in the sidebar
    order = shown.assign(rank=shown["survey_status"].map({"Surveying now": 0, "Survey found": 1}).fillna(2))
    choices = {ALL_SHIPS: None}
    for _, v in order.sort_values(["rank", "dataset", "vessel"]).iterrows():
        where = ("" if v["vessel"] in (v["dataset"], safe_name(v["dataset"])) else f" · {v['dataset']}")
        choices[f"{vessel_label(v)}{where} · {v['survey_status']}"] = (v["dataset"], v["vessel"])
    if st.session_state.get("zoom_ship") not in choices:
        st.session_state["zoom_ship"] = ALL_SHIPS
    pick = v_col.selectbox("Zoom to a ship", list(choices), key="zoom_ship",
                           on_change=lambda: st.session_state.update(focus_area=None))
    focus = choices[pick]
    focus_area = st.session_state.get("focus_area")
    if focus_area and not any(k == tuple(focus_area) for k, _ in labels):
        focus_area = None
    a_col.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    a_col.button("Show all", on_click=show_everything, width="stretch",
                 disabled=focus is None and focus_area is None)

    map_col, list_col = st.columns([3, 1.15])
    with map_col:
        components.html(map_html(res["geojson"], shown, focus, labels,
                                 tuple(focus_area) if focus_area else None), height=640)
    with list_col:
        shown_keys = set(zip(shown["dataset"], shown["vessel"]))
        listed = (area_list[[k in shown_keys for k in zip(area_list["dataset"], area_list["vessel"])]]
                  if len(area_list) else area_list)
        st.markdown(f"**Survey areas ({len(listed)})**")
        n_live = int((vessels["survey_status"] == "Surveying now").sum())
        st.caption(f"**{n_live} ship{'s are' if n_live != 1 else ' is'} surveying now:** look for the pink "
                   "*next lines* label on the map; the pink dashed lines are where the next survey lines "
                   "should fall." if n_live else
                   "No ship is mid-survey at the end of these dates, so there are no predicted next lines "
                   "(pink). They appear for ships still running survey lines at their last position.")
        if not len(listed):
            st.caption("No survey patterns in these ships' tracks for the chosen dates. Try a longer "
                       "timeframe in the menu on the left: one week rarely holds a whole survey.")
        with st.container(height=600, border=False):
            for _, a in listed.iterrows():
                key = (a["dataset"], a["vessel"], int(a["area_id"]))
                name, flag = names.get((a["dataset"], a["vessel"]), (a["vessel"], ""))
                when = (f"{str(a['start_time'])[:10]} → {str(a['end_time'])[:10]}"
                        if "start_time" in a and not _blank(a["start_time"]) else "")
                hid = int(a["hotspot_id"]) if "hotspot_id" in a and pd.notna(a["hotspot_id"]) else -1
                hot = hotspots[hotspots["hotspot_id"] == hid] if hid > 0 and len(hotspots) else hotspots.iloc[0:0]
                badges = (":red-badge[Surveying now · next lines in pink] " if a["live"] else "") + (
                    f":orange-badge[{int(hot.iloc[0]['n_vessels'])} ships here] "
                    if len(hot) and hot.iloc[0]["n_vessels"] > 1 else "")
                on = focus_area is not None and tuple(focus_area) == key
                with st.container(border=True):
                    st.markdown(f"**#{int(a['number'])} · {name}** {flag_emoji(flag) if flag else ''}  \n"
                                f"{when}  \n{int(a['n_lines'])} lines · {a['area_km2']:,.0f} km² · "
                                f"lines {a['line_axis_compass']}" + (f"  \n{badges}" if badges else ""))
                    st.button("Zoomed in" if on else "Zoom to area", key=f"zoom|{key}", width="stretch",
                              on_click=zoom_to_area, args=(key,), disabled=on,
                              type="primary" if on else "secondary")

    legend = [(AREA_COLOR, "■", "Survey area (numbered)"),
              (HOTSPOT_COLORS[2], "⬢", "Hotspot: 2 ships"), (HOTSPOT_COLORS[3], "⬢", "Hotspot: 3+ ships"),
              (PREDICTION_COLOR, "╍", "Predicted next lines")]
    legend += [(c, "●", k) for k, c in LINK_COLORS.items()]
    legend += [(FLAG_PORT_COLOR, "◉", "Nearest port in the ship's own country (gold, with its route)"),
               (PLAIN_PORT_COLOR, "●", "Other port")]
    st.container(key="legend").markdown(
        "<div class='legend-keys'>"
        + "".join(f"<span><b style='color:{c};text-shadow:0 0 1px #000'>{mark}</b>{label}</span>"
                  for c, mark, label in legend)
        + "</div><div class='legend-help'>Thin coloured lines are the ships' tracks and small dots their "
          "last positions (red: still surveying). Gold rings are each survey's nearest port in the "
          "ship's own country (and its nearest rare-earth linked port there), with the sea route; "
          "the other ports and routes appear when you zoom to a ship or an area. More layers "
          "(rare-earth sites, seabed mining "
          "areas, all world ports) are under the stack icon at the top right of the map; change the "
          "basemap at the bottom left. Click anything for details.</div>", unsafe_allow_html=True)

# ============================================================
# SHIPS TAB
# ============================================================
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


def first_port(tbl: pd.DataFrame) -> dict:
    out = {}
    for (ds, vs), g in tbl.sort_values("sea_km").groupby(["dataset", "vessel"]) if len(tbl) else []:
        r = g.iloc[0]
        out[(ds, vs)] = f"{r['port']} ({r['country']}), {r['sea_km']:,.0f} km"
    return out


with tab_ships:
    # --- vessels whose files carry no identity: let the user say who they are ------
    was_given = pd.Series([k in given for k in zip(vessels["dataset"], vessels["vessel"])], index=vessels.index)
    need = vessels[(vessels["flag"] == "") | vessels["flag_source"].eq("entered") | was_given]
    if len(need):
        with st.expander(f"Identify ships with an unknown flag ({int((need['flag'] == '').sum())} unknown)",
                         expanded=bool((need["flag"] == "").any())):
            st.caption("Their files carry no MMSI or flag (MarineTraffic position exports, for example). "
                       "Enter the MMSI from the ship's MarineTraffic page, and its flag follows from the "
                       "first three digits (413 = China, 366 = United States...), or pick the flag. "
                       "To skip this step, put the MMSI in the file name, e.g. 413123456_export.csv.")
            flag_names = sorted(set(port_intel.port_countries())
                                | {re.sub(r"\s*\(.*\)", "", c) for c in port_intel.MID_COUNTRY.values()})
            with st.form("identities_form"):
                typed = {}
                for _, v in need.iterrows():
                    key = (v["dataset"], v["vessel"])
                    old = given.get(key, {"mmsi": "", "flag": "", "name": ""})
                    i1, i2, i3, i4 = st.columns([3, 2, 2, 2])
                    where = "" if v["vessel"] in (v["dataset"], safe_name(v["dataset"])) else f" · {v['dataset']}"
                    i1.markdown(f"**{vessel_label(v)}**{where}  \n{v['survey_status']}"
                                + (f" · now **{v['flag']}**" if v["flag"] else ""))
                    tag = f"{v['dataset']}|{v['vessel']}"
                    typed[key] = {
                        "mmsi": i2.text_input("MMSI", value=old["mmsi"], key=f"id_mmsi_{tag}",
                                              placeholder="e.g. 413123456"),
                        "flag": i3.selectbox("or flag", [""] + flag_names, key=f"id_flag_{tag}",
                                             index=([""] + flag_names).index(old["flag"])
                                             if old["flag"] in flag_names else 0),
                        "name": i4.text_input("Name (optional)", value=old["name"], key=f"id_name_{tag}"),
                    }
                if st.form_submit_button("Apply and re-run"):
                    bad = [k for k, t in typed.items() if t["mmsi"] and not re.fullmatch(r"\d{9}", t["mmsi"].strip())]
                    if bad:
                        st.error("An MMSI is 9 digits: check " + ", ".join(vs for _, vs in bad) + ".")
                    else:
                        st.session_state["identities"] = {
                            k: {f: t[f].strip() for f in t} for k, t in typed.items() if any(t.values())}
                        st.rerun()

    ship_choices = {"Pick a ship to see its details": None}
    ship_choices.update({k: v for k, v in choices.items() if v is not None})
    default = next((i for i, v in enumerate(ship_choices.values()) if v == focus), 0)
    detail = ship_choices[st.selectbox("Ship", list(ship_choices), index=default, key="detail_ship",
                                       label_visibility="collapsed")]

    if detail is None:
        keys = list(zip(shown["dataset"], shown["vessel"]))
        best, home, home_ree = (first_port(linked_tbl),
                                first_port(home_tbl[home_tbl["category"] == "flag-state port"] if len(home_tbl) else home_tbl),
                                first_port(home_tbl[home_tbl["ree_link"] != ""] if len(home_tbl) else home_tbl))
        overview = shown.assign(nearest_ree_port=[best.get(k, "") for k in keys],
                                home_port=[home.get(k, "") for k in keys],
                                home_ree_port=[home_ree.get(k, "") for k in keys])
        st.dataframe(overview[["name", "vessel", "flag", "ship_type", "survey_status", "survey_areas",
                               "home_ree_port", "home_port", "nearest_ree_port",
                               "positions_used", "track_km", "marinetraffic_url"]],
                     hide_index=True, width="stretch",
                     column_config={"vessel": "Vessel", "name": "Name", "flag": "Flag",
                                    "ship_type": "Type", "survey_status": "Status", "survey_areas": "Areas",
                                    "nearest_ree_port": "Nearest rare-earth linked port (any country)",
                                    "home_port": "Nearest port in its own country",
                                    "home_ree_port": "Nearest rare-earth linked port in its own country",
                                    "positions_used": "Positions",
                                    "track_km": st.column_config.NumberColumn("Track (km)", format="%.0f"),
                                    "marinetraffic_url": st.column_config.LinkColumn("MarineTraffic",
                                                                                     display_text="open")})
    else:
        ds, vs = detail
        v = vessels[(vessels["dataset"] == ds) & (vessels["vessel"] == vs)].iloc[0]
        st.subheader(vessel_label(v))
        left, right = st.columns(2)
        with left:
            size = " × ".join(f"{v[c]} m" for c in ("length_m", "width_m") if c in v and not _blank(v[c]))
            ident = [("Name", v["name"]), ("MMSI", v["mmsi"]), ("IMO", v["imo"]), ("Call sign", v["callsign"]),
                     ("Flag", f"{v['flag']} (from {v['flag_source']})" if v["flag"] else ""),
                     ("Ship type", v["ship_type"]), ("Size", size), ("Destination", v["destination"]),
                     ("Ports matched to", f"{v['port_country']} ({v['port_country_basis']})"
                                          if v["port_country"] else "")]
            st.markdown("**Identity**")
            st.markdown("  \n".join(f"{k}: **{val}**" for k, val in ident if not _blank(val)))
            if v["marinetraffic_url"]:
                st.link_button("Open on MarineTraffic", v["marinetraffic_url"])
        with right:
            period = (f"{str(v['first_time'])[:16]} → {str(v['last_time'])[:16]} UTC"
                      if "first_time" in v and not _blank(v["first_time"]) else "no timestamps (file order used)")
            st.markdown("**Track**")
            st.markdown(f"Status: **{v['survey_status']}**  \n"
                        f"Positions used: **{int(v['positions_used']):,}** of {int(v['positions']):,}  \n"
                        f"Distance covered: **{v['track_km']:,.0f} km**  \n"
                        f"Period: {period}  \n"
                        f"Last position: **{v['last_lat']:.4f}, {v['last_lon']:.4f}**")

        v_areas = (area_list[(area_list["dataset"] == ds) & (area_list["vessel"] == vs)]
                   if len(area_list) else area_list)
        if not len(v_areas):
            st.info("No survey pattern found for this ship in the chosen dates.")
        for _, a in v_areas.iterrows():
            live = bool(a["live"])
            with st.expander(f"Survey area #{int(a['number'])}" + (" · surveying now" if live else ""),
                             expanded=len(v_areas) == 1):
                st.markdown(f"{a['n_lines']} lines in {a['n_blocks']} block(s), best confidence "
                            f"{a['best_confidence']}. Lines run {a['line_axis_compass']}, ~{a['median_spacing_km']} km "
                            f"apart; {a['total_line_km']} line-km over ~{a['area_km2']} km², centred at "
                            f"{a['centroid_lat']}, {a['centroid_lon']}.")
                hid = int(a["hotspot_id"]) if "hotspot_id" in a and pd.notna(a["hotspot_id"]) else -1
                hot = hotspots[hotspots["hotspot_id"] == hid] if hid > 0 and len(hotspots) else hotspots.iloc[0:0]
                if len(hot):
                    h = hot.iloc[0]
                    if h["n_vessels"] > 1:
                        together = h.get("surveyed_together")
                        st.warning(f"**Hotspot {hid}**: {int(h['n_vessels'])} ships have surveyed here: "
                                   f"{h['vessels']}."
                                   + (f" There at the same time: {together}." if not _blank(together) else ""))
                    else:
                        st.info(f"**Hotspot {hid}**: this ship surveyed here {int(h['n_survey_areas'])} times.")
                near = (ports_tbl[(ports_tbl["dataset"] == ds) & (ports_tbl["vessel"] == vs)
                                  & (ports_tbl["area_id"] == a["area_id"])] if len(ports_tbl) else ports_tbl)
                if len(near):
                    def describe(r) -> str:
                        site = (f": {r['ree_site']} ({r['ree_site_status']}) is {r['ree_site_km']:,.0f} km "
                                "from the port" if not _blank(r["ree_site"]) else "")
                        return (f"**{r['port']} ({r['country']})**, ~{r['sea_km']:,.0f} km by "
                                f"{r['distance_basis']}. {r['ree_link']}{site}.")

                    any_ree = near[(near["ree_link"] != "") & (near["match_country"] == "")].sort_values("sea_km").head(1)
                    home_rows = near[near["match_country"] != ""]
                    if len(home_rows):   # the matched country (flag state or chosen) is the headline
                        country = home_rows.iloc[0]["match_country"]
                        first = home_rows[home_rows["category"] == "flag-state port"].sort_values("sea_km").head(1)
                        h_ree = home_rows[home_rows["ree_link"] != ""].sort_values("sea_km").head(1)
                        head = (f"Closest rare-earth linked port in {country}: " + describe(h_ree.iloc[0])
                                if len(h_ree) else f"No rare-earth linked port in {country} is listed.")
                        if len(first):
                            f0 = first.iloc[0]
                            head += (f"  \nNearest port in {country}: **{f0['port']}**, ~{f0['sea_km']:,.0f} km "
                                     f"by {f0['distance_basis']}.")
                        st.error(head)
                        if len(any_ree):
                            st.caption("Closest rare-earth linked port in any country: " + describe(any_ree.iloc[0]))
                    elif len(any_ree):
                        st.error("Closest rare-earth linked port: " + describe(any_ree.iloc[0]))
                    st.markdown("**Ports near this survey** (red: rare-earth linked; gold: the ship's own country)")
                    order_first = {"flag-state port": 0, "flag-state rare-earth linked port": 1}
                    port_table(near.sort_values(["category", "rank"],
                                                key=lambda c: c.map(order_first).fillna(2) if c.name == "category" else c))
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
        drawn = res["maps"].get(spd.map_filename(ds, vs))
        if drawn and len(drawn["track"]) > 1 and st.toggle(
                "Show the detector's quick-look map (PNG)", key=f"png|{ds}|{vs}",
                help="The ship's whole track with every straight line, survey block and survey area, "
                     "drawn by the detector. Takes a second or two."):
            with st.spinner("Drawing..."):
                png = on_request(res, f"png|{ds}|{vs}", lambda: spd.draw_map(drawn))
            if png:
                st.image(png, width="stretch")

# ============================================================
# HOTSPOTS TAB
# ============================================================
with tab_hot:
    st.caption("Places surveyed more than once: survey areas by any ships that overlap or lie within "
               f"{settings['hotspot_join_km']:g} km of each other. Several ships in one place, especially "
               "at the same time, point to a coordinated survey campaign. On the map they are the orange "
               "and red outlines (layer *Survey hotspots*).")
    if not len(hotspots):
        st.info("No place was surveyed more than once in the chosen ships and dates.")
    else:
        hs = hotspots.copy()
        for col in ("surveyed_together", "flags", "first_time", "last_time"):
            if col not in hs:
                hs[col] = ""
        hs["first_time"] = hs["first_time"].astype(str).str[:10].replace("nan", "")
        hs["last_time"] = hs["last_time"].astype(str).str[:10].replace("nan", "")
        st.dataframe(hs[["hotspot_id", "n_vessels", "vessels", "flags", "surveyed_together",
                         "max_vessels_at_once", "n_survey_areas", "total_line_km", "area_km2",
                         "first_time", "last_time", "centroid_lat", "centroid_lon"]].fillna(""),
                     hide_index=True, width="stretch",
                     column_config={"hotspot_id": "Hotspot", "n_vessels": "Ships", "vessels": "Ships surveying",
                                    "flags": "Flags", "surveyed_together": "There at the same time",
                                    "max_vessels_at_once": "Most at once", "n_survey_areas": "Survey areas",
                                    "total_line_km": st.column_config.NumberColumn("Line-km", format="%.0f"),
                                    "area_km2": st.column_config.NumberColumn("Area (km²)", format="%.0f"),
                                    "first_time": "From", "last_time": "To",
                                    "centroid_lat": "Lat", "centroid_lon": "Lon"})

# ============================================================
# PORTS TAB
# ============================================================
with tab_ports:
    st.caption("Ports within 300 km of a rare-earth processing site or mine, or known to handle rare-earth "
               "cargo, near the surveys found. Pick a ship in the Ships tab for every port near each of "
               "its surveys.")
    shown_keys = set(zip(shown["dataset"], shown["vessel"]))
    linked_shown = (linked_tbl[[k in shown_keys for k in zip(linked_tbl["dataset"], linked_tbl["vessel"])]]
                    if len(linked_tbl) else linked_tbl)
    if len(linked_shown):
        port_table(linked_shown.sort_values("sea_km"), extra=("vessel", "area_id"))
    else:
        st.info("No rare-earth linked ports near the surveys found (or no surveys found).")

# ============================================================
# DATA TAB
# ============================================================
with tab_data:
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Everything (ZIP)", res["zip"], "survey_results.zip", "application/zip",
                       help="CSVs and GeoJSON (combined and per layer).")
    xlsx_ready = (res["id"], "xlsx") in st.session_state.get("made_files", {})
    if xlsx_ready or d2.button("Prepare Excel workbook", help="One sheet per table. Large analyses take a "
                                                             "while (the positions sheet has a row per position)."):
        with st.spinner("Writing the Excel workbook..."):
            xlsx = on_request(res, "xlsx", lambda: _excel(T))
        d2.download_button("Excel workbook", xlsx, "survey_results.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d3.download_button("GeoJSON (QGIS / ArcGIS)", json.dumps(res["geojson"]), "survey_results.geojson",
                       "application/geo+json")
    if d4.button("Prepare map (HTML)", help="The world map as a standalone page to open or share."):
        d4.download_button("Interactive map (HTML)", map_html(res["geojson"], vessels, None, labels),
                           "survey_map.html", "text/html")

    tables = st.tabs(["Survey areas", "Ships", "Nearby ports", "Hotspots", "Survey blocks", "Survey lines",
                      "Rejected patterns", "Predictions", "Positions"])
    SHOW_ROWS = 1000   # every table is sent to the browser on each run, open or not: keep big ones short
    for tab, key in zip(tables, ["survey_areas", "vessels", "nearby_ports", "survey_hotspots", "survey_blocks",
                                 "survey_lines", "rejected_blocks", "predictions", "positions_processed"]):
        with tab:
            if len(T[key]):
                df = T[key].head(SHOW_ROWS).copy()
                text = df.select_dtypes(include=["object", "string"]).columns
                df[text] = df[text].fillna("")
                if len(T[key]) > SHOW_ROWS:
                    st.caption(f"First {SHOW_ROWS:,} of {len(T[key]):,} rows. The full table is in the ZIP.")
                st.dataframe(df, hide_index=True, width="stretch")
            else:
                st.write("Nothing found.")

# ============================================================
# HELP TAB
# ============================================================
with tab_help:
    st.markdown(
        "**How to use this site**\n\n"
        "1. **Choose ships** in the menu on the left: open a country, tick the ships you want and press "
        "**Show on map**. *Mining ships* picks the deep-sea mining watchlist in one go.\n"
        "2. **Pick a timeframe** below the ships. *Last 6 months* is about what it takes to catch a ship "
        "surveying; *Latest week* shows where the ships are now.\n"
        "3. **Read the map.** Survey areas are the **yellow, numbered patches**; the list beside the map "
        "has one card per area, and *Zoom to area* frames it with the routes to its ports. *Zoom to a "
        "ship* does the same for one ship, and the **Ships** tab has its full details.\n\n"
        "**What am I looking at?**\n\n" + WHAT_IS_IT)
    st.caption(CREDITS)
