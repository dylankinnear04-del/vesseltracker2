# Seamount factor and seafloor layer — design

Date: 2026-11-17 · Status: approved

## Intent

The team noticed Da Yang Hao surveying over seamounts and underwater ranges. Their research: seamount
mining is common, because seamount slopes hold minerals (cobalt-rich crusts; sulphides on ridges) and are
easier to reach than the abyssal floor. So seamount presence should **count as evidence of possible
mining in how detections are judged**, not mark every ship that passes over one. Analysts should also be
able to **see the seafloor** on the map.

Checked against our data: Da Yang Hao's survey at 43.4°N 170°E (Emperor Seamounts) sits at 2,833 m with the
floor 5,424 m around it; its stations near 38°S 50°E are on the Southwest Indian Ridge; its long station
series at 9°N 157°W is on flat abyssal plain (no flag). Today all of these score resource context 0.1
("No ISA area or rare-earth site within 300 km").

## Goals

- Each survey and station-keeping detection gets a **seafloor assessment**: on a seamount, on a ridge, or
  neither, with the numbers behind it.
- That assessment **raises the resource-context score** and is stated in the evidence ("On a seamount:
  summit 1,450 m, rises 3,900 m above the surrounding floor · cobalt-rich crust depth").
- A **Seafloor (GEBCO) layer** in the Layers panel shows shaded bathymetry.
- Detections over seamounts or ridges are **visible as such** in the alert queue and the detection panel.

## Non-goals / anti-goals

- Not flagging ships that merely cross a seamount: only surveys and station keeping (the existing
  detections) are assessed.
- No new detection types; no change to how surveys or stations are found.
- No change to the factor weights (resource context stays 22 %); seamounts change the factor's value.
- Anti-goal: a seamount must never outrank being inside an ISA contract area, and must not turn a
  shallow-shelf or near-port stop into a high priority.

## Approach chosen: A (in conversation)

Approaches considered:
- **A (chosen):** relief measured from the NOAA ETOPO 2022 grid we already ship
  (`reference_data/depth_etopo2022_5min.npz`, ~9 km cells), GEBCO's public bathymetry as the map layer.
  Uses data we have and may use, catches ridges as well as seamounts, works everywhere. Cost: seamounts
  narrower than ~10 km can be missed; the layer depends on GEBCO's server.
- B: a published seamount catalogue (Yesson et al., ~33k seamounts, many named). Outside data to fetch and
  license-check; misses ridges and unmapped seamounts.
- C: A plus catalogue names. Most informative, most work; can follow later if NGA wants names.

## Design

**Seafloor assessment (Python, at console-data build time)** — new function in `geo_lookup.py`
(`seafloor_at(lat, lon) -> dict`), added to each event in `webapp/seatrace_export.py` as `seafloor`:
`{kind: "seamount" | "ridge" | null, summit_m, base_m, rise_m, crust_depth: bool}`.
- summit = shallowest grid depth within 25 km of the detection centre; base = the 25th-percentile depth in
  the ring 25–75 km out; rise = summit − base.
- **Seamount:** rise ≥ 1,000 m and summit deeper than 200 m (not an island or shelf).
  `crust_depth` = the seamount's slopes cross the cobalt-crust window, 800–2,500 m (summit shallower than
  2,500 m and base deeper than 800 m). Changed after checking the grid: the Emperor Seamount summit is 496 m,
  so a summit-only test would miss the crusts on its flanks.
- **Ridge:** the same relief test, but the centre lies in a "Seafloor massive sulphides" region of
  `reference_data/seabed_resources.csv` (mid-ocean ridges, back-arc basins).
- Otherwise `kind: null` (the numbers are still recorded).
- Pure function on the grid; no network. Built into `prebuilt/` like everything else.

**Scoring (views/seatrace/engine.js, resource context)** — the value becomes the higher of the existing
rule and the seafloor rule:
- seamount at crust depth 0.75 · other seamount 0.6 · ridge 0.6 · none: no change.
- Inside an ISA contract the contract value stands (all ≥ 0.6) and the seafloor finding is appended to the
  description; near an ISA area or Minamitorishima, the higher value wins and both are described.
- Only applies when the detection's water depth is deeper than 200 m (keeps shelf/anchorage stops out).
- `explain()` adds "on a seamount (summit 1,450 m, rises 3,900 m)" / "on a mid-ocean ridge".
- The Method & data sheet's resource-context row is updated to describe the new rule.

**Map layer** — "Seafloor (GEBCO)" in the Layers panel's Context group, **off by default**, drawn under
the land and zones: GEBCO's public WMS (`https://wms.gebco.net/mapserv`, latest grid, shaded relief),
with the credit "GEBCO Compilation Group, GEBCO Grid" in the Method & data sheet. Repeats round the globe
like the other layers. If GEBCO is unreachable the layer just stays empty.

**Visibility** — a small "Seamount" or "Ridge" tag on the detection's row in the alert queue and in the
detection panel's header area; the evidence list carries the numbers.

## Errors

Depth grid missing → `seafloor` null for every event, scores unchanged. Detection centre on land → null.
GEBCO down → empty layer, nothing else affected.

## Testing

- `seafloor_at`: Emperor Seamounts point (43.388, 170.05) → seamount; abyssal-plain point (9.33, −156.62)
  → null; a Southwest Indian Ridge point (−37.94, 49.26) → ridge; a shelf point → null; missing grid → null.
- Export: every event has `seafloor`; strict JSON; prebuilt fingerprint covers the depth grid (already).
- Engine (smoke pages): a seamount detection's resource component ≥ 0.6 and its description mentions the
  seamount; an ISA-contract detection's value unchanged; no JS errors; the GEBCO layer toggles.

## Left to the builder

Exact tag styling (SeaTrace's existing chip styles); the WMS layer name after checking GEBCO's
GetCapabilities; grid-window arithmetic near the poles and the dateline.
