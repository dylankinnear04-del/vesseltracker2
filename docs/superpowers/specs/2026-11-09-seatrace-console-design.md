# SeaTrace console: design

Date: 2026-11-09 · Status: draft for review · Supersedes the page layout and look of
`2026-11-09-website-revamp-design.md` (its data-side work, sections 5–8 and 11.1–11.4, stays).

## 1. Goal

Make the site look, move and organise information exactly like **SeaTrace**
(`~/Downloads/SeaTrace.html`, a JMU capstone prototype built on this project's GFW export), while
keeping every feature the Survey Detector has that SeaTrace lacks. The user's words: "copy basically
everything … all of the designs and features. The aesthetic, animations, and way it organizes the
information is exactly what I have been trying to accomplish."

Decisions made with the user:
- **Embed** SeaTrace's actual interface (HTML/CSS/JS) in the Streamlit app; do not re-create it with
  Streamlit widgets.
- The site is called **SeaTrace**; the original prototype is credited on the Method & data sheet.
- The Survey Detector's extra features go **inside the console**, in SeaTrace's style; tools that need
  Python (upload, settings, model comparison, downloads) are dark pages in the same style, reached
  from the console.
- Analyst reviews (case status and notes) are saved **in the browser** (localStorage), as SeaTrace does,
  plus CSV export/import.
- The user was asked to check that the SeaTrace author is fine with the reuse; SeaTrace is credited either way.

## 2. What SeaTrace is (the reference)

A single-page, full-viewport dark "analyst console" (IBM Plex Sans / Sans Condensed / Mono; tokens
`--bg #07121a`, accent `#5cc8ff`, P1–P4 `#ff5f56 #f4a93b #5aa9d6 #748797`, survey `#ffd34d`,
prediction `#ff7ec3`, zone colours PMN/REE/crust/SMS):
- **Header:** logo, title + subtitle, live stats, **Briefing**, view switch **Map / Gallery /
  Timeline**, **Validation**, **Method & data**; a classification-style source banner above it.
- **Left pane:** tabs **Fleet** (search with "/" shortcut, filter chips flagged / watchlist /
  same-port return / active, per-ship rows, "Select flagged", "Clear") and **Alert queue** (priority
  chips P1–P4, model chips SURVEY / STATION, ranked detections).
- **Centre:** Leaflet map (inlined Leaflet core CSS, Leaflet 1.9.4 from cdnjs, world outline from the
  echarts world map on jsDelivr) with a fold-out **Layers** panel, cursor coordinates, HUD, intro card,
  briefing overlay, a canvas fast-forward ("lapse") animation, and a **time bar**: play, map-time
  readout, histogram + range slider, speed (6 h / 1 d / 3 d per step), **LATEST** and **SEASON ▸**
  replay with fading trails.
- **Right pane:** the selected ship / detection **assessment**: priority with the eight weighted factors,
  confidence with its criteria, plain-English reasons, the operation cycle strip (port → transit →
  operation → return), context, GFW registry and events, reference events and watch items, and a
  **Case** panel (NEW / REVIEWING / CONFIRMED / DISMISSED / ESCALATED + note; "next unreviewed").
- **Gallery view** (detection thumbnails), **Timeline view** (ship rows over the season),
  **Validation sheet** (regression table, GFW agreement, precision from analyst review by model and
  depth band), **Method & data sheet**, toasts.
- An **engine** (JS) that builds ships, detections, confidence and priority scores, tiers, reasons,
  coordination / revisits, hotspots and statistics from one embedded JSON blob (`seatrace-data`).

## 3. Architecture

```
app.py                         st.navigation: SeaTrace (default) + Analyst pages; dark theme
views/seatrace.py              full-viewport page: builds the payload, injects it, shows the console
views/seatrace/console.html    SeaTrace's markup + CSS (copied), with {{DATA}} and {{CONFIG}} slots
views/seatrace/engine.js       SeaTrace's ENGINE (copied), hard-coded content moved to the payload
views/seatrace/ui.js           SeaTrace's UI script (copied) + the additions in section 5
webapp/seatrace_export.py      our results -> SeaTrace's data format (pure Python, tested)
views/analyst_*.py             Upload, Detection settings, Compare models, Data & downloads (dark)
```

- The console runs in an `st.iframe` (HTML string) sized to the viewport; the Streamlit header,
  padding and footer are hidden on that page so it looks like a standalone app.
- The payload is built once per (ship group, season, settings) and cached with `st.cache_resource`
  (shared by all visitors; same rule as today: default settings are shared, custom ones per session).
- Links out of the console (Analyst pages, shareable links) use `target="_top"`.
- The SeaTrace files are copied **verbatim first** (one commit), then changed in small, reviewable
  commits, so every deviation from the original is visible in git.

## 4. The data hand-off (`webapp/seatrace_export.py`)

Produces exactly SeaTrace's `seatrace-data` schema, from our pipeline (`data.public_results`,
`intel.build`, the library, reference data):

| Key | Source |
|---|---|
| `T0`, `AS_OF` | season start (UTC ISO) and hours to the newest position |
| `meta` | positions raw / embedded |
| `vessels[]` | library ships with data in the season: `id` (lower-case name, letters and digits, as SeaTrace), name, ISO2 flag, country, mmsi, imo, callsign, `cls` (geo_lookup.vessel_class), `watch` (mining watchlist), `home` (port index of the nearest flag-state home port), `enc` (delta-encoded 30-min track: Δt in 30-min units, lat×100, lon×100, speed×10), `n_raw`, `calls` (track_events.port_calls, port = index into `ports`, times in hours from T0, `open`), `gaps` (track_events.ais_gaps), `gfw` (gfw_vessel_info + gfw_events: ids, owner, ownerFlag, type, lengthM, gt, registry, events `k` P/L/E) |
| `events[]` | survey areas (`model LAWNMOWER_SURVEY`, `L`: lines a/b/t0/t1/len, n, spacing, spacingCV, dev, overlap, progression, newTrack, coverage, speed, area, axis, offshore, blocks, score, detConf, pattern, hull, hotspot) and stations (`STATIONKEEPING_OPERATION`, `S`: center, r95, r50, medSog, onHours, totalHours, onFrac, net, cells, portKm, cloud); both with `zone` / `nearZone` / `nearZoneKm` (ISA, live), `nearestPort`, `foreign`, `mntKm` (km to Minamitorishima), `eez`, `depth`, `boundary`, `gfwMatch` |
| `screened[]` | rejected_blocks.csv: vessel, t0, t1, reason, center, n |
| `ports[]` | world_ports.csv: id, name, cc (country), lat, lon, size |
| `zones[]` | ISA contract areas read live (`data.isa_zones`), never written to disk |
| `ree[]` | reference_data/ree_sites.csv |
| `hotspots[]` | survey_hotspots.csv: id, vessels, n, lat, lon, together, maxAtOnce |
| `eezLines[]` | reference_data/eez_boundaries.geojson (t, n, c) |
| `gfwVal` | stations vs GFW loitering events (sk, skAgree, gfwLong, gfwMissed, gfwDrift, missed[], pulled, window) |
| `extras` (new) | per detection: home / rare-earth ports with sea km and route geometry, likely resource, predicted next lines; reference events, watch items, regression table (section 6) |

Payload size target: under 6 MB for all ships over 6 months (SeaTrace's is 3.7 MB).

## 5. Survey Detector features added to the console (in SeaTrace's style)

1. **Season / ship-group selector** in the header (Mining ships · Chinese research · All ships;
   Last 30 days · Last 6 months · Last year · All data). Changing it reloads the console with that
   payload (URL `?group=&time=`).
2. **Ports** section in the assessment pane: nearest home-country port, rare-earth-linked port and
   other nearby ports with sea distance and hours at 10 kn; **routes** drawn on the map for the focused
   detection (searoute lanes, around land).
3. **Likely surveying for** line in the assessment (resource_context.describe).
4. **Layers** panel gains: Predicted next lines (pink, `--pred`), Port routes, Seabed resource regions.
5. **Alert queue**: Export reviews (CSV), Import reviews (CSV), Download as labels (for Compare models).
6. **Shareable links**: the focused ship / detection and view live in the URL hash (`#v=…&e=…&view=…`)
   and are restored on load; "Copy link" button in the assessment pane.
7. **Analyst menu** in the header: Upload your own track, Detection settings, Compare models,
   Data & downloads (dark Streamlit pages, same fonts and colours). Upload results open in the console
   (a payload built from the uploaded files).
8. Ships on the watchlist without data are listed at the bottom of the Fleet tab, greyed.
9. Custom-settings and stale-data notices appear as SeaTrace toasts / a banner line.

## 6. Hard-coded SeaTrace content, made data-driven

- `REFERENCE` (Chikyu documented events, GFW site, sources) and `WATCH` (watch items) come from
  `reference_data/reference_events.csv`, `watch_items.csv` and the GFW events for that ship.
- `REGRESSION` (synthetic regression table) comes from running the default model on
  `benchmarks/*` with their labels at payload build time (cached).
- **Briefing judgments** stay as written but each one is shown only when the data supports it
  (e.g. the East China Sea step needs survey events of the two Haiyang Dizhi ships in the season);
  otherwise it is skipped. No briefing step may throw on a season without its ships.
- Header subtitle and banner text: "SeaTrace · Deep-sea mineral activity intelligence" with the
  actual data window and sources; "JMU capstone prototype" credit moves to Method & data.

## 6b. Fixes carried over from the final code review of the previous build

The independent review (2026-11-09) found no critical issues. Findings in pages being removed
(Explore replay cache, map re-click, Home / profile KeyError) go away with them. The rest apply to the
data side the console keeps and are fixed in this work:
- **Stable detection ids.** Ids no longer renumber when the window slides: `SURVEY-<CODE>-<YYYYMMDD>`
  / `STATION-<CODE>-<YYYYMMDD>` (start date, UTC; `-b`, `-c` on a same-day clash). SeaTrace's case
  states in localStorage and imported review CSVs are keyed by these ids, so a review can never land
  on a different detection.
  SeaTrace's engine numbers ids itself (`E-<CODE>-NN` by start order); it is changed to use the `id`
  each event carries in the payload.
- **AIS gaps inside port stays are dropped** (both ends within 5 km of the same port, or inside a
  port call): they are not "going dark".
- **ISA outage is not cached as a result**: a failed ISA fetch is retried on the next payload build
  (short ttl), and a payload built without ISA zones expires after 1 hour instead of a week.
- **Custom settings** cache the whole payload per session (one entry), so analyst clicks do not re-run
  the analysis and intel.
- **Labels upload in Compare models** checks for `vessel` and `is_survey` columns and explains what is
  wrong instead of crashing.
- **`prepare()`** always returns survey-area tables with their columns, even when none were found.
- Minor: `_centre` uses a date-line-safe mean; a blank flag scores "flag unknown" (0.5), not "foreign
  EEZ"; `gfw_tables` tolerates a malformed events file; truncate-then-escape in labels; stray line in
  the `webapp/data.py` docstring.
- **Memory**: measured before rollout (gate in section 9); `_public` keeps at most 3 group/season
  payloads and does not cache country-filtered runs.

## 7. What is removed

The Nautical chart theme and the pages `home, explore, findings, ships, ship_profile, hotspots,
how_it_works, about, briefing, analyst_review` (the console covers each). `webapp/ui.py` keeps only
what the Analyst pages use. They remain in git history.

## 8. Error handling

- ISA service down: zones empty, resource factor falls back as today, a toast says "ISA contract
  areas unavailable".
- GFW enrich files missing: registry/events sections say so; gfwVal shows "not pulled yet".
- A season with no detections: the console opens with an empty alert queue and a toast suggesting a
  longer season.
- External scripts (Leaflet, world outline) fail to load: SeaTrace's own "Coastline layer could not
  load" note; tracks and zones still draw.
- Payload build failure: a dark error panel on the page with the message, never a blank page.

## 9. Testing

- `tests/test_seatrace_export.py`: schema check against SeaTrace's own data (same keys and types for
  every record type, using a recorded sample of `SeaTrace.html`'s blob as the reference), track
  encoding round trip, ids match SeaTrace's for the same ships, ISA zones never written to disk,
  payload size under 6 MB.
- **Engine smoke test in a real JS engine**: run `engine.js` in a headless browser (Playwright, via the
  playwright-cli skill) on our payload, and assert no console errors, ≥ 1 detection, tiers present, and
  every briefing step builds.
- AppTest: the SeaTrace page and every Analyst page render without exceptions.
- Browser pass (desktop, plus phone width where SeaTrace's own CSS allows): every header button,
  view, sheet, layer and the time bar; screenshots in `upload_batches/2026-11-09_seatrace/`.
- Memory: peak RSS for the default page ≤ the earlier budget.

## 10. Rollout

Unchanged from the previous spec: local build and tests, then the user's go-ahead, then the GitHub
web-editor push (text files), the user dragging binary files, a manual 12-month run of the weekly
workflow (for the GFW enrich files), and a Streamlit reboot.
