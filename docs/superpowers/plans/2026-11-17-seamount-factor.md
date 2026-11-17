# Seamount factor and seafloor layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Survey and station detections over seamounts or mid-ocean ridges score higher on resource context, say why, carry a tag, and the map gains an optional GEBCO seafloor layer.

**Architecture:** A pure Python relief test on the ETOPO grid we already ship (`geo_lookup.seafloor_at`) runs at console-data build time and is written onto every event as `seafloor`. SeaTrace's engine reads it into the resource-context factor and the evidence text; addons.js adds the WMS layer; ui.js shows the tag.

**Tech Stack:** Python 3 / numpy / pandas, pytest; SeaTrace vanilla JS + Leaflet 1.9; Streamlit host.

**Spec:** `docs/superpowers/specs/2026-11-17-seamount-factor-design.md`

## Global Constraints

- Summit = shallowest grid value within 25 km of the centre; base = 25th-percentile value in the 25–75 km ring; rise = summit − base (metres, heights negative below sea level).
- Seamount: rise ≥ 1000 and summit < −200. Crust depth: summit > −2500 and base < −800.
- Ridge: same relief test, centre inside a "Seafloor massive sulphides" box of `reference_data/seabed_resources.csv` (ridge wins over seamount there).
- Scores: seamount + crust depth 0.75 · other seamount 0.6 · ridge 0.6. Resource value = max(existing rule, seafloor rule). Inside an ISA contract the contract value stands. Seafloor rule applies only when `e.depth < -200`.
- No change to any factor weight. Seafloor layer off by default. No network at build time.
- GEBCO WMS: `https://wms.gebco.net/mapserv`, layer `GEBCO_LATEST` (checked in GetCapabilities 2026-11-17), credit "GEBCO Compilation Group, GEBCO Grid".

## Review Focus

1. Dateline: a detection at lon 179.9 must use cells on both sides (window wraps) — test in Task 1.
2. Islands/atolls: summit above −200 m must not be a seamount (Hawaii 19.0, −155.5 → null) — test in Task 1.
3. Shallow detection on a seamount flank near shore (e.depth > −200): seafloor rule must not raise the score — smoke check in Task 2.
4. Old prebuilt files or blobs without `seafloor` (the original SeaTrace reference data): engine must treat a missing field as none, no JS error — smoke page `original_data.html` in Task 4.
5. High latitude (|lat| > 80): the ring must not blow up from cos(lat) → 0 — test in Task 1.

---

### Task 1: `seafloor_at` and the export field

**Files:**
- Modify: `geo_lookup.py` (after `depth_m`, ~line 157)
- Modify: `webapp/seatrace_export.py:275` (event dict)
- Test: `tests/test_geo_lookup.py`, `tests/test_seatrace_export.py`

**Interfaces:**
- Produces: `geo_lookup.seafloor_at(lat: float, lon: float) -> dict | None` returning `{"kind": "seamount"|"ridge"|None, "summit_m": int, "base_m": int, "rise_m": int, "crust_depth": bool}`; None when the grid is missing. Each blob event gains `"seafloor"` with that value.

- [ ] **Step 1: Write the failing tests** in `tests/test_geo_lookup.py`:

```python
def test_seafloor_emperor_seamount():
    s = geo_lookup.seafloor_at(43.388, 170.05)
    assert s["kind"] == "seamount" and s["crust_depth"] and s["rise_m"] >= 1000

def test_seafloor_abyssal_plain():
    assert geo_lookup.seafloor_at(9.33, -156.62)["kind"] is None

def test_seafloor_southwest_indian_ridge():
    assert geo_lookup.seafloor_at(-37.94, 49.26)["kind"] == "ridge"

def test_seafloor_island_is_not_a_seamount():
    assert geo_lookup.seafloor_at(19.0, -155.5)["kind"] is None

def test_seafloor_shelf():
    assert geo_lookup.seafloor_at(30.5, 122.5)["kind"] is None      # East China Sea shelf

def test_seafloor_dateline_and_pole_do_not_crash():
    for lat, lon in ((43.0, 179.95), (43.0, -179.95), (85.0, 10.0), (-81.0, 0.0)):
        assert isinstance(geo_lookup.seafloor_at(lat, lon), dict)

def test_seafloor_without_grid(monkeypatch, tmp_path):
    monkeypatch.setattr(geo_lookup, "DEPTH_FILE", tmp_path / "none.npz")
    geo_lookup._depth.cache_clear()
    try:
        assert geo_lookup.seafloor_at(43.388, 170.05) is None
    finally:
        geo_lookup._depth.cache_clear()
```

And in `tests/test_seatrace_export.py`, using the existing `blob` fixture:

```python
def test_every_event_has_seafloor(blob):
    assert blob["events"] and all("seafloor" in e for e in blob["events"])
    json.loads(sx.to_json(blob))          # strict JSON (no NaN)
```

- [ ] **Step 2: Run** `pytest tests/test_geo_lookup.py tests/test_seatrace_export.py -q` — expect AttributeError on `seafloor_at` and KeyError/assert on `seafloor`.

- [ ] **Step 3: Implement** `seafloor_at` in `geo_lookup.py`: select grid rows within ±75 km of lat (75/111.2 deg) and columns within ±75 km of lon using wrapped longitude differences `((lons - lon + 180) % 360) - 180`, with the longitude span computed from `max(cos(lat), 0.05)`; distance per cell by equirectangular km; apply the Global Constraints thresholds. Ridge test via `resource_context.regions_at(lat, lon)` (import inside the function to avoid an import cycle) with `category == "Seafloor massive sulphides"`. Return ints. In `seatrace_export.py` add `"seafloor": geo_lookup.seafloor_at(lat, lon)` to the event dict.

- [ ] **Step 4: Run** the same pytest command — all pass. Also `pytest tests/test_prebuilt.py -q` (fingerprint already covers `geo_lookup.py`).

- [ ] **Step 5: Commit** `git commit -am "Seafloor assessment: seamount or ridge under each detection"`

### Task 2: Engine scoring and evidence

**Files:**
- Modify: `views/seatrace/engine.js:125` (copy `seafloor: r.seafloor || null` onto e), `:170-174` (fRes), `explain()` ~`:237`
- Modify: `views/seatrace/ui.js:706` (Method & data resource-context row)
- Test: `tests/js/build_smoke.py` driver

**Interfaces:**
- Consumes: event `seafloor` from Task 1.
- Produces: `e.seafloor` on engine events; helper `E.seafloorText(sf) -> string` exported on the engine object (e.g. "On a seamount: summit 496 m, rises 4,963 m · cobalt-crust depth" / "On a mid-ocean ridge: rises 1,202 m"), used by Task 4.

- [ ] **Step 1: Add smoke checks** to the DRIVER in `tests/js/build_smoke.py`, reported in its result JSON:
  - `seamountOk`: every event with `seafloor.kind` and `depth < -200` and no `zone` has a resource component value ≥ 0.6 and its description contains "seamount" or "ridge";
  - `shallowOk`: every event with `depth >= -200` has the same resource value it would without seafloor (value ≤ 0.8 and description lacks "seamount");
  - `zoneOk`: every event with `zone` has resource value equal to `ZONE_TYPES[zone.type].w`.
- [ ] **Step 2: Build smoke pages** (`python tests/js/build_smoke.py OUT`, preview "smoke") and confirm `seamountOk` is false.
- [ ] **Step 3: Implement** in engine.js: after the existing fRes chain, if `e.seafloor && e.seafloor.kind && e.depth < -200`: `sv = kind==='ridge' ? 0.6 : crust ? 0.75 : 0.6`; inside a zone append `' · ' + seafloorText` to resD; else if `sv > fRes` set `fRes = sv`, `resD = seafloorText + (old resD isn't the "No ISA area…" default ? ' · ' + old resD : '')`. In `explain()` push "on a seamount (summit X m, rises Y m)" / "on a mid-ocean ridge" after the zone/Minamitorishima line. Update ui.js:706 text to: "Inside an ISA contract area scores by mineral type; within 300 km of Minamitorishima 0.8; on a seamount whose slopes reach cobalt-crust depth (800–2,500 m) 0.75; on another seamount or a mid-ocean ridge 0.6; within 300 km of an ISA area half; otherwise low."
- [ ] **Step 4: Rebuild smoke pages**, check `seamountOk`, `shallowOk`, `zoneOk` true and no console errors on all pages.
- [ ] **Step 5: Commit** `"Seamounts and ridges raise resource context and appear in the evidence"`

### Task 3: Seafloor (GEBCO) map layer

**Files:**
- Modify: `views/seatrace/addons.js:99-142` (extra layers), Method & data credit (ui.js ~:699, data sources table)
- Test: `tests/js/build_smoke.py` driver

- [ ] **Step 1: Smoke check** `seafloorLayer`: Layers list has a `data-layer="seafloor"` entry, it is off at start, clicking it adds a layer whose `_url` contains `wms.gebco.net`, clicking again removes it.
- [ ] **Step 2: Rebuild smoke pages**, confirm it fails.
- [ ] **Step 3: Implement**: `map.createPane('seafloor').style.zIndex = 200` (below land at 250); `gSeafloor = L.tileLayer.wms('https://wms.gebco.net/mapserv', {layers: 'GEBCO_LATEST', format: 'image/png', pane: 'seafloor', opacity: 0.85})` (tile layers repeat across world copies by themselves; do not add it to `A.groups`). Add `['seafloor', 'Seafloor (GEBCO)', 'linear-gradient(90deg,#0b2a4a,#3a7bb8,#a8d1e8)']` to EXTRA_LAYERS, `S.layers.seafloor = false`, include it in `applyLayers` and the click handler. Add a data-sources row: "Seafloor shading · GEBCO Compilation Group, GEBCO Grid (WMS, wms.gebco.net)".
- [ ] **Step 4: Rebuild**, `seafloorLayer` true; screenshot at 1440×900 with the layer on around 43°N 170°E shows shaded relief under the land.
- [ ] **Step 5: Commit** `"Seafloor (GEBCO) layer, off by default"`

### Task 4: Seamount / Ridge tag

**Files:**
- Modify: `views/seatrace/ui.js:107` (alert row r1), `:396` (evhead)
- Test: `tests/js/build_smoke.py` driver

- [ ] **Step 1: Smoke check** `tagOk`: number of `.sftag` elements in the alert queue equals the number of listed alerts whose `seafloor.kind` is set and `depth < -200`; selecting such an event shows a `.sftag` in `.evhead` with `title` equal to `E.seafloorText(e.seafloor)`.
- [ ] **Step 2: Rebuild**, confirm it fails.
- [ ] **Step 3: Implement** a `sfTag(e)` helper in ui.js returning `'<span class="sftag" title="…">SEAMOUNT</span>'` / `RIDGE` (or '' when not applicable), styled like `.badge.ree` but smaller; insert after the flag in the alert row and after the status in `.evhead`.
- [ ] **Step 4: Rebuild**, `tagOk` true; `original_data.html` (no `seafloor` field) loads with no errors and no tags.
- [ ] **Step 5: Commit** `"Seamount and Ridge tags in the alert queue and detection panel"`

### Task 5: Full check, release, live verification

- [ ] **Step 1:** `pytest -q` (recreate the scratchpad venv first if it is gone) — all pass.
- [ ] **Step 2:** README: one paragraph under the scoring section describing the seamount rule and the layer.
- [ ] **Step 3:** Merge to main, `git pull --rebase && git push`; wait for the "Build console data" workflow to finish and pull its commit.
- [ ] **Step 4:** On vesseltracker-v2.streamlit.app, mining group: SURVEY-DAYANGHAO-20260819 shows a SEAMOUNT tag and resource context 0.75 with "cobalt-crust depth"; the Seafloor layer toggles.
