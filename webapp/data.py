"""
Data for the website: the ship library, running the detector, and the shared public results.
Moved from the single-page app.py (2026-11-09 revamp); the detector itself is unchanged.
"""
from __future__ import annotations

import datetime
import gc
import gzip
import hashlib
import io
import json
import re
import tempfile
import time
import urllib.request
import uuid
import warnings
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import intel
import models
import stationkeeping
import survey_pattern_detector as spd
from isa_contracts import ISA_LAYERS, ISA_SERVICE

HERE = Path(__file__).resolve().parents[1]     # the project folder (this file is in webapp/)
LIBRARY = HERE / "library"          # vessels.csv catalog + tracks/ position files
UPLOAD_TYPES = ["csv", "txt", "tsv", "xlsx", "xlsm"]
TABLES = ["vessels", "nearby_ports", "survey_hotspots", "survey_areas", "survey_blocks", "survey_lines",
          "rejected_blocks", "predictions", "positions_processed"]

SETTINGS = {
    "Cleaning": {
        "min_speed_kn": "Points slower than this are loitering/drifting and dropped (knots).",
        "min_step_km": "A point closer than this to the previous one counts as stationary.",
        "max_implied_speed_kn": "Faster than this between fixes = bad position.",
        "max_gap_hours": "Split the track at reporting gaps longer than this.",
        "max_gap_km_no_time": "Without timestamps, split the track at jumps longer than this.",
    },
    "Straight lines": {
        "rdp_tolerance_km": "How far a track may wander and still count as straight.",
        "min_segment_km": "Shorter pieces are treated as turns.",
        "merge_heading_tol_deg": "Pieces within this heading of each other can join into one line.",
        "merge_offset_km": "Pieces this close to one line get merged.",
        "merge_gap_km": "...across at most this much turn or dog-leg.",
        "min_line_km": "Shortest straight line counted as a survey line.",
        "min_points_per_line": "Fewest position reports a line may have.",
    },
    "Lawnmower pattern": {
        "antiparallel_tol_deg": "Next line must run within this of the opposite direction.",
        "block_axis_tol_deg": "Every line must stay within this of the block's axis.",
        "min_spacing_km": "Narrowest gap between adjacent lines.",
        "max_spacing_km": "Widest gap between adjacent lines.",
        "min_overlap_frac": "Adjacent lines must cover at least this share of the same stretch.",
        "min_length_ratio": "Shorter line / longer line, for adjacent lines.",
        "max_connector_km": "Longest turn between the end of one line and the next.",
        "max_turn_hours": "Longest time between one line and the next: legs days apart are repeat trips, not a survey.",
        "max_skip_lines": "Odd lines (cross-lines, turn pieces) tolerated inside a block.",
        "min_lines_per_block": "Fewest lines that make a survey block.",
        "area_join_km": "Blocks this close with the same axis form one survey area.",
    },
    "Is it a real survey?": {
        "min_score": "Drop blocks scoring below this (0-1): they only loosely fit the pattern.",
        "max_spacing_cv": "Lawnmower line spacing must be this regular (spread / mean).",
        "min_new_track_frac": "Share of lines on new ground, not re-running an earlier line (shuttles, patrols).",
        "min_progression": "Lawnmower: share of steps that advance the same way across the block.",
        "min_interleaved_lines": "Interleaved / racetrack surveys (3D seismic) need at least this many lines...",
        "min_coverage": "...filling this share of the block's width (1 km strips)...",
        "min_width_km": "...which is at least this wide (km)...",
        "interleaved_max_speed_kn": "...run at towed-seismic speed or slower (kn)...",
        "interleaved_max_turn_hours": "...turning straight onto the next line (hours).",
        "min_survey_speed_kn": "Slowest median speed on the lines that counts as surveying.",
        "max_survey_speed_kn": "Fastest: ferries and patrols run faster than survey ships.",
        "min_offshore_km": "Survey lines must lie at least this far from the coast (median).",
        "shore_turn_km": "A line ending this close to the coast turns at the shore...",
        "max_shore_turn_frac": "...and no more than this share of line ends may do that.",
    },
    "Survey hotspots": {
        "hotspot_join_km": "Survey areas this close, by any ships, count as one hotspot.",
    },
    "Prediction": {
        "predict_lines": "How many upcoming lines to project.",
        "min_progression_for_prediction": "Only predict when at least this share of steps advance the same way.",
    },
}


# ============================================================
# RUNNING THE DETECTOR
# ============================================================

# Streamlit Community Cloud gives an app about 1 GB: keep few big results cached
def _run_analysis(groups: tuple, settings: dict, identities: tuple = ()) -> dict:
    """
    Run the detector and collect everything the page shows.
    groups: ((dataset name, ((file name, bytes), ...)), ...), one per dataset.
    identities: ((dataset, vessel or None, mmsi, flag, name, source, imo), ...) for vessels
    whose files carry no identity (library catalog entries, the identity form).
    """
    cfg = spd.Config(**settings)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "input", Path(tmp) / "results"
        src.mkdir()
        sources, i = {}, 0
        for dataset, files in groups:
            for name, data in files:
                path = src / f"{i:03d}" / Path(name).name    # each file keeps its own name
                path.parent.mkdir()
                path.write_bytes(data)
                sources.setdefault(dataset, []).append(str(path))
                i += 1

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # quick-look PNGs and the Excel workbook are slow (about two thirds of the time
            # for many ships) and rarely opened: they are made on request instead (see below)
            results, notes, n_rows = spd.run(
                sources, cfg, out, workers=1, make_maps=False,
                identities={(ds, vs): {"mmsi": m, "flag": f, "name": n, "source": how, "imo": imo}
                            for ds, vs, m, f, n, how, imo in identities})

        tables = {}
        for key in TABLES:
            try:
                tables[key] = pd.read_csv(out / f"{key}.csv", low_memory=False)
            except (FileNotFoundError, pd.errors.EmptyDataError):
                tables[key] = pd.DataFrame()
        maps = {spd.map_filename(r["dataset"], r["vessel"]): {k: r[k] for k in spd.MAP_KEYS}
                for r in results}
        geojson = json.loads((out / "survey_results.geojson").read_text())
        zip_bytes = _zip_folder(out, extra={})
    del results
    gc.collect()                           # hand the detector's working memory back before the page is built
    return {"notes": notes, "n_rows": n_rows, "tables": tables, "maps": maps,
            "geojson": geojson, "zip": zip_bytes, "id": uuid.uuid4().hex,
            "seconds": time.perf_counter() - started}


# per-session results (uploads, custom settings): copied per reader, so few are kept
analyse = st.cache_data(show_spinner=False, max_entries=2)(_run_analysis)


def on_request(res: dict, what: str, make):
    """A file made only when asked for, once per analysis result (kept for the session)."""
    made = st.session_state.setdefault("made_files", {})
    key = (res["id"], what)
    if key not in made:
        if len(made) > 40:                 # keep the session small
            made.clear()
        made[key] = make()
    return made[key]


def _excel(tables: dict) -> bytes:
    names = {"vessels": "Vessels", "nearby_ports": "Nearby Ports", "survey_hotspots": "Survey Hotspots",
             "survey_areas": "Survey Areas", "survey_blocks": "Survey Blocks", "survey_lines": "Survey Lines",
             "rejected_blocks": "Rejected Patterns", "predictions": "Predictions",
             "positions_processed": "Positions"}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for key, sheet in names.items():
            tables[key].to_excel(xl, sheet_name=sheet, index=False)
    return buf.getvalue()


def _zip_folder(folder: Path, extra: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path("survey_results") / p.relative_to(folder))
        for name, data in extra.items():
            z.writestr(f"survey_results/{name}", data)
    return buf.getvalue()



# ============================================================
# SHIP LIBRARY
# ============================================================

def library_files() -> tuple:
    """(file, modified time) for the catalog, every track and the GFW registry/events: the library's cache key."""
    files = ([LIBRARY / "vessels.csv"] + sorted((LIBRARY / "tracks").glob("*"))
             + [LIBRARY / "gfw_vessel_info.csv", LIBRARY / "gfw_events.csv"])
    return tuple((str(f), f.stat().st_mtime) for f in files if f.is_file())


@st.cache_data(show_spinner=False)
def load_library(stamp: tuple) -> pd.DataFrame:
    """The catalog, with each track's date span and number of positions added."""
    path = LIBRARY / "vessels.csv"
    if not path.exists():
        return pd.DataFrame()
    cat = pd.read_csv(path, dtype=str).fillna("")
    first, last, count = [], [], []
    for track in cat.get("track_file", pd.Series([""] * len(cat))):
        f = LIBRARY / "tracks" / track
        if not track or not f.is_file():
            first.append(None); last.append(None); count.append(0)
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            std, _ = spd.standardize(spd.read_any(f), f.stem)
        times = std["time"].dropna()
        first.append(times.min().date() if len(times) else None)
        last.append(times.max().date() if len(times) else None)
        count.append(len(std))
    return cat.assign(data_from=first, data_to=last, positions=count,
                      has_data=[n > 0 for n in count])


@st.cache_data(show_spinner=False, max_entries=16)
def library_track(track: str, stamp: float, start, end) -> bytes:
    """A library track cut to [start, end] (dates), as CSV bytes in its original columns."""
    f = LIBRARY / "tracks" / track
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = spd.read_any(f)
        std, _ = spd.standardize(raw, f.stem)
    if std["time"].notna().any() and start and end:
        day = std["time"].dt.date
        raw = raw.iloc[std.loc[(day >= start) & (day <= end), "row_in_file"]]
    return raw.to_csv(index=False).encode()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "vessel"


# the deep-sea mining watchlist (the GFW export the weekly update also pulls): a quick pick
WATCHLIST = LIBRARY / "watchlist_deep_sea_mining.csv"


@st.cache_data(show_spinner=False)
def watchlist_mmsi(stamp: float) -> frozenset:
    """MMSIs on the deep-sea mining watchlist (stamp: the file's modified time, for the cache)."""
    try:
        w = pd.read_csv(WATCHLIST, dtype=str)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return frozenset()
    col = next((c for c in w.columns if c.strip().lower() == "mmsi"), None)
    return frozenset(w[col].dropna().str.strip()) if col else frozenset()


KIND_ORDER = ["Research / survey ship", "Seismic ship (oil & gas)", "Other ship", "Coast guard"]


def ship_kind(ship_type: str) -> str:
    """The catalog's ship type in plain words, for grouping and filtering."""
    t = str(ship_type).lower()
    if "coast guard" in t:
        return "Coast guard"
    if "seismic" in t and "research" not in t:
        return "Seismic ship (oil & gas)"
    if re.search(r"research|survey|hydrographic|geolog|icebreaker", t):
        return "Research / survey ship"
    return "Other ship"



# ============================================================
# PUBLIC RESULTS (2026-11-09 revamp)
# ============================================================

GROUPS = {"mining": "Mining ships", "china": "Chinese research", "all": "All ships"}
WINDOWS = {"30d": ("Last 30 days", 30), "6m": ("Last 6 months", 182),
           "1y": ("Last year", 365), "all": ("All data", None)}


def default_settings() -> dict:
    """The detector's defaults, as the public pages use them."""
    return {**asdict(spd.Config()), "model": models.DEFAULT, "port_country": "flag"}


def default_station_settings() -> dict:
    return asdict(stationkeeping.StationConfig())


def library() -> pd.DataFrame:
    """The catalog with kind of ship, flag ("Unknown" when blank) and the mining watchlist marked."""
    lib = load_library(library_files())
    if not len(lib):
        return lib
    mining = watchlist_mmsi(WATCHLIST.stat().st_mtime if WATCHLIST.exists() else 0.0)
    return lib.assign(kind=lib["ship_type"].map(ship_kind), flag=lib["flag"].replace("", "Unknown"),
                      mining=lib["mmsi"].isin(mining))


def last_updated(lib: pd.DataFrame) -> datetime.date | None:
    """Newest position in the library: when the weekly update last brought data."""
    days = [d for d in lib.get("data_to", []) if d] if len(lib) else []
    return max(days) if days else None


def select_ships(lib: pd.DataFrame, group: str, countries: tuple = ()) -> pd.DataFrame:
    """Ships with position data in a group (unknown group = mining), optionally from some countries."""
    if not len(lib):
        return lib
    group = group if group in GROUPS else "mining"
    keep = lib["has_data"].astype(bool) & ~lib["ship_type"].str.lower().str.startswith("demo")   # simulated ships stay off public pages
    if group == "mining":
        keep &= lib["mining"]
    elif group == "china":
        keep &= (lib["flag"] == "China") & (lib["kind"] == "Research / survey ship")
    if countries:
        keep &= lib["flag"].isin(countries)
    return lib[keep]


def window_dates(chosen: pd.DataFrame, window: str) -> tuple:
    """(start, end) dates of a shared window ending at the chosen ships' newest position."""
    span_from = min(d for d in chosen["data_from"] if d)
    span_to = max(d for d in chosen["data_to"] if d)
    days = WINDOWS.get(window, WINDOWS["6m"])[1]
    if days is None:
        return span_from, span_to
    return max(span_from, span_to - datetime.timedelta(days=days - 1)), span_to


def build_groups(chosen: pd.DataFrame, window: str) -> tuple:
    """
    (groups, identities, quiet): the chosen library ships cut to one shared window, in the form
    analyse() takes; quiet = names of ships with no positions in that window.
    """
    groups, ids, quiet = [], [], []
    if not len(chosen):
        return (), (), []
    start, end = window_dates(chosen, window)
    for _, row in chosen.iterrows():
        if not row["data_to"] or row["data_to"] < start or row["data_from"] > end:
            quiet.append(row["name"])
            continue
        f = LIBRARY / "tracks" / row["track_file"]
        data = library_track(row["track_file"], f.stat().st_mtime, start, end)
        groups.append((row["name"], ((f"{safe_name(row['name'])}.csv", data),)))
        ids.append((row["name"], None, row["mmsi"], row["flag"], row["name"], "library", row.get("imo", "")))
    return tuple(groups), tuple(ids), quiet


def prepare(res: dict) -> dict:
    """The analysis tables tidied for display, with survey areas numbered newest first (live on top)."""
    T = res["tables"]
    vessels, ports_tbl = T["vessels"].copy(), T["nearby_ports"].copy()
    for col in ("dataset", "vessel", "name", "mmsi", "imo", "callsign", "flag", "flag_source",
                "ship_type", "destination", "marinetraffic_url", "port_country", "port_country_basis"):
        vessels[col] = (vessels[col].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
                        if col in vessels else "")
    if len(ports_tbl):
        text_cols = ports_tbl.select_dtypes(include=["object", "string"]).columns
        ports_tbl[text_cols] = ports_tbl[text_cols].fillna("")
        ports_tbl["ree_link"] = ports_tbl["ree_link"].fillna("").astype(str)
        ports_tbl[["dataset", "vessel"]] = ports_tbl[["dataset", "vessel"]].astype(str)
    if len(ports_tbl) and "match_country" not in ports_tbl:
        ports_tbl["match_country"] = ""
    linked = ports_tbl[ports_tbl["ree_link"] != ""] if len(ports_tbl) else ports_tbl
    home = ports_tbl[ports_tbl["match_country"] != ""] if len(ports_tbl) else ports_tbl
    if len(vessels):
        vessels["flag_shown"] = vessels["flag"].replace("", "Unknown")

    areas = T["survey_areas"].copy()
    if not len(areas):     # nothing found: keep the columns pages and exports rely on
        areas = pd.DataFrame(columns=["dataset", "vessel", "area_id", "status", "n_lines", "block_ids", "area_km2",
                                      "centroid_lat", "centroid_lon", "start_time", "end_time", "median_spacing_km",
                                      "live", "number"])
    if len(areas):
        areas[["dataset", "vessel"]] = areas[["dataset", "vessel"]].astype(str)
        areas["live"] = areas["status"].astype(str).str.startswith("IN")
        areas["_end"] = areas["end_time"].astype(str) if "end_time" in areas else ""
        areas = areas.sort_values(["live", "_end"], ascending=[False, False]).reset_index(drop=True)
        areas["number"] = np.arange(1, len(areas) + 1)
    labels = tuple(((r["dataset"], r["vessel"], int(r["area_id"])), int(r["number"]))
                   for _, r in areas.iterrows()) if len(areas) else ()
    return {"vessels": vessels, "ports": ports_tbl, "areas": areas, "preds": T["predictions"],
            "hotspots": T["survey_hotspots"], "linked": linked, "home": home, "labels": labels,
            "res": res}


PORTS_FILE = HERE / "reference_data" / "world_ports.csv"
GFW_INFO = LIBRARY / "gfw_vessel_info.csv"
GFW_EVENTS = LIBRARY / "gfw_events.csv"


class _ISAUnavailable(Exception):
    pass


@st.cache_data(show_spinner=False, ttl=86400)
def _isa_fetch() -> list:
    """Raises when the service is unreachable, so a failure is never cached."""
    feats, offset = [], 0
    try:
        while True:
            url = (f"{ISA_SERVICE}/{ISA_LAYERS['active']}/query?where=1%3D1&outSR=4326&f=geojson"
                   f"&returnGeometry=true&maxAllowableOffset=0.01&geometryPrecision=3&outFields=ContractID"
                   f"&resultOffset={offset}&resultRecordCount=1000")
            req = urllib.request.Request(url, headers={"User-Agent": "SurveyDetector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                page = json.loads(r.read())
            feats += page.get("features", [])
            if not page.get("features") or not page.get("properties", {}).get("exceededTransferLimit"):
                break
            offset += len(page["features"])
    except Exception as exc:
        raise _ISAUnavailable(str(exc)) from exc
    if not feats:
        raise _ISAUnavailable("no features")
    return feats


_ISA_DOWN_UNTIL = 0.0          # after a failed fetch, don't make every visitor wait for the timeout again
ISA_RETRY_SECONDS = 600


def isa_zones() -> list | None:
    """
    ISA exploration contract areas (active contracts), read live from the ISA's public service and
    kept in memory for a day; never written to disk (ISA terms). None while the service is unreachable
    (tried again on the next call).
    """
    global _ISA_DOWN_UNTIL
    if time.time() < _ISA_DOWN_UNTIL:
        return None
    try:
        return _isa_fetch()
    except _ISAUnavailable:
        _ISA_DOWN_UNTIL = time.time() + ISA_RETRY_SECONDS
        return None


def _isa_clear() -> None:
    global _ISA_DOWN_UNTIL
    _ISA_DOWN_UNTIL = 0.0
    _isa_fetch.clear()


isa_zones.clear = _isa_clear


@st.cache_data(show_spinner=False)
def ports_table(stamp: float) -> pd.DataFrame:
    return pd.read_csv(PORTS_FILE, usecols=["port", "country", "lat", "lon"]).dropna(subset=["lat", "lon"])


@st.cache_data(show_spinner=False)
def gfw_tables(stamp: tuple) -> tuple[pd.DataFrame, pd.DataFrame]:
    """GFW registry info and events written by gfw_fetch.py --enrich (empty until the first run)."""
    try:
        info = pd.read_csv(GFW_INFO, dtype=str).fillna("")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        info = pd.DataFrame(columns=["mmsi", "vessel_type"])
    try:
        ev = pd.read_csv(GFW_EVENTS, dtype={"mmsi": str}, low_memory=False)
        for c in ("start", "end"):
            ev[c] = pd.to_datetime(ev[c], utc=True, errors="coerce")
    except (FileNotFoundError, pd.errors.EmptyDataError, KeyError, ValueError):
        ev = pd.DataFrame(columns=["mmsi", "kind", "start", "end", "lat", "lon", "hours"])
    return info, ev


def _stamp(path: Path):
    return path.stat().st_mtime if path.exists() else 0.0


def tracks_from_groups(groups: tuple) -> dict:
    """{(dataset, vessel): standardized track} for the files that were analysed."""
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for dataset, files in groups:
            frames = []
            for name, data in files:
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / Path(name).name
                    f.write_bytes(data)
                    try:
                        frames.append(spd.standardize(spd.read_any(f), f.stem)[0])
                    except (ValueError, KeyError):
                        continue            # the detector reports unreadable files itself
            std = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if std.empty:
                continue
            for vessel, tr in std.groupby(std["vessel"].astype(str)):
                out[(str(dataset), vessel)] = tr[["time", "lat", "lon", "speed_kn"]].reset_index(drop=True)
    return out


def with_intel(prepared: dict, groups: tuple, station: dict | None = None) -> dict:
    """Add the detections / priority / ship events (intel.py) to a prepared result."""
    tracks = tracks_from_groups(groups)
    newest = max((tr["time"].max() for tr in tracks.values() if tr["time"].notna().any()), default=None)
    info, ev = gfw_tables((_stamp(GFW_INFO), _stamp(GFW_EVENTS)))
    prepared["intel"] = intel.build(prepared, tracks, ports_table(_stamp(PORTS_FILE)), info, ev,
                                    intel.isa_index(isa_zones()), newest,
                                    station_cfg=stationkeeping.StationConfig(**station) if station else None)
    prepared["tracks"] = tracks
    return prepared


@st.cache_resource(show_spinner=False, max_entries=3)
def _public(group: str, window: str, countries: tuple, settings_items: tuple, stamp: tuple, isa_key: str) -> dict | None:
    """Shared by every visitor (cache_resource: one copy in memory, not one per reader)."""
    chosen = select_ships(library(), group, countries)
    groups, ids, _ = build_groups(chosen, window)
    if not groups:
        return None
    return with_intel(prepare(_run_analysis(groups, dict(settings_items), ids)), groups)


def public_results(group: str, window: str, countries: tuple = (), settings: dict | None = None,
                   station: dict | None = None) -> dict | None:
    """
    Survey results for a ship group and time window. settings=None: the default detector settings,
    computed once and shared. Custom settings run (and cache) separately through analyse().
    None when no chosen ship has positions in the window.
    """
    group = group if group in GROUPS else "mining"
    window = window if window in WINDOWS else "6m"
    if settings is None and station is None:
        # built while the ISA service is down: keyed by the hour, so it is rebuilt once ISA is back
        isa_key = "isa" if isa_zones() is not None else f"no-isa-{datetime.datetime.now(datetime.timezone.utc):%Y%m%d%H}"
        return _public(group, window, tuple(sorted(countries)),
                       tuple(sorted(default_settings().items())), library_files(), isa_key)
    chosen = select_ships(library(), group, tuple(countries))
    groups, ids, _ = build_groups(chosen, window)
    if not groups:
        return None
    return with_intel(prepare(analyse(groups, settings or default_settings(), ids)), groups, station)


# ============================================================ hand-written reference notes
WATCH_ITEMS = HERE / "reference_data" / "watch_items.csv"
REFERENCE_EVENTS = HERE / "reference_data" / "reference_events.csv"


@st.cache_data(show_spinner=False)
def _notes(path: str, stamp: float) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=["mmsi"])


def watch_items() -> pd.DataFrame:
    return _notes(str(WATCH_ITEMS), _stamp(WATCH_ITEMS))


def reference_events() -> pd.DataFrame:
    return _notes(str(REFERENCE_EVENTS), _stamp(REFERENCE_EVENTS))


def hotspot_mmsis(text: str) -> list[str]:
    """MMSIs in a hotspot's 'vessels' text ("Name (mmsi); Name (mmsi)")."""
    return re.findall(r"\((\d{6,9})\)", str(text))


# ============================================================ uploads (Analyst)
def groups_from_uploads(files: list, combine: bool) -> tuple:
    """[(file name, bytes)] -> analyse() groups: one dataset per file (names made unique) or one combined."""
    if combine:
        return (("Combined upload", tuple(files)),) if files else ()
    taken, out = set(), []
    for name, raw in files:
        base = Path(name).stem
        label, n = base, 2
        while label in taken:
            label, n = f"{base} ({n})", n + 1
        taken.add(label)
        out.append((label, ((name, raw),)))
    return tuple(out)


def run_upload(groups: tuple, identities: tuple, settings: dict | None = None,
               station: dict | None = None) -> tuple[dict | None, str | None]:
    """Analyse uploaded files: (results, None), or (None, a message saying what went wrong)."""
    try:
        res = analyse(groups, settings or default_settings(), identities)
    except (ValueError, KeyError, FileNotFoundError, ImportError, pd.errors.ParserError) as exc:
        return None, f"Could not read the data: {exc}"
    prepared = prepare(res)
    if not len(prepared["vessels"]):
        return None, "No ship positions found in these files: check that they have latitude and longitude columns."
    return with_intel(prepared, groups, station), None


def parse_labels(raw: bytes) -> tuple[dict | None, str | None]:
    """A labels CSV (vessel, is_survey 1/0) -> ({vessel: 0/1}, None), or (None, what is wrong)."""
    try:
        lab = pd.read_csv(io.BytesIO(raw), dtype=str)
    except Exception as exc:
        return None, f"Could not read the labels file ({type(exc).__name__})."
    if not {"vessel", "is_survey"} <= set(lab.columns):
        return None, ("A labels file needs the columns vessel and is_survey (1 or 0). Use the Alert queue's "
                      "'Download as labels', not the reviews export.")
    vals = pd.to_numeric(lab["is_survey"], errors="coerce")
    if vals.isna().any() or not vals.isin([0, 1]).all():
        return None, "is_survey must be 1 or 0 on every row."
    return dict(zip(lab["vessel"].astype(str), vals.astype(int))), None



# ============================================================ the SeaTrace console's data
def _console_blob(group: str, window: str) -> dict | None:
    """The console's data for a ship group and season with the default settings (slow: runs the detector)."""
    from webapp import seatrace_export as sx
    # built from an uncached analysis: the console only needs the finished data, so the (large) results,
    # tracks and tables are dropped as soon as it exists instead of sitting in the shared cache
    chosen = select_ships(library(), group)
    groups, ids, _ = build_groups(chosen, window)
    if not groups:
        return None
    res = with_intel(prepare(_run_analysis(groups, default_settings(), ids)), groups)
    blob = sx.build_blob(res, library(), isa_zones(), view={"group": group, "time": window})
    del res
    gc.collect()
    return blob


def _finish(blob: dict) -> tuple[str, str, str]:
    from webapp import seatrace_export as sx
    return (sx.to_json(blob),) + sx.header_text(blob)


@st.cache_resource(show_spinner=False, max_entries=3)
def _payload(group: str, window: str, stamp: tuple, isa_key: str) -> tuple[str, str, str] | None:
    blob = _console_blob(group, window)
    if blob is None:
        return None
    out = _finish(blob)
    del blob
    gc.collect()
    return out


# ------------------------------------------------ built ahead of time (scripts/build_console_data.py)
# The weekly update (and every push to main) builds the console data for each ship group and season and
# commits it to prebuilt/, so a visitor gets it at once instead of waiting about a minute for the detector.
# A file is used only when its fingerprint matches the ship data and detector code the site is running.
# ISA polygons are never written (they are read live and added at page load).
PREBUILT = HERE / "prebuilt"
_STAMP_CODE = ["survey_pattern_detector.py", "intel.py", "stationkeeping.py", "track_events.py", "port_intel.py",
               "resource_context.py", "geo_lookup.py", "isa_contracts.py", "webapp/data.py", "webapp/seatrace_export.py",
               "benchmarks/regression_results.json"]


def stamp_inputs() -> list[Path]:
    """Every file the console data depends on: ship library, reference data, detector and model code."""
    files = [HERE / f for f in _STAMP_CODE] + sorted((HERE / "models").glob("*.py"))
    files += sorted(f for f in (HERE / "reference_data").rglob("*") if f.is_file())
    files += [Path(f) for f, _ in library_files()] + [WATCHLIST]
    return [f for f in files if f.is_file() and not f.name.startswith(".")]     # .DS_Store etc. are not on GitHub


@st.cache_data(show_spinner=False, max_entries=4)
def _inputs_stamp(key: tuple) -> str:
    h = hashlib.sha256()
    for name, _ in key:
        f = Path(name)
        h.update(f.relative_to(HERE).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:20]


def inputs_stamp() -> str:
    """Content fingerprint of stamp_inputs() (by content, not modified time: a git checkout resets those)."""
    return _inputs_stamp(tuple((str(f), f.stat().st_mtime) for f in stamp_inputs()))


def prebuilt_path(group: str, window: str) -> Path:
    return PREBUILT / f"{group}_{window}.json.gz"


def write_prebuilt(group: str, window: str) -> Path:
    """Build the console data now and save it (without ISA polygons) for the site to read."""
    from webapp import seatrace_export as sx
    blob = _console_blob(group, window)
    if blob is not None:
        blob["zones"] = []
    # no build time inside: the same inputs give the same bytes, so an unchanged rebuild commits nothing
    meta = {"stamp": inputs_stamp(), "isa": isa_zones() is not None, "group": group, "window": window, "blob": blob}
    path = prebuilt_path(group, window)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(sx.to_json(meta).encode(), compresslevel=9, mtime=0))
    return path


def _read_prebuilt(group: str, window: str, stamp: str, isa_up: bool) -> dict | None:
    """The saved file's contents if it is current, else None. Built while ISA was down: current only while it still is."""
    try:
        meta = json.loads(gzip.decompress(prebuilt_path(group, window).read_bytes()))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if meta.get("stamp") != stamp or (isa_up and not meta.get("isa")):
        return None
    return meta


@st.cache_resource(show_spinner=False, max_entries=6)
def _prebuilt_payload(group: str, window: str, stamp: str, isa_key: str, file_key: float):
    """(json, banner, subtitle) from the saved file with today's ISA areas; None: no ships; False: no usable file."""
    from webapp import seatrace_export as sx
    zones = isa_zones()
    meta = _read_prebuilt(group, window, stamp, zones is not None)
    if meta is None:
        return False
    blob = meta["blob"]
    if blob is None:
        return None
    blob["zones"] = sx.zones_list(zones)
    return _finish(blob)


def public_payload(group: str, window: str, settings: dict | None = None, station: dict | None = None):
    """(json, banner, subtitle) for the console: shared for default settings, per visitor otherwise."""
    from webapp import seatrace_export as sx
    group = group if group in GROUPS else "mining"
    window = window if window in WINDOWS else "6m"
    if settings is None and station is None:
        isa_key = "isa" if isa_zones() is not None else f"no-isa-{datetime.datetime.now(datetime.timezone.utc):%Y%m%d%H}"
        path = prebuilt_path(group, window)
        if path.is_file():
            pre = _prebuilt_payload(group, window, inputs_stamp(), isa_key, path.stat().st_mtime)
            if pre is not False:
                return pre
        return _payload(group, window, library_files(), isa_key)
    key = ("payload", group, window, tuple(sorted((settings or {}).items())), tuple(sorted((station or {}).items())))
    if st.session_state.get("custom_payload_key") != key:      # one custom payload per visitor
        res = public_results(group, window, settings=settings, station=station)
        if res is None:
            st.session_state["custom_payload"] = None
        else:
            blob = sx.build_blob(res, library(), isa_zones(), station, view={"group": group, "time": window})
            st.session_state["custom_payload"] = (sx.to_json(blob),) + sx.header_text(blob)
        st.session_state["custom_payload_key"] = key
    return st.session_state["custom_payload"]
