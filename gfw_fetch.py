#!/usr/bin/env python3
"""
GLOBAL FISHING WATCH TRACK FETCHER
==================================

Pulls hourly vessel tracks from the Global Fishing Watch (GFW) API into the
ship library, so the web app and detector can look for survey patterns.

    python gfw_fetch.py                                  # last 12 months, every Chinese survey vessel
    python gfw_fetch.py --months 3
    python gfw_fetch.py --start 2025-01-01 --end 2025-12-31
    python gfw_fetch.py --flag AUS,FRA --types seismic_vessel
    python gfw_fetch.py --watchlist "Deep Sea Mining Vessels.csv"
    python gfw_fetch.py --watchlist list.csv --vessel-group my-group-id
    python gfw_fetch.py --watchlist list.csv --vessel-group my-group-id --group-only

How: GFW's "4Wings" AIS vessel-presence report, grouped by vessel at hourly
time and 0.01-degree (~1 km) space resolution, gives one grid cell per vessel
per hour: in effect an hourly track, from satellite and terrestrial AIS
worldwide. Reports cannot be filtered to single vessels, only by flag and GFW
vessel type, or to a GFW vessel group. So:

  * default / --flag / --types: every vessel of those flags and types is kept;
  * --watchlist CSV (columns name, MMSI, flag (ISO3), GFW vessel type, as GFW
    exports them): only the listed MMSIs are kept. Ships GFW classes as
    "Seismic vessel" are fetched by flag + type in one request per month.
    Other types (Other, Cargo...) would mean pulling whole national fleets, so
    they need --vessel-group: a group you create on the GFW map website
    (API tokens cannot create groups) whose ID is then given here.

Output:
  library/tracks/gfw_<MMSI>.csv   one file per vessel (merged with earlier pulls)
  library/vessels.csv             existing ships get their track linked; new
                                  vessels are added (identity from GFW / the watchlist)

Needs a GFW API token (free, non-commercial use only) in gfw_token.txt next to
this file, or in the GFW_TOKEN environment variable. Never upload the token.

Data: Powered by Global Fishing Watch (https://globalfishingwatch.org),
CC BY-NC 4.0. Tracks are hourly positions snapped to ~1 km cells, so survey
lines closer together than about 1-2 km blur together.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "library"
API = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
DATASET = "public-global-presence:latest"
WORLD = {"type": "Polygon", "coordinates": [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]]}
CREDIT = "Global Fishing Watch 4Wings AIS presence, hourly ~1 km (CC BY-NC 4.0, Powered by Global Fishing Watch)"
FLAG_NAMES = {"CHN": "China", "USA": "United States", "JPN": "Japan", "KOR": "South Korea", "RUS": "Russia",
              "IND": "India", "DEU": "Germany", "FRA": "France", "GBR": "United Kingdom", "NOR": "Norway",
              "AUS": "Australia", "COK": "Cook Islands", "DNK": "Denmark", "MHL": "Marshall Islands",
              "MLT": "Malta", "BHS": "The Bahamas", "SGP": "Singapore", "TWN": "Taiwan",
              "KNA": "Saint Kitts and Nevis", "NLD": "Netherlands", "BEL": "Belgium", "NRU": "Nauru",
              "TON": "Tonga", "KIR": "Kiribati", "JAM": "Jamaica", "BRA": "Brazil", "POL": "Poland"}
GFW_TYPES = {"seismic vessel": "seismic_vessel", "other": "other_non_fishing", "cargo": "cargo",
             "passenger": "passenger", "carrier": "carrier", "bunker": "bunker", "support": "support",
             "fishing": "fishing", "gear": "gear"}


def token() -> str:
    t = (os.environ.get("GFW_TOKEN") or "").strip()   # a pasted secret often ends in a newline
    f = HERE / "gfw_token.txt"
    if not t and f.exists():
        t = f.read_text().strip()
    if not t:
        sys.exit("No GFW token: put it in gfw_token.txt next to this script (or set GFW_TOKEN).")
    return t


def months(start: dt.date, end: dt.date):
    """Calendar-month chunks [a, b) covering start..end."""
    a = start
    while a <= end:
        nxt = (a.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        yield a, min(nxt, end + dt.timedelta(days=1))
        a = nxt


def report(tok: str, start: dt.date, end: dt.date, flags: list[str] | str = (), types: list[str] = (),
           vessel_group: str = "") -> list[dict]:
    """Hourly ~1 km presence rows for one date range, by flag/type filter or a vessel group."""
    flags = [flags] if isinstance(flags, str) else list(flags)
    parts = []
    if flags:
        parts.append("flag in (" + ",".join(f"'{f}'" for f in flags) + ")")
    if types:
        parts.append("vessel_type in (" + ",".join(f"'{t}'" for t in types) + ")")
    params = {"spatial-resolution": "HIGH", "temporal-resolution": "HOURLY", "group-by": "VESSEL_ID",
              "datasets[0]": DATASET, "format": "JSON", "date-range": f"{start},{end}"}
    if parts:
        params["filters[0]"] = " AND ".join(parts)
    if vessel_group:
        params["vessel-groups[0]"] = vessel_group
    url = f"{API}?{urllib.parse.urlencode(params)}"
    body = json.dumps({"geojson": WORLD}).encode()
    waited = 0
    for attempt in range(40):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {tok}", "Content-Type": "application/json",
            "User-Agent": "SurveyDetector/1.0 (non-commercial research)"})   # default Python UA is blocked
        try:
            d = json.load(urllib.request.urlopen(req, timeout=600))
            entries = d.get("entries") or [{}]
            return next(iter(entries[0].values()), []) if entries[0] else []
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            # 429: GFW runs one report per account at a time, and an earlier report can hold
            # that slot for several minutes; wait it out (up to ~15 min) before giving up
            if e.code == 429 and waited < 900:
                if waited == 0:
                    print("  GFW is still busy with an earlier report; waiting...", flush=True)
                time.sleep(60)
                waited += 60
                continue
            if e.code in (500, 502, 503, 504, 524) and attempt < 4:   # 524: report took > 100 s
                time.sleep(30 * (attempt + 1))
                continue
            sys.exit(f"GFW API error {e.code}: {msg}")
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(30)
                continue
            sys.exit(f"Network error: {e}")
    return []


def kind_of(name: str, geartype: str) -> str:
    n = name.upper().replace(" ", "")
    if "COASTGUARD" in n:
        return "Coast guard (GFW classes it as survey)"
    if n.startswith(("HAIYANGSHIYOU", "BINHAI", "DONGFANGMINGZHU")):
        return "Offshore oil & gas seismic vessel"
    return "Survey / research vessel (GFW: seismic)" if "SEISMIC" in (geartype or "").upper() else \
        f"{(geartype or 'unknown').replace('_', ' ').lower()} (GFW)"


def read_watchlist(path: Path) -> pd.DataFrame:
    """One row per MMSI from a GFW-style vessel list; a real name wins over 'Unknown vessel'."""
    w = pd.read_csv(path, dtype=str).fillna("")
    cols = {c.lower().strip(): c for c in w.columns}
    def col(*names):
        return next((cols[n] for n in names if n in cols), None)
    out = pd.DataFrame({
        "name": w[col("name", "shipname", "vessel name")],
        "mmsi": w[col("mmsi", "ssvid")].str.replace(r"\.0$", "", regex=True).str.strip(),
        "flag3": w[col("flag")].str.upper().str.strip() if col("flag") else "",
        "type": w[col("gfw vessel type", "vessel type", "type")] if col("gfw vessel type", "vessel type", "type") else "",
    })
    out["unknown"] = out["name"].str.lower().str.startswith("unknown")
    out = out[out["mmsi"].str.fullmatch(r"\d{9}")].sort_values("unknown").drop_duplicates("mmsi")
    out["gfw_type"] = out["type"].str.lower().map(
        lambda t: next((v for k, v in GFW_TYPES.items() if k in t.split(",")[-1].strip()), ""))
    return out.drop(columns="unknown")


def fetch(tok: str, start: dt.date, end: dt.date, label: str, **query) -> pd.DataFrame:
    rows = []
    for a, b in months(start, end):
        t0 = time.time()
        got = report(tok, a, b, **query)
        rows += got
        print(f"  {label} {a} .. {b - dt.timedelta(days=1)}: {len(got):,} vessel-hours "
              f"({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows)


def save(df: pd.DataFrame, names: dict | None = None) -> tuple[int, int]:
    """Write/merge one track per vessel and link or add catalog rows. names: mmsi -> watchlist row."""
    if not len(df):
        return 0, 0
    df = df.copy()
    df["mmsi"] = df["mmsi"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["Timestamp"] = pd.to_datetime(df["date"]) + pd.Timedelta(minutes=30)   # middle of the hour
    (LIBRARY / "tracks").mkdir(parents=True, exist_ok=True)
    catalog = pd.read_csv(LIBRARY / "vessels.csv", dtype=str).fillna("")
    for c in ("callsign", "built", "source"):
        if c not in catalog:
            catalog[c] = ""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    added = linked = 0
    for mmsi, g in df.groupby("mmsi"):
        if not re.fullmatch(r"\d{9}", mmsi) or (names is not None and mmsi not in names):
            continue
        g = g.sort_values("Timestamp")
        info, listed = g.iloc[-1], (names or {}).get(mmsi, {})
        flag3 = (listed.get("flag3") or str(info.get("flag") or "")).upper()
        flag = FLAG_NAMES.get(flag3, flag3)
        track = pd.DataFrame({
            "Timestamp": g["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"), "Latitude": g["lat"],
            "Longitude": g["lon"], "Speed": g["speed"].round(2) if "speed" in g else "",
            "MMSI": mmsi, "IMO": info.get("imo") or "", "CallSign": info.get("callsign") or "",
            "ShipName": info.get("shipName") or "", "Flag": flag})
        fname = f"gfw_{mmsi}.csv"
        path = LIBRARY / "tracks" / fname
        if path.exists():   # merge with earlier pulls: keep all hours, newest pull wins
            old = pd.read_csv(path, dtype=str)
            track = (pd.concat([old, track.astype(str)]).drop_duplicates("Timestamp", keep="last")
                     .sort_values("Timestamp"))
        track.to_csv(path, index=False)

        name = listed.get("name") or str(info.get("shipName") or mmsi).title()
        hit = catalog.index[catalog["mmsi"] == mmsi]
        if not len(hit):   # same ship listed without an MMSI yet (e.g. Sagar Nidhi)
            hit = catalog.index[(catalog["mmsi"] == "") & (catalog["name"].map(norm) == norm(name))]
        if len(hit):
            i = hit[0]
            if not catalog.loc[i, "mmsi"]:
                catalog.loc[i, "mmsi"] = mmsi
            if not catalog.loc[i, "track_file"] or catalog.loc[i, "track_file"].startswith("gfw_"):
                catalog.loc[i, "track_file"] = fname
                if "Global Fishing Watch" not in catalog.loc[i, "source"]:
                    catalog.loc[i, "source"] = (catalog.loc[i, "source"] + "; track: " + CREDIT).strip("; ")
                linked += 1
        else:
            if norm(name) in set(catalog["name"].map(norm)):   # library ships are keyed by name
                name = f"{name} ({flag})"
            kind = (f"{listed['type']} (GFW)" if listed.get("type") else
                    kind_of(str(info.get("shipName") or ""), str(info.get("geartype") or "")))
            catalog.loc[len(catalog)] = {
                "name": name, "flag": flag, "mmsi": mmsi, "imo": str(info.get("imo") or ""),
                "callsign": str(info.get("callsign") or ""), "built": "", "ship_type": kind, "operator": "",
                "notes": "From your deep-sea mining vessel list." if listed else
                         "Added from Global Fishing Watch survey-vessel search.",
                "source": "Identity and track: " + CREDIT, "track_file": fname}
            added += 1
    catalog.to_csv(LIBRARY / "vessels.csv", index=False)
    return linked, added


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=12, help="how far back from today (default 12)")
    ap.add_argument("--start", help="YYYY-MM-DD (overrides --months)")
    ap.add_argument("--end", help="YYYY-MM-DD (default: 4 days ago, GFW's lag)")
    ap.add_argument("--flag", default="CHN", help="ISO3 flag code(s), comma-separated (default CHN)")
    ap.add_argument("--types", default="seismic_vessel",
                    help="comma-separated GFW vessel types (default seismic_vessel; '' for all types)")
    ap.add_argument("--watchlist", help="CSV of vessels to keep (GFW export: name, MMSI, flag, GFW vessel type)")
    ap.add_argument("--vessel-group", default="", help="GFW vessel group ID to pull (made on the GFW map site)")
    ap.add_argument("--group-only", action="store_true",
                    help="with --watchlist and --vessel-group: skip the seismic-class pull")
    args = ap.parse_args()

    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today() - dt.timedelta(days=4)
    if args.start:
        start = dt.date.fromisoformat(args.start)
    else:   # first day of the month, args.months calendar months back (counting the current one)
        k = end.year * 12 + end.month - 1 - (args.months - 1)
        start = dt.date(k // 12, k % 12 + 1, 1)
    tok = token()
    print(f"Global Fishing Watch tracks, {start} to {end}")

    linked = added = 0
    if args.watchlist:
        w = read_watchlist(Path(args.watchlist))
        names = {r.mmsi: r._asdict() for r in w.itertuples(index=False)}
        seismic = w[w["gfw_type"] == "seismic_vessel"]
        others = w[w["gfw_type"] != "seismic_vessel"]
        print(f"Watchlist: {len(w)} vessels ({len(seismic)} seismic-class, {len(others)} other types)")
        if len(seismic) and not (args.group_only and args.vessel_group):
            flags = sorted(set(seismic["flag3"]) - {""})
            df = fetch(tok, start, end, "seismic", flags=flags, types=["seismic_vessel"])
            got = set(df["mmsi"].astype(str)) if len(df) else set()
            l, a = save(df, names)
            linked, added = linked + l, added + a
            missing = seismic[~seismic["mmsi"].isin(got)]
            if len(missing):
                print("  no positions in this period for: " + ", ".join(missing["name"]))
        if args.vessel_group:
            df = fetch(tok, start, end, "group", vessel_group=args.vessel_group)
            l, a = save(df, names)
            linked, added = linked + l, added + a
        elif len(others):
            print("Not fetched (types other than seismic need --vessel-group): " + ", ".join(others["name"]))
    else:
        flags = [f.strip().upper() for f in args.flag.split(",") if f.strip()]
        types = [t.strip() for t in args.types.split(",") if t.strip()]
        df = fetch(tok, start, end, ",".join(flags) or "all", flags=flags, types=types,
                   vessel_group=args.vessel_group)
        linked, added = save(df)
    print(f"\nLibrary: {linked} existing ships linked to tracks, {added} new ships added.")
    print("Powered by Global Fishing Watch (https://globalfishingwatch.org), CC BY-NC 4.0.")


if __name__ == "__main__":
    main()
