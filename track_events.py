"""
What a ship did between surveys, from its (hourly) track: port calls, voyages between them,
AIS gaps (dark periods) and its status at the last position. Pure pandas, no Streamlit.

A track is a DataFrame with time (UTC timestamps), lat, lon and speed_kn, as
survey_pattern_detector.standardize() produces it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_KM = 6371.0088
CALL_MIN_HOURS = 6.0       # stopped at least this long ...
CALL_MAX_KN = 1.0          # ... at this speed or slower ...
CALL_PORT_KM = 5.0         # ... this close to a port
GAP_HOURS = 12.0           # positions further apart than this = AIS gap
UNDERWAY_KN = 3.0
STALE_DAYS = 3.0

CALL_COLS = ["port", "country", "lat", "lon", "start", "end", "hours", "open"]
VOYAGE_COLS = ["from_port", "to_port", "start", "end", "days", "same_port", "at_sea"]
GAP_COLS = ["start", "end", "hours", "km", "implied_kn", "lat0", "lon0", "lat1", "lon1"]


def _xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(np.asarray(lon2, float) - np.asarray(lon1, float))
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return EARTH_KM * 2 * np.arcsin(np.minimum(1, np.sqrt(a)))


def nearest_port(lat, lon, ports: pd.DataFrame):
    """(index into ports, distance km) for each point."""
    tree = cKDTree(_xyz(ports["lat"], ports["lon"]))
    chord, idx = tree.query(_xyz(lat, lon))
    return idx, 2 * EARTH_KM * np.arcsin(np.minimum(1, np.asarray(chord) / 2))


def _clean(track: pd.DataFrame) -> pd.DataFrame:
    t = track.dropna(subset=["time", "lat", "lon"]).sort_values("time").reset_index(drop=True)
    if "speed_kn" not in t:
        t["speed_kn"] = np.nan
    return t


def port_calls(track: pd.DataFrame, ports: pd.DataFrame) -> pd.DataFrame:
    """Stays of >= 6 h at <= 1 kn within 5 km of a port. open = still there at the last fix."""
    t = _clean(track)
    if t.empty or ports is None or not len(ports):
        return pd.DataFrame(columns=CALL_COLS)
    idx, km = nearest_port(t["lat"], t["lon"], ports)
    stopped = (t["speed_kn"].fillna(0) <= CALL_MAX_KN).to_numpy() & (km <= CALL_PORT_KM)
    calls, i, n = [], 0, len(t)
    while i < n:
        if not stopped[i]:
            i += 1
            continue
        j, port = i, idx[i]
        while j + 1 < n and stopped[j + 1] and idx[j + 1] == port:
            j += 1
        hours = (t["time"].iloc[j] - t["time"].iloc[i]).total_seconds() / 3600
        if hours >= CALL_MIN_HOURS:
            p = ports.iloc[port]
            calls.append({"port": p["port"], "country": p.get("country", ""), "lat": float(p["lat"]),
                          "lon": float(p["lon"]), "start": t["time"].iloc[i], "end": t["time"].iloc[j],
                          "hours": round(hours, 1), "open": j == n - 1})
        i = j + 1
    return pd.DataFrame(calls, columns=CALL_COLS)


def voyages(calls: pd.DataFrame, track_end) -> pd.DataFrame:
    """Port-to-port legs; a last leg still at sea when the track ends has to_port None."""
    rows = []
    if calls is None or calls.empty:
        return pd.DataFrame(columns=VOYAGE_COLS)
    c = calls.sort_values("start").reset_index(drop=True)
    for a, b in zip(c.iloc[:-1].itertuples(), c.iloc[1:].itertuples()):
        rows.append({"from_port": a.port, "to_port": b.port, "start": a.end, "end": b.start,
                     "same_port": a.port == b.port, "at_sea": False})
    last = c.iloc[-1]
    if not last["open"] and track_end is not None and pd.Timestamp(track_end) > last["end"]:
        rows.append({"from_port": last["port"], "to_port": None, "start": last["end"],
                     "end": pd.Timestamp(track_end), "same_port": False, "at_sea": True})
    v = pd.DataFrame(rows, columns=VOYAGE_COLS)
    if len(v):
        v["days"] = (v["end"] - v["start"]).dt.total_seconds() / 86400
    return v


def ais_gaps(track: pd.DataFrame, min_hours: float = GAP_HOURS, ports: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Consecutive positions more than min_hours apart (the ship went dark, or out of coverage).
    With ports: holes that start and end at the same port are port stays, not gaps.
    """
    t = _clean(track)
    if len(t) < 2:
        return pd.DataFrame(columns=GAP_COLS)
    dh = t["time"].diff().dt.total_seconds().div(3600).to_numpy()
    at_port = None
    if ports is not None and len(ports):
        idx, km = nearest_port(t["lat"], t["lon"], ports)
        at_port = np.where(km <= CALL_PORT_KM, idx, -1)
    rows = []
    for k in np.nonzero(dh > min_hours)[0]:
        if at_port is not None and at_port[k - 1] >= 0 and at_port[k - 1] == at_port[k]:
            continue                                   # in port the whole time
        a, b = t.iloc[k - 1], t.iloc[k]
        km = float(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]))
        rows.append({"start": a["time"], "end": b["time"], "hours": round(float(dh[k]), 1), "km": round(km, 1),
                     "implied_kn": round(km / 1.852 / dh[k], 1), "lat0": a["lat"], "lon0": a["lon"],
                     "lat1": b["lat"], "lon1": b["lon"]})
    return pd.DataFrame(rows, columns=GAP_COLS)


def ship_status(track: pd.DataFrame, calls: pd.DataFrame, active_kinds: set, newest_time) -> tuple[str, bool]:
    """
    (status, stale): SURVEYING / ON STATION while a detection is active, IN PORT during an open port
    call, UNDERWAY above 3 kn, else SLOW / STOPPED. stale = last fix over 3 days before newest_time.
    """
    t = _clean(track)
    last = t.iloc[-1] if len(t) else None
    stale = bool(last is not None and newest_time is not None
                 and (pd.Timestamp(newest_time) - last["time"]).total_seconds() > STALE_DAYS * 86400)
    if "survey" in active_kinds:
        return "SURVEYING", stale
    if "station" in active_kinds:
        return "ON STATION", stale
    if calls is not None and len(calls) and bool(calls.iloc[-1]["open"]):
        return "IN PORT", stale
    if last is not None and float(last["speed_kn"] or 0) > UNDERWAY_KN:
        return "UNDERWAY", stale
    return "SLOW / STOPPED", stale
