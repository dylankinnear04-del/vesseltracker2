"""
Detections and how much they matter (website spec §11.1).

A detection is a survey area (lawnmower detector) or a station event (stationkeeping.py). For each:
  confidence  how sure the pattern is real (labelled parts, HIGH / MODERATE / LOW)
  priority    how much it matters: weighted mean of eight factors, tier P1-P4
  why         plain-English reasons built from the same facts
Also per ship: port calls, voyages, AIS gaps and status (track_events.py).

Pure pandas/numpy, no Streamlit. Lookups (EEZ, boundary, depth) are injectable for tests.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from scipy.spatial import cKDTree

import geo_lookup
import resource_context
import stationkeeping
import track_events
from isa_contracts import ISA_CONTRACTORS, mineral_of

H = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)

FACTORS = [("resource", "Resource context", 0.22), ("capability", "Ship type", 0.22),
           ("strategic", "EEZ / jurisdiction", 0.16), ("depth", "Water depth", 0.10),
           ("pattern", "Pattern of life", 0.10), ("coord", "Ships working together", 0.08),
           ("dark", "AIS gaps", 0.06), ("recency", "Recency", 0.06)]
CLASS_WEIGHT = {"MINING": 1.0, "DRILLING": 0.9, "GEO": 0.75, "DEEP": 0.75, "SUPPORT": 0.5,
                "RESEARCH": 0.5, "ENERGY": 0.35, "UNK": 0.35, "GOV": 0.25}
CLASS_STATION_FIT = {"MINING": 1.0, "DRILLING": 1.0, "GEO": 1.0, "DEEP": 1.0, "SUPPORT": 1.0,
                     "ENERGY": 0.8, "RESEARCH": 0.7, "GOV": 0.3, "UNK": 0.3}
MINERAL_NAMES = {"nodules": "polymetallic nodules", "sulphides": "polymetallic sulphides",
                 "crusts": "cobalt-rich crusts", "ree": "rare-earth mud"}
DEEP_MINERAL_CATEGORIES = {"Polymetallic nodules": "nodules", "Cobalt-rich crusts": "crusts",
                           "Seafloor massive sulphides": "sulphides"}
NEAR_KM = 300.0


def clamp(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def tier_of(score: float) -> str:
    return "P1" if score >= 0.70 else "P2" if score >= 0.50 else "P3" if score >= 0.35 else "P4"


def conf_label(score: float) -> str:
    return "HIGH" if score >= 0.8 else "MODERATE" if score >= 0.6 else "LOW"


def _weighted(parts) -> float:
    return sum(v * w for v, w in parts) / sum(w for _, w in parts)


def _km(lat1, lon1, lat2, lon2):
    return float(track_events.haversine_km(lat1, lon1, lat2, lon2))


def _fmt_h(h: float) -> str:
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} days"


# ============================================================ ISA areas
def isa_index(features: list | None):
    """ISA contract polygons (GeoJSON features from the ISA service) ready for lookups; None if unavailable."""
    if not features:
        return None
    polys, pts, owner = [], [], []
    for f in features:
        g = f.get("geometry") or {}
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        cid = (f.get("properties") or {}).get("ContractID", "")
        contractor, sponsor = ISA_CONTRACTORS.get(cid, (cid or "ISA contractor", ""))
        info = {"contract": cid, "contractor": contractor, "sponsor": sponsor, "mineral": mineral_of(cid)}
        for rings in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            ring = np.asarray(rings[0], float)
            polys.append((MplPath(ring), ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max(), info))
            for (x0, y0), (x1, y1) in zip(ring[:-1], ring[1:]):
                n = max(1, int(np.hypot(x1 - x0, y1 - y0) / 0.05))
                t = np.linspace(0, 1, n, endpoint=False)
                pts.append(np.column_stack([y0 + (y1 - y0) * t, x0 + (x1 - x0) * t]))
                owner.extend([len(polys) - 1] * n)
    if not polys:
        return None
    ll = np.vstack(pts)
    tree = cKDTree(track_events._xyz(ll[:, 0], ll[:, 1]))
    return {"polys": polys, "tree": tree, "owner": np.asarray(owner)}


def isa_at(lat: float, lon: float, isa) -> tuple[dict | None, float | None, dict | None]:
    """(contract containing the point, km to the nearest contract, that nearest contract)."""
    if not isa:
        return None, None, None
    x = ((lon + 180) % 360) - 180
    for path, x0, y0, x1, y1, info in isa["polys"]:
        if x0 <= x <= x1 and y0 <= lat <= y1 and path.contains_point((x, lat)):
            return info, 0.0, info
    chord, i = isa["tree"].query(track_events._xyz([lat], [x])[0])
    km = float(2 * track_events.EARTH_KM * np.arcsin(min(1.0, chord / 2)))
    return None, km, isa["polys"][isa["owner"][i]][5]


# ============================================================ the eight factors
def _ree_region(lat, lon):
    """Rare-earth mud region containing or within 300 km of the point (resource_context boxes)."""
    regs = resource_context.regions()
    if regs.empty:
        return None
    ree = regs[regs["category"] == "Rare-earth-rich mud"]
    x = ((lon + 180) % 360) - 180
    for _, r in ree.iterrows():
        cy = min(max(lat, r["min_lat"]), r["max_lat"])
        cx = min(max(x, r["min_lon"]), r["max_lon"])
        if _km(lat, x, cy, cx) <= NEAR_KM:
            return r["name"]
    return None


def resource_factor(lat: float, lon: float, isa) -> tuple[float, str, str]:
    """(value, reason, resource kind: nodules / sulphides / crusts / ree / '')."""
    inside, km, near = isa_at(lat, lon, isa)
    if inside:
        return 0.9, f"Inside ISA contract area: {inside['contractor']} ({MINERAL_NAMES[inside['mineral']]})", inside["mineral"]
    ree = _ree_region(lat, lon)
    if ree:
        return 0.8, f"In or near a rare-earth mud area ({ree})", "ree"
    if isa and km is not None and km <= NEAR_KM:
        return 0.45, f"{km:,.0f} km from ISA area of {near['contractor']}", near["mineral"]
    if not isa:
        hits = resource_context.regions_at(lat, lon)
        deep = hits[hits["category"].isin(DEEP_MINERAL_CATEGORIES)] if len(hits) else hits
        if len(deep):
            r = deep.iloc[0]
            return 0.45, f"In {r['name']} (ISA areas unavailable)", DEEP_MINERAL_CATEGORIES[r["category"]]
        return 0.1, "No known deep-sea mineral area here (ISA areas unavailable)", ""
    return 0.1, "No ISA area or rare-earth site within 300 km", ""


def strategic_factor(eez: dict | None, boundary: tuple | None, flag: str, sponsor: str | None) -> tuple[float, str]:
    near = boundary is not None and boundary[0] < 50
    if not flag or flag == "Unknown":
        return 0.5, "Flag unknown" + (f": inside {eez['name']}" if eez else ", high seas")
    if eez and flag not in eez["sovereigns"]:
        return 1.0, f"Inside a foreign EEZ: {eez['name']}"
    if eez and eez["type"] != "200NM":
        return 0.75, f"Inside {eez['name']}"
    if eez and near:
        return 0.6, f"Own EEZ, {boundary[0]:.0f} km from the {boundary[1]} boundary"
    if eez:
        return 0.15, f"Inside its own flag's EEZ ({eez['name']})"
    if sponsor and flag and sponsor != flag:
        return 0.8, f"High seas, in an area sponsored by {sponsor}"
    if near:
        return 0.6, f"High seas, {boundary[0]:.0f} km from the {boundary[1]} boundary"
    return 0.4, "High seas (outside all EEZs)"


def depth_factor(depth: float | None) -> tuple[float, str]:
    if depth is None or (isinstance(depth, float) and np.isnan(depth)):
        return 0.5, "Depth unknown"
    if depth >= 0:
        return 0.05, f"Depth grid shows land or intertidal ({depth:.0f} m)"
    if depth <= -1000:
        return 1.0, f"{-depth:,.0f} m water depth"
    if depth <= -200:
        return 0.6, f"{-depth:,.0f} m water depth (slope)"
    return 0.15, f"{-depth:,.0f} m water depth (shelf)"


def recency_factor(active: bool, end, newest) -> tuple[float, str]:
    if active:
        return 1.0, "Active at the last report"
    if end is None or pd.isna(end) or newest is None:
        return 0.1, "Date unknown"
    age = (pd.Timestamp(newest) - pd.Timestamp(end)) / DAY
    v = 0.8 if age < 14 else 0.6 if age < 45 else 0.3 if age < 120 else 0.1
    return v, f"Ended {age:.0f} days before the latest data"


def pattern_factor(rel: dict, same_port_return: bool) -> tuple[float, str]:
    if rel["revisits"]:
        return 1.0, f"Repeat visit: {len(rel['revisits']) + 1} operations at this site"
    if rel["others"]:
        return 0.8, f"Other ships worked this site at other times ({len(rel['others'])})"
    if rel["same_trip"]:
        return 0.6, "Several operations here on one voyage"
    if same_port_return:
        return 0.4, "Single trip with a return to the same port"
    return 0.3, "Single operation"


def relations(dets: list[dict]) -> dict:
    """For each detection key: coord / revisits / others / same_trip lists of other keys (spec §11.1)."""
    out = {d["key"]: {"coord": [], "revisits": [], "others": [], "same_trip": [], "coord_km": {}} for d in dets}
    timed = [d for d in dets if not pd.isna(d["start"]) and not pd.isna(d["end"])]
    for a in timed:
        for b in timed:
            if a is b:
                continue
            km = _km(a["lat"], a["lon"], b["lat"], b["lon"])
            apart = abs((a["start"] - b["start"]) / DAY)
            same = a["vessel"] == b["vessel"] and a["dataset"] == b["dataset"]
            r = out[a["key"]]
            if not same:
                overlap_h = (min(a["end"], b["end"]) - max(a["start"], b["start"])) / H
                if overlap_h > 12 and km < 80:
                    r["coord"].append(b["key"])
                    r["coord_km"][b["key"]] = km
                if apart > 7 and km < 50:
                    r["others"].append(b["key"])
            else:
                if apart > 7 and km < 150:
                    r["revisits"].append(b["key"])
                elif apart <= 7 and km < 150:
                    r["same_trip"].append(b["key"])
    return out


# ============================================================ confidence
def survey_confidence(blocks: pd.DataFrame) -> tuple[float, list]:
    """(headline score = the detector's best block score, labelled parts) for one survey area."""
    if blocks is None or not len(blocks):
        return 0.5, []
    b = blocks.sort_values("score", ascending=False).iloc[0]
    g = lambda k, d=0.0: float(b[k]) if k in b and pd.notna(b[k]) else d   # noqa: E731
    speed = g("survey_speed_kn")
    parts = [("Repeated passes", clamp((g("n_lines") - 2) / 8), f"{g('n_lines'):.0f} survey lines"),
             ("Spacing regularity", clamp(1 - g("spacing_cv") / 0.5),
              f"{g('median_spacing_km'):.1f} km apart, spread {g('spacing_cv'):.2f}"),
             ("Reversal consistency", clamp(1 - g("mean_antiparallel_dev_deg") / 20),
              f"turns within {g('mean_antiparallel_dev_deg'):.0f}° of a U-turn"),
             ("Line overlap", clamp(g("mean_overlap_frac")), f"{g('mean_overlap_frac') * 100:.0f}% overlap"),
             ("Progressive coverage", clamp(g("progression_frac")), f"{g('progression_frac') * 100:.0f}% of steps advance"),
             ("Survey speed", 1.0 if 2 <= speed <= 8 else 0.5, f"{speed:.1f} kn median")]
    return round(clamp(g("score", 0.5)), 3), parts


def station_confidence(st: pd.Series, cls: str, gfw: dict | None) -> tuple[float, list]:
    parts = [("Extended dwell", clamp((st["hours"] - 24) / (7 * 24)), _fmt_h(st["hours"]) + " on station", 0.3),
             ("Tight radius", clamp(1 - (st["r95_km"] - 1.0) / 2.5), f"95% within {st['r95_km'] * 1000:,.0f} m", 0.25),
             ("Near-zero speed", clamp(1 - (st["median_kn"] - 0.2) / 1), f"median {st['median_kn']:.1f} kn", 0.25),
             ("Low net drift", clamp(1 - st["net_km"] / 3), f"{st['net_km'] * 1000:,.0f} m start to end", 0.1),
             ("Ship type fits station work", CLASS_STATION_FIT.get(cls, 0.3), geo_lookup.CLASSES.get(cls, cls), 0.1),
             ("Confirmed by GFW loitering", (1.0 if gfw["overlap"] >= 0.5 else 0.7) if gfw else 0.2,
              f"GFW loitering {_fmt_h(gfw['hours'])}, {gfw['overlap'] * 100:.0f}% overlap" if gfw else "no GFW loitering event", 0.15)]
    score = _weighted([(v, w) for _, v, _, w in parts])
    return round(score, 3), [(lab, round(v, 3), d) for lab, v, d, _ in parts]


# ============================================================ build
def _code(name: str, vessel: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name or vessel).upper()) or "SHIP"


def _ts(x):
    t = pd.to_datetime(x, utc=True, errors="coerce")
    return None if pd.isna(t) else t


def build(prepared: dict, tracks: dict, ports: pd.DataFrame, gfw_info, gfw_events, isa, newest,
          eez=None, boundary=None, depth=None, station_cfg: stationkeeping.StationConfig | None = None) -> dict:
    """
    Everything the pages show about detections. prepared: webapp.data.prepare() output;
    tracks: {(dataset, vessel): standardized track in the analysed window}.
    """
    eez = eez or geo_lookup.eez_at
    boundary = boundary or geo_lookup.nearest_boundary_km
    depth = depth or geo_lookup.depth_m
    station_cfg = station_cfg or stationkeeping.StationConfig()
    newest = _ts(newest)
    gfw_info = gfw_info if gfw_info is not None else pd.DataFrame()
    gfw_events = gfw_events if gfw_events is not None else pd.DataFrame()

    vessels = prepared["vessels"]
    info = {(str(r["dataset"]), str(r["vessel"])): r for _, r in vessels.iterrows()}
    gfw_type = dict(zip(gfw_info.get("mmsi", pd.Series(dtype=str)).astype(str),
                        gfw_info.get("vessel_type", pd.Series(dtype=str)).astype(str))) if len(gfw_info) else {}

    def who(ds, vs):
        r = info.get((ds, vs))
        name = (r.get("name") if r is not None else "") or vs
        mmsi = str(r.get("mmsi") or "") if r is not None else ""
        flag = (r.get("flag") if r is not None else "") or ""
        cls, inferred = geo_lookup.vessel_class(mmsi, r.get("ship_type", "") if r is not None else "", gfw_type.get(mmsi, ""))
        return name, mmsi, flag, cls, inferred

    # --- per-ship events: port calls, voyages, gaps, stations ---
    calls_all, voy_all, gaps_all, st_all = [], [], [], []
    for (ds, vs), tr in tracks.items():
        if tr is None or tr.empty:
            continue
        c = track_events.port_calls(tr, ports)
        v = track_events.voyages(c, tr["time"].max())
        g = track_events.ais_gaps(tr, ports=ports)
        s = stationkeeping.detect_stations(tr, ports, station_cfg, depth=depth)
        name, mmsi, *_ = who(ds, vs)
        if len(s):
            ev = gfw_events[gfw_events["mmsi"].astype(str) == mmsi] if len(gfw_events) and "mmsi" in gfw_events else pd.DataFrame()
            s["gfw"] = stationkeeping.match_loitering(s, ev)
            s["active"] = s["end"] >= tr["time"].max() - 12 * H
        for frame, bucket in ((c, calls_all), (v, voy_all), (g, gaps_all), (s, st_all)):
            if len(frame):
                bucket.append(frame.assign(dataset=ds, vessel=vs))
    cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()   # noqa: E731
    calls, voys, gaps, stations = cat(calls_all), cat(voy_all), cat(gaps_all), cat(st_all)

    # --- detections ---
    blocks = prepared.get("res", {}).get("tables", {}).get("survey_blocks", pd.DataFrame())
    dets = []
    for _, a in prepared["areas"].iterrows():
        ds, vs = str(a["dataset"]), str(a["vessel"])
        ids = {int(x) for x in str(a.get("block_ids", "")).split() if x.strip().isdigit()}
        bl = blocks[(blocks["dataset"].astype(str) == ds) & (blocks["vessel"].astype(str) == vs)
                    & blocks["block_id"].isin(ids)] if len(blocks) else blocks
        conf, parts = survey_confidence(bl)
        dets.append({"key": len(dets), "kind": "survey", "dataset": ds, "vessel": vs,
                     "start": _ts(a.get("start_time")), "end": _ts(a.get("end_time")), "active": bool(a.get("live", False)),
                     "lat": float(a["centroid_lat"]), "lon": float(a["centroid_lon"]), "area_number": int(a["number"]),
                     "confidence": conf, "conf_parts": parts, "gfw_confirmed": False})
    for _, s in stations.iterrows():
        _, _, _, cls, _ = who(s["dataset"], s["vessel"])
        conf, parts = station_confidence(s, cls, s.get("gfw"))
        dets.append({"key": len(dets), "kind": "station", "dataset": s["dataset"], "vessel": s["vessel"],
                     "start": s["start"], "end": s["end"], "active": bool(s.get("active", False)),
                     "lat": float(s["lat"]), "lon": float(s["lon"]), "area_number": None,
                     "confidence": conf, "conf_parts": parts, "gfw_confirmed": s.get("gfw") is not None,
                     "station": s.drop(labels=["gfw"], errors="ignore").to_dict()})
    rel = relations(dets)
    by_key = {d["key"]: d for d in dets}

    rows = []
    for d in dets:
        name, mmsi, flag, cls, inferred = who(d["dataset"], d["vessel"])
        res_v, res_d, res_kind = resource_factor(d["lat"], d["lon"], isa)
        inside, _, _ = isa_at(d["lat"], d["lon"], isa)
        z, bd = eez(d["lat"], d["lon"]), boundary(d["lat"], d["lon"])
        str_v, str_d = strategic_factor(z, bd, flag, inside["sponsor"] if inside else None)
        dep = d["station"]["depth_m"] if d["kind"] == "station" else depth(d["lat"], d["lon"])
        dep_v, dep_d = depth_factor(dep)
        r = rel[d["key"]]
        same_port = False
        if len(voys) and d["start"] is not None:
            mine = voys[(voys["dataset"] == d["dataset"]) & (voys["vessel"] == d["vessel"])]
            hit = mine[(mine["start"] <= d["start"]) & (mine["end"] >= d["start"])]
            same_port = bool(len(hit) and hit.iloc[0]["same_port"])
        pat_v, pat_d = pattern_factor(r, same_port)
        co_names = [f"{who(by_key[k]['dataset'], by_key[k]['vessel'])[0]} within {r['coord_km'][k]:.0f} km" for k in r["coord"]]
        co_v, co_d = (1.0, "; ".join(co_names)) if co_names else (0.0, "No other ship working nearby at the same time")
        my_gaps = pd.DataFrame()
        if len(gaps) and d["start"] is not None:
            mg = gaps[(gaps["dataset"] == d["dataset"]) & (gaps["vessel"] == d["vessel"])]
            my_gaps = mg[(mg["end"] >= d["start"] - 7 * DAY) & (mg["start"] <= d["end"])]
        dark_v, dark_d = ((1.0, ", ".join(f"{_fmt_h(h)} AIS gap" for h in my_gaps["hours"]))
                          if len(my_gaps) else (0.0, "Continuous AIS"))
        rec_v, rec_d = recency_factor(d["active"], d["end"], newest)
        cap_d = geo_lookup.CLASSES[cls] + (" (inferred)" if inferred else "")
        values = {"resource": (res_v, res_d), "capability": (CLASS_WEIGHT[cls], cap_d), "strategic": (str_v, str_d),
                  "depth": (dep_v, dep_d), "pattern": (pat_v, pat_d), "coord": (co_v, co_d),
                  "dark": (dark_v, dark_d), "recency": (rec_v, rec_d)}
        pri_parts = [(k, lab, round(values[k][0], 3), w, values[k][1]) for k, lab, w in FACTORS]
        priority = round(_weighted([(v, w) for _, _, v, w, _ in pri_parts]), 2)

        # always: what it is, whose waters, how deep; then whatever else raises the priority
        lower = lambda s: s[0].lower() + s[1:] if s else s   # noqa: E731
        why = []
        if d["kind"] == "survey":
            st_ = d["conf_parts"]
            if st_:
                why.append(f"{st_[0][2]} in a lawnmower pattern, {st_[1][2].split(',')[0]}")
        else:
            why.append(f"{_fmt_h(d['station']['hours'])} holding one spot ({d['station']['r95_km'] * 1000:,.0f} m)")
            if d["gfw_confirmed"]:
                why.append("confirmed by a GFW loitering event")
        if res_v >= 0.45:
            why.append(lower(res_d))
        why.append(lower(str_d))
        if dep is not None and not (isinstance(dep, float) and np.isnan(dep)):
            why.append(dep_d)
        why += [f"{n}" for n in co_names]
        if dark_v:
            why.append(dark_d)
        if r["revisits"]:
            why.append("repeat visit to this site")
        if same_port:
            why.append("returned to the port it left from")
        rows.append({"key": d["key"], "kind": d["kind"], "dataset": d["dataset"], "vessel": d["vessel"], "mmsi": mmsi,
                     "name": name, "flag": flag, "ship_class": cls, "start": d["start"], "end": d["end"],
                     "active": d["active"], "lat": d["lat"], "lon": d["lon"], "area_number": d["area_number"],
                     "confidence": d["confidence"], "conf_label": conf_label(d["confidence"]), "conf_parts": d["conf_parts"],
                     "priority": priority, "tier": tier_of(priority), "pri_parts": pri_parts, "why": why,
                     "resource": res_kind, "eez": z["name"] if z else "", "depth_m": dep,
                     "coord": r["coord"], "gfw_confirmed": d["gfw_confirmed"]})
    det = pd.DataFrame(rows)
    if len(det):
        det["_t"] = det["start"].apply(lambda t: t if t is not None else pd.Timestamp.max.tz_localize("UTC"))
        det = det.sort_values(["vessel", "kind", "_t"])
        # stable ids: kind, ship and start date, so they do not renumber when the window slides
        base = [f"{k.upper()}-{_code(n, v)}-{t:%Y%m%d}" if t is not None and t.year < 9000 else f"{k.upper()}-{_code(n, v)}-NODATE"
                for k, n, v, t in zip(det["kind"], det["name"], det["vessel"], det["_t"])]
        seen: dict = {}
        ids = []
        for b in base:
            n = seen.get(b, 0)
            seen[b] = n + 1
            ids.append(b if n == 0 else f"{b}-{chr(ord('a') + n)}")
        det["id"] = ids
        key_to_id = dict(zip(det["key"], det["id"]))
        det["coord"] = det["coord"].apply(lambda ks: [key_to_id[k] for k in ks])
        det = det.drop(columns=["_t", "key"]).sort_values(["priority", "confidence"], ascending=False).reset_index(drop=True)

    # --- status per ship ---
    status = []
    for (ds, vs), tr in tracks.items():
        if tr is None or tr.empty:
            continue
        kinds = set(det[(det["dataset"] == ds) & (det["vessel"] == vs) & det["active"]]["kind"]) if len(det) else set()
        mine = calls[(calls["dataset"] == ds) & (calls["vessel"] == vs)] if len(calls) else pd.DataFrame()
        s, stale = track_events.ship_status(tr, mine, kinds, newest)
        status.append({"dataset": ds, "vessel": vs, "status": s, "stale": stale, "last_time": tr["time"].max()})
    return {"detections": det, "stations": stations, "calls": calls, "voyages": voys, "gaps": gaps,
            "status": pd.DataFrame(status, columns=["dataset", "vessel", "status", "stale", "last_time"])}
