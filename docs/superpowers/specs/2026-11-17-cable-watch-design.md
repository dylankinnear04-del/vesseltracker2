# Cable watch and ship overview — design

Date: 2026-11-17 · Status: awaiting approval (builder check done; answers below)

## Intent

The project is a proof of concept for NGA on national security and US supply chains. The team wants to
**keep watch for attacks on undersea fibre-optic cables, and predict them where possible**: see where cables
run, and flag the ships we follow that behave suspiciously over one. The team names two suspicious
behaviours: **running a survey pattern over a cable**, and **sitting still on top of one for an unusual
length of time**. Separately, the port data must stay visible and be **joined with the supply-chain
features into one overview per ship**, so an analyst sees where a ship goes, who it works for, and what it
did over cables in one place.

## Goals

- A **Submarine cables** map layer: cable routes with name, owners, landing points and ready-for-service year.
- A **cable watch** on every followed ship's full track: episodes of slow or stopped time on top of a cable,
  away from ports, including ones too short or too close to shore to count as station keeping.
- Survey and station-keeping detections on top of a cable get a **CABLE** tag and the cable in their evidence.
- A **Ship overview** card per ship: identity, owner chain and restricted-list result, port calls (countries,
  counts, last call, rare-earth-linked ports), areas worked and their minerals, and cable-watch episodes.
- Port data stays where it is today (Ports & target section, Port routes and WPI ports layers, observed port
  calls on the map and timeline); nothing is removed.

## Non-goals / anti-goals

- Not watching ships we don't follow: we only hold tracks for the followed groups. Say so in the console.
- No cable-route-survey detection (lines running *along* a cable) in this round; revisit once real cases exist.
- No change to how surveys or stations are detected, and no change to the priority factor weights.
- Anti-goals: an ordinary crossing (minutes over a cable) must never be flagged; cable-laying or repair ships
  must be labelled as such, not hidden and not presented as threats; a ship waiting at anchor inside a port
  must not be flagged because cables land there.

## Constraints

- Cable data: TeleGeography's public Submarine Cable Map (`submarinecablemap.com/api/v3`): `cable/cable-geo.json`
  (735 cables, routes), `landing-point/landing-point-geo.json` (1,929 points), and per-cable
  `cable/{id}.json` (owners, landing points with country, length, RFS year, planned flag). Its routes are
  **schematic**, accurate to a few km at best. License has historically been CC BY-NC-SA (non-commercial,
  share-alike), acceptable for this proof of concept; credit "TeleGeography, Submarine Cable Map" in Method &
  data.
- Fetched once by a script into `reference_data/` (slimmed), not at page load; no network at build or view time.
- Everything is computed at console-data build time and written into the prebuilt files like the rest.

## Approaches (chosen: B)

- A: tag only existing survey/station detections that lie on a cable. Cheap, few false alarms, but the station
  rule needs ≥ 24 h and > 25 km from port, so it misses the short, near-shore stops seen in real cable cuts
  (Baltic, Taiwan's outlying islands).
- **B (chosen):** A, plus a cable watch over each ship's whole track for slow/stopped time on a cable.
- C: B plus cable-route surveys (lines along a cable). Strongest mapping signal, noisiest; deferred.

## Design

**Cable data (`scripts/fetch_cables.py` → `reference_data/submarine_cables.geojson`, `reference_data/cable_landings.csv`).**
Routes as MultiLineStrings with properties `id, name, owners, length_km, rfs_year, planned, landings`
(landing names + countries). Coordinates rounded to 3 decimals. Planned cables kept but marked.

**Cable index (`cables.py`).** `load_cables()`, and `near_cable(lat, lon, km) -> list[{id, name, km}]` using a
KD-tree over route points densified to ≤ 1 km spacing (so distance to the line, not to vertices).

**Cable watch (`cables.watch(track, ports, cls) -> list[episode]`).** On one ship's track (time, lat, lon, sog):
- input is the **raw window track** from `res["tracks"]` (`time, lat, lon, speed_kn`), never the `thin()`ned
  export track (thinning drops exactly the repeated fixes of a ship sitting still). Measured on the all-ships
  6-month data: fixes are **hourly** (median and p90 spacing 1 h; 1.6 % of gaps > 2 h, 0.6 % > 6 h);
- a fix is **on cable** when within **5 km** of a cable route (fixed constant `CABLE_KM`; schematic routes)
  and **more than 10 km from any port or cable landing point** (WPI ports from the existing port list plus
  TeleGeography landing points: cables land there and anchorages are not attacks). Planned cables excluded;
- an **episode** is a run of on-cable fixes with speed **under 3 kn**, merged across gaps under 2 h, lasting at
  least **2 hours** in total, i.e. at least 3 consecutive hourly fixes (an ordinary crossing at 10 kn spends
  about one hour in a 10 km band and shows as 0-1 fixes, often at speed);
- an AIS gap that **starts or ends on a cable** (within 5 km, away from ports) and lasts **over 6 h** is also
  an episode, kind "dark" (6 h, not 2 h: with hourly fixes, 2-4 h gaps are ordinary sampling; the existing
  12 h gap rule in `track_events.py` stays as it is for its own uses);
- each episode: `{t0, t1, hours, kind: "slow"|"stopped"|"dark", cables: [{id, name, km}] (every cable within
  5 km at the episode centre, nearest first, at most 3), center}` (`stopped` when median speed < 0.5 kn).
- **cable ships**: name or ship type contains CABLE (the rule `resource_context.vessel_hint` already uses),
  plus an optional `cable_ship` column in `reference_data/vessel_classes.csv` for known MMSIs. Their episodes
  are kept and shown, marked "cable ship · likely maintenance"; they get no CABLE badge in the fleet list and
  are left out of the Cable watch filter; their detections still get the CABLE tag.
- "Unusual" in the console: the episode's hours beside the **blob's** norm, the median hours per cable
  crossing over all followed ships in that file (one number per group and window file, computed with the
  same track pass), e.g. "9 h on cable · usual crossing 1 h".
- episodes are computed per prebuilt file from that window's tracks (the console only shows that window);
  a ship in several groups gets the same episodes for the same window, since the rule is per ship.

**What counts as unusual (changed 2026-11-17, after testing on real data).** The episode rule above, run on
all followed ships over 6 months, flagged 72 of 86 ships (1,350 episodes): research and survey ships stop for
hours as routine, and the seas they work are dense with cables. So a ship is **flagged** only when it stops
on cables more than chance: **cable affinity** = share of its slow time (under 3 kn, away from ports) that is
on a cable ÷ share of its underway time (5 kn or more, away from ports) that is on a cable, each plus 0.01.
Flag when affinity ≥ **1.5** and on-cable slow time ≥ **24 h**, with at least 10 slow and 10 underway fixes,
and not a cable ship. Measured: median 0.55; top Kilo Moana 2.3, Sagar Nidhi 2.0, Côtes de la Manche 2.0,
China Coast Guard 3101 (72 % of its slow time on cables) 1.7. Episodes are still computed and listed for
every ship in the Ship overview; the CABLE badge, the Cable watch filter and the map markers use the flag
(markers also show for the selected ship). The console states the affinity, e.g. "stops on cables 1.7× more
than chance · 72 % of stopped time".

**Detections on a cable.** Each survey/station event gets `cable: {id, name, km}` when its centre (station)
or any survey line comes within 5 km of a cable, else null.

**Export (`webapp/seatrace_export.py`).** Blob gains `cables` (map layer data embedded in each file, like
`eezLines`), `extras.cableWatch` per vessel id, and event `cable`. Size budget: the cable layer at most
**600 KB** of JSON (routes simplified to ~2 km, 2-decimal coordinates; owners and landings as short strings);
if it does not fit, drop planned cables from the layer first. The 6 MB blob test must still pass.

**Console.**
- Layers ▸ Context: **Submarine cables** (off by default), thin lines, tooltip with name, owners, landings, RFS;
  planned cables dashed. **Cable watch** markers (on by default when a ship has episodes): one marker per
  episode, colour by kind.
- Engine: a detection with `cable` gets a CABLE tag (same style as SEAMOUNT) and "on the X cable (n km)" in its
  evidence. **No score change** in this round (weights stay; the flag is for watch, not ranking).
- Fleet list: a CABLE badge on ships with any non-cable-ship episode; a "Cable watch" filter chip next to
  "Has detections".
- **Ship overview** card at the top of the vessel panel (shown whenever a ship is selected): owner chain and
  restricted-list summary (from the supply chain card's data), port calls by country (count, last call,
  rare-earth-linked ports marked, foreign vs home), areas worked (detections by tier, minerals from area
  chains), and cable-watch episodes with "show on map". The per-detection supply card and Ports & target
  section stay as they are.
- Method & data: cable source, credit, the rule above, and the limit "only ships we follow are watched;
  routes are schematic".

**Cable data version.** The fetched files are committed with the fetch date in
`reference_data/cable_meta.json` (`{fetched, source, license, cables, landings}`). If the API fields differ
from those above, map what exists and leave missing properties empty; if TeleGeography's terms have moved
to something that forbids this use, stop and ask the team.

## Errors

No cable files → no layer, no watch, `cable` null everywhere, notice in Method & data. A ship with no track
→ no episodes. Planned cables are not used by the watch (no fibre there yet).

## Testing

- `near_cable` returns a cable for a point on a known route and nothing for mid-ocean far from cables.
- `watch`: synthetic tracks — a 10 kn crossing → no episode; 3 h at 1 kn on a cable → one episode; the same
  inside 10 km of a port → none; a 6 h gap starting on a cable → a "dark" episode; a cable ship → episode
  marked.
- Export: every vessel has a `cableWatch` list, every event has `cable`; blob size test still passes.
- Smoke pages: layers toggle, CABLE tags count matches, Ship overview renders for every ship with no JS errors
  on old data without the new fields.

## Left to the builder

Exact densification and simplification tolerances; marker styling; how the overview lays out on narrow
panels (desktop only matters); TeleGeography fetch politeness (sequential, small delay).
