"""
Where is a point? Exclusive Economic Zone (and whose), distance to the nearest boundary between two
states' zones, seabed depth, and what kind of ship an MMSI is. Used by intel.py's priority scores.

Data (reference_data/, built by scripts/build_reference.py):
  eez_v12_simplified.geojson, eez_boundaries.geojson   Marine Regions World EEZ v12, CC BY 4.0
  depth_etopo2022_5min.npz                             NOAA ETOPO 2022 (public domain), 5' grid
  vessel_classes.csv                                   hand-checked ship classes, with sources
No Streamlit here: pure functions, cached in memory after the first call.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from scipy.spatial import cKDTree

REF = Path(__file__).resolve().parent / "reference_data"
EEZ_FILE = REF / "eez_v12_simplified.geojson"
BOUNDARY_FILE = REF / "eez_boundaries.geojson"
DEPTH_FILE = REF / "depth_etopo2022_5min.npz"
CLASS_FILE = REF / "vessel_classes.csv"
EARTH_KM = 6371.0088

# priority order when zones overlap: the more specific regime wins
_TYPE_RANK = {"Joint regime": 0, "Overlapping claim": 1, "200NM": 2}


def _wrap(lon: float) -> float:
    """Longitude in [-180, 180)."""
    return ((float(lon) + 180.0) % 360.0) - 180.0


def _parts(geom: dict):
    """Polygon / MultiPolygon -> list of (exterior Path, [hole Paths])."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    out = []
    for rings in polys:
        ext = np.asarray(rings[0], float)
        out.append((MplPath(ext), [MplPath(np.asarray(h, float)) for h in rings[1:]],
                    (ext[:, 0].min(), ext[:, 1].min(), ext[:, 0].max(), ext[:, 1].max())))
    return out


@lru_cache(maxsize=1)
def _eez() -> list:
    if not EEZ_FILE.exists():
        return []
    zones = []
    for f in json.loads(EEZ_FILE.read_text())["features"]:
        p = f["properties"]
        zones.append(({"name": p["name"], "sovereigns": tuple(p.get("sovereigns") or ()),
                       "type": p.get("type") or "200NM", "mrgid": p.get("mrgid")}, _parts(f["geometry"])))
    return zones


def _inside(path: MplPath, pt) -> bool:
    # edges count as inside: test with a hair of tolerance either way (ring orientation varies)
    return path.contains_point(pt, radius=1e-9) or path.contains_point(pt, radius=-1e-9)


def eez_at(lat: float, lon: float) -> dict | None:
    """The EEZ containing the point: {"name", "sovereigns", "type"}, or None on the high seas."""
    pt = (_wrap(lon), float(lat))
    found = []
    for info, parts in _eez():
        for ext, holes, (x0, y0, x1, y1) in parts:
            if not (x0 - 1e-6 <= pt[0] <= x1 + 1e-6 and y0 - 1e-6 <= pt[1] <= y1 + 1e-6):
                continue
            if _inside(ext, pt) and not any(h.contains_point(pt) for h in holes):
                found.append((_TYPE_RANK.get(info["type"], 3), (x1 - x0) * (y1 - y0), info))
                break
    if not found:
        return None
    # the more specific regime wins, then the smaller zone (an enclave inside a bigger zone)
    return dict(sorted(found, key=lambda f: (f[0], f[1]))[0][2])


def _xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


@lru_cache(maxsize=1)
def _boundaries():
    if not BOUNDARY_FILE.exists():
        return None
    pts, names = [], []
    for i, f in enumerate(json.loads(BOUNDARY_FILE.read_text())["features"]):
        geom = f["geometry"]
        lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for line in lines:
            a = np.asarray(line, float)
            for (x0, y0), (x1, y1) in zip(a[:-1], a[1:]):
                dx = ((x1 - x0 + 180) % 360) - 180          # the short way round
                n = max(1, int(np.hypot(dx, y1 - y0) / 0.05))   # a point every ~5 km
                t = np.linspace(0, 1, n, endpoint=False)
                pts.append(np.column_stack([y0 + (y1 - y0) * t, x0 + dx * t]))
                names.extend([i] * n)
            pts.append(a[-1:, ::-1])
            names.append(i)
    if not pts:
        return None
    ll = np.vstack(pts)
    labels = [f["properties"] for f in json.loads(BOUNDARY_FILE.read_text())["features"]]
    return cKDTree(_xyz(ll[:, 0], ll[:, 1])), np.asarray(names), labels


def nearest_boundary_km(lat: float, lon: float) -> tuple[float, str] | None:
    """Distance (km) to the nearest line between two states' zones, and that line's name."""
    b = _boundaries()
    if b is None:
        return None
    tree, idx, labels = b
    chord, i = tree.query(_xyz(np.array([lat]), np.array([lon]))[0])
    return float(2 * EARTH_KM * np.arcsin(min(1.0, chord / 2))), labels[idx[i]]["name"]


def nearest_boundary(lat: float, lon: float) -> dict | None:
    """The nearest line between two states' zones: {"km", "name", "type", "sov"}."""
    b = _boundaries()
    if b is None:
        return None
    tree, idx, labels = b
    chord, i = tree.query(_xyz(np.array([lat]), np.array([lon]))[0])
    p = labels[idx[i]]
    return {"km": float(2 * EARTH_KM * np.arcsin(min(1.0, chord / 2))), "name": p["name"], "type": p["type"],
            "sov": list(p.get("sovereigns") or [])}


@lru_cache(maxsize=1)
def _depth():
    if not DEPTH_FILE.exists():
        return None
    d = np.load(DEPTH_FILE)
    return d["z"], d["lat"].astype(float), d["lon"].astype(float)


def _nearest(axis: np.ndarray, x: float) -> int:
    i = int(np.clip(np.searchsorted(axis, x), 1, len(axis) - 1))
    return i if abs(axis[i] - x) < abs(axis[i - 1] - x) else i - 1


def depth_m(lat: float, lon: float) -> float | None:
    """Seabed height in metres at the point (negative below sea level); None without the grid."""
    d = _depth()
    if d is None:
        return None
    z, lats, lons = d
    return float(z[_nearest(lats, float(lat)), _nearest(lons, _wrap(lon))])


@lru_cache(maxsize=1)
def _classes() -> dict:
    if not CLASS_FILE.exists():
        return {}
    t = pd.read_csv(CLASS_FILE, dtype=str).fillna("")
    return dict(zip(t["mmsi"], t["class"]))


CLASSES = {
    "MINING": "Mining / production ship", "DRILLING": "Deep-sea drilling ship",
    "GEO": "Resource / geophysical survey ship", "DEEP": "Deep-submergence support ship",
    "SUPPORT": "Offshore construction / support ship", "ENERGY": "Offshore oil & gas ship",
    "RESEARCH": "Oceanographic research ship", "GOV": "Government / coast guard ship",
    "UNK": "Ship type not yet catalogued",
}
_KEYWORDS = [  # first match wins
    ("GOV", r"coast ?guard|navy|naval|government"),
    ("MINING", r"mining|nodule collect|production"),
    ("DRILLING", r"drill"),
    ("ENERGY", r"oil|gas"),
    ("DEEP", r"submersible|rov support"),
    ("SUPPORT", r"construction|offshore support|supply"),
    ("GEO", r"geolog|geophysic|exploration|resource survey"),
    ("RESEARCH", r"research|survey|hydrograph|oceanograph|icebreaker|seismic"),
]


def vessel_class(mmsi: str, ship_type: str, gfw_type: str = "") -> tuple[str, bool]:
    """(class key, inferred?): the hand-checked list first, else keywords in the ship type."""
    listed = _classes().get(str(mmsi).strip())
    if listed:
        return listed, False
    text = f"{ship_type} {gfw_type}".lower()
    for key, pattern in _KEYWORDS:
        if re.search(pattern, text):
            return key, True
    return "UNK", True
