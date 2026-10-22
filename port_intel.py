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
Distances and the routes drawn on the map follow shipping lanes (searoute
package) and go around land (a land grid made from Natural Earth); for nearby
ports the shortest way around land is used when the lanes make a detour. All
approximate.
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


# ============================================================
# ROUTES AROUND LAND
# ============================================================
# The shipping-lane network (searoute) is coarse: its legs onto and off the
# network, and some legs near the coast, are straight lines that can cut across
# headlands and islands. Every leg is checked against a land grid and any leg
# over land is re-routed through the water cells around it, then smoothed.
# reference_data/landmask_ne10m.npz: Natural Earth 1:10m land and minor islands
# (public domain) rasterized to a 1/40 degree (~2.8 km) grid.

LANDMASK = REF / "landmask_ne10m.npz"
COAST_GAP_KM = 4.0     # a leg may touch land this close to its ends (ports sit on the shore)
PORT_GAP_KM = 25.0     # ...and this close to a port up a river or deep in a harbour
APPROACH_KM = 60.0     # a re-routed leg may end this far short of a port it cannot reach by water
MAX_WINDOW_CELLS = 400 # search window side when re-routing a leg (bigger windows use coarser cells)
SHORE_BUFFER_KM = 6.0  # routes keep about this far off the coast where there is room...
SHORE_COST = 3.0       # ...because water this close to land counts this many times its length
DIRECT_MAX_KM = 1500.0 # ports closer than this also get a direct over-water route


class _PackedLand:
    """
    The land grid kept as packed bits (13 MB instead of 104 MB unpacked: the web app
    has about 1 GB). Indexed like a bool array with [rows, cols] index arrays.
    """

    def __init__(self, bits, shape):
        self.bits, self.shape = bits, shape

    def __getitem__(self, key):
        rows, cols = np.broadcast_arrays(*key)
        byte = self.bits[rows, cols >> 3]
        return ((byte >> (7 - (cols & 7))) & 1).astype(bool)


@lru_cache(maxsize=1)
def _land_grid():
    """(land grid indexed like a bool array, degrees per cell), or None without the file."""
    try:
        z = np.load(LANDMASK)
    except OSError:
        return None
    h, w = (int(v) for v in z["shape"])
    return _PackedLand(np.ascontiguousarray(z["land_bits"]), (h, w)), float(z["res"])


def _cell(lat, lon, res, shape):
    row = np.clip(((90 - np.asarray(lat, float)) / res).astype(int), 0, shape[0] - 1)
    col = (np.floor(((np.asarray(lon, float) + 180) % 360) / res)).astype(int) % shape[1]
    return row, col


def _leg_hits_land(a, b, grid, ends=(True, True)) -> bool:
    """
    Does the straight leg a -> b ([lon, lat]) cross land, away from its ends? Each of
    `ends` is False (check right up to that end), True (allow COAST_GAP_KM of land)
    or a number of km.
    """
    land, res = grid
    km = float(haversine_km(a[1], a[0], b[1], b[0]))
    n = max(2, int(km / 1.0) + 1)                   # a sample every km
    t = np.linspace(0, 1, n)
    lon, lat = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    gap0, gap1 = (COAST_GAP_KM if e is True else float(e) for e in ends)
    keep = (t * km > gap0) & ((1 - t) * km > gap1)
    if not keep.any():
        return False
    hit = land[_cell(lat[keep], lon[keep], res, land.shape)]
    # clipping the corner of a land cell is below the grid's resolution: it takes
    # three fixes in a row (~2 km) over land to count as crossing it
    return bool((hit[:-2] & hit[1:-1] & hit[2:]).any()) if len(hit) >= 3 else False


def _water_path(a, b, grid, pad_deg: float):
    """
    Shortest path from a to b ([lon, lat], lon may run past +/-180) through
    water cells of a window around them, smoothed; None if there is none.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    land, res = grid
    lo0, lo1 = min(a[0], b[0]) - pad_deg, max(a[0], b[0]) + pad_deg
    la0, la1 = max(min(a[1], b[1]) - pad_deg, -85), min(max(a[1], b[1]) + pad_deg, 85)
    nx, ny = int((lo1 - lo0) / res) + 1, int((la1 - la0) / res) + 1
    if max(nx, ny) > 24 * MAX_WINDOW_CELLS:
        return None
    lons = lo0 + (np.arange(nx) + 0.5) * res
    lats = la1 - (np.arange(ny) + 0.5) * res
    gl, gt = np.meshgrid(lons, lats)
    water = ~land[_cell(gt, gl, res, land.shape)]
    f = -(-max(nx, ny) // MAX_WINDOW_CELLS)
    if f > 1:   # big window: coarser cells, wet if any part is water (keeps straits open)
        ny, nx = -(-ny // f), -(-nx // f)
        pad = ((0, ny * f - water.shape[0]), (0, nx * f - water.shape[1]))
        water = np.pad(water, pad).reshape(ny, f, nx, f).any(axis=(1, 3))
        res = res * f
        gl, gt = np.meshgrid(lo0 + (np.arange(nx) + 0.5) * res, la1 - (np.arange(ny) + 0.5) * res)

    def nearest_water(p):
        """Index of the water cell nearest p (the port itself is often a land cell)."""
        r, c = int((la1 - p[1]) / res), int((p[0] - lo0) / res)
        for rad in range(0, 25):
            r0, r1, c0, c1 = max(r - rad, 0), min(r + rad + 1, ny), max(c - rad, 0), min(c + rad + 1, nx)
            rr, cc = np.nonzero(water[r0:r1, c0:c1])
            if len(rr):
                k = np.argmin((rr + r0 - r) ** 2 + (cc + c0 - c) ** 2)
                return (rr[k] + r0) * nx + cc[k] + c0
        return None

    s, e = nearest_water(a), nearest_water(b)
    if s is None or e is None:
        return None
    idx = np.arange(ny * nx).reshape(ny, nx)
    kx = np.cos(np.radians(gt)) * res * 111.32            # km per cell east-west, by row
    # ships keep off the shore: water within SHORE_BUFFER_KM of land costs more to cross,
    # so routes stand off headlands but can still thread a strait
    rad = max(1, int(round(SHORE_BUFFER_KM / (res * 111.0))))
    dry = np.pad(~water, rad, constant_values=False)
    near = np.zeros_like(water)
    for dr in range(-rad, rad + 1):
        for dc in range(-rad, rad + 1):
            near |= dry[rad + dr:rad + dr + ny, rad + dc:rad + dc + nx]
    cost = np.where(near, SHORE_COST, 1.0).ravel()
    rows, cols, wts = [], [], []
    wet = water.ravel()
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):       # 8-connected, both directions
        c0, c1 = max(0, -dc), nx - max(0, dc)
        A = idx[0:ny - dr, c0:c1].ravel()
        B = idx[dr:ny, c0 + dc:c1 + dc].ravel()
        ok = wet[A] & wet[B]
        w = (np.hypot(dc * kx.ravel()[A[ok]], dr * res * 110.57)
             * np.maximum(cost[A[ok]], cost[B[ok]]))
        rows += [A[ok], B[ok]]; cols += [B[ok], A[ok]]; wts += [w, w]
    g = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))),
                   shape=(ny * nx, ny * nx)).tocsr()
    dist, pred = dijkstra(g, indices=s, return_predecessors=True)
    if not np.isfinite(dist[e]):
        # the end lies in water the grid cannot reach (a narrow fjord or river): sail to
        # the nearest reachable water and let the last leg be the harbour approach
        reach = np.flatnonzero(np.isfinite(dist))
        gap = haversine_km(gt.flat[reach], gl.flat[reach], b[1], b[0])
        if not len(reach) or gap.min() > APPROACH_KM:
            return None
        e = reach[np.argmin(gap)]
    path, k = [], e
    while k != s and k >= 0:
        path.append(k); k = pred[k]
    path.append(s)
    pts = [[float(gl.flat[k]), float(gt.flat[k])] for k in reversed(path)]
    pts = [list(a)] + pts + [list(b)]

    # string-pull: from each kept point jump to the farthest point still reachable over water
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and _leg_hits_land(pts[i], pts[j], grid, ends=(i == 0, j == len(pts) - 1)):
            j = max(i + 1, i + (j - i) // 2) if j - i > 8 else j - 1
        out.append(pts[j]); i = j
    return out


@lru_cache(maxsize=4096)
def _detour(a: tuple, b: tuple, pad_deg: float):
    """_water_path, remembered: routes to different ports share the same legs."""
    path = _water_path(list(a), list(b), _land_grid(), pad_deg)
    return tuple(tuple(p) for p in path) if path else None


def _around_land(coords: list) -> list:
    """Route [[lon, lat], ...] with every leg that crosses land replaced by a path over water."""
    grid = _land_grid()
    if grid is None or len(coords) < 2:
        return coords
    out = [coords[0]]
    last = len(coords) - 2
    for k, (a, b) in enumerate(zip(coords[:-1], coords[1:])):
        detour = None
        if _leg_hits_land(a, b, grid, ends=(k == 0, k == last)):
            span = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            for pad in (max(0.5, 0.3 * span), max(2.0, span), max(8.0, 3 * span)):
                detour = _detour(tuple(np.round(a, 4)), tuple(np.round(b, 4)), round(pad, 3))
                if detour:
                    break
        out += [list(p) for p in detour[1:]] if detour else [b]
    return out


def _inland_km(lat, lon, grid, max_km: float = 120.0) -> float:
    """How far a port lies from water the grid can resolve (0 on an open coast)."""
    land, res = grid
    r, c = _cell(lat, lon, res, land.shape)
    rad = int(max_km / (res * 111.0))
    rows = np.arange(r - rad, r + rad + 1)
    cols = np.arange(c - rad, c + rad + 1) % land.shape[1]
    rows = rows[(rows >= 0) & (rows < land.shape[0])]
    rr, cc = np.nonzero(~land[np.ix_(rows, cols)])
    if not len(rr):
        return max_km
    dy = (rows[rr] - r) * res * 110.57
    dx = (cc - rad) * res * 111.32 * np.cos(np.radians(lat))
    return float(np.sqrt(dx ** 2 + dy ** 2).min())


def route_km(coords) -> float:
    c = np.asarray(coords, float)
    return float(haversine_km(c[:-1, 1], c[:-1, 0], c[1:, 1], c[1:, 0]).sum())


def _wrap(coords):
    return [[(x + 180) % 360 - 180, y] for x, y in coords]   # maps split it at the date line


def sea_route(lat: float, lon: float, port_lat: float, port_lon: float):
    """
    (km, [[lon, lat], ...]) along shipping lanes, using the searoute package's
    maritime network, or (None, None) without it. Includes the legs from the
    survey onto the network and from the network into the port. Longitudes
    are left unwrapped (they may run past +/-180); see realistic_route().
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
    # Routes across the Pacific carry longitudes past -180 (e.g. -238 for
    # China); that is fine. But some Arctic / Bering routes run down the 180th
    # meridian itself and back (Chukchi Sea to Nome came out at 7,100 km):
    # treat those, and any route over 4x the straight line, as unknown.
    on_180 = np.abs(np.abs(c[:, 0]) - 180) < 0.01
    along_180 = on_180[:-1] & on_180[1:] & (np.abs(np.diff(c[:, 1])) > 1)
    if along_180.any() or km > 4 * max(float(haversine_km(lat, lon, port_lat, port_lon)), 50.0):
        return None, None
    return km, coords


def _route_clear(coords, grid, port_gap: float) -> bool:
    """
    True if the route stays off land, except within port_gap km of the port along the
    route (a port up a river, in a fjord or behind a causeway the grid cannot resolve)
    and its first COAST_GAP_KM.
    """
    to_go = np.r_[np.cumsum([route_km([a, b]) for a, b in zip(coords[:-1], coords[1:])][::-1])[::-1], 0.0]
    for k, (a, b) in enumerate(zip(coords[:-1], coords[1:])):
        if to_go[k + 1] >= port_gap:           # this leg ends before the port's approach
            end = False
        elif to_go[k] <= port_gap:             # wholly inside the approach
            continue
        else:                                  # enters the approach part-way
            end = port_gap - to_go[k + 1]
        if _leg_hits_land(a, b, grid, ends=(k == 0, end)):
            return False
    return True


def realistic_route(lat, lon, port_lat, port_lon, lanes=None):
    """
    (km, [[lon, lat], ...] wrapped to +/-180, basis) for the map: the shipping-lane
    route with every stretch over land replaced by a path through the water around
    it, or for nearby ports (or when the lanes fail) the shortest way around land.
    Where nothing over water is found the distance is kept and no line is drawn.
    """
    straight = float(haversine_km(lat, lon, port_lat, port_lon))
    direct = [[lon, lat], [port_lon + round((lon - port_lon) / 360) * 360, port_lat]]
    grid = _land_grid()
    if grid is None:
        return (straight, _wrap(direct), "straight line") if lanes is None else \
            (max(route_km(lanes), straight), _wrap(lanes), "sea route")
    # ports up a river or deep in a fjord sit behind land the grid cannot resolve
    port_gap = max(PORT_GAP_KM, _inland_km(port_lat, port_lon, grid) + 10)

    options = []
    if lanes is not None:
        coords = _around_land(lanes)
        if _route_clear(coords, grid, port_gap):
            options.append(("sea route", coords))
    if not options or straight <= DIRECT_MAX_KM:
        # the lane network can make odd detours near the coast (via a hub port, or
        # through a strait closed by a causeway): the shortest way around land
        coords = _around_land(direct)
        if _route_clear(coords, grid, port_gap):
            options.append(("around land" if len(coords) > 2 else "direct over water", coords))
    if not options:
        return straight, [], "straight line (no sea route found)"
    km = [route_km(c) for _, c in options]
    best = int(np.argmin(km))
    if options[0][0] == "sea route" and km[0] <= 1.1 * km[best]:
        best = 0                                    # shipping lanes win unless clearly longer
    basis, coords = options[best]
    return max(km[best], straight), _wrap(coords), basis


# category of each row returned by nearby_ports
NEAREST, LINKED = "nearest port", "nearest rare-earth linked port"
FLAG_NEAREST, FLAG_LINKED = "flag-state port", "flag-state rare-earth linked port"


def nearby_ports(lat: float, lon: float, n_nearest: int = 8, n_linked: int = 6,
                 min_linked_size: int = 2, country: str = "", n_country: int = 5,
                 n_country_linked: int = 3) -> list[dict]:
    """
    Ports for a survey area centred at (lat, lon): the n_nearest ports of any
    size, then the n_linked nearest rare-earth linked ports of at least Small
    size (offloading cargo needs more than an anchorage). With `country`
    (a port-list country name, e.g. the vessel's flag state), also its
    n_country nearest ports and n_country_linked nearest rare-earth linked
    ports, counting territories in COUNTRY_GROUPS. Ranked by sea-route
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
        pool["lanes"] = [r[1] for r in routes]
        # only the ports kept get their route taken around land (slower), then re-ranked
        pool = pool.nsmallest(n, "sea_km").copy()
        real = [realistic_route(lat, lon, r.lat, r.lon, r.lanes) for r in pool.itertuples()]
        pool["sea_km"] = np.round([x[0] for x in real], 1)
        pool["route"] = [x[1] for x in real]
        pool["distance_basis"] = [x[2] for x in real]
        return pool.drop(columns="lanes").sort_values("sea_km").assign(category=category)

    def nearest_and_linked(pool, n, n_link, near_cat, link_cat):
        near = measure(pool, n, near_cat) if len(pool) else pool.iloc[:0]
        linked = pool[(pool["ree_link"] != "") & (pool["size_rank"] >= min_linked_size)
                      & ~pool.index.isin(near.index)]
        return [near, measure(linked, n_link, link_cat) if len(linked) else linked.iloc[:0]]

    parts = nearest_and_linked(ports, n_nearest, n_linked, NEAREST, LINKED)
    if country:
        home = ports[ports["country"].isin(country_scope(country))]
        parts += [x.assign(match_country=country) for x in
                  nearest_and_linked(home, n_country, n_country_linked, FLAG_NEAREST, FLAG_LINKED)]
    out = pd.concat(parts)
    if not len(out):
        return []
    out["match_country"] = out["match_country"].fillna("") if "match_country" in out else ""
    out["sea_nm"] = np.round(out["sea_km"] / KM_PER_NM, 1)
    out["hours_at_10kn"] = np.round(out["sea_nm"] / 10, 1)
    unlinked = out["ree_link"] == ""          # a site 3,000 km away is not a link
    out.loc[unlinked, ["ree_site", "ree_site_type", "ree_site_status"]] = ""
    out.loc[unlinked, "ree_site_km"] = np.nan
    out = out[["category", "match_country"] + PORT_COLUMNS + ["route"]]
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


# ============================================================
# FLAG STATE -> PORT COUNTRY
# ============================================================

# flag names and codes that differ from the World Port Index country names
COUNTRY_ALIASES = {
    "cn": "China", "chn": "China", "prc": "China", "people's republic of china": "China",
    "peoples republic of china": "China", "p.r. china": "China",
    "hk": "Hong Kong", "hkg": "Hong Kong", "hong kong sar": "Hong Kong",
    "mo": "Macau", "mac": "Macau", "macao": "Macau", "tw": "Taiwan", "twn": "Taiwan",
    "us": "United States", "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "united states of america": "United States", "america": "United States",
    "gb": "United Kingdom", "uk": "United Kingdom", "gbr": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom",
    "ru": "Russia", "rus": "Russia", "russian federation": "Russia",
    "kr": "South Korea", "kor": "South Korea", "korea": "South Korea", "republic of korea": "South Korea",
    "korea, republic of": "South Korea", "kp": "North Korea", "prk": "North Korea",
    "jp": "Japan", "jpn": "Japan", "in": "India", "ind": "India", "de": "Germany", "deu": "Germany",
    "fr": "France", "fra": "France", "no": "Norway", "nor": "Norway", "nl": "Netherlands",
    "nld": "Netherlands", "au": "Australia", "aus": "Australia", "ca": "Canada", "can": "Canada",
    "br": "Brazil", "bra": "Brazil", "pa": "Panama", "pan": "Panama", "lr": "Liberia", "lbr": "Liberia",
    "mh": "Marshall Islands", "mhl": "Marshall Islands", "sg": "Singapore", "sgp": "Singapore",
    "mt": "Malta", "mlt": "Malta", "bs": "The Bahamas", "bhs": "The Bahamas", "bahamas": "The Bahamas",
    "gr": "Greece", "grc": "Greece", "cy": "Cyprus", "cyp": "Cyprus", "it": "Italy", "ita": "Italy",
    "es": "Spain", "esp": "Spain", "pt": "Portugal", "prt": "Portugal", "tr": "Turkey", "tur": "Turkey",
    "turkiye": "Turkey", "ir": "Iran", "irn": "Iran", "vn": "Vietnam", "vnm": "Vietnam", "viet nam": "Vietnam",
    "ph": "Philippines", "phl": "Philippines", "id": "Indonesia", "idn": "Indonesia",
    "my": "Malaysia", "mys": "Malaysia", "th": "Thailand", "tha": "Thailand", "nz": "New Zealand",
    "nzl": "New Zealand", "za": "South Africa", "zaf": "South Africa", "mx": "Mexico", "mex": "Mexico",
    "cl": "Chile", "chl": "Chile", "ar": "Argentina", "arg": "Argentina", "pe": "Peru", "per": "Peru",
    "ae": "United Arab Emirates", "are": "United Arab Emirates", "uae": "United Arab Emirates",
    "sa": "Saudi Arabia", "sau": "Saudi Arabia", "eg": "Egypt", "egy": "Egypt", "dk": "Denmark",
    "dnk": "Denmark", "se": "Sweden", "swe": "Sweden", "fi": "Finland", "fin": "Finland",
    "pl": "Poland", "pol": "Poland", "ua": "Ukraine", "ukr": "Ukraine", "be": "Belgium", "bel": "Belgium",
    "ie": "Ireland", "irl": "Ireland", "is": "Iceland", "isl": "Iceland", "pk": "Pakistan",
    "pak": "Pakistan", "bd": "Bangladesh", "bgd": "Bangladesh", "lk": "Sri Lanka", "lka": "Sri Lanka",
    "myanmar": "Burma", "mm": "Burma", "mmr": "Burma", "gambia": "The Gambia",
    "congo": "Congo (Brazzaville)", "dr congo": "Congo (Kinshasa)",
    "democratic republic of the congo": "Congo (Kinshasa)", "falkland islands": "Falkland Islands (Islas Malvinas)",
    "micronesia": "Federated States of Micronesia", "saint helena": "Saint Helena, Ascension, and Tristan da Cunha",
    "saint vincent and the grenadines": "Saint Vincent and the Grenadines (Windward Islands)",
    "united states virgin islands": "U.S. Virgin Islands", "curacao / sint maarten / bonaire": "Curacao",
}

# ports a ship of that flag counts as "home": territories with their own flag
# registry or MID but under the same country
COUNTRY_GROUPS = {
    "China": ["China", "Hong Kong", "Macau"],
    "Hong Kong": ["China", "Hong Kong", "Macau"],
    "Macau": ["China", "Hong Kong", "Macau"],
    "United States": ["United States", "Puerto Rico", "Guam", "U.S. Virgin Islands", "American Samoa",
                      "Northern Mariana Islands", "Midway Islands", "Wake Island", "Johnson Atoll"],
    "France": ["France", "French Guiana", "Guadeloupe", "Martinique", "Reunion"],
    "Netherlands": ["Netherlands", "Caribbean Netherlands"],
    "Curacao": ["Curacao", "Sint Maarten", "Caribbean Netherlands"],
    "Norway": ["Norway", "Svalbard"],
}


@lru_cache(maxsize=1)
def port_countries() -> list:
    """Country names as used by the port list, sorted."""
    ports = load_ports()
    return sorted(ports["country"].dropna().unique()) if len(ports) else []


def normalize_country(value) -> str:
    """
    Port-list country name for a flag given as a name, ISO code or MID name
    ('CN', 'PRC', 'United States (Alaska)' ...). '' when unknown or landlocked.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value).strip()
    names = {c.lower(): c for c in port_countries()}
    for key in (text.lower(), re.sub(r"\s*\(.*\)", "", text).strip().lower()):
        if key in names:
            return names[key]
        if key in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[key]
    return ""


def country_scope(country: str) -> list:
    """The port countries that count as `country`'s own ports."""
    return COUNTRY_GROUPS.get(country, [country])


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
