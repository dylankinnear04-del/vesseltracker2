"""
Our results in SeaTrace's data format (the JSON its console reads from <script id="seatrace-data">).

SeaTrace (a JMU capstone prototype built on this project's GFW export) shipped one frozen snapshot;
here the same structure is built from the live pipeline: the ship library, the survey detector,
stationkeeping, port calls / AIS gaps, GFW registry and events, EEZs, depth, ISA contract areas
(read live, in memory only) and hotspots. SeaTrace's own engine then scores and presents it.

Times are hours from T0 (the season start, UTC). Positions are [lat, lon].
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

import geo_lookup
import intel
import track_events
from isa_contracts import ISA_CONTRACTORS, mineral_of
from webapp import data

H = pd.Timedelta(hours=1)
MINAMITORISHIMA = (24.29, 153.98)
ZONE_TYPE = {"nodules": "POLYMETALLIC_NODULE", "sulphides": "SEAFLOOR_MASSIVE_SULFIDE", "crusts": "COBALT_RICH_CRUST"}
ISO2 = {"China": "CN", "France": "FR", "Japan": "JP", "United States": "US", "Germany": "DE", "Russia": "RU",
        "Denmark": "DK", "Norway": "NO", "South Korea": "KR", "India": "IN", "Malta": "MT", "Marshall Islands": "MH",
        "Saint Kitts and Nevis": "KN", "Taiwan": "TW", "United Kingdom": "GB", "Netherlands": "NL", "Belgium": "BE",
        "Australia": "AU", "Canada": "CA", "Singapore": "SG", "Hong Kong": "HK", "Panama": "PA", "Liberia": "LR",
        "Bahamas": "BS", "Cyprus": "CY", "Italy": "IT", "Spain": "ES", "Brazil": "BR", "Philippines": "PH",
        "Vietnam": "VN", "Indonesia": "ID", "Malaysia": "MY"}
PORTS_FILE = data.HERE / "reference_data" / "world_ports.csv"
REE_FILE = data.HERE / "reference_data" / "ree_sites.csv"
BOUNDARY_FILE = data.HERE / "reference_data" / "eez_boundaries.geojson"


def vessel_id(name: str) -> str:
    """SeaTrace's ship id: the name in lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower()) or "ship"


def hours(t, t0) -> float | None:
    if t is None or pd.isna(t):
        return None
    return round((pd.Timestamp(t) - t0) / H, 2)


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# ============================================================ tracks
def thin(track: pd.DataFrame) -> pd.DataFrame:
    """Drop fixes that repeat the previous ~1 km cell (port stays, stations), keeping each run's ends."""
    t = track.dropna(subset=["time", "lat", "lon"]).sort_values("time").reset_index(drop=True)
    if len(t) < 3:
        return t
    cell = (np.round(t["lat"] * 100).astype(int) * 100000 + np.round(t["lon"] * 100).astype(int)).to_numpy()
    same_prev = np.r_[False, cell[1:] == cell[:-1]]
    same_next = np.r_[cell[:-1] == cell[1:], False]
    gap_next = np.r_[(t["time"].diff().dt.total_seconds().to_numpy()[1:] > 6 * 3600), False]
    keep = ~(same_prev & same_next & ~gap_next)
    return t[keep].reset_index(drop=True)


def encode_track(track: pd.DataFrame, t0) -> list[int]:
    """SeaTrace's track encoding: per fix [Δt (30-min steps), Δlat×100, Δlon×100, speed×10]."""
    out, pt, pla, plo = [], 0, 0, 0
    for _, r in track.iterrows():
        t = int(round((r["time"] - t0) / pd.Timedelta(minutes=30)))
        la, lo = int(round(r["lat"] * 100)), int(round(r["lon"] * 100))
        sog = r.get("speed_kn")
        out += [t - pt, la - pla, lo - plo, int(round((0 if sog is None or pd.isna(sog) else sog) * 10))]
        pt, pla, plo = t, la, lo
    return out


def decode_track(enc: list[int], t0) -> pd.DataFrame:
    rows, t, la, lo = [], 0, 0, 0
    for i in range(0, len(enc), 4):
        t, la, lo = t + enc[i], la + enc[i + 1], lo + enc[i + 2]
        rows.append({"time": t0 + pd.Timedelta(minutes=30 * t), "lat": la / 100, "lon": lo / 100, "speed_kn": enc[i + 3] / 10})
    return pd.DataFrame(rows)


# ============================================================ reference tables
def ports_list() -> tuple[list, pd.DataFrame]:
    p = pd.read_csv(PORTS_FILE).dropna(subset=["lat", "lon"]).reset_index(drop=True)
    recs = [{"id": i, "name": str(r["port"]), "cc": str(r.get("country", "")), "lat": round(float(r["lat"]), 3),
             "lon": round(float(r["lon"]), 3), "size": str(r.get("harbor_size", "") if pd.notna(r.get("harbor_size")) else "")}
            for i, r in p.iterrows()]
    return recs, p


def zones_list(isa_features: list | None) -> list:
    """ISA contract areas grouped by contract, rings as [lat, lon] (longitudes continuous across 180°)."""
    by = {}
    for f in isa_features or []:
        g = f.get("geometry") or {}
        cid = (f.get("properties") or {}).get("ContractID")
        if not cid or g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        z = by.setdefault(cid, {"rings": [], "km2": 0.0})
        z["km2"] += float((f.get("properties") or {}).get("AreaKM2") or 0)
        for rings in polys:
            ring = rings[0]
            ref = ring[0][0] % 360
            z["rings"].append([[round(lat, 4), round(ref + ((lon % 360 - ref + 180) % 360) - 180, 4)] for lon, lat in ring])
    out = []
    for cid, z in sorted(by.items()):
        pts = np.array([p for ring in z["rings"] for p in ring])
        contractor, sponsor = ISA_CONTRACTORS.get(cid, (cid, ""))
        out.append({"id": cid, "type": ZONE_TYPE[mineral_of(cid)], "contractor": contractor, "sponsor": sponsor,
                    "km2": int(round(z["km2"])), "rings": z["rings"],
                    "bbox": [round(pts[:, 0].min(), 4), round(pts[:, 1].min(), 4), round(pts[:, 0].max(), 4), round(pts[:, 1].max(), 4)],
                    "label": [round(float(pts[:, 0].mean()), 3), round(float(pts[:, 1].mean()), 3)]})
    return out


def eez_lines() -> list:
    try:
        feats = json.loads(BOUNDARY_FILE.read_text())["features"]
    except (FileNotFoundError, ValueError):
        return []
    out = []
    for f in feats:
        g = f["geometry"]
        for line in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
            out.append({"t": f["properties"]["type"], "n": f["properties"]["name"],
                        "c": [[round(lat, 3), round(lon, 3)] for lon, lat in line]})
    return out


def ree_list() -> list:
    try:
        r = pd.read_csv(REE_FILE).fillna("")
    except FileNotFoundError:
        return []
    return [{"name": x["name"], "type": x["type"], "status": x["status"], "country": x["country"], "notes": x["notes"],
             "lat": float(x["lat"]), "lon": float(x["lon"])} for _, x in r.iterrows()]


# ============================================================ the blob
def _lib_rows(res: dict, lib: pd.DataFrame) -> dict:
    by_mmsi = {str(r["mmsi"]): r for _, r in lib.iterrows() if r.get("mmsi")}
    by_name = {str(r["name"]): r for _, r in lib.iterrows()}
    out = {}
    for _, v in res["vessels"].iterrows():
        row = by_mmsi.get(str(v.get("mmsi") or ""))
        out[(str(v["dataset"]), str(v["vessel"]))] = row if row is not None else by_name.get(str(v["dataset"]))
    return out


def _stats_cloud(tr: pd.DataFrame, start, end, lat, lon) -> dict:
    w = tr[(tr["time"] >= start) & (tr["time"] <= end)]
    if w.empty:
        return {"r50": 0.0, "onFrac": 1.0, "cells": 1, "cloud": [[round(lat, 2), round(lon, 2)]], "totalHours": 0.0}
    d = track_events.haversine_km(lat, lon, w["lat"].to_numpy(), w["lon"].to_numpy())
    cells = sorted({(round(a, 2), round(b, 2)) for a, b in zip(w["lat"], w["lon"])})
    return {"r50": round(float(np.median(d)), 3), "onFrac": round(float((d <= 3.5).mean()), 3), "cells": len(cells),
            "cloud": [list(c) for c in cells[:200]], "totalHours": round((w["time"].max() - w["time"].min()) / H, 1)}


def build_blob(res: dict, lib: pd.DataFrame, isa_features: list | None, station: dict | None = None,
               view: dict | None = None) -> dict:
    tracks = res.get("tracks", {})
    times = [t["time"].min() for t in tracks.values() if len(t)] + [t["time"].max() for t in tracks.values() if len(t)]
    t0 = min(times).floor("D") if times else pd.Timestamp.now(tz="UTC").floor("D")
    newest = max(times) if times else t0
    ports, ports_df = ports_list()
    lib_of = _lib_rows(res, lib)
    intel_r = res["intel"]
    isa = intel.isa_index(isa_features)
    info, gev = data.gfw_tables((data._stamp(data.GFW_INFO), data._stamp(data.GFW_EVENTS)))

    def port_index(lat, lon):
        return int(track_events.nearest_port([lat], [lon], ports_df.rename(columns={"port": "port"}))[0][0])

    # --- vessels -------------------------------------------------------------------------------
    vessels, vid = [], {}
    positions_raw = positions_kept = 0
    for (ds, vs), tr in tracks.items():
        row = lib_of.get((ds, vs))
        name = (row["name"] if row is not None else ds) or vs
        mmsi = str(row["mmsi"]) if row is not None and row.get("mmsi") else str(vs)
        country = (row["flag"] if row is not None else "") or "Unknown"
        cls, _ = geo_lookup.vessel_class(mmsi, row.get("ship_type", "") if row is not None else "")
        thinned = thin(tr)
        positions_raw += len(tr)
        positions_kept += len(thinned)
        sel = lambda df: df[(df["dataset"] == ds) & (df["vessel"] == vs)] if len(df) else df   # noqa: E731
        calls = [{"port": port_index(c["lat"], c["lon"]), "t0": hours(c["start"], t0), "t1": hours(c["end"], t0),
                  "arrObserved": True, "open": bool(c["open"])} for _, c in sel(intel_r["calls"]).iterrows()]
        gaps = [{"t0": hours(g["start"], t0), "t1": hours(g["end"], t0), "hours": float(g["hours"]), "km": float(g["km"]),
                 "kn": float(g["implied_kn"]), "a": [float(g["lat0"]), float(g["lon0"])], "b": [float(g["lat1"]), float(g["lon1"])]}
                for _, g in sel(intel_r["gaps"]).iterrows()]
        home_calls = [c for c in calls if ports[c["port"]]["cc"] == country]
        home = max(home_calls, key=lambda c: (c["t1"] or 0) - (c["t0"] or 0))["port"] if home_calls else None
        gi = info[info["mmsi"].astype(str) == mmsi] if len(info) else info
        ge = gev[gev["mmsi"].astype(str) == mmsi] if len(gev) else gev
        gfw = None
        if len(gi) or len(ge):
            g = gi.iloc[0] if len(gi) else {}
            evs = []
            for _, e in ge.iterrows():
                k = {"loitering": "L", "port_visit": "P", "gap": "G"}.get(str(e["kind"]), "E")
                if k == "L" and float(e.get("hours") or 0) < 6:
                    continue                                   # SeaTrace drops loitering under 6 h
                x = {"k": k, "t0": hours(e["start"], t0), "t1": hours(e["end"], t0), "lat": _r(e.get("lat")),
                     "lon": _r(e.get("lon")), "h": _r(e.get("hours"), 1)}
                if k == "P":
                    x.update({"port": e.get("port") or None, "pfl": None})
                elif k == "L":
                    x.update({"km": _r(e.get("km"), 2), "kn": _r(e.get("kn"), 3), "shoreKm": _r(e.get("shore_km"), 0),
                              "portKm": _r(e.get("port_km"), 0), "hs": int(e.get("high_seas") or 0)})
                elif k == "G":
                    x.update({"km": _r(e.get("km"), 1), "off": [_r(e.get("off_lat"), 5), _r(e.get("off_lon"), 5)],
                              "on": [_r(e.get("on_lat"), 5), _r(e.get("on_lon"), 5)], "intent": int(e.get("intent") or 0)})
                evs.append(x)
            gfw = {"ids": str(g.get("gfw_ids", "")).split() if len(gi) else [], "imo": str(g.get("imo", "") or row.get("imo", "") if row is not None else ""),
                   "owner": g.get("owner") or None if len(gi) else None, "ownerFlag": g.get("owner_flag") or None if len(gi) else None,
                   "type": str(g.get("vessel_type", "")).replace("_", " ").capitalize() if len(gi) else "",
                   "lengthM": _r(g.get("length_m"), 0) if len(gi) and str(g.get("length_m", "")) else None,
                   "gt": _r(g.get("gross_tonnage"), 0) if len(gi) and str(g.get("gross_tonnage", "")) else None,
                   "registry": bool(len(gi) and g.get("registry_source") == "GFW registry"),
                   "callsign": row.get("callsign", "") if row is not None else "", "events": evs}
        v_id = vessel_id(name)
        while v_id in {x["id"] for x in vessels}:
            v_id += "x"
        vid[(ds, vs)] = v_id
        vessels.append({"id": v_id, "name": name, "flag": ISO2.get(country, "XX"), "country": country,
                        "mmsi": int(mmsi) if mmsi.isdigit() else mmsi,
                        "imo": int(row["imo"]) if row is not None and str(row.get("imo", "")).isdigit() else None,
                        "callsign": row.get("callsign", "") if row is not None else "", "cls": cls,
                        "watch": bool(row is not None and row.get("mining")), "calls": calls, "gaps": gaps, "home": home,
                        "enc": encode_track(thinned, t0), "n_raw": len(tr), "gfw": gfw})

    # --- events ---------------------------------------------------------------------------------
    areas = res["areas"]
    lines = res["res"]["tables"].get("survey_lines", pd.DataFrame())
    block_sum = {}
    for m in res["res"].get("maps", {}).values():
        for b in m.get("blocks", []):
            block_sum[(str(m["dataset"]), str(m["vessel"]), int(b["block_id"]))] = b
    hulls = {(str(f["properties"]["dataset"]), str(f["properties"]["vessel"]), int(f["properties"]["area_id"])):
             f["geometry"]["coordinates"][0] for f in res["res"]["geojson"]["features"] if f["properties"]["layer"] == "survey_area"}
    hot = res.get("hotspots", pd.DataFrame())
    stations = intel_r["stations"]
    events = []
    for _, d in intel_r["detections"].iterrows():
        ds, vs = d["dataset"], d["vessel"]
        if (ds, vs) not in vid:
            continue
        lrow = lib_of.get((ds, vs))
        flag = lrow["flag"] if lrow is not None else ""
        lat, lon = float(d["lat"]), float(d["lon"])
        inside, km, near = intel.isa_at(lat, lon, isa)
        z = geo_lookup.eez_at(lat, lon)
        bd = geo_lookup.nearest_boundary(lat, lon)
        idx, pkm = track_events.nearest_port([lat], [lon], ports_df)
        foreign = ports_df[ports_df["country"] != flag]
        fidx, fkm = track_events.nearest_port([lat], [lon], foreign) if len(foreign) else ([None], [None])
        ev = {"id": d["id"], "vessel": vid[(ds, vs)], "t0": hours(d["start"], t0), "t1": hours(d["end"], t0),
              "center": [round(lat, 4), round(lon, 4)],
              "zone": inside["contract"] if inside else None,
              "nearZone": near["contract"] if near else None, "nearZoneKm": _r(km, 1) if km is not None else None,
              "nearestPort": {"port": int(idx[0]), "km": round(float(pkm[0]), 1)},
              "foreign": ({"port": int(foreign.index[fidx[0]]), "km": round(float(fkm[0]), 1),
                           "country": str(foreign.iloc[fidx[0]]["country"])} if fidx[0] is not None else None),
              "mntKm": round(float(track_events.haversine_km(lat, lon, *MINAMITORISHIMA)), 1),
              "eez": {"mrgid": z.get("mrgid"), "name": z["name"], "type": z["type"], "sov": list(z["sovereigns"])} if z else None,
              "depth": int(d["depth_m"]) if d["depth_m"] is not None and not pd.isna(d["depth_m"]) else None,
              "boundary": {k: (round(v, 1) if k == "km" else v) for k, v in bd.items()} if bd else None,
              "gfwMatch": None}
        if d["kind"] == "survey":
            a = areas[areas["number"] == d["area_number"]].iloc[0]
            key = (ds, vs, int(a["area_id"]))
            bl = [block_sum[(ds, vs, int(b))] for b in str(a.get("block_ids", "")).split()
                  if b.strip().isdigit() and (ds, vs, int(b)) in block_sum]
            best = max(bl, key=lambda b: b.get("score", 0)) if bl else {}
            ln = lines[(lines["dataset"].astype(str) == ds) & (lines["vessel"].astype(str) == vs)
                       & (lines["area_id"] == int(a["area_id"]))] if len(lines) else lines
            hid = -1
            for _, h in hot.iterrows() if len(hot) else []:
                if track_events.haversine_km(lat, lon, h["centroid_lat"], h["centroid_lon"]) < 50:
                    hid = int(h["hotspot_id"])
                    break
            mean = lambda k: _r(np.mean([b[k] for b in bl if pd.notna(b.get(k))]), 3) if bl else None   # noqa: E731
            ev.update({"model": "LAWNMOWER_SURVEY", "areaId": int(a["area_id"]),
                       "status": "active" if d["active"] else "completed",
                       "L": {"lines": [{"a": [_r(l["start_lat"]), _r(l["start_lon"])], "b": [_r(l["end_lat"]), _r(l["end_lon"])],
                                        "t0": hours(pd.to_datetime(l["start_time"], utc=True, errors="coerce"), t0),
                                        "t1": hours(pd.to_datetime(l["end_time"], utc=True, errors="coerce"), t0),
                                        "len": _r(l["length_km"], 2), "k": int(l["line_id"])} for _, l in ln.iterrows()],
                             "n": int(a["n_lines"]), "nFull": int(a["n_lines"]), "spacing": _r(a["median_spacing_km"]),
                             "spacingCV": _r(best.get("spacing_cv")), "dev": _r(best.get("mean_antiparallel_dev_deg"), 1),
                             "overlap": _r(best.get("mean_overlap_frac"), 2), "progression": _r(best.get("progression_frac"), 2),
                             "newTrack": mean("new_track_frac"), "coverage": mean("coverage_frac"),
                             "speed": _r(best.get("survey_speed_kn"), 1), "meanLen": mean("mean_line_km"),
                             "totalLen": _r(sum(b.get("total_line_km", 0) for b in bl), 1), "area": _r(a["area_km2"], 1),
                             "axis": _r(a.get("line_axis_deg"), 1), "axisCompass": str(a.get("line_axis_compass", "")),
                             "offshore": mean("offshore_km"), "blocks": len(bl), "score": _r(best.get("score"), 2),
                             "detConf": str(a.get("best_confidence", "")), "pattern": str(best.get("pattern", "")),
                             "hull": [[_r(p[1], 4), _r(p[0], 4)] for p in hulls.get(key, [])], "hotspot": hid}})
        else:
            s = stations[(stations["dataset"] == ds) & (stations["vessel"] == vs) & (stations["start"] == d["start"])].iloc[0]
            extra = _stats_cloud(tracks[(ds, vs)], s["start"], s["end"], s["lat"], s["lon"])
            gm = s.get("gfw")
            ev.update({"model": "STATIONKEEPING_OPERATION",
                       "S": {"center": [round(lat, 4), round(lon, 4)], "r95": _r(s["r95_km"]), "r50": extra["r50"],
                             "medSog": _r(s["median_kn"], 2), "onHours": _r(s["hours"], 1), "totalHours": extra["totalHours"],
                             "onFrac": extra["onFrac"], "net": _r(s["net_km"]), "cells": extra["cells"],
                             "portKm": _r(s["port_km"], 1), "cloud": extra["cloud"]},
                       "gfwMatch": ({"overlap": gm["overlap"], "km": gm["km"], "hours": gm["hours"], "distKm": gm["km"],
                                     "kn": None, "t0": ev["t0"], "t1": ev["t1"]} if isinstance(gm, dict) else None)})
        events.append(ev)

    # --- screened (patterns the detector rejected) ----------------------------------------------
    screened = []
    rej = res["res"]["tables"].get("rejected_blocks", pd.DataFrame())
    for _, r in rej.iterrows() if len(rej) else []:
        key = (str(r["dataset"]), str(r["vessel"]))
        if key in vid:
            screened.append({"vessel": vid[key], "t0": hours(pd.to_datetime(r.get("start_time"), utc=True, errors="coerce"), t0),
                             "t1": hours(pd.to_datetime(r.get("end_time"), utc=True, errors="coerce"), t0),
                             "reason": "Line pattern rejected by the survey detector: " + str(r.get("rejected_because", "")) + ".",
                             "center": [_r(r.get("centroid_lat"), 4), _r(r.get("centroid_lon"), 4)], "n": int(r.get("n_lines", 0))})

    hotspots = [{"id": int(h["hotspot_id"]), "vessels": h["vessels"], "n": int(h["n_vessels"]), "lat": float(h["centroid_lat"]),
                 "lon": float(h["centroid_lon"]), "together": bool(str(h.get("surveyed_together") or "")),
                 "maxAtOnce": int(h.get("max_vessels_at_once") or 1)} for _, h in hot.iterrows()] if len(hot) else []

    blob = {"eezLines": eez_lines(), "T0": t0.isoformat(), "AS_OF": round((newest - t0) / H, 1), "vessels": vessels,
            "events": events, "screened": screened, "ports": ports, "zones": zones_list(isa_features), "ree": ree_list(),
            "hotspots": hotspots, "meta": {"positions_raw": positions_raw, "positions_embedded": positions_kept},
            "gfwVal": gfw_validation(intel_r, gev, events, t0, newest), "extras": {}}
    return add_extras(blob, res, lib, station, vid, view)


def gfw_validation(intel_r: dict, gev: pd.DataFrame, events: list, t0, newest) -> dict:
    """Stations against GFW's independent loitering events (SeaTrace's gfwVal)."""
    st = [e for e in events if e["model"] == "STATIONKEEPING_OPERATION"]
    lo = gev[(gev["kind"] == "loitering")] if len(gev) else gev
    if len(lo):
        lo = lo[(lo["start"] >= t0) & (lo["end"] <= newest)]
    long_ = lo[(lo["hours"] >= 24) & (pd.to_numeric(lo.get("km"), errors="coerce").fillna(0) <= 10)] if len(lo) else lo
    det = intel_r["stations"]
    missed = []
    for _, e in long_.iterrows() if len(long_) else []:
        mine = det[det.get("vessel", pd.Series(dtype=str)).notna()] if len(det) else det
        hit = False
        for _, s in mine.iterrows() if len(mine) else []:
            if min(s["end"], e["end"]) > max(s["start"], e["start"]) and \
                    track_events.haversine_km(s["lat"], s["lon"], e["lat"], e["lon"]) <= 10:
                hit = True
                break
        if not hit:
            missed.append({"vessel": str(e["mmsi"]), "day": round((e["start"] - t0) / pd.Timedelta(days=1), 1),
                           "hours": round(float(e["hours"]), 1), "portKm": None, "km": _r(e.get("km"), 2)})
    drift = lo[(lo["hours"] >= 24) & (pd.to_numeric(lo.get("km"), errors="coerce") > 10)] if len(lo) else lo
    pulled = pd.Timestamp(data._stamp(data.GFW_EVENTS), unit="s").date().isoformat() if data._stamp(data.GFW_EVENTS) else None
    return {"sk": len(st), "skAgree": sum(1 for e in st if e["gfwMatch"]), "gfwLong": len(long_), "gfwMissed": len(missed),
            "gfwDrift": int(len(drift)), "gfwInSurvey": 0, "missed": missed,
            "ids": {"accepted": int(gev["mmsi"].nunique()) if len(gev) else 0, "untested": 0, "rejected": 0},
            "rejectedTrack": [], "pulled": pulled, "window": [t0.date().isoformat(), pd.Timestamp(newest).date().isoformat()],
            "groupIds": int(gev["mmsi"].nunique()) if len(gev) else 0, "rows": int(len(gev))}


def _clean(x):
    """Strict JSON for the browser: NaN, infinity, pd.NA and NaT become null; numpy numbers become Python's."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if x is pd.NA or x is pd.NaT or x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def to_json(blob: dict) -> str:
    """Compact, strict JSON safe inside <script type="application/json">."""
    # every "<" escaped: nothing in the data can end the <script> or start an HTML comment in it
    return json.dumps(_clean(blob), separators=(",", ":"), default=str, allow_nan=False).replace("<", "\\u003c")


# ============================================================ extras: reference case, watch items, regression
def _ms(t) -> int:
    return int(pd.Timestamp(t).timestamp() * 1000)


def reference_cases(vid_by_mmsi: dict, tracks_by_mmsi: dict, gev: pd.DataFrame) -> dict:
    """SeaTrace's REFERENCE: documented events per ship, plus GFW's own record of the operation they describe."""
    refs = data.reference_events()
    out = {}
    if not len(refs):
        return out
    for mmsi, rows in refs.groupby("mmsi"):
        vid_ = vid_by_mmsi.get(str(mmsi))
        if not vid_:
            continue
        dates = pd.to_datetime(rows["date"], utc=True)
        case = {"events": [{"t": _ms(d), "label": r["label"]} for d, (_, r) in zip(dates, rows.iterrows())],
                "notes": "Public reporting, as listed in reference_data/reference_events.csv; compare with the tracks.",
                "sources": [{"title": t, "url": u} for t, u in dict.fromkeys(zip(rows["source_title"], rows["source_url"]))]}
        ev = gev[gev["mmsi"].astype(str) == str(mmsi)] if len(gev) else gev
        lo = ev[(ev["kind"] == "loitering") & (ev["start"] <= dates.max() + pd.Timedelta(days=30))
                & (ev["end"] >= dates.min())] if len(ev) else ev
        if len(lo):
            s = lo.sort_values("hours", ascending=False).iloc[0]
            tr = tracks_by_mmsi.get(str(mmsi))
            w = tr[(tr["time"] >= s["start"]) & (tr["time"] <= s["end"])] if tr is not None else pd.DataFrame()
            bbox = ([float(w["lon"].min()), float(w["lat"].min()), float(w["lon"].max()), float(w["lat"].max())] if len(w)
                    else [float(s["lon"]) - 0.01, float(s["lat"]) - 0.01, float(s["lon"]) + 0.01, float(s["lat"]) + 0.01])
            near = ev[(ev["start"] >= s["start"] - pd.Timedelta(days=40)) & (ev["end"] <= s["end"] + pd.Timedelta(days=40))]
            case["gfw"] = {
                "source": f"Global Fishing Watch v3 events API for MMSI {mmsi} (gfw_fetch.py --enrich); position from the loitering event",
                "events": [{"t0": _ms(e["start"]), "t1": _ms(e["end"]),
                            "kind": {"loitering": "Loitering", "port_visit": "Port visit", "gap": "AIS gap"}.get(e["kind"], e["kind"]),
                            "label": (e["port"] or "port visit") if e["kind"] == "port_visit"
                            else f"{e['hours']:.0f} h" + (f", {e['km']:.2f} km total movement" if pd.notna(e.get("km")) else "")}
                           for _, e in near.sort_values("start").iterrows()],
                "site": {"lat": float(s["lat"]), "lon": float(s["lon"]), "depth": geo_lookup.depth_m(s["lat"], s["lon"]),
                         "mntKm": round(float(track_events.haversine_km(s["lat"], s["lon"], *MINAMITORISHIMA))),
                         "t0": _ms(s["start"]), "t1": _ms(s["end"]), "km": _r(s.get("km"), 2) or 0.0,
                         "kn": _r(s.get("kn"), 3) or 0.0, "bbox": bbox}}
        out[vid_] = case
    return out


def watch_items(vid_by_mmsi: dict) -> list:
    w = data.watch_items()
    return [{"id": r["id"], "vessel": vid_by_mmsi[str(r["mmsi"])], "title": r["title"], "window": r["window"],
             "basis": r["basis"], "expect": r["expect"]} for _, r in w.iterrows() if str(r["mmsi"]) in vid_by_mmsi]


_REGRESSION_CACHE: dict = {}
REGRESSION_FILE = data.HERE / "benchmarks" / "regression_results.json"


def _bench_files() -> list:
    bench = data.HERE / "benchmarks"
    return sorted(p for p in bench.glob("*.csv") if not p.stem.endswith("_labels") and (bench / f"{p.stem}_labels.csv").exists())


def regression_stamp() -> str:
    """Fingerprint of everything the regression table depends on: detector code, models, benchmarks."""
    import hashlib
    h = hashlib.sha256()
    files = [data.HERE / "survey_pattern_detector.py"] + sorted((data.HERE / "models").glob("*.py"))
    for f in _bench_files():
        files += [f, f.with_name(f"{f.stem}_labels.csv")]
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def compute_regression() -> dict:
    """Run the default model on the labelled benchmarks (slow, memory-heavy: done offline, see scripts/)."""
    import gc
    files = _bench_files()
    rows, s = [], {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for f in files:
        lab = pd.read_csv(f.with_name(f"{f.stem}_labels.csv"), dtype={"vessel": str})
        r = data._run_analysis(((f.stem, ((f.name, f.read_bytes()),)),), data.default_settings(), ())
        V = r["tables"]["vessels"]
        found = dict(zip(V["vessel"].astype(str), V["survey_status"] != "No survey pattern"))
        A = r["tables"]["survey_areas"]
        n_areas = A["vessel"].astype(str).value_counts().to_dict() if len(A) else {}
        del r
        gc.collect()
        for _, l in lab.iterrows():
            v, truth = str(l["vessel"]), int(l["is_survey"])
            got = bool(found.get(v, False))
            s[("tp" if got else "fn") if truth else ("fp" if got else "tn")] += 1
            rows.append([v, "Survey" if truth else "Not a survey", "Survey" if truth else "No survey",
                         f"Survey ({n_areas.get(v, 0)} area{'s' if n_areas.get(v, 0) != 1 else ''})" if got else "No survey",
                         got == bool(truth)])
    return {"source": "benchmarks/*.csv with their _labels.csv files (benchmarks/make_demo_datasets.py), default model",
            "rows": rows, "survey": s, "fixed": True,
            "note": f"Default detection model on {len(files)} labelled benchmark files ({len(rows)} ships): "
                    f"{s['tp']} of {s['tp'] + s['fn']} surveys found, {s['fp']} false alarm{'s' if s['fp'] != 1 else ''}. "
                    "Compare other models under Analyst ▸ Compare models.",
            "stamp": regression_stamp()}


def regression() -> dict:
    """SeaTrace's REGRESSION table, read from benchmarks/regression_results.json (built by scripts/build_regression.py)."""
    if "table" not in _REGRESSION_CACHE:
        try:
            _REGRESSION_CACHE["table"] = json.loads(REGRESSION_FILE.read_text())
        except (FileNotFoundError, ValueError):
            _REGRESSION_CACHE["table"] = {"source": "not built yet: python scripts/build_regression.py", "rows": [],
                                          "survey": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}, "fixed": True,
                                          "note": "The benchmark results have not been built yet."}
    return _REGRESSION_CACHE["table"]


def header_text(blob: dict) -> tuple[str, str]:
    """(banner, subtitle) for the console header, HTML-escaped, from the data window."""
    import html as _html
    t0 = pd.Timestamp(blob["T0"])
    t1 = t0 + pd.Timedelta(hours=blob["AS_OF"])
    when = f"{t0:%-d %b} – {t1:%-d %b %Y}"
    banner = (f"Unclassified · real AIS: Global Fishing Watch, {when} · GFW events & registry, last 12 months · "
              + ("ISA contract areas (live)" if blob.get("zones") else "ISA contract areas unavailable") +
              " · Marine Regions EEZs · updated weekly · research prototype")
    return _html.escape(banner), _html.escape("Deep-sea mineral activity intelligence · Survey Detector")


PORT_CAT = {"flag-state port": "home", "flag-state rare-earth linked port": "home-ree"}


def survey_detector_extras(blob: dict, res: dict, lib: pd.DataFrame, vid: dict, view: dict | None) -> dict:
    """What the Survey Detector adds to SeaTrace: ports and routes, likely target, predictions, resource
    regions, watchlist ships without data, the group / season selector, and analysis vessel ids."""
    import resource_context
    det = res["intel"]["detections"]
    areas = res["areas"]
    P = res.get("ports", pd.DataFrame())
    feats = res["res"]["geojson"]["features"]
    ports, routes, target = {}, {}, {}
    for _, d in det.iterrows():
        if (d["dataset"], d["vessel"]) not in vid:
            continue
        ship = lib[lib["mmsi"].astype(str) == str(d["mmsi"])]
        stype = ship["ship_type"].iloc[0] if len(ship) else ""
        tg = resource_context.describe(float(d["lat"]), float(d["lon"]), d["name"], stype)
        target[d["id"]] = {"likely": tg["likely_target"], "basis": tg["target_basis"], "region": tg["target_region"],
                           "alternatives": tg["target_alternatives"]}
        if d["kind"] != "survey" or not len(P):
            continue
        a = areas[areas["number"] == d["area_number"]]
        if not len(a):
            continue
        area_id = int(a.iloc[0]["area_id"])
        mine = P[(P["dataset"] == d["dataset"]) & (P["vessel"] == d["vessel"]) & (P["area_id"] == area_id)]
        def item(r):
            cat = "ree" if r["ree_link"] else PORT_CAT.get(r["category"], "near")
            return {"name": r["port"], "country": r["country"], "km": _r(r["sea_km"], 0), "h": _r(r["hours_at_10kn"], 0),
                    "cat": cat, "basis": r["distance_basis"], "link": r["ree_link"] or None, "site": r["ree_site"] or None}
        rows = [item(r) for _, r in mine.sort_values("sea_km").iterrows()]
        ports[d["id"]] = {"home": [x for x in rows if x["cat"].startswith("home")][:3],
                          "ree": [x for x in rows if x["cat"] == "ree" or x["link"]][:3],
                          "near": [x for x in rows if x["cat"] == "near"][:3]}
        rr = []
        for f in feats:
            q = f["properties"]
            if q.get("layer") == "port_route" and str(q.get("dataset")) == d["dataset"] and str(q.get("vessel")) == d["vessel"] \
                    and q.get("area_id") == area_id:
                g = f["geometry"]
                lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
                for line in lines:
                    rr.append({"cat": "ree" if q.get("ree_link") else PORT_CAT.get(q.get("category"), "near"),
                               "port": q.get("port"), "km": q.get("sea_km"), "c": [[round(lat, 3), round(lon, 3)] for lon, lat in line]})
        if rr:
            routes[d["id"]] = rr
    pred = []
    for f in feats:
        q = f["properties"]
        if q.get("layer") == "predicted_line" and (str(q.get("dataset")), str(q.get("vessel"))) in vid:
            g = f["geometry"]
            pred.append({"vessel": vid[(str(q["dataset"]), str(q["vessel"]))],
                         "c": [[round(lat, 4), round(lon, 4)] for lon, lat in g["coordinates"]]})
    regs = resource_context.regions()
    regions = [{"name": r["name"], "category": r["category"], "commodities": r["commodities"], "depth": r["depth"],
                "box": [float(r["min_lat"]), float(r["min_lon"]), float(r["max_lat"]), float(r["max_lon"])],
                "color": resource_context.CATEGORY_COLORS.get(r["category"], "#a1b5c3")} for _, r in regs.iterrows()] if len(regs) else []
    tracked = {str(v["mmsi"]) for v in blob["vessels"]}
    no_data = lib[(~lib["has_data"]) & ~lib["ship_type"].str.lower().str.startswith("demo")] if len(lib) else lib
    watch = [{"name": r["name"], "country": r["flag"], "mmsi": r["mmsi"], "type": r["ship_type"], "mining": bool(r["mining"])}
             for _, r in no_data.iterrows() if str(r["mmsi"]) not in tracked]
    v = view or {}
    return {"ports": ports, "routes": routes, "target": target, "pred": pred, "regions": regions, "watchNoData": watch,
            "view": {"group": v.get("group", "mining"), "time": v.get("time", "6m"),
                     "groups": data.GROUPS, "windows": {k: lab for k, (lab, _) in data.WINDOWS.items()}},
            "analysisVessel": {vid_: str(vs) for (ds, vs), vid_ in vid.items()}}


def add_extras(blob: dict, res: dict, lib: pd.DataFrame, station: dict | None = None,
               vid: dict | None = None, view: dict | None = None) -> dict:
    vid_by_mmsi = {str(v["mmsi"]): v["id"] for v in blob["vessels"]}
    lib_of = _lib_rows(res, lib)
    tracks_by_mmsi = {str(lib_of[k]["mmsi"]): tr for k, tr in res.get("tracks", {}).items() if lib_of.get(k) is not None}
    _, gev = data.gfw_tables((data._stamp(data.GFW_INFO), data._stamp(data.GFW_EVENTS)))
    blob["extras"].update({"reference": reference_cases(vid_by_mmsi, tracks_by_mmsi, gev),
                           "watch": watch_items(vid_by_mmsi), "regression": regression(),
                           "stationCfg": station or data.default_station_settings()})
    if vid is not None:
        blob["extras"].update(survey_detector_extras(blob, res, lib, vid, view))
    return blob
