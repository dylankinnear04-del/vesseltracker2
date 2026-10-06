"""
PORT & VESSEL INTELLIGENCE
==========================

Reference lookups used by survey_pattern_detector.py:

* Nearby ports for a survey area, from the NGA World Port Index (Pub. 150,
  public domain): reference_data/world_ports.csv
* Rare-earth sites: processing and separation plants, magnet plants, mines,
  ports that handle rare-earth cargo, and seabed-mineral areas. Curated and
  editable: reference_data/ree_sites.csv (add rows to extend it; locations
  are approximate, so verify before relying on them).
* Flag state from an MMSI (ITU Maritime Identification Digits) and plain
  names for AIS ship-type codes.

A port is "rare-earth linked" when it is (a) one of the logistics ports in
ree_sites.csv, or (b) within LINK_KM of a processing / magnet site or a mine.
Distances follow shipping lanes when the searoute package is installed
and are straight-line otherwise; both are approximate.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

REF = Path(__file__).resolve().parent / "reference_data"
EARTH_RADIUS_KM = 6371.0088
KM_PER_NM = 1.852

LINK_KM = 300.0            # port counts as near a processing site / mine within this
LOGISTICS_MATCH_KM = 30.0  # a WPI port this close to a listed logistics port is that port
SIZE_ORDER = {"Large": 4, "Medium": 3, "Small": 2, "Very Small": 1, "Unknown": 0}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ============================================================
# REFERENCE DATA
# ============================================================

@lru_cache(maxsize=1)
def load_ree_sites() -> pd.DataFrame:
    path = REF / "ree_sites.csv"
    if not path.exists():
        return pd.DataFrame(columns=["name", "type", "status", "operator", "country", "lat", "lon", "notes"])
    return pd.read_csv(path).fillna({"operator": "", "notes": ""})


@lru_cache(maxsize=1)
def load_ports() -> pd.DataFrame:
    """World ports, each tagged with its nearest rare-earth site and why it is linked."""
    path = REF / "world_ports.csv"
    if not path.exists():
        return pd.DataFrame()
    ports = pd.read_csv(path)
    ports["size_rank"] = ports["harbor_size"].map(SIZE_ORDER).fillna(0).astype(int)

    sites = load_ree_sites()
    onshore = sites[sites["type"].isin(["processing", "magnet", "mine"])]
    logistics = sites[sites["type"] == "logistics port"]
    ports["ree_link"] = ""
    ports["ree_site"] = ""
    ports["ree_site_type"] = ""
    ports["ree_site_status"] = ""
    ports["ree_site_km"] = np.nan

    if len(onshore):
        d = haversine_km(ports["lat"].to_numpy()[:, None], ports["lon"].to_numpy()[:, None],
                         onshore["lat"].to_numpy()[None, :], onshore["lon"].to_numpy()[None, :])
        # rank processing / magnet sites ahead of mines at a similar distance
        weight = np.where(onshore["type"].to_numpy() == "mine", 1.5, 1.0)
        best = np.argmin(d * weight[None, :], axis=1)
        best_km = d[np.arange(len(ports)), best]
        site = onshore.iloc[best]
        ports["ree_site"] = site["name"].to_numpy()
        ports["ree_site_type"] = site["type"].to_numpy()
        ports["ree_site_status"] = site["status"].to_numpy()
        ports["ree_site_km"] = np.round(best_km, 1)
        near = best_km <= LINK_KM
        kind = np.where(site["type"].to_numpy() == "mine", "Near rare-earth mine",
                        "Near rare-earth processing site")
        ports.loc[near, "ree_link"] = kind[near]

    if len(logistics):
        d = haversine_km(ports["lat"].to_numpy()[:, None], ports["lon"].to_numpy()[:, None],
                         logistics["lat"].to_numpy()[None, :], logistics["lon"].to_numpy()[None, :])
        hit = d.min(axis=1) <= LOGISTICS_MATCH_KM
        ports.loc[hit, "ree_link"] = "Known rare-earth cargo port"
        ports.loc[hit, "ree_note"] = logistics["notes"].to_numpy()[d.argmin(axis=1)][hit]
    if "ree_note" not in ports:
        ports["ree_note"] = ""
    ports["ree_note"] = ports["ree_note"].fillna("")
    return ports


# ============================================================
# NEARBY PORTS
# ============================================================

PORT_COLUMNS = ["port", "country", "harbor_size", "sea_km", "sea_nm", "hours_at_10kn",
                "straight_km", "distance_basis", "ree_link", "ree_site", "ree_site_type",
                "ree_site_status", "ree_site_km", "ree_note", "max_vessel_draft_m",
                "channel_depth_m", "solid_bulk", "railway", "dry_dock", "unlocode", "lat", "lon"]

CANDIDATES = 30   # ports per list re-measured along sea routes (straight-line pre-filter)


def sea_route(lat: float, lon: float, port_lat: float, port_lon: float):
    """
    (km, [[lon, lat], ...]) along shipping lanes, using the searoute package's
    maritime network, or (None, None) without it. Includes the legs from the
    survey onto the network and from the network into the port.
    """
    try:
        import searoute
    except ImportError:
        return None, None
    try:
        r = searoute.searoute([lon, lat], [port_lon, port_lat], units="km")
    except Exception:  # noqa: BLE001 - a route the network cannot make
        return None, None
    coords = [[lon, lat]] + [list(c[:2]) for c in r.geometry["coordinates"]] + [[port_lon, port_lat]]
    c = np.array(coords)
    legs = haversine_km(c[:-1, 1], c[:-1, 0], c[1:, 1], c[1:, 0])
    km = float(legs.sum())
    # the network is broken at the 180th meridian: routes there run down the
    # date line and back (Chukchi Sea to Nome came out at 7,100 km). Treat
    # those, and any route over 4x the straight line, as unknown.
    on_dateline = (np.abs(c[:-1, 0]) >= 179.99) & (np.abs(c[1:, 0]) >= 179.99) & (np.abs(np.diff(c[:, 1])) > 1)
    if on_dateline.any() or km > 4 * max(float(haversine_km(lat, lon, port_lat, port_lon)), 50.0):
        return None, None
    return km, coords


def nearby_ports(lat: float, lon: float, n_nearest: int = 8, n_linked: int = 6,
                 min_linked_size: int = 2) -> list[dict]:
    """
    Ports for a survey area centred at (lat, lon): the n_nearest ports of any
    size, then the n_linked nearest rare-earth linked ports of at least Small
    size (offloading cargo needs more than an anchorage). Ranked by sea-route
    distance when the searoute package is installed, else straight-line.
    Each row carries its route as `route` ([[lon, lat], ...]) for maps.
    """
    ports = load_ports()
    if not len(ports):
        return []
    straight = haversine_km(lat, lon, ports["lat"].to_numpy(), ports["lon"].to_numpy())
    ports = ports.assign(straight_km=np.round(straight, 1))

    def measure(pool: pd.DataFrame, n: int, category: str) -> pd.DataFrame:
        pool = pool.nsmallest(CANDIDATES, "straight_km").copy()
        routes = [sea_route(lat, lon, r.lat, r.lon) for r in pool.itertuples()]
        km = [max(r[0], s) if r[0] is not None else s for r, s in zip(routes, pool["straight_km"])]
        pool["sea_km"] = np.round(km, 1)
        pool["distance_basis"] = ["sea route" if r[0] is not None else "straight line" for r in routes]
        pool["route"] = [r[1] if r[1] else [[lon, lat], [p_lon, p_lat]]
                         for r, p_lon, p_lat in zip(routes, pool["lon"], pool["lat"])]
        return pool.nsmallest(n, "sea_km").assign(category=category)

    nearest = measure(ports, n_nearest, "nearest port")
    linked = ports[(ports["ree_link"] != "") & (ports["size_rank"] >= min_linked_size)
                   & ~ports.index.isin(nearest.index)]
    linked = measure(linked, n_linked, "nearest rare-earth linked port") if len(linked) else linked

    out = pd.concat([nearest, linked])
    out["sea_nm"] = np.round(out["sea_km"] / KM_PER_NM, 1)
    out["hours_at_10kn"] = np.round(out["sea_nm"] / 10, 1)
    unlinked = out["ree_link"] == ""          # a site 3,000 km away is not a link
    out.loc[unlinked, ["ree_site", "ree_site_type", "ree_site_status"]] = ""
    out.loc[unlinked, "ree_site_km"] = np.nan
    out = out[["category"] + PORT_COLUMNS + ["route"]]
    return [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()}
            for r in out.to_dict("records")]


def nearby_ree_sites(lat: float, lon: float, n: int = 5) -> list[dict]:
    """The n rare-earth sites (any type) closest to (lat, lon)."""
    sites = load_ree_sites()
    if not len(sites):
        return []
    d = haversine_km(lat, lon, sites["lat"].to_numpy(), sites["lon"].to_numpy())
    near = sites.assign(distance_km=np.round(d, 1)).nsmallest(n, "distance_km")
    return near.to_dict("records")


# ============================================================
# VESSEL IDENTITY
# ============================================================

MID_COUNTRY = {
    201: "Albania", 202: "Andorra", 203: "Austria", 204: "Portugal (Azores)", 205: "Belgium",
    206: "Belarus", 207: "Bulgaria", 208: "Vatican City", 209: "Cyprus", 210: "Cyprus",
    211: "Germany", 212: "Cyprus", 213: "Georgia", 214: "Moldova", 215: "Malta",
    216: "Armenia", 218: "Germany", 219: "Denmark", 220: "Denmark", 224: "Spain",
    225: "Spain", 226: "France", 227: "France", 228: "France", 229: "Malta", 230: "Finland",
    231: "Faroe Islands", 232: "United Kingdom", 233: "United Kingdom", 234: "United Kingdom",
    235: "United Kingdom", 236: "Gibraltar", 237: "Greece", 238: "Croatia", 239: "Greece",
    240: "Greece", 241: "Greece", 242: "Morocco", 243: "Hungary", 244: "Netherlands",
    245: "Netherlands", 246: "Netherlands", 247: "Italy", 248: "Malta", 249: "Malta",
    250: "Ireland", 251: "Iceland", 252: "Liechtenstein", 253: "Luxembourg", 254: "Monaco",
    255: "Portugal (Madeira)", 256: "Malta", 257: "Norway", 258: "Norway", 259: "Norway",
    261: "Poland", 262: "Montenegro", 263: "Portugal", 264: "Romania", 265: "Sweden",
    266: "Sweden", 267: "Slovakia", 268: "San Marino", 269: "Switzerland", 270: "Czechia",
    271: "Turkey", 272: "Ukraine", 273: "Russia", 274: "North Macedonia", 275: "Latvia",
    276: "Estonia", 277: "Lithuania", 278: "Slovenia", 279: "Serbia",
    301: "Anguilla", 303: "United States (Alaska)", 304: "Antigua and Barbuda",
    305: "Antigua and Barbuda", 306: "Curacao / Sint Maarten / Bonaire", 307: "Aruba",
    308: "Bahamas", 309: "Bahamas", 310: "Bermuda", 311: "Bahamas", 312: "Belize",
    314: "Barbados", 316: "Canada", 319: "Cayman Islands", 321: "Costa Rica", 323: "Cuba",
    325: "Dominica", 327: "Dominican Republic", 329: "Guadeloupe", 330: "Grenada",
    331: "Greenland", 332: "Guatemala", 334: "Honduras", 336: "Haiti", 338: "United States",
    339: "Jamaica", 341: "Saint Kitts and Nevis", 343: "Saint Lucia", 345: "Mexico",
    347: "Martinique", 348: "Montserrat", 350: "Nicaragua", 351: "Panama", 352: "Panama",
    353: "Panama", 354: "Panama", 355: "Panama", 356: "Panama", 357: "Panama",
    358: "Puerto Rico", 359: "El Salvador", 361: "Saint Pierre and Miquelon",
    362: "Trinidad and Tobago", 364: "Turks and Caicos Islands", 366: "United States",
    367: "United States", 368: "United States", 369: "United States", 370: "Panama",
    371: "Panama", 372: "Panama", 373: "Panama", 374: "Panama",
    375: "Saint Vincent and the Grenadines", 376: "Saint Vincent and the Grenadines",
    377: "Saint Vincent and the Grenadines", 378: "British Virgin Islands",
    379: "United States Virgin Islands",
    401: "Afghanistan", 403: "Saudi Arabia", 405: "Bangladesh", 408: "Bahrain", 410: "Bhutan",
    412: "China", 413: "China", 414: "China", 416: "Taiwan", 417: "Sri Lanka", 419: "India",
    422: "Iran", 423: "Azerbaijan", 425: "Iraq", 428: "Israel", 431: "Japan", 432: "Japan",
    434: "Turkmenistan", 436: "Kazakhstan", 437: "Uzbekistan", 438: "Jordan",
    440: "South Korea", 441: "South Korea", 443: "Palestine", 445: "North Korea",
    447: "Kuwait", 450: "Lebanon", 451: "Kyrgyzstan", 453: "Macao", 455: "Maldives",
    457: "Mongolia", 459: "Nepal", 461: "Oman", 463: "Pakistan", 466: "Qatar", 468: "Syria",
    470: "United Arab Emirates", 471: "United Arab Emirates", 472: "Tajikistan",
    473: "Yemen", 475: "Yemen", 477: "Hong Kong", 478: "Bosnia and Herzegovina",
    501: "France (Adelie Land)", 503: "Australia", 506: "Myanmar", 508: "Brunei",
    510: "Micronesia", 511: "Palau", 512: "New Zealand", 514: "Cambodia", 515: "Cambodia",
    516: "Christmas Island", 518: "Cook Islands", 520: "Fiji", 523: "Cocos (Keeling) Islands",
    525: "Indonesia", 529: "Kiribati", 531: "Laos", 533: "Malaysia",
    536: "Northern Mariana Islands", 538: "Marshall Islands", 540: "New Caledonia",
    542: "Niue", 544: "Nauru", 546: "French Polynesia", 548: "Philippines",
    550: "Timor-Leste", 553: "Papua New Guinea", 555: "Pitcairn Islands",
    557: "Solomon Islands", 559: "American Samoa", 561: "Samoa", 563: "Singapore",
    564: "Singapore", 565: "Singapore", 566: "Singapore", 567: "Thailand", 570: "Tonga",
    572: "Tuvalu", 574: "Vietnam", 576: "Vanuatu", 577: "Vanuatu", 578: "Wallis and Futuna",
    601: "South Africa", 603: "Angola", 605: "Algeria", 607: "France (St Paul and Amsterdam)",
    608: "United Kingdom (Ascension)", 609: "Burundi", 610: "Benin", 611: "Botswana",
    612: "Central African Republic", 613: "Cameroon", 615: "Congo", 616: "Comoros",
    617: "Cabo Verde", 618: "France (Crozet)", 619: "Cote d'Ivoire", 620: "Comoros",
    621: "Djibouti", 622: "Egypt", 624: "Ethiopia", 625: "Eritrea", 626: "Gabon",
    627: "Ghana", 629: "Gambia", 630: "Guinea-Bissau", 631: "Equatorial Guinea",
    632: "Guinea", 633: "Burkina Faso", 634: "Kenya", 635: "France (Kerguelen)",
    636: "Liberia", 637: "Liberia", 638: "South Sudan", 642: "Libya", 644: "Lesotho",
    645: "Mauritius", 647: "Madagascar", 649: "Mali", 650: "Mozambique", 654: "Mauritania",
    655: "Malawi", 656: "Niger", 657: "Nigeria", 659: "Namibia", 660: "Reunion",
    661: "Rwanda", 662: "Sudan", 663: "Senegal", 664: "Seychelles", 665: "Saint Helena",
    666: "Somalia", 667: "Sierra Leone", 668: "Sao Tome and Principe", 669: "Eswatini",
    670: "Chad", 671: "Togo", 672: "Tunisia", 674: "Tanzania", 675: "Uganda",
    676: "DR Congo", 677: "Tanzania", 678: "Zambia", 679: "Zimbabwe",
    701: "Argentina", 710: "Brazil", 720: "Bolivia", 725: "Chile", 730: "Colombia",
    735: "Ecuador", 740: "Falkland Islands", 745: "French Guiana", 750: "Guyana",
    755: "Paraguay", 760: "Peru", 765: "Suriname", 770: "Uruguay", 775: "Venezuela",
}


def flag_from_mmsi(mmsi) -> str:
    """Flag state from a ship's 9-digit MMSI ('' when it is not a ship MMSI)."""
    digits = re.sub(r"\D", "", str(mmsi).split(".")[0])
    if len(digits) != 9 or digits[0] not in "234567":
        return ""
    return MID_COUNTRY.get(int(digits[:3]), "")


AIS_TYPES = {
    30: "Fishing", 31: "Towing", 32: "Towing (large)", 33: "Dredging or underwater operations",
    34: "Diving operations", 35: "Military operations", 36: "Sailing", 37: "Pleasure craft",
    50: "Pilot vessel", 51: "Search and rescue", 52: "Tug", 53: "Port tender",
    54: "Anti-pollution", 55: "Law enforcement", 58: "Medical transport",
    59: "Noncombatant ship",
}


def ship_type_name(value) -> str:
    """Plain name for an AIS ship-type code; text values are passed through."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value).strip()
    try:
        code = int(float(text))
    except ValueError:
        return text
    if code in AIS_TYPES:
        return f"{AIS_TYPES[code]} ({code})"
    for lo, name in ((20, "Wing in ground"), (40, "High-speed craft"), (60, "Passenger"),
                     (70, "Cargo"), (80, "Tanker"), (90, "Other")):
        if lo <= code <= lo + 9:
            return f"{name} ({code})"
    return f"Type {code}"
