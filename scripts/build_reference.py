"""
Build the reference data the website's priority scores use (run once, by hand; not on the site):

  reference_data/eez_v12_simplified.geojson  EEZ polygons (name, sovereigns, type), simplified
  reference_data/eez_boundaries.geojson      lines between two states' zones (treaty, median, unsettled)
  reference_data/depth_etopo2022_5min.npz    seabed depth, 5 arc-minute grid, int16 metres

Sources:
  Marine Regions, World EEZ v12 (Flanders Marine Institute 2023), CC BY 4.0, via its public WFS.
  NOAA ETOPO 2022 15 arc-second (public domain), via NOAA CoastWatch ERDDAP, every 20th cell.

Needs shapely and xarray + scipy (build only):  python scripts/build_reference.py [--only eez|depth]
"""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reference_data"
UA = {"User-Agent": "SurveyDetector-reference-build/1.0"}
WFS = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.nc"
SIMPLIFY_DEG = 0.04        # about 4 km: enough for "is this survey inside that EEZ"


def get(url: str, timeout: int = 600) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as exc:              # flaky public services: retry with a pause
            if attempt == 3:
                raise
            print(f"  retry after {exc}")
            time.sleep(10 * (attempt + 1))


def wfs(type_name: str, props: str, start: int, count: int) -> dict:
    url = (f"{WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames={type_name}"
           f"&outputFormat=application/json&count={count}&startIndex={start}&sortBy=mrgid"
           f"&propertyName={props}") if type_name.endswith(":eez") else (
           f"{WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames={type_name}"
           f"&outputFormat=application/json&count={count}&startIndex={start}&sortBy=line_id"
           f"&propertyName={props}")
    return json.loads(get(url))


def build_eez() -> None:
    from shapely.geometry import MultiPolygon, Polygon, mapping, shape

    feats, start = [], 0
    while True:
        page = wfs("MarineRegions:eez", "mrgid,geoname,pol_type,sovereign1,sovereign2,sovereign3,the_geom",
                   start, 5)
        if not page["features"]:
            break
        for f in page["features"]:
            p = f["properties"]
            geom = shape(f["geometry"])
            # drop interior rings (land and islands cut out of the zone): surveys are never on land,
            # and they are most of the file's size
            polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms)
            geom = MultiPolygon([Polygon(q.exterior) for q in polys]).simplify(SIMPLIFY_DEG, preserve_topology=True)
            if geom.is_empty:
                continue
            sov = [s for s in (p.get("sovereign1"), p.get("sovereign2"), p.get("sovereign3")) if s]
            feats.append({"type": "Feature", "geometry": mapping(geom),
                          "properties": {"mrgid": p["mrgid"], "name": p["geoname"],
                                         "type": p["pol_type"], "sovereigns": sov}})
        start += len(page["features"])
        print(f"  EEZ polygons: {start}")
    _write_geojson(OUT / "eez_v12_simplified.geojson", feats)

    lines, start = [], 0
    while True:
        page = wfs("MarineRegions:eez_boundaries", "line_id,line_name,line_type,sovereign1,sovereign2,the_geom",
                   start, 500)
        if not page["features"]:
            break
        for f in page["features"]:
            p = f["properties"]
            if not p.get("sovereign2") or "200 NM" in str(p.get("line_type")):
                continue                       # outer limits face the high seas, not a neighbour
            geom = shape(f["geometry"]).simplify(SIMPLIFY_DEG / 2)
            lines.append({"type": "Feature", "geometry": mapping(geom),
                          "properties": {"name": p["line_name"], "type": p["line_type"],
                                         "sovereigns": [p["sovereign1"], p["sovereign2"]]}})
        start += len(page["features"])
        print(f"  boundary lines: {start}")
    _write_geojson(OUT / "eez_boundaries.geojson", lines)


def _write_geojson(path: Path, feats: list) -> None:
    def rnd(x):
        return [rnd(v) for v in x] if isinstance(x, (list, tuple)) else round(x, 2)
    for f in feats:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"wrote {path.name}: {len(feats)} features, {path.stat().st_size / 1e6:.1f} MB")


def build_depth() -> None:
    import xarray as xr

    rows, lats, lons = [], [], None
    for lat0 in range(-90, 90, 30):            # six bands keep each ERDDAP request modest
        lat1 = lat0 + 30 - 1 / 12
        q = f"?z%5B({lat0 + 1 / 24}):20:({lat1 + 1 / 24})%5D%5B(-179.99791666666667):20:(179.99791666666667)%5D"
        raw = get(ERDDAP + q, timeout=900)
        ds = xr.open_dataset(io.BytesIO(raw), engine="scipy")
        rows.append(ds["z"].values.astype(np.float32))
        lats.append(ds["latitude"].values)
        lons = ds["longitude"].values
        print(f"  depth band {lat0}..{lat0 + 30}: {rows[-1].shape}")
    z = np.concatenate(rows, axis=0)
    z = np.clip(np.round(z), -11000, 9000).astype(np.int16)
    path = OUT / "depth_etopo2022_5min.npz"
    # bands can come back a row short at their edges: keep each row's real latitude
    np.savez_compressed(path, z=z, lat=np.concatenate(lats).astype(np.float32), lon=lons.astype(np.float32))
    print(f"wrote {path.name}: {z.shape}, {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["eez", "depth"])
    a = ap.parse_args()
    if a.only in (None, "eez"):
        build_eez()
    if a.only in (None, "depth"):
        build_depth()
