"""
Stationkeeping detector: a ship holding one spot at sea for a day or more, away from ports and over
deep water. That is what seabed sampling, drilling and mining tests look like in AIS (Chikyu's 2026
rare-earth mud test sat within 7 km for 22 days), where a survey's lawnmower lines are absent.

Pure pandas/numpy, no Streamlit. Tracks are survey_pattern_detector.standardize() output.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import track_events

STATION_COLS = ["start", "end", "hours", "r95_km", "median_kn", "net_km", "lat", "lon", "port_km", "depth_m"]


@dataclass
class StationConfig:
    min_hours: float = 24.0        # on station at least this long
    r95_km: float = 3.5            # 95% of positions within this of the station's centre
    max_median_kn: float = 1.2     # median speed on station
    min_port_km: float = 25.0      # further than this from the nearest port (else: in port / anchorage)
    min_depth_m: float = 200.0     # water at least this deep (else: anchored on the shelf)
    merge_gap_hours: float = 12.0  # stays this close in time (and place) count as one


STATION_HELP = {
    "min_hours": "Shortest time on one spot that counts as working on station (hours).",
    "r95_km": "95% of positions must lie within this distance of the station's centre (km).",
    "max_median_kn": "Median speed on station must be this slow or slower (knots).",
    "min_port_km": "Stations closer than this to a port are port or anchorage stays (km).",
    "min_depth_m": "Stations in shallower water than this are anchoring on the shelf (m).",
    "merge_gap_hours": "Two stays this close in time, at the same spot, become one station (hours).",
}


def _centre(lat, lon):
    """Median position; longitudes unwrapped around the first fix, so a spot on the 180° line works."""
    lon = np.asarray(lon, float)
    if not len(lon):
        return float("nan"), float("nan")
    rel = ((lon - lon[0] + 180) % 360) - 180
    c = lon[0] + float(np.median(rel))
    return float(np.median(lat)), ((c + 180) % 360) - 180


def _stays(t: pd.DataFrame, cfg: StationConfig) -> list[tuple[int, int]]:
    """Greedy runs of slow positions that stay near their own running centre."""
    lat, lon = t["lat"].to_numpy(), t["lon"].to_numpy()
    slow = (t["speed_kn"].fillna(0).to_numpy() <= 2 * cfg.max_median_kn)
    runs, i, n = [], 0, len(t)
    while i < n:
        if not slow[i]:
            i += 1
            continue
        j, c = i, (lat[i], lon[i])
        while j + 1 < n and slow[j + 1]:
            if j - i < 6 or (j - i) % 12 == 0:      # the running centre, refreshed every 12 positions
                c = _centre(lat[i:j + 1], lon[i:j + 1])
            if track_events.haversine_km(c[0], c[1], lat[j + 1], lon[j + 1]) > 2 * cfg.r95_km:
                break
            j += 1
        runs.append((i, j))
        i = j + 1
    return runs


def detect_stations(track: pd.DataFrame, ports: pd.DataFrame, cfg: StationConfig = StationConfig(),
                    depth=None) -> pd.DataFrame:
    """Station events in a track. depth(lat, lon) -> metres (negative below sea level)."""
    if depth is None:
        import geo_lookup
        depth = geo_lookup.depth_m
    t = track.dropna(subset=["time", "lat", "lon"]).sort_values("time").reset_index(drop=True)
    if len(t) < 2:
        return pd.DataFrame(columns=STATION_COLS)
    if "speed_kn" not in t:
        t["speed_kn"] = np.nan

    # merge stays close in time and place, then judge each merged stay
    merged: list[list[int]] = []
    for a, b in _stays(t, cfg):
        if merged:
            pa, pb = merged[-1]
            gap_h = (t["time"].iloc[a] - t["time"].iloc[pb]).total_seconds() / 3600
            c0 = _centre(t["lat"].iloc[pa:pb + 1], t["lon"].iloc[pa:pb + 1])
            c1 = _centre(t["lat"].iloc[a:b + 1], t["lon"].iloc[a:b + 1])
            if gap_h <= cfg.merge_gap_hours and track_events.haversine_km(*c0, *c1) <= cfg.r95_km:
                merged[-1][1] = b
                continue
        merged.append([a, b])

    rows = []
    for a, b in merged:
        w = t.iloc[a:b + 1]
        hours = (w["time"].iloc[-1] - w["time"].iloc[0]).total_seconds() / 3600
        if hours < cfg.min_hours:
            continue
        clat, clon = _centre(w["lat"], w["lon"])
        dist = track_events.haversine_km(clat, clon, w["lat"].to_numpy(), w["lon"].to_numpy())
        r95 = float(np.percentile(dist, 95))
        med = float(np.nanmedian(w["speed_kn"])) if w["speed_kn"].notna().any() else 0.0
        if r95 > cfg.r95_km or med > cfg.max_median_kn:
            continue
        port_km = float(track_events.nearest_port([clat], [clon], ports)[1][0]) if ports is not None and len(ports) else np.inf
        if port_km <= cfg.min_port_km:
            continue
        dep = depth(clat, clon)
        if dep is not None and -dep < cfg.min_depth_m:
            continue
        net = float(track_events.haversine_km(w["lat"].iloc[0], w["lon"].iloc[0], w["lat"].iloc[-1], w["lon"].iloc[-1]))
        rows.append({"start": w["time"].iloc[0], "end": w["time"].iloc[-1], "hours": round(hours, 1),
                     "r95_km": round(r95, 2), "median_kn": round(med, 2), "net_km": round(net, 2),
                     "lat": clat, "lon": clon, "port_km": round(port_km, 1), "depth_m": dep})
    return pd.DataFrame(rows, columns=STATION_COLS)


def match_loitering(stations: pd.DataFrame, gfw_events: pd.DataFrame, max_km: float = 10.0) -> pd.Series:
    """
    For each station, the GFW loitering event that overlaps it in time within max_km
    ({"hours", "overlap" (share of the station covered), "km"}), or None.
    """
    out = []
    loiter = (gfw_events[gfw_events["kind"].astype(str).str.contains("loiter", case=False)]
              if gfw_events is not None and len(gfw_events) and "kind" in gfw_events else pd.DataFrame())
    for _, s in stations.iterrows():
        best = None
        dur = max((s["end"] - s["start"]).total_seconds(), 1.0)
        for _, e in loiter.iterrows():
            ov = (min(s["end"], e["end"]) - max(s["start"], e["start"])).total_seconds()
            if ov <= 0:
                continue
            km = float(track_events.haversine_km(s["lat"], s["lon"], e["lat"], e["lon"]))
            if km > max_km:
                continue
            cand = {"hours": float(e["hours"]), "overlap": round(min(1.0, ov / dur), 3), "km": round(km, 2)}
            if best is None or cand["overlap"] > best["overlap"]:
                best = cand
        out.append(best)
    return pd.Series(out, index=stations.index, dtype=object)
