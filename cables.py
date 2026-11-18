"""
Submarine cables and the cable watch.

Data: TeleGeography's public Submarine Cable Map, fetched once by scripts/fetch_cables.py into
reference_data/ (routes are schematic, good to a few km). Everything here runs at console-data build time.

    near_cable(lat, lon)        cables within CABLE_KM of a point, nearest first
    watch(track, avoid)         slow / stopped / dark episodes of one ship on a cable, away from ports
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REF = Path(__file__).resolve().parent / "reference_data"
CABLES_FILE = REF / "submarine_cables.geojson"
LANDINGS_FILE = REF / "cable_landings.csv"
CLASSES_FILE = REF / "vessel_classes.csv"
EARTH_KM = 6371.0088

CABLE_KM = 5.0       # a fix this close to a cable route is on the cable (routes are schematic)
PORT_KM = 10.0       # ...unless it is this close to a port or cable landing (cables land there)
SLOW_KN = 3.0        # on-cable fixes slower than this count towards an episode
STOPPED_KN = 0.5     # episode median speed under this: "stopped"
MERGE_H = 2.0        # slow runs separated by less than this are one episode
MIN_H = 2.0          # an episode lasts at least this (with hourly fixes: 3 in a row)
DARK_H = 6.0         # an AIS gap this long starting or ending on a cable is a "dark" episode
MAX_LISTED = 3       # cables named per point
STEP_KM = 1.0        # route points are densified to this spacing


def _xyz(lat, lon):
    lat, lon = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def _chord(km: float) -> float:
    return 2 * np.sin(min(km / EARTH_KM, np.pi) / 2)


def _seg_km(a, b) -> float:
    return float(2 * EARTH_KM * np.arcsin(min(1.0, np.linalg.norm(_xyz(*a) - _xyz(*b)) / 2)))


@lru_cache(maxsize=1)
def load_cables() -> list:
    """[{id, name, owners, length_km, rfs_year, planned, landings: [{name, country}], lines: [[[lat, lon]...]...]}]"""
    if not CABLES_FILE.exists():
        return []
    out = []
    for f in json.loads(CABLES_FILE.read_text())["features"]:
        p = f["properties"]
        lines = [[[pt[1], pt[0]] for pt in line] for line in f["geometry"]["coordinates"] if len(line) > 1]
        if lines:
            out.append({"id": p["id"], "name": p.get("name") or p["id"], "owners": p.get("owners") or "",
                        "length_km": p.get("length_km"), "rfs_year": p.get("rfs_year"),
                        "planned": bool(p.get("planned")), "landings": p.get("landings") or [], "lines": lines})
    return out


def _densify(line: list) -> np.ndarray:
    pts = [line[0]]
    for a, b in zip(line, line[1:]):
        dlon = (b[1] - a[1] + 180) % 360 - 180               # the short way round, also across ±180
        n = max(1, int(np.ceil(_seg_km(a, [b[0], a[1] + dlon]) / STEP_KM)))
        t = np.arange(1, n + 1) / n
        pts.extend(zip(a[0] + t * (b[0] - a[0]), (a[1] + t * dlon + 180) % 360 - 180))
    return np.asarray(pts, float)


@lru_cache(maxsize=1)
def _index():
    """KD-tree over densified points of every built (not planned) cable, and the cable each point belongs to."""
    cs = load_cables()
    pts, owner = [], []
    for i, c in enumerate(cs):
        if c["planned"]:
            continue
        for line in c["lines"]:
            d = _densify(line)
            pts.append(d)
            owner.append(np.full(len(d), i))
    if not pts:
        return None
    pts = np.vstack(pts)
    return cKDTree(_xyz(pts[:, 0], pts[:, 1])), np.concatenate(owner), cs


def _near_many(lat, lon, km: float) -> list:
    """near_cable for many points at once."""
    idx = _index()
    lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
    if idx is None:
        return [[] for _ in lat]
    tree, owner, cs = idx
    q = _xyz(lat, lon)
    out = []
    for p, hits in zip(q, tree.query_ball_point(q, _chord(km))):
        if not hits:
            out.append([])
            continue
        hits = np.asarray(hits)
        d = 2 * EARTH_KM * np.arcsin(np.clip(np.linalg.norm(tree.data[hits] - p, axis=1) / 2, 0, 1))
        best = {}
        for o, k in zip(owner[hits], d):
            if o not in best or k < best[o]:
                best[o] = k
        out.append([{"id": cs[o]["id"], "name": cs[o]["name"], "km": round(float(k), 2)}
                    for o, k in sorted(best.items(), key=lambda x: x[1])[:MAX_LISTED]])
    return out


def near_cable(lat: float, lon: float, km: float = CABLE_KM) -> list:
    """Built cables within km of the point, nearest first, at most 3: [{id, name, km}]."""
    return _near_many([lat], [lon], km)[0]


@lru_cache(maxsize=1)
def landing_points() -> np.ndarray:
    """Cable landing points, shape (n, 2) lat/lon (empty without the file)."""
    if not LANDINGS_FILE.exists():
        return np.empty((0, 2))
    d = pd.read_csv(LANDINGS_FILE).dropna(subset=["lat", "lon"])
    return d[["lat", "lon"]].to_numpy(float)
