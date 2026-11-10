"""
The world map: survey areas, tracks, ports, routes, rare-earth sites and the live ISA layers
(moved from app.py in the 2026-11-09 revamp), plus clicking on it (streamlit-folium).
"""
from __future__ import annotations

import html
import json

import folium
import numpy as np
import pandas as pd
import streamlit as st
from branca.element import MacroElement
from folium.plugins import FastMarkerCluster, GroupedLayerControl, MousePosition, TimestampedGeoJson
from jinja2 import Template
from matplotlib.path import Path as MplPath

import port_intel
import resource_context
from isa_contracts import CCZ_OUTLINE, ISA_CONTRACTORS, ISA_LAYERS, ISA_SERVICE
from webapp.data import HERE, safe_name


# one colour per dataset; red/orange/gold are kept for rare-earth ports, magenta for predictions
DATASET_COLORS = ["#2f6fdf", "#16a34a", "#8e44ad", "#0e9aa7", "#8d5a3b", "#d63384",
                  "#5c6f82", "#9aa20f"]
PREDICTION_COLOR = "#ff2fb3"
HOTSPOT_COLORS = {1: "#ffb300", 2: "#f4511e", 3: "#8e0038"}   # by ships surveying it (3 = 3 or more)
AREA_COLOR, AREA_EDGE = "#ffe500", "#1b1b1b"   # survey areas: bright yellow, outlined in near-black
LINK_COLORS = {"Known rare-earth cargo port": "#d62728",
               "Near rare-earth processing site": "#f28e2b",
               "Near rare-earth mine": "#c9a227"}
TIER_EDGE = {"P1": "#C8322B", "P2": "#B86E0B", "P3": "#2F78A8", "P4": "#66798A"}   # same as ui.TIER_COLORS
STATION_COLOR = "#7C5CD6"
GAP_COLOR = "#C8322B"
BOUNDARY_FILE = HERE / "reference_data" / "eez_boundaries.geojson"
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
NATIONAL_SEABED = HERE / "reference_data" / "national_seabed_areas.geojson"
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


def dataset_note(row) -> str:
    """' · dataset' for labels, unless the dataset is just the ship itself (library ships, one-ship files)."""
    ds = str(row["dataset"])
    same = {str(row["vessel"]).lower(), str(row.get("name") or "").lower()}
    return "" if ds.lower() in same or safe_name(ds).lower() in same else f" · {ds}"


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
              focus_area: tuple | None = None, extras: dict | None = None) -> folium.Map:
    """
    The world map. focus: (dataset, vessel) to zoom to; focus_area: (dataset, vessel, area_id)
    to zoom to one survey area; labels: ((dataset, vessel, area_id), number) for the numbered
    survey-area badges, matching the list beside the map.
    """
    number = {k: n for k, n in labels}
    extras = extras or {}
    tier_edge = {k: TIER_EDGE[t] for k, t in (extras.get("tiers") or {}).items()}
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
            folium.Polygon(ring, color=tier_edge.get((str(p["dataset"]), str(p["vessel"]), p["area_id"]), AREA_EDGE),
                           weight=3, fill=True, fill_color=AREA_COLOR,
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

    resources = {cat: folium.FeatureGroup(f"Likely target: {cat.lower()}", show=False)
                 for cat in resource_context.CATEGORY_ORDER}
    for _, r in resource_context.regions().iterrows():
        col = resource_context.CATEGORY_COLORS.get(r["category"], "#555")
        # edges every few degrees, so a box spanning the 180° line or the whole globe stays whole
        lo0, lo1 = ((c - 180, c + 180) if r["max_lon"] - r["min_lon"] >= 359     # whole-globe band
                    else (r["min_lon"], r["max_lon"]))
        lons = np.linspace(lo0, lo1, max(2, int((lo1 - lo0) // 10) + 2))
        ring = ([[lo, r["min_lat"]] for lo in lons] + [[lo, r["max_lat"]] for lo in lons[::-1]])
        folium.Polygon(_unwrap(ring, c), color=col, weight=1.5, fill=True,
                       fill_opacity=0.08, tooltip=f"{r['name']}: {r['category']}",
                       popup=folium.Popup(_rows([("Region", f"<b>{html.escape(r['name'])}</b>"),
                                                 ("Resource", r["category"]), ("Commodities", r["commodities"]),
                                                 ("Depth", r["depth"]), ("Note", r["notes"]),
                                                 ("Source", r["source"]),
                                                 ("Outline", "approximate box, for indication only")]),
                                          max_width=360)).add_to(resources.setdefault(
            r["category"], folium.FeatureGroup(f"Likely target: {r['category'].lower()}", show=False)))

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
    groups["What surveys here look for (approx.)"] = list(resources.values())
    groups["Reference"] = [world_ports]
    _intel_layers(groups, highlight, c, extras, keep)
    for members in groups.values():
        for g in members:
            g.add_to(m)
    highlight.add_to(m)                    # added last: drawn above everything else
    GroupedLayerControl({"Survey areas": [highlight], **groups},
                        exclusive_groups=False, collapsed=True).add_to(m)   # opens on hover / tap
    # the layer list is taller than the map: give it its own scroll bar, and keep the
    # mouse wheel / touch drag inside it from zooming or panning the map
    m.get_root().header.add_child(folium.Element(
        "<style>.leaflet-control-layers-expanded{max-height:min(520px,calc(100vh - 120px));"
        "overflow-y:auto;overscroll-behavior:contain;}</style>"))
    m.get_root().script.add_child(folium.Element(
        "setTimeout(function () { document.querySelectorAll('.leaflet-control-layers').forEach("
        "function (el) { L.DomEvent.disableScrollPropagation(el); L.DomEvent.disableClickPropagation(el); }); }, 0);"))
    LiveSeabedAreas(c, seabed).add_to(m)
    folium.LayerControl(position="bottomleft", collapsed=True).add_to(m)   # basemaps
    MousePosition(position="bottomright", separator=" · ", prefix="", empty_string="",
                  lat_formatter="function(n){return Math.abs(n).toFixed(3)+'°'+(n>=0?'N':'S');}",
                  lng_formatter="function(n){n=((n+180)%360+360)%360-180;return Math.abs(n).toFixed(3)+'°'+(n>=0?'E':'W');}"
                  ).add_to(m)

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


MAP_STYLE = 8   # bump when build_map changes: the cache below only sees its own code, not build_map's


@st.cache_data(show_spinner=False, max_entries=4)
def map_html(geojson: dict, vessels: pd.DataFrame, focus: tuple | None, labels: tuple = (),
             focus_area: tuple | None = None, extras: dict | None = None, style: int = MAP_STYLE) -> str:
    return build_map(geojson, vessels, focus, labels, focus_area, extras).get_root().render()



# ============================================================
# CLICKS (2026-11-09 revamp)
# ============================================================

PICK_KM = 20.0          # a click this close to a track vertex selects the ship
STATION_PICK_KM = 15.0  # ... and this close to a station's centre selects the station


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.minimum(1, np.sqrt(a)))


def pick_at(lat: float, lon: float, geojson: dict, labels: tuple, c: float, stations: list | None = None):
    """
    What a click at (lat, lon) on a map centred on longitude c landed on:
    ("area", list number) inside a survey area, else ("ship", (dataset, vessel)) for the
    nearest track vertex within PICK_KM, else None. Longitudes are compared in the map's
    frame, so areas across the 180° line are found from either side.
    """
    number = {k: n for k, n in labels}
    lon = _wrap(lon, c)
    for f in geojson.get("features", []):
        p = f["properties"]
        if p.get("layer") != "survey_area" or f["geometry"]["type"] != "Polygon":
            continue
        key = (str(p.get("dataset")), str(p.get("vessel")), int(p.get("area_id")))
        if key not in number:
            continue
        ring = [[lt, ln] for lt, ln in _unwrap(f["geometry"]["coordinates"][0], lon)]
        if MplPath([(ln, lt) for lt, ln in ring]).contains_point((lon, lat), radius=1e-9) or \
                MplPath([(ln, lt) for lt, ln in ring]).contains_point((lon, lat), radius=-1e-9):
            return ("area", number[key])
    for s_lat, s_lon, s_id in stations or []:
        if _haversine_km(lat, lon, s_lat, s_lon) <= STATION_PICK_KM:
            return ("station", s_id)
    best = None
    for f in geojson.get("features", []):
        p = f["properties"]
        if p.get("layer") != "track" or f["geometry"]["type"] != "LineString":
            continue
        pts = np.asarray(f["geometry"]["coordinates"], float)
        if not len(pts):
            continue
        d = _haversine_km(lat, lon, pts[:, 1], pts[:, 0]).min()
        if d <= PICK_KM and (best is None or d < best[0]):
            best = (d, (str(p.get("dataset")), str(p.get("vessel"))))
    return ("ship", best[1]) if best else None


def map_centre(geojson: dict) -> float:
    """The central longitude build_map draws around (the same rule it uses)."""
    lons = [f["properties"].get("centroid_lon") for f in geojson.get("features", [])
            if f["properties"].get("layer") == "survey_area" and f["properties"].get("centroid_lon") is not None]
    return _central_lon(lons)


def show_map(geojson: dict, vessels: pd.DataFrame, labels: tuple, focus=None, focus_area=None,
             key: str = "map", height: int = 620, extras: dict | None = None):
    """
    Draw the map with streamlit-folium and return what a NEW click picked (see pick_at), or None.
    Only clicks rerun the page: panning and zooming do not.
    """
    from streamlit_folium import st_folium
    m = build_map(geojson, vessels, focus, labels, focus_area, extras)
    out = st_folium(m, key=key, height=height, use_container_width=True,
                    returned_objects=["last_object_clicked"])
    click = (out or {}).get("last_object_clicked")
    if not click:
        return None
    stamp = (round(click["lat"], 6), round(click["lng"], 6))
    seen = st.session_state.setdefault("handled_clicks", {})
    if seen.get(key) == stamp:
        return None
    seen[key] = stamp
    st_list = [(r["lat"], r["lon"], r["id"]) for _, r in (extras or {}).get("stations", pd.DataFrame()).iterrows()]
    return pick_at(click["lat"], click["lng"], geojson, labels, map_centre(geojson), st_list)


def static_map(geojson: dict, vessels: pd.DataFrame, labels: tuple = (), focus=None, focus_area=None,
               height: int = 620, extras: dict | None = None) -> None:
    """The map as plain HTML (no clicks): previews, and the fallback when st_folium cannot draw it."""
    st.iframe(map_html(geojson, vessels, focus, labels, focus_area, extras), height=height)


# ============================================================
# DETECTIONS AND SHIP EVENTS ON THE MAP (spec §11)
# ============================================================

def _boundary_lines() -> list:
    try:
        return json.loads(BOUNDARY_FILE.read_text())["features"]
    except (FileNotFoundError, ValueError):
        return []


def _intel_layers(groups: dict, highlight, c: float, extras: dict, keep: set) -> None:
    """Station rings (on top, clickable), AIS gaps, port calls, GFW events and EEZ boundaries."""
    if not extras:
        return
    mine = lambda df: df[[(str(a), str(b)) in keep for a, b in zip(df["dataset"], df["vessel"])]] if len(df) else df  # noqa: E731
    for _, s in mine(extras.get("stations", pd.DataFrame())).iterrows():
        edge = TIER_EDGE.get(s.get("tier"), STATION_COLOR)
        folium.CircleMarker([s["lat"], _wrap(s["lon"], c)], radius=10, color=edge, weight=3, fill=True,
                            fill_color=STATION_COLOR, fill_opacity=0.35,
                            tooltip=f"Station {s['id']} · {html.escape(str(s['name']))} · {s['hours'] / 24:.1f} days on one spot"
                            ).add_to(highlight)
    gaps = folium.FeatureGroup("AIS gaps (ship went dark)")
    for _, g in mine(extras.get("gaps", pd.DataFrame())).iterrows():
        _polyline([[g["lon0"], g["lat0"]], [g["lon1"], g["lat1"]]], gaps, c, color=GAP_COLOR, weight=2,
                  dash_array="6 6", opacity=0.9, tooltip=f"AIS gap {g['hours']:.0f} h · {g['km']:.0f} km")
    calls = folium.FeatureGroup("Port calls", show=False)
    for _, k in mine(extras.get("calls", pd.DataFrame())).iterrows():
        folium.CircleMarker([k["lat"], _wrap(k["lon"], c)], radius=4, color="#2F78A8", fill=True, fill_opacity=0.9,
                            tooltip=f"Port call: {html.escape(str(k['port']))} · {k['hours']:.0f} h").add_to(calls)
    gfw = folium.FeatureGroup("GFW events (loitering, port visits)", show=False)
    for _, e in extras.get("gfw_events", pd.DataFrame()).iterrows():
        if pd.notna(e.get("lat")) and pd.notna(e.get("lon")):
            folium.CircleMarker([e["lat"], _wrap(e["lon"], c)], radius=3, color="#66798A", fill=True,
                                tooltip=f"GFW {html.escape(str(e.get('kind', '')))} · {str(e.get('start', ''))[:10]}").add_to(gfw)
    eez = folium.FeatureGroup("EEZ boundaries between states (Marine Regions)", show=bool(extras.get("eez", True)))
    for f in _boundary_lines():
        g = f["geometry"]
        for line in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
            _polyline(line, eez, c, color="#5D93B5", weight=1.2, dash_array="4 4", opacity=0.8,
                      tooltip=f"{html.escape(f['properties']['name'])} ({html.escape(f['properties']['type'].lower())})")
    groups["Detections and ship events"] = [gaps, calls, gfw, eez]


def in_range(start, end, lo, hi) -> bool:
    """Does [start, end] (timestamps, may be missing) touch [lo, hi]? Missing dates always count."""
    if lo is None or hi is None or start is None or pd.isna(start):
        return True
    end = start if end is None or pd.isna(end) else end
    return end >= lo and start <= hi


def filter_geojson(geojson: dict, keep_areas: set) -> dict:
    """Only the survey areas (and their blocks) in keep_areas {(dataset, vessel, area_id)}."""
    out = []
    for f in geojson["features"]:
        p = f["properties"]
        if p.get("layer") in ("survey_area", "survey_block") and p.get("area_id") is not None:
            if (str(p.get("dataset")), str(p.get("vessel")), int(p["area_id"])) not in keep_areas:
                continue
        out.append(f)
    return {**geojson, "features": out}


def extras_from(res: dict, by_priority: bool = True, lo=None, hi=None) -> dict:
    """The intel layers for build_map, limited to detections and events in [lo, hi]."""
    intel = res.get("intel", {})
    det = intel.get("detections", pd.DataFrame())
    by_number = {n: k for k, n in res.get("labels", ())}
    tiers, stations = {}, []
    for _, d in det.iterrows():
        if not in_range(d["start"], d["end"], lo, hi):
            continue
        if d["kind"] == "survey" and d["area_number"] in by_number and by_priority:
            tiers[by_number[d["area_number"]]] = d["tier"]
        elif d["kind"] == "station":
            stations.append(d)
    rng = lambda df: df[[in_range(a, b, lo, hi) for a, b in zip(df["start"], df["end"])]] if len(df) else df  # noqa: E731
    return {"tiers": tiers,
            "stations": pd.DataFrame(stations)[["dataset", "vessel", "id", "name", "lat", "lon", "tier", "start", "end"]
                                               ].assign(hours=[(s["end"] - s["start"]).total_seconds() / 3600 for s in stations])
            if stations else pd.DataFrame(columns=["dataset", "vessel", "id", "name", "lat", "lon", "tier", "hours"]),
            "gaps": rng(intel.get("gaps", pd.DataFrame())), "calls": rng(intel.get("calls", pd.DataFrame())),
            "gfw_events": pd.DataFrame()}


def replay_map(res: dict, step_hours: int = 6) -> folium.Map:
    """The season on fast-forward: each ship trails its last four days, detections flash as they start."""
    tracks = res.get("tracks", {})
    lons = [float(tr["lon"].iloc[-1]) for tr in tracks.values() if len(tr)]
    c = _central_lon(lons)
    m = folium.Map(location=[15, c], zoom_start=2, min_zoom=2, tiles=None, world_copy_jump=False)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
                     attr="Tiles &copy; Esri, GEBCO, NOAA, Garmin, HERE", max_native_zoom=10, name="Ocean").add_to(m)
    feats = []
    for i, ((ds, vs), tr) in enumerate(tracks.items()):
        t = tr.dropna(subset=["time"]).set_index("time").sort_index()
        if t.empty:
            continue
        t = t[["lat", "lon"]].resample(f"{step_hours}h").first().dropna()
        color = DATASET_COLORS[i % len(DATASET_COLORS)]
        coords, times = [], []
        for ts, r in t.iterrows():
            lon = _wrap(r["lon"], coords[-1][0] if coords else c)
            coords.append([round(lon, 3), round(r["lat"], 3)])
            times.append(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
        if len(coords) > 1:
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                          "properties": {"times": times, "style": {"color": color, "weight": 2, "opacity": 0.85},
                                         "popup": html.escape(str(ds))}})
    for _, d in res.get("intel", {}).get("detections", pd.DataFrame()).iterrows():
        if d["start"] is None or pd.isna(d["start"]):
            continue
        color = AREA_COLOR if d["kind"] == "survey" else STATION_COLOR
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [_wrap(d["lon"], c), d["lat"]]},
                      "properties": {"times": [d["start"].strftime("%Y-%m-%dT%H:%M:%SZ")], "icon": "circle",
                                     "iconstyle": {"fillColor": color, "fillOpacity": 0.9, "stroke": True,
                                                   "color": TIER_EDGE.get(d["tier"], "#333"), "radius": 9},
                                     "popup": f"{d['id']} · {html.escape(str(d['name']))}"}})
    TimestampedGeoJson({"type": "FeatureCollection", "features": feats}, period="P1D", duration="P4D",
                       add_last_point=True, auto_play=False, loop=False, max_speed=10, loop_button=True,
                       date_options="YYYY-MM-DD", time_slider_drag_update=True).add_to(m)
    return m


def walk_map(res: dict, area_key: tuple, stage: int) -> folium.Map:
    """
    One survey, built up step by step for the briefing: 0 = the raw hourly positions,
    1 = plus the straight passes the detector found, 2 = plus the survey area it drew around them.
    """
    ds, vs, area_id = area_key
    feats = res["res"]["geojson"]["features"]
    area = next((f for f in feats if f["properties"]["layer"] == "survey_area" and _match(f, ds, vs)
                 and int(f["properties"]["area_id"]) == int(area_id)), None)
    ring = area["geometry"]["coordinates"][0] if area else []
    c = _central_lon([lon for lon, _ in ring]) if ring else 0.0
    pts = _unwrap(ring, c)
    m = folium.Map(tiles=None, control_scale=True, prefer_canvas=True, zoom_control=False)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
                     attr="Tiles &copy; Esri, GEBCO, NOAA, Garmin, HERE", max_native_zoom=10).add_to(m)
    p = area["properties"] if area else {}
    t0 = pd.to_datetime(p.get("start_time"), utc=True, errors="coerce")
    t1 = pd.to_datetime(p.get("end_time"), utc=True, errors="coerce")
    track = res.get("tracks", {}).get((ds, vs))
    if track is not None and not pd.isna(t0) and not pd.isna(t1):
        for _, r in track[(track["time"] >= t0) & (track["time"] <= t1)].iterrows():
            folium.CircleMarker([r["lat"], _wrap(r["lon"], c)], radius=2, color="#1D5C8C", weight=0, fill=True,
                                fill_opacity=0.8).add_to(m)
    if stage >= 1:
        for f in feats:
            q = f["properties"]
            if q["layer"] == "line" and _match(f, ds, vs) and q.get("area_id") == int(area_id):
                _polyline(f["geometry"]["coordinates"], m, c, color="#A3166E", weight=3)
    if stage >= 2 and pts:
        folium.Polygon(pts, color=AREA_EDGE, weight=2, fill=True, fill_color=AREA_COLOR, fill_opacity=0.35).add_to(m)
    if pts:
        lats, lons = [a for a, _ in pts], [b for _, b in pts]
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(20, 20))
    return m
