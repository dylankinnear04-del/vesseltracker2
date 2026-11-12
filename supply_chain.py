"""
Supply chain for a detected survey: ship -> owner -> parent / ultimate owner -> US restricted lists, and
area -> ISA contractor & sponsoring state -> minerals -> US import reliance -> processing sites.

Data: library/screening_list.csv.gz (US Consolidated Screening List, refreshed weekly by
gfw_fetch.py --screening), reference_data/entity_links.csv (hand-kept by the team: parents, state ownership,
verified list hits), reference_data/mineral_import_reliance.csv (USGS). Matching is advisory: every hit says
how it was found (confirmed by the team, likely, or possible - verify). No network, no Streamlit.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
LIST_FILE = HERE / "library" / "screening_list.csv.gz"
LINKS_FILE = HERE / "reference_data" / "entity_links.csv"
RELIANCE_FILE = HERE / "reference_data" / "mineral_import_reliance.csv"

LIST_COLUMNS = ["name", "alt_names", "source", "programs", "start_date", "source_list_url",
                "source_information_url", "type", "call_sign", "vessel_flag", "ids"]
SUFFIXES = {"JSC", "AO", "OAO", "ZAO", "PJSC", "CO", "COMPANY", "LTD", "LIMITED", "CORP", "CORPORATION", "INC",
            "LLC", "PLC", "GROUP", "HOLDINGS", "SA", "AG", "GMBH"}
SHORT_LISTS = [("Specially Designated Nationals", "SDN"), ("Entity List", "Entity List"),
               ("Chinese Military-Industrial", "CMIC"), ("Military End User", "MEU"),
               ("Sectoral Sanctions", "SSI"), ("Unverified List", "UVL"), ("Denied Persons", "DPL"),
               ("ITAR Debarred", "ITAR Debarred"), ("Nonproliferation", "Nonproliferation"),
               ("Menu-Based", "NS-MBS"), ("Capta", "CAPTA")]
MIN_LEN, MIN_PREFIX, POSSIBLE = 4, 8, 0.88
TRUNCATED = 28          # GFW registry owner names are cut at ~30 characters: only those may match by prefix
ORDINALS = {"FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH"}


def _markers(n: str) -> set[str]:
    """Words that tell sister organisations apart ("Second" vs "Third Institute", "No 1" vs "No 2")."""
    return {w for w in n.split() if w in ORDINALS or w.isdigit()}


def normalise(name: str) -> str:
    """Upper case, no bracketed text or punctuation, no legal-form words ("Yuzhmorgeologiya JSC" -> "YUZHMORGEOLOGIYA")."""
    s = re.sub(r"\([^)]*\)", " ", str(name or "")).upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in SUFFIXES)


def short_list(source: str) -> str:
    return next((short for key, short in SHORT_LISTS if key in str(source)), str(source))


def load_list(path: Path = LIST_FILE) -> pd.DataFrame:
    """The slim screening list with normalised names; an empty frame when the file is missing."""
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except (FileNotFoundError, OSError, ValueError, pd.errors.EmptyDataError):
        df = pd.DataFrame(columns=LIST_COLUMNS)
    df = df.reindex(columns=LIST_COLUMNS).fillna("")
    df["norm"] = df["name"].map(normalise)
    df["norm_alts"] = df["alt_names"].map(lambda a: [n for n in (normalise(x) for x in str(a).split(";")) if n])
    df["words"] = [{w[:3] for n in [a, *b] for w in n.split()} for a, b in zip(df["norm"], df["norm_alts"])]
    return df


def _hit(row, score: float, level: str) -> dict:
    return {"list": short_list(row["source"]), "source": row["source"], "program": row["programs"],
            "entry": row["name"], "score": round(score, 3), "level": level,
            "url": row["source_information_url"] or row["source_list_url"], "date": row["start_date"]}


def screen(name: str, lst: pd.DataFrame, confirmed: set[str] | frozenset = frozenset()) -> list[dict]:
    """List entries matching a company name: likely (exact, other name, or a truncated registry name's prefix),
    possible (similar), confirmed (likely/possible on a list the team verified in entity_links.csv)."""
    q = normalise(name)
    if len(q) < MIN_LEN or not len(lst):
        return []
    starts = {w[:3] for w in q.split()}
    truncated = len(str(name).strip()) >= TRUNCATED
    hits = []
    for _, row in lst[lst["words"].map(lambda ws: bool(ws & starts))].iterrows():
        names = [n for n in [row["norm"], *row["norm_alts"]] if len(n) >= MIN_LEN and _markers(n) == _markers(q)]
        if q in names:
            score, level = 1.0, "likely"
        elif truncated and len(q) >= MIN_PREFIX and any(n.startswith(q) for n in names):
            score, level = 0.95, "likely"
        else:
            score = max((difflib.SequenceMatcher(None, q, n).ratio() for n in names), default=0.0)
            if score < POSSIBLE:
                continue
            level = "possible"
        hit = _hit(row, score, level)
        if hit["list"] in confirmed:
            hit["level"] = "confirmed"
        hits.append(hit)
    order = {"confirmed": 0, "likely": 1, "possible": 2}
    return sorted(hits, key=lambda h: (order[h["level"]], -h["score"], h["list"], h["entry"]))
