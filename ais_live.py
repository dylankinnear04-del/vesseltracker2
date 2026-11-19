"""
Near-shore ship positions from aisstream.io, to keep the library updating while Global Fishing Watch's
track service is down (or lagging).

aisstream.io is a free live feed from shore-based AIS receivers (beta, no SLA, no history): it only sees ships
within roughly 40-70 km of a receiver, so ships far offshore stay silent until GFW is back. Needs a free key
(sign up at https://aisstream.io) in the AISSTREAM_API_KEY environment variable / repository secret.

    python ais_live.py --seconds 1200     # listen 20 min for the library's ships; add to ais_buffer/
    python ais_live.py --merge            # daily: move the buffer into library/tracks after GFW's last date

Rules: positions go into the ship's gfw_<MMSI>.csv track with Source "aisstream", one per ship per hour, and
only after the newest GFW position; when GFW data for those hours arrives, it replaces them (prefer_gfw).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "library"
BUFFER = HERE / "ais_buffer" / "positions.csv.gz"
STATUS_FILE = LIBRARY / "ais_status.json"
URL = "wss://stream.aisstream.io/v0/stream"
SOURCE = "aisstream"
MAX_SHIPS = 200                     # aisstream's limit per subscription
POSITION_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport",
                  "LongRangeAisBroadcastMessage"]
BUFFER_COLUMNS = ["mmsi", "time", "lat", "lon", "speed", "course", "name"]
QUICK_CLOSE_S = 5.0                 # a connection closed this soon with no data at all...
QUICK_CLOSES = 3                    # ...this many times in a row: the server is refusing us (e.g. a bad key)


def subscription(key: str, mmsis: list) -> dict:
    """The message aisstream needs within 3 s of connecting: the whole world, our ships, position messages."""
    return {"APIKey": key, "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FiltersShipMMSI": [str(m) for m in mmsis][:MAX_SHIPS], "FilterMessageTypes": POSITION_TYPES}


def _time(text) -> pd.Timestamp | None:
    """aisstream's time_utc, e.g. '2026-11-19 10:15:30.123456789 +0000 UTC' (nanoseconds dropped)."""
    m = re.match(r"(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)", str(text or ""))
    return pd.Timestamp(m.group(1), tz="UTC") if m else None


def _num(*vals):
    for v in vals:
        try:
            if v is not None and v != "":
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def parse(msg: dict, wanted: set, received: pd.Timestamp | None = None) -> dict | None:
    """One position for a followed ship, or None (other ships, errors, 'not available' positions)."""
    kind = msg.get("MessageType")
    if kind not in POSITION_TYPES:
        return None
    meta, body = msg.get("MetaData") or {}, (msg.get("Message") or {}).get(kind) or {}
    mmsi = str(meta.get("MMSI") or body.get("UserID") or "")
    if mmsi not in wanted:
        return None
    lat = _num(meta.get("latitude"), meta.get("Latitude"), body.get("Latitude"))
    lon = _num(meta.get("longitude"), meta.get("Longitude"), body.get("Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None                         # 91 / 181 mean "not available"
    sog, cog = _num(body.get("Sog")), _num(body.get("Cog"))
    when = _time(meta.get("time_utc")) or received or pd.Timestamp.now(tz="UTC")
    return {"mmsi": mmsi, "time": when, "lat": round(lat, 6), "lon": round(lon, 6),
            "speed": sog if sog is not None and sog < 102.3 else float("nan"),       # 102.3: not available
            "course": cog if cog is not None and cog < 360 else float("nan"),
            "name": str(meta.get("ShipName") or "").strip()}


def hourly(rows: list) -> pd.DataFrame:
    """One position per ship per hour (the latest), like GFW's hourly tracks."""
    df = pd.DataFrame(rows, columns=BUFFER_COLUMNS)
    if not len(df):
        return df
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["hour"] = df["time"].dt.floor("h")
    out = df.sort_values("time").groupby(["mmsi", "hour"], as_index=False).last()
    return out[BUFFER_COLUMNS].sort_values(["mmsi", "time"]).reset_index(drop=True)


async def record(key: str, mmsis: list, seconds: float, connect=None, rows: list | None = None) -> list:
    """Listen for `seconds`, reconnecting with backoff; positions of the given ships, appended to `rows` (so
    the caller keeps what arrived even if this raises). Raises RuntimeError when aisstream reports an error or
    closes every connection at once with no data."""
    if connect is None:
        import websockets
        connect = lambda url: websockets.connect(url, compression="deflate", max_size=2 ** 22)  # noqa: E731
    wanted, rows = {str(m) for m in mmsis}, (rows if rows is not None else [])
    deadline, wait, quick = time.monotonic() + seconds, 1.0, 0
    while time.monotonic() < deadline:
        opened, frames = time.monotonic(), 0
        try:
            async with connect(URL) as ws:
                await ws.send(json.dumps(subscription(key, mmsis)))
                async for raw in _until(ws, deadline):
                    frames += 1
                    try:
                        msg = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
                    except ValueError:
                        continue
                    if msg.get("error"):
                        raise RuntimeError(f"aisstream: {msg['error']}")
                    p = parse(msg, wanted, received=pd.Timestamp.now(tz="UTC"))
                    if p:
                        rows.append(p)
                        wait = 1.0
        except RuntimeError:                            # e.g. a bad key: the person has to act
            raise
        except Exception as exc:                        # dropped connection
            print(f"  connection: {exc}", flush=True)
        quick = quick + 1 if not frames and time.monotonic() - opened < QUICK_CLOSE_S else 0
        if quick >= QUICK_CLOSES:
            raise RuntimeError("aisstream closed every connection at once without sending data: "
                               "check the AISSTREAM_API_KEY secret")
        left = deadline - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(wait, left))            # back off (with jitter), then resubscribe
        wait = min(60.0, wait * 2) * (1 + random.random() / 4)
    return rows


async def _until(ws, deadline: float):
    it = ws.__aiter__()
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        try:
            yield await asyncio.wait_for(it.__anext__(), timeout=left)
        except (StopAsyncIteration, asyncio.TimeoutError):
            return


# ---------- buffer (ais_buffer/, outside the library so recording does not invalidate the site's data) ----------

def read_buffer(path: Path = BUFFER) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BUFFER_COLUMNS)
    df = pd.read_csv(path, dtype={"mmsi": str})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def append_buffer(path: Path, rows: list) -> int:
    """Add positions to the buffer, one per ship per hour; returns the buffer's size."""
    new = hourly(rows)
    both = pd.concat([read_buffer(path), new], ignore_index=True) if len(new) else read_buffer(path)
    both = hourly(both.to_dict("records")) if len(both) else both
    path.parent.mkdir(parents=True, exist_ok=True)
    both.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    return len(both)


# ---------- daily merge into the library ------------------------------------------------------------------------

def prefer_gfw(track: pd.DataFrame) -> pd.DataFrame:
    """Drop aisstream positions at or before the newest GFW position: GFW wins where it has data."""
    if "Source" not in track or not len(track):
        return track
    src = track["Source"].fillna("").astype(str)
    gfw_times = pd.to_datetime(track.loc[src != SOURCE, "Timestamp"], errors="coerce")
    if not gfw_times.notna().any():
        return track
    newest = gfw_times.max()
    ais_times = pd.to_datetime(track["Timestamp"], errors="coerce")
    return track[~((src == SOURCE) & (ais_times <= newest))].reset_index(drop=True)


def followed_mmsis(library: Path = LIBRARY) -> list:
    cat = pd.read_csv(library / "vessels.csv", dtype=str).fillna("")
    return sorted({m for m in cat.get("mmsi", []) if re.fullmatch(r"\d{9}", m)})


def merge_into_library(buffer: Path = BUFFER, library: Path = LIBRARY) -> dict:
    """Move buffered positions into each ship's gfw_<MMSI>.csv after its newest GFW position, then clear the buffer.
    Ships whose track is a hand-made file (not gfw_*) are left alone."""
    buf = read_buffer(buffer)
    cat_path = library / "vessels.csv"
    cat = pd.read_csv(cat_path, dtype=str).fillna("")
    ships = positions = 0
    for mmsi, g in buf.groupby("mmsi"):
        hit = cat.index[cat["mmsi"] == mmsi]
        if not len(hit):
            continue
        i = hit[0]
        tf = cat.loc[i, "track_file"]
        if tf and not tf.startswith("gfw_"):
            continue
        fname = tf or f"gfw_{mmsi}.csv"
        path = library / "tracks" / fname
        old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=["Timestamp"])
        if "Source" not in old:
            old["Source"] = ""
        new = pd.DataFrame({"Timestamp": g["time"].dt.strftime("%Y-%m-%d %H:%M:%S"), "Latitude": g["lat"].astype(str),
                            "Longitude": g["lon"].astype(str),
                            "Speed": g["speed"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}"),
                            "MMSI": mmsi, "ShipName": g["name"].fillna("").astype(str), "Source": SOURCE})
        both = prefer_gfw(pd.concat([old, new], ignore_index=True)
                          .drop_duplicates("Timestamp", keep="first").sort_values("Timestamp"))
        added = len(both) - len(old)
        if added <= 0:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        both.to_csv(path, index=False)
        if not tf:
            cat.loc[i, "track_file"] = fname
        ships, positions = ships + 1, positions + added
    cat.to_csv(cat_path, index=False)
    if buffer.exists():
        buffer.unlink()
    return {"ships": ships, "positions": positions}


def write_status(**fields) -> None:
    try:
        status = json.loads(STATUS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        status = {}
    status.update(fields)
    STATUS_FILE.write_text(json.dumps(status, indent=1) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=1200, help="how long to listen (default 20 min)")
    ap.add_argument("--merge", action="store_true", help="merge the buffer into library/tracks instead of listening")
    args = ap.parse_args(argv)
    today = dt.date.today().isoformat()
    if args.merge:
        n = merge_into_library()
        write_status(last_merge=today, merged_positions=n["positions"], merged_ships=n["ships"])
        print(f"Merged {n['positions']} aisstream positions for {n['ships']} ships into the library.")
        return 0
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        print("No AISSTREAM_API_KEY: nothing recorded. Sign up at https://aisstream.io and add the key as a "
              "repository secret named AISSTREAM_API_KEY.")
        return 0
    mmsis = followed_mmsis()
    print(f"Listening {args.seconds:.0f}s to aisstream.io for {min(len(mmsis), MAX_SHIPS)} ships")
    rows, error = [], None
    try:
        asyncio.run(record(key, mmsis, args.seconds, rows=rows))
    except RuntimeError as exc:                   # bad key etc.: the person has to act
        error = str(exc)
    size = append_buffer(BUFFER, rows)            # keep what arrived, even after an error
    seen = sorted({r["mmsi"] for r in rows})
    write_status(ok=error is None, error=error, last_attempt=today, last_positions=len(rows), last_ships=len(seen))
    print(f"{len(rows)} positions from {len(seen)} ships; buffer now {size} ship-hours.")
    if error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
