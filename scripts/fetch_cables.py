"""
Fetch the public Submarine Cable Map (TeleGeography) once into reference_data/:

    reference_data/submarine_cables.geojson   routes + name, owners, length, RFS year, planned, landings
    reference_data/cable_landings.csv         landing points (name, lat, lon)
    reference_data/cable_meta.json            fetch date, source, license, counts

    python scripts/fetch_cables.py

Routes are schematic (a few km). License has historically been CC BY-NC-SA 3.0; credit
"TeleGeography, Submarine Cable Map".
"""
import csv
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

API = "https://www.submarinecablemap.com/api/v3/"
OUT = Path(__file__).resolve().parents[1] / "reference_data"
UA = {"User-Agent": "survey-detector-cable-fetch/1.0"}


def get(path: str):
    req = urllib.request.Request(API + path, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _round(coords):
    return [_round(c) for c in coords] if isinstance(coords[0], list) else [round(coords[0], 3), round(coords[1], 3)]


def _km(text) -> float | None:
    m = re.search(r"[\d,.]+", str(text or ""))
    try:
        return float(m.group().replace(",", "")) if m else None
    except ValueError:
        return None


def main() -> None:
    geo = get("cable/cable-geo.json")
    landings = get("landing-point/landing-point-geo.json")
    routes: dict[str, list] = {}
    for f in geo["features"]:
        cid = f["properties"]["id"]
        g = f["geometry"]
        lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        routes.setdefault(cid, []).extend(_round(lines))
    feats = []
    for i, cid in enumerate(sorted(routes)):
        try:
            d = get(f"cable/{cid}.json")
        except Exception as err:                      # keep the route even if its details are missing
            print(f"  {cid}: {err}", file=sys.stderr)
            d = {"id": cid, "name": cid}
        feats.append({"type": "Feature",
                      "geometry": {"type": "MultiLineString", "coordinates": routes[cid]},
                      "properties": {"id": cid, "name": d.get("name") or cid, "owners": d.get("owners") or "",
                                     "length_km": _km(d.get("length")), "rfs_year": d.get("rfs_year"),
                                     "planned": bool(d.get("is_planned")),
                                     "landings": [{"name": p.get("name", ""), "country": p.get("country", "")}
                                                  for p in d.get("landing_points") or []]}})
        if i % 100 == 0:
            print(f"{i}/{len(routes)}")
        time.sleep(0.2)
    (OUT / "submarine_cables.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                             separators=(",", ":")))
    with open(OUT / "cable_landings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "lat", "lon"])
        for f in landings["features"]:
            lon, lat = f["geometry"]["coordinates"]
            w.writerow([f["properties"]["id"], f["properties"]["name"], round(lat, 4), round(lon, 4)])
    meta = {"fetched": date.today().isoformat(), "source": API,
            "license": "TeleGeography Submarine Cable Map; historically CC BY-NC-SA 3.0",
            "cables": len(feats), "landings": len(landings["features"])}
    (OUT / "cable_meta.json").write_text(json.dumps(meta, indent=1))
    print(meta)


if __name__ == "__main__":
    main()
