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
LIST_META = HERE / "library" / "screening_list.json"      # {"fetched": "YYYY-MM-DD", "rows": n}, written with the list

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


def safe_url(url: str) -> str:
    """Only plain web links reach the page (no javascript: or data: URLs from list or links text)."""
    u = str(url or "").strip()
    return u if re.match(r"^https?://", u, re.I) else ""


def _hit(row, score: float, level: str) -> dict:
    return {"list": short_list(row["source"]), "source": row["source"], "program": row["programs"],
            "entry": row["name"], "score": round(score, 3), "level": level,
            "url": safe_url(row["source_information_url"]) or safe_url(row["source_list_url"]), "date": row["start_date"]}


def screen(name: str, lst: pd.DataFrame, confirmed: set[str] | frozenset = frozenset(),
           truncated: bool = False) -> list[dict]:
    """List entries matching a company name: likely (exact, other name, or - for a name the GFW registry cut
    short, truncated=True - a prefix), possible (similar, or a short one-word name), confirmed (a likely hit on
    a list the team verified for this name in entity_links.csv)."""
    q = normalise(name)
    if len(q) < MIN_LEN or not len(lst):
        return []
    generic = " " not in q and len(q) < 6        # "OCEAN", "WORLD": too common to call a match likely
    starts = {w[:3] for w in q.split()}
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
        if generic:
            level = "possible"
        hit = _hit(row, score, level)
        if level == "likely" and hit["list"] in confirmed:
            hit["level"] = "confirmed"
        hits.append(hit)
    order = {"confirmed": 0, "likely": 1, "possible": 2}
    return sorted(hits, key=lambda h: (order[h["level"]], -h["score"], h["list"], h["entry"]))


# ============================================================ ship -> owner -> parent -> lists
LINK_COLUMNS = ["match_name", "parent", "ultimate_owner", "state_owned", "country", "confirmed_lists", "note", "source"]


def load_links(path: Path = LINKS_FILE) -> pd.DataFrame:
    """The team's owner -> parent links; rows without a match_name are skipped (and reported)."""
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except (FileNotFoundError, OSError, ValueError, pd.errors.EmptyDataError):
        df = pd.DataFrame(columns=LINK_COLUMNS)
    df = df.reindex(columns=LINK_COLUMNS).fillna("")
    bad = df["match_name"].str.strip() == ""
    if bad.any():
        print(f"entity_links.csv: skipped {int(bad.sum())} row(s) without a match_name")
    df = df[~bad].copy()
    df["norm"] = df["match_name"].map(normalise)
    return df.reset_index(drop=True)


def _link_for(owner: str, links: pd.DataFrame, truncated: bool = False):
    """The links row for an owner: exact name, else the longest row whose whole words begin the owner's name;
    a row longer than the owner's name only when the registry cut that name short (truncated)."""
    q = normalise(owner)
    if not q or not len(links):
        return None
    best = None
    for _, r in links.iterrows():
        n = r["norm"]
        if not n:
            continue
        if q == n:
            return r
        ok = (len(n) >= MIN_PREFIX and q.startswith(n + " ")) or (truncated and len(q) >= MIN_PREFIX and n.startswith(q))
        if ok and (best is None or len(n) > len(best["norm"])):
            best = r
    return best


def _vessel_hits(ship: dict, lst: pd.DataFrame) -> list[dict]:
    """Listed vessels with this ship's IMO number (likely) or only its exact name (possible: names repeat);
    ship names never match companies."""
    if not len(lst):
        return []
    v = lst[lst["type"] == "Vessel"]
    imo = re.sub(r"\D", "", str(ship.get("imo") or ""))
    q = normalise(ship.get("name", ""))
    out = []
    for _, row in v.iterrows():
        if len(imo) == 7 and f"IMO {imo}" in row["ids"]:
            out.append(_hit(row, 1.0, "likely"))
        elif len(q) >= MIN_LEN and q in [row["norm"], *row["norm_alts"]]:
            out.append(_hit(row, 1.0, "possible"))
    return out


def ship_chain(ship: dict, registry_owner: str, links: pd.DataFrame, lst: pd.DataFrame) -> dict:
    """The ownership half of the chain for one ship (ship: name, imo, flag, operator)."""
    owner, src, notes = None, None, []
    if str(registry_owner or "").strip():
        owner, src = str(registry_owner).strip(), "GFW registry"
    elif str(ship.get("operator") or "").strip():
        owner, src = str(ship["operator"]).strip(), "catalog"
    else:
        notes.append("Owner unknown: no owner in the GFW registry or the ship catalog")
    cut = src == "GFW registry" and len(owner or "") >= TRUNCATED
    link = _link_for(owner, links, truncated=cut) if owner else None
    parent = (link["parent"] or None) if link is not None else None
    ultimate = (link["ultimate_owner"] or None) if link is not None else None
    verified = [x.strip() for x in link["confirmed_lists"].split(";") if x.strip()] if link is not None else []
    hits, seen = [], set()
    speaks_for = "parent" if parent else "owner"           # the entity the links row's verified lists are about
    for who, name in (("owner", owner), ("parent", parent), ("ultimate_owner", ultimate)):
        conf = set(verified) if who == speaks_for else set()
        for h in screen(name, lst, conf, truncated=cut and who == "owner") if name else []:
            if (h["list"], h["entry"]) not in seen:
                seen.add((h["list"], h["entry"]))
                hits.append({**h, "matched": who})
    state = {"yes": True, "no": False}.get(link["state_owned"].strip().lower()) if link is not None else None
    return {"ship_hits": _vessel_hits(ship, lst), "owner": owner, "owner_source": src, "parent": parent,
            "ultimate_owner": ultimate, "state_owned": state, "country": (link["country"] or None) if link is not None else None,
            "verified_lists": verified, "verified_for": speaks_for if verified else None, "hits": hits, "notes": notes,
            "link_note": (link["note"] or None) if link is not None else None,
            "link_source": (link["source"] or None) if link is not None else None,
            "link_url": safe_url(str(link["source"]).split(" ; ")[0]) if link is not None else ""}


# ============================================================ area -> contract -> minerals -> processing
NEAR_KM = 300.0
MINERALS = {"nodules": ["nickel", "cobalt", "copper", "manganese"],
            "sulphides": ["copper", "zinc", "gold", "silver"],
            "crusts": ["cobalt", "manganese", "nickel", "tellurium", "platinum", "rare earths"]}
CODES = {"Ni": "nickel", "Co": "cobalt", "Cu": "copper", "Mn": "manganese", "REE": "rare earths", "Zn": "zinc",
         "Au": "gold", "Ag": "silver", "Te": "tellurium", "Pt": "platinum"}


def _mineral_rows(names: list[str], reliance: pd.DataFrame) -> list[dict]:
    by = {str(r["mineral"]): r for _, r in reliance.fillna("").iterrows()}
    out = []
    for n in names:
        r = by.get(n)
        out.append({"name": n, "reliance_pct": (r["net_import_reliance_pct"] if r is not None else "") or None,
                    "top_sources": (r["top_sources"] if r is not None else "") or None,
                    "critical": (r["us_critical_mineral"] == "yes") if r is not None else None,
                    "year": (r["year"] if r is not None else "") or None})
    return out


def area_chain(event: dict, reliance: pd.DataFrame, ree_sites: pd.DataFrame) -> dict:
    """The resource half of the chain for one detection (event: zone, nearZone, nearZoneKm, center)."""
    from isa_contracts import ISA_CONTRACTORS, mineral_of
    import resource_context
    cid, basis, region, names, notes = None, None, None, [], []
    if event.get("zone"):
        cid, basis = event["zone"], "inside"
    elif event.get("nearZone") and event.get("nearZoneKm") is not None and float(event["nearZoneKm"]) <= NEAR_KM:
        cid, basis = event["nearZone"], "near"
    if cid:
        names = MINERALS[mineral_of(cid)]
    else:
        lat, lon = event.get("center") or (None, None)
        hits = resource_context.regions_at(float(lat), float(lon)) if lat is not None else pd.DataFrame()
        if len(hits):
            r = hits.iloc[0]
            region, basis = str(r["name"]), "region"
            names = list(dict.fromkeys(CODES[c] for c in re.findall(r"\b(Ni|Co|Cu|Mn|REE|Zn|Au|Ag|Te|Pt)\b", str(r["commodities"]))))
        else:
            notes.append("Not in or within 300 km of an ISA contract, and outside the known seabed resource regions")
    contractor, sponsor = ISA_CONTRACTORS.get(cid, (cid, "")) if cid else (None, None)
    proc = []
    if "rare earths" in names and len(ree_sites):
        p = ree_sites[ree_sites["type"] == "processing"]
        proc = [{"site": r["name"], "operator": r["operator"], "country": r["country"]} for _, r in p.iterrows()]
    return {"contract": cid, "contractor": contractor, "sponsor": sponsor or None, "basis": basis, "region": region,
            "minerals": _mineral_rows(names, reliance), "processing": proc, "notes": notes}


# ============================================================ across detections
LEVEL_ORDER = {"confirmed": 0, "likely": 1, "possible": 2, None: 3}


def chips(chain: dict) -> list[dict]:
    """Every list hit for a ship's chain, each with its own level and the link it is about (ship, owner,
    parent, ultimate_owner), team-verified lists included."""
    out = [{"list": h["list"], "level": h["level"], "matched": h["matched"]} for h in chain["hits"]]
    out += [{"list": h["list"], "level": h["level"], "matched": "ship"} for h in chain["ship_hits"]]
    out += [{"list": l, "level": "confirmed", "matched": chain["verified_for"]} for l in chain["verified_lists"]]
    best = {}
    for c in out:
        k = (c["list"], c["matched"])
        if k not in best or LEVEL_ORDER[c["level"]] < LEVEL_ORDER[best[k]["level"]]:
            best[k] = c
    return sorted(best.values(), key=lambda c: (LEVEL_ORDER[c["level"]], c["list"], c["matched"]))


def _best(chain: dict):
    levels = [c["level"] for c in chips(chain)]
    return min(levels, key=lambda lv: LEVEL_ORDER[lv]) if levels else None


def entities(ships: dict[str, dict], events: list[dict], areas: dict[str, dict]) -> list[dict]:
    """One row per parent company (or owner when there is no known parent), with its ships, detections,
    restricted lists and the minerals of the areas it surveyed. Listed entities first, then by detections."""
    rows = {}
    for vid, c in ships.items():
        name = c["parent"] or c["owner"]
        if not name:
            continue
        r = rows.setdefault(name, {"name": name, "kind": "parent" if c["parent"] else "owner", "country": c["country"],
                                   "state_owned": c["state_owned"], "ultimate_owner": c["ultimate_owner"],
                                   "ships": [], "events": [], "chips": {}, "minerals": set(), "best": None})
        r["ships"].append(vid)
        for ch in chips(c):
            k = (ch["list"], ch["matched"])
            if k not in r["chips"] or LEVEL_ORDER[ch["level"]] < LEVEL_ORDER[r["chips"][k]["level"]]:
                r["chips"][k] = ch
        b = _best(c)
        if LEVEL_ORDER[b] < LEVEL_ORDER[r["best"]]:
            r["best"] = b
    owner_of = {vid: (c["parent"] or c["owner"]) for vid, c in ships.items()}
    for e in events:
        name = owner_of.get(e["vessel"])
        if name in rows:
            rows[name]["events"].append(e["id"])
            rows[name]["minerals"] |= {m["name"] for m in (areas.get(e["id"]) or {}).get("minerals", [])}
    out = []
    for r in rows.values():
        ch = sorted(r["chips"].values(), key=lambda c: (LEVEL_ORDER[c["level"]], c["list"], c["matched"]))
        r.update(ships=sorted(r["ships"]), events=sorted(r["events"]), chips=ch, lists=sorted({c["list"] for c in ch}),
                 minerals=sorted(r["minerals"]), detections=len(r["events"]))
        out.append(r)
    return sorted(out, key=lambda r: (LEVEL_ORDER[r["best"]], -r["detections"], r["name"]))
