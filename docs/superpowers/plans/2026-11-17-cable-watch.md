# Cable watch and ship overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A submarine-cable layer, a cable watch over every followed ship's track (slow/stopped/dark episodes on a cable), CABLE tags on detections, and one Ship overview card per ship joining port calls with the supply chain.

**Architecture:** A new `cables.py` loads TeleGeography routes fetched once into `reference_data/` and does all geometry at console-data build time; `webapp/seatrace_export.py` writes the layer, per-event `cable`, `extras.cableWatch`, `extras.cableNorm` and `extras.shipPorts` into the blob; `views/seatrace/` reads them (addons.js for layers/markers/overview, ui.js for tag, badge and filter chip, engine.js only to carry `cable` onto events).

**Tech Stack:** Python 3 / numpy / pandas / scipy cKDTree, pytest; SeaTrace vanilla JS + Leaflet 1.9; Streamlit host; GitHub Actions builds `prebuilt/`.

**Spec:** `docs/superpowers/specs/2026-11-17-cable-watch-design.md`

## Global Constraints

- `CABLE_KM = 5.0` (on cable), `PORT_KM = 10.0` (port or landing exclusion), `SLOW_KN = 3.0`, `STOPPED_KN = 0.5` (median), `MERGE_H = 2.0`, `MIN_H = 2.0`, `DARK_H = 6.0`; at most 3 cables listed per episode; planned cables never used by the watch.
- Watch input is the raw window track `res["tracks"][(dataset, vessel)]` (`time, lat, lon, speed_kn`), never `thin()`'s output. Tracks are hourly.
- Cable ship: name or ship type contains `CABLE` (case-insensitive, spaces removed), or `cable_ship` truthy in `reference_data/vessel_classes.csv` for its MMSI. Episodes kept, marked; no fleet badge; excluded from the Cable watch filter; detections still tagged.
- No score or weight change. Submarine cables layer off by default; Cable watch markers on by default.
- Cable layer JSON ≤ 600 KB; drop planned cables from the layer first if over. Blob test (< 6 MB) must pass.
- `views/seatrace/console.html` stays byte-identical (CSS goes in addons.js's style block).
- Credit "TeleGeography, Submarine Cable Map" in Method & data, with the limits "only ships we follow are watched; routes are schematic (a few km)".
- Full suite command: `python -m pytest tests -q` (bare `pytest` trips on `upload_batches/`).

## Review Focus

1. A ship anchored a few km off a cable landing that is not in WPI (landing point list covers it) → no episode. Test in Task 2.
2. A cable crossing the antimeridian (e.g. Pacific cables at ±180): `near_cable` near lon 179.99 / −179.99 finds it. Test in Task 1.
3. Old blobs/prebuilt files without `cables`, `cable`, `cableWatch`, `shipPorts` → no JS error, no overview crash. Smoke `original_data.html` in Tasks 4–5.
4. A ship with calls but no detections and no supply data → overview still renders (ports only). Smoke in Task 5.
5. A track with a single on-cable fix at 0 kn between two transit fixes (1 h) → no episode (needs ≥ 3 consecutive slow fixes / 2 h). Test in Task 2.

---

### Task 1: Cable data and `near_cable`

**Files:**
- Create: `scripts/fetch_cables.py`, `cables.py`, `reference_data/submarine_cables.geojson`, `reference_data/cable_landings.csv`, `reference_data/cable_meta.json`
- Modify: `webapp/data.py:649` (`_STAMP_CODE` += `"cables.py"`)
- Test: `tests/test_cables.py`

**Interfaces:**
- Produces: `cables.load_cables() -> list[dict]` each `{"id", "name", "owners", "length_km": float|None, "rfs_year": int|None, "planned": bool, "landings": [{"name", "country"}], "lines": [[[lat, lon], ...], ...]}` (lru_cached; `[]` when the file is missing); `cables.landing_points() -> np.ndarray` shape (n, 2) lat/lon; `cables.near_cable(lat: float, lon: float, km: float = CABLE_KM) -> list[{"id", "name", "km"}]` nearest first, ≤ 3, planned excluded; constants from Global Constraints.

- [ ] **Step 1: Fetch the data.** Write `scripts/fetch_cables.py` (sequential requests, 0.2 s apart, generic User-Agent) reading `cable/cable-geo.json`, `landing-point/landing-point-geo.json` and each `cable/{id}.json` from `https://www.submarinecablemap.com/api/v3/`; write the three files above (coordinates rounded to 3 decimals; `cable_meta.json` = `{fetched, source, license: "TeleGeography Submarine Cable Map; historically CC BY-NC-SA 3.0", cables, landings}`). Run it. Expected: ~735 cables, ~1,929 landings. If the per-cable fields differ, map what exists and leave the rest empty (spec).
- [ ] **Step 2: Failing tests** in `tests/test_cables.py`:

```python
def test_cables_loaded():
    cs = cables.load_cables()
    assert len(cs) > 500 and all(c["lines"] for c in cs)

def test_near_cable_on_a_route():
    c = next(c for c in cables.load_cables() if not c["planned"] and len(c["lines"][0]) > 3)
    lat, lon = c["lines"][0][len(c["lines"][0]) // 2]
    assert any(h["id"] == c["id"] and h["km"] < 1 for h in cables.near_cable(lat, lon))

def test_near_cable_between_vertices():      # distance to the line, not to vertices
    c = next(c for c in cables.load_cables() if not c["planned"]
             and any(cables._seg_km(a, b) > 50 for a, b in zip(c["lines"][0], c["lines"][0][1:])))
    a, b = next((a, b) for a, b in zip(c["lines"][0], c["lines"][0][1:]) if cables._seg_km(a, b) > 50)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert cables.near_cable(*mid)

def test_near_cable_far_from_any():
    assert cables.near_cable(-60.0, -120.0) == []       # Southern Ocean

def test_near_cable_across_the_antimeridian():
    hits = [c for c in cables.load_cables() if not c["planned"]
            and any(abs(p[1]) > 179 for l in c["lines"] for p in l)]
    lat, lon = next(p for l in hits[0]["lines"] for p in l if abs(p[1]) > 179)
    assert cables.near_cable(lat, -lon if abs(lon) > 179.9 else lon)    # works on either side

def test_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cables, "CABLES_FILE", tmp_path / "none.geojson"); cables.load_cables.cache_clear()
    try: assert cables.load_cables() == [] and cables.near_cable(0, 0) == []
    finally: cables.load_cables.cache_clear(); cables._index.cache_clear()
```

- [ ] **Step 3: Run** `python -m pytest tests/test_cables.py -q` → fails (no module).
- [ ] **Step 4: Implement `cables.py`.** `_index()` (lru_cached): densify every non-planned line so consecutive points are ≤ 1 km apart (split segments crossing ±180 by shortest way), KD-tree on unit-sphere xyz (same `_xyz` idea as `geo_lookup`), parallel array of cable index; `near_cable` queries `query_ball_point` at chord(km + 0.5) then best km per cable. `_seg_km(a, b)` great-circle km. `landing_points()` from `cable_landings.csv`.
- [ ] **Step 5: Run** the tests → pass. Add `"cables.py"` to `_STAMP_CODE`; `python -m pytest tests/test_prebuilt.py -q` → pass.
- [ ] **Step 6: Commit** `"Submarine cable data (TeleGeography) and near_cable"`.

### Task 2: Cable watch on a track

**Files:** Modify `cables.py`; Test `tests/test_cables.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `cables.watch(track: pd.DataFrame, avoid: np.ndarray, cable_ship: bool = False) -> list[dict]` episodes `{"t0": Timestamp, "t1": Timestamp, "hours": float, "kind": "slow"|"stopped"|"dark", "cables": [{"id","name","km"}], "center": [lat, lon], "cable_ship": bool}`; `cables.crossing_hours(track, avoid) -> list[float]` (hours of each maximal run of on-cable fixes at any speed, a single fix counting as 1 h); `cables.is_cable_ship(name: str, ship_type: str, mmsi: str) -> bool`. `avoid` = lat/lon array of ports + landing points (km ≤ PORT_KM excluded).

- [ ] **Step 1: Failing tests.** Build synthetic hourly tracks along a real cable point `P` (from `load_cables()`, mid-route, > 50 km from every landing and port) with a helper `track(points, speeds, start="2026-06-01")`:
  - `test_crossing_at_speed_is_not_an_episode`: fixes every hour at 10 kn passing P once → `watch(...) == []` and `crossing_hours` == [1.0].
  - `test_three_hours_slow_on_cable`: 4 hourly fixes within 2 km of P at 1 kn → one episode, kind "slow", hours ≥ 2, cables[0]["km"] < 5.
  - `test_stopped_kind`: same at 0.1 kn → kind "stopped".
  - `test_single_slow_fix_is_not_an_episode`: transit, one 0 kn fix at P, transit → `[]` (Review Focus 5).
  - `test_near_port_is_ignored`: the 4 slow fixes with `avoid` containing a point 6 km away → `[]`.
  - `test_near_landing_point_is_ignored`: same with avoid = `cables.landing_points()` and fixes 3 km from a real landing point that is on a cable (Review Focus 1).
  - `test_dark_gap_on_cable`: fix at P, next fix 7 h later 60 km away → one "dark" episode; a 4 h gap → none.
  - `test_cable_ship_marked`: `is_cable_ship("CS Reliance", "", "")` and `is_cable_ship("X", "Cable Layer", "")` true, `is_cable_ship("Da Yang Hao", "Research", "")` false; `watch(..., cable_ship=True)` episodes carry `cable_ship: True`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** Vectorised: `on = near_cable` per fix (batch KD query) & min distance to `avoid` > PORT_KM; slow = speed < SLOW_KN (NaN speed → derive from neighbouring fixes); runs of on&slow merged across gaps < MERGE_H; keep runs with (t_last − t_first) ≥ MIN_H; kind by median speed. Dark: consecutive fixes Δt > DARK_H where either end is on cable. `is_cable_ship` uses Global Constraints rule (read `cable_ship` column if present).
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `"Cable watch: slow, stopped and dark episodes on a cable"`.

### Task 3: Export

**Files:** Modify `webapp/seatrace_export.py` (event dict ~:275, `build_blob` blob dict ~:337, `add_extras` ~:620); Test `tests/test_seatrace_export.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces in the blob: `blob["cables"] = [{"id","name","owners","rfs","planned","landings": "Name, Country; …","c": [[[lat,lon],…],…]}]` (2-decimal coords, simplified ~2 km); event `"cable": {"id","name","km"} | None` (station centre, or any survey line sampled every ~1 km between `a` and `b`); `extras.cableWatch = {vessel_id: [{"t0","t1" (hours since T0), "hours","kind","cables","center","cableShip"}]}` (every vessel id present, possibly `[]`); `extras.cableNorm = float` (median of `crossing_hours` over all vessels in the file, 1.0 when none); `extras.shipPorts = {vessel_id: [{"country","calls","last" (hours since T0),"home": bool,"ports": [{"name","calls","ree": str}]}]}` sorted by calls desc, `ree` = `port_intel.load_ports()` `ree_link` of the nearest port_intel port within 5 km of the blob port, else "".

- [ ] **Step 1: Failing tests** (module `blob` fixture; extras via `sx.add_extras(blob, res, lib, vid=...)` the way `data._console_blob` calls it — reuse that path with a module fixture `full = json.loads(data._console_blob("all", "6m") …)` if simpler):
  - `test_every_event_has_cable`: all events have key `"cable"`.
  - `test_cable_layer_size`: `len(json.dumps(blob["cables"])) <= 600_000` and `len(blob["cables"]) > 300`.
  - `test_cable_watch_per_vessel`: `set(full["extras"]["cableWatch"]) == {v["id"] for v in full["vessels"]}`; every episode has `kind in {"slow","stopped","dark"}` and `hours >= 2`.
  - `test_ship_ports`: for every vessel with calls, `sum(c["calls"] for c in shipPorts[vid]) == len(v["calls"])`.
  - existing `test_blob_size_under_6mb` still passes.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** as in Interfaces; `avoid` = blob ports lat/lon + `cables.landing_points()`; cable-ship flag from `cables.is_cable_ship(name, ship_type, mmsi)`.
- [ ] **Step 4: Run** `python -m pytest tests/test_seatrace_export.py tests/test_prebuilt.py -q` → pass. Print, for the record, episode counts per kind on all/6m.
- [ ] **Step 5: Commit** `"Export cable layer, cable on detections, cable watch and per-ship ports"`.

### Task 4: Console — layer, markers, tag, badge, filter

**Files:** Modify `views/seatrace/engine.js:125` (`cable: r.cable || null`), `views/seatrace/ui.js` (FCH :57, vMatch :58-66, fleet row badge ~:86, `sfTag` beside it → also CABLE tag, Method & data rows), `views/seatrace/addons.js` (EXTRA_LAYERS, style block); Test `tests/js/build_smoke.py` DRIVER

**Interfaces:**
- Consumes: blob fields from Task 3.
- Produces: `E.cableFlag(v) -> boolean` (`X.cableAffinity[v.id].flag`, amended after the user chose "compare to chance") exported on ENGINE; watch markers drawn for flagged ships and the selected ship only; layer keys `cables` (off) and `cablewatch` (on); CSS classes `.cbtag` (CABLE tag, same look as `.sftag` but cyan) and `.cbbadge` (fleet).

- [ ] **Step 1: Smoke checks** (pushed to `window.__errors` when false): `cableLayer` — `[data-layer="cables"]` exists, unchecked at start, toggling adds/removes a layer group with > 300 polylines (use the async 60 ms pattern of `seafloorLayer`); `cableTagOk` — `.alert .cbtag` count equals listed alerts with `e.cable`; `cableBadgeOk` — `.cbbadge` count in the fleet equals vessels with `E.cableFlag(v)`; `cableFilterOk` — clicking `[data-f="cable"]` leaves exactly those vessels listed, clicking again restores; `original_data.html` passes all with zero counts.
- [ ] **Step 2: Rebuild smoke pages and confirm failures.**
- [ ] **Step 3: Implement.** Cables drawn once per world copy offset (like `gRegions`, OFFS), weight 1.2, colour `#2ec4d6`, planned dashed, tooltip name · owners · landings · RFS. Watch markers: circle at `center` per episode (stopped `#ff5d5d`, slow `#ffb347`, dark `#b48cff`; cable ships grey), tooltip "9 h stopped on {cable} · usual crossing {cableNorm} h · {dates}" (+ "cable ship · likely maintenance"), click focuses the vessel. Method & data: source row and resource-free rule text from the spec.
- [ ] **Step 4: Rebuild, all checks true on all 6 pages, zero errors.**
- [ ] **Step 5: Commit** `"Cable layer, cable watch markers, CABLE tag, fleet badge and filter"`.

### Task 5: Ship overview card

**Files:** Modify `views/seatrace/addons.js` (`decorateIntel`: insert after `.idhead`); Test `tests/js/build_smoke.py`

**Interfaces:**
- Consumes: `X.shipPorts`, `X.cableWatch`, `X.cableNorm`, `X.supply.ships[vid]`, `X.supply.areas[eventId]`, `V[vid].events`.
- Produces: `<div class="sec stx-overview">` with four blocks: **Ownership** (owner → parent → ultimate owner, worst list level as one chip, or "not screened"/"no match"), **Port calls** (one row per country: count, last call date, HOME marker, rare-earth-linked port names), **Areas worked** (detections by tier, union of minerals from area chains, critical first), **Cable watch** (episodes, newest first, each with "Show on map" that flies to `center` at zoom 8).

- [ ] **Step 1: Smoke check** `overviewOk`: for every vessel (focus each via `A.focusVessel` or the fleet row), `.stx-overview` exists exactly once, its port-call total equals `v.calls.length`, and no errors; on `original_data.html` the card renders with "No port data" style fallbacks.
- [ ] **Step 2: Rebuild, confirm failure.**
- [ ] **Step 3: Implement** (all text through `esc`, URLs through `webUrl`).
- [ ] **Step 4: Rebuild, `overviewOk` true on all pages; screenshot Da Yang Hao's overview at 1440×900.**
- [ ] **Step 5: Commit** `"Ship overview: ownership, port calls, areas and cable watch in one card"`.

### Task 6: Docs, full check, release

- [ ] README: a "Cable watch" section (source, rule, limits) and a line on the Ship overview.
- [ ] `python -m pytest tests -q` → all pass; final whole-branch review; fixes test-first.
- [ ] Merge to main, `git pull --rebase && git push`; wait for "Build console data"; pull its commit.
- [ ] Live check on vesseltracker-v2.streamlit.app: Submarine cables layer toggles, CABLE badges/filter work, Da Yang Hao's Ship overview shows port calls by country and its owner chain.
