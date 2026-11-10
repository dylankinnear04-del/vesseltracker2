# Survey Detector website revamp: design

Date: 2026-11-09 · Status: revision 2 (adds the SeaTrace features, section 11), for review

## 1. Goal

Turn the Survey Detector from one crowded Streamlit page (sidebar + seven tabs) into a
consumer-friendly, multi-page website that someone with no AIS background can land on,
understand, and use without help, while keeping every analyst feature reachable.

**Audience:** public first (journalists, students, curious visitors), with analysts and
partners served by a separate "Analyst" area.

**Success looks like:**
- A first-time visitor can answer "what is this, and what has it found?" from the Home page
  in under a minute, and reach a specific ship or survey area in two clicks.
- No page asks the visitor to configure anything before showing a result.
- Every view has a shareable link.
- Nothing the current site can do is lost; analyst tools are one menu away.
- It stays on Streamlit Cloud within its ~1 GB memory limit, and the weekly GFW update keeps
  working unchanged.

**Decisions already made with the user:**
- Platform: stay on Streamlit (approach B), restyled into a real multi-page site.
- Look: "Nautical chart", an evolution of today's theme (light chart-paper feel, Newsreader
  serif headings, Public Sans body, magenta `#A3166E` for anything flagged, `.streamlit/config.toml`
  palette kept; dark mode keeps the ECDIS night palette).
- Explore map layout: filter pills above a wide map, details panel on the right.

## 2. Out of scope

- The AIS lookup by name/MMSI/IMO with a paid API (still pending a provider decision).
- Changes to the lawnmower detector itself: `survey_pattern_detector.py`, `port_intel.py`,
  `resource_context.py` and the existing `models/` files keep their behaviour. (Revision 2 adds
  new modules beside them and extends `gfw_fetch.py`; see section 11.)
- User accounts, logins or passwords.
- Moving off Streamlit Cloud.

## 3. Site map

Top navigation bar (`st.navigation(position="top")`), no sidebar on public pages.

| Page | File | Job |
|---|---|---|
| Home | `pages/home.py` | Explain the site in one screen and route people onward |
| Briefing | `pages/briefing.py` (hidden, opened from Home) | Step-through story of what the data shows (11.6) |
| Explore map | `pages/explore.py` | See every survey area on a map and inspect any of them |
| Findings | `pages/findings.py` | Every detection ranked by priority, as a gallery (11.1) |
| Ships | `pages/ships.py` | Find a ship |
| Ship profile | `pages/ship_profile.py` (hidden from nav, reached from links) | Everything about one ship |
| Hotspots | `pages/hotspots.py` | Places several ships surveyed together |
| How it works | `pages/how_it_works.py` | Plain-language method and limits |
| About & data | `pages/about.py` | Sources, credits, licences, contact |
| **Analyst ▾** Upload your own track | `pages/analyst_upload.py` | Today's file upload + identity form |
| **Analyst ▾** Review queue | `pages/analyst_review.py` | Triage detections: status + notes (11.7) |
| **Analyst ▾** Validation | `pages/analyst_compare.py` | Today's ⚖️ Compare models tab + validation evidence (11.7) |
| **Analyst ▾** Data & downloads | `pages/analyst_data.py` | Today's tables, Excel/ZIP, "Notes on the data", full rare-earth port table |
| **Analyst ▾** Detection settings | `pages/analyst_settings.py` | Model picker, advanced thresholds, port-country mode |

Every page ends with one "next step" link (e.g. Home → Explore map, Ship profile → Hotspots
it belongs to) and the shared footer with the credits.

## 4. Pages in detail

### 4.1 Home
- Eyebrow "SEAFLOOR SURVEY WATCH", headline "Spotting the ships that quietly map the seafloor",
  one-sentence explanation, buttons **Explore the map** (primary, magenta) and **How it works**.
  Background: faint chart-grid pattern.
- Stat tiles: ships tracked · survey areas found (default window) · surveying now · last updated
  (date of the newest library position).
- A small static preview map (same areas as Explore, no controls) linking to Explore.
- "Recently surveying" strip: up to 4 ship cards with the most recent survey activity.
- Three short "What you can do here" cards: Explore map / Ships / Hotspots.

### 4.2 Explore map
- **Filter pills** above the map:
  - Ship group: Mining ships (default) · Chinese research · All ships. Groups come from the
    existing watchlist (`library/watchlist_deep_sea_mining.csv`) and the catalog's flag and
    type columns.
  - Time: Last 30 days · Last 6 months (default) · Last year · All data.
  - Country (multi-select dropdown).
- **Map** (about 70% width): today's `build_map` layers kept (survey areas as yellow numbered
  patches, ships' tracks, headline home-country ports and routes, rare-earth sites/ports and
  seabed-resource layers when zoomed, ISA areas loaded live in the browser, pink "next lines"
  predictions). Rendered with `streamlit-folium` so clicks reach the page.
- **Details panel** (about 30%):
  - Nothing selected: "What you're looking at" (legend in words, counts for the current
    filter) and a scrollable list of survey areas. Clicking a row selects that area.
  - Area selected: ship (flag + name), dates, lines, area size, "Likely surveying for", nearest
    home-country port and distance, "surveying now" badge if live, buttons **Zoom to area**
    and **View ship profile →**.
  - Ship selected (track clicked): mini profile summary + **View ship profile →**.
- Selection and filters live in the URL (`?group=mining&time=6m&area=7`).

### 4.3 Ships
- Search box (name, MMSI, IMO, operator) and filter pills (group, country, "has surveys").
- Grid of ship cards: flag, name, kind of ship, operator, number of survey areas, last seen,
  a "Surveying now" badge. Click → Ship profile.
- Ships with no position data are shown greyed under "On our watchlist, no tracking data yet",
  collapsed by default.

### 4.4 Ship profile (`?mmsi=…`)
- Header: flag, name, identifiers (MMSI, IMO, call sign), kind, operator, notes, data source.
- Key facts row: survey areas, total surveyed km², first and last seen, surveying now.
- Map of this ship only (its track + its survey areas + headline ports and routes).
- Survey areas list (today's per-area panel content: dates, likely resource, nearest
  home-country and rare-earth-linked ports).
- "Surveyed alongside" links to Hotspots this ship is part of.
- Unknown or missing `mmsi` → friendly "We couldn't find that ship" with a link to Ships.

### 4.5 Hotspots
- Ranked cards (most ships first): place name or coordinates, ships involved (linked),
  date span, likely resource. Click a card → map below zooms to it and highlights the areas.
- `?hotspot=N` selects one.

### 4.6 How it works
Plain-language explainer in four illustrated steps (inline SVG, nautical style):
1. Ships broadcast their position (AIS); we use Global Fishing Watch and public NOAA data.
2. Survey ships drive a "lawnmower" pattern of parallel lines.
3. Filters that throw out look-alikes (turn time, new ground, distance offshore, speed,
   number of lines), each in one sentence.
4. What we add: likely resource, nearest home-country ports and rare-earth sites.

Then "What this can't tell you" (AIS gaps, ships switching AIS off, false positives such as
coast-guard patrols near unmapped shoals) and a link to the Analyst tools.

### 4.7 About & data
Sources and licences (Global Fishing Watch CC BY-NC 4.0 "Powered by Global Fishing Watch",
NOAA AIS public domain, ICES platform register, Marine Regions EEZ CC BY 4.0, ISA contract
areas loaded live, Natural Earth), update schedule (weekly, Mondays), team/contact,
non-commercial note.

### 4.8 Analyst pages
Same functions as today, moved out of the sidebar and tabs:
- **Upload your own track:** file uploader, "combine files" toggle, identity form for files
  with no MMSI or flag, then results shown with the same map + details layout as Explore.
- **Compare models:** today's Compare models tab unchanged.
- **Data & downloads:** today's Data & downloads tab, plus "Notes on the data" and the
  rare-earth port table from today's Ports tab.
- **Detection settings:** model picker, advanced thresholds with "Reset to defaults",
  port-country mode. Changes apply to this visitor only. While any setting differs from the
  default, every page shows a small banner "Custom detection settings active · Reset".
- Analyst pages may use the left sidebar for their own controls; public pages never do.

## 5. Architecture

```
app.py                 entry: page config, CSS, st.navigation, footer
webapp/                (new package; "site" would clash with Python's built-in module)
  data.py              library loading, analyse() with caching, filters, public results
  mapping.py           build_map (moved from app.py) + st_folium wrapper + click decoding
  ui.py                CSS injection, page header, stat tile, ship card, pill filters,
                       empty state, banners, footer, flag emoji, labels
  state.py             URL query-param helpers and session settings
pages/                 one file per page (section 3)
```

- Code from today's `app.py` is **moved, not rewritten**: `analyse`, `build_map`,
  `load_library`, `library_track`, `vessel_label`, `ship_kind`, `flag_emoji`, `port_table`,
  `_excel`, `_zip_folder` etc. keep their behaviour. Bump `MAP_STYLE` whenever `build_map`
  changes (cache key).
- **Public results:** one cached analysis per (group, time window) with the default model and
  default settings, held in `st.cache_data` and shared by every visitor (bounded with
  `max_entries`). Analyst custom settings run their own analysis per session.
- **Map clicks:** `st_folium(..., returned_objects=["last_object_clicked_tooltip"])` so panning
  and zooming do not rerun the page. Each survey area's and track's tooltip carries a stable id
  (`area:<n>`, `ship:<mmsi>`) that `mapping.py` decodes. The ISA live layer and the existing
  JavaScript stay as they are; if one fails under `st_folium`, that layer falls back to today's
  static `components.html` rendering, and the details panel list still works.
- **URL state:** `state.py` reads and writes `st.query_params` so filters and selections are
  shareable and survive a refresh; invalid values fall back to defaults silently.
- **Styling:** `.streamlit/config.toml` theme kept. `ui.py` injects one stylesheet for cards,
  pills, the hero grid, the details panel and the hidden-sidebar layout. No external JS.
- **New dependency:** `streamlit-folium` added to `requirements.txt`.

## 6. Data flow

1. Visitor opens a page → `state.py` reads the URL (group, time, area, mmsi …).
2. `data.public_results(group, window)` returns the cached analysis (survey areas, lines,
   hotspots, ports, predictions, vessel table), computing it on the first request after a
   deploy or library change (cache key includes library file modification times, as today).
3. The page filters that result (country, search) and renders cards, the map and the panel.
4. A map click → `st_folium` returns the tooltip id → selection written to the URL → panel
   re-renders.
5. Analyst custom settings → `data.analyse()` with that session's settings; results kept in
   session state only.

## 7. Error handling and empty states

- No surveys for the current filter: "No survey patterns from these ships in the last 6 months"
  plus one-click buttons to widen the time window or switch to All ships.
- Weekly data older than 10 days: a thin banner "Ship data last updated <date>".
- Unknown ship, area or hotspot in the URL: friendly not-found message with a way back.
- Upload errors (unreadable file, no positions): today's messages, shown as a single clear box
  per file.
- Map layer failure (e.g. ISA service down): the map still shows; the details panel is
  unaffected.

## 8. Memory and performance

- Budget: peak RSS of the default Home → Explore → Ship profile path must not exceed today's
  default-view measurement on the same harness (about 1.2 GB with AppTest here, about 810 MB
  last measured on Cloud).
- If "All ships, Last 6 months" as a shared public analysis breaks the budget, the fallback is
  to have the weekly GitHub Action also write the default public results to
  `library/public_results/` (small CSV/GeoJSON) and have the public pages read those files.
  That would change the weekly workflow, so it needs the user's OK before it is built.
- Tables stay capped at 1,000 rows; PNG/Excel/ZIP stay on request.

## 9. Testing

- `tests/test_pages.py` (Streamlit `AppTest`): every page renders without exceptions with
  default URL state; Ship profile renders for one known MMSI (Xue Long 412018330) and shows
  not-found for a bad one; Explore with `?area=` shows that area's panel; Detection settings
  change shows the banner and Reset clears it.
- Unit tests for `state.py` (query-param parsing and defaults) and `mapping.py` tooltip-id
  decoding.
- The existing demo benchmark numbers (`benchmarks/`) must be unchanged with the default model.
- Manual pass in the browser pane at desktop and phone (375 px) widths, light and dark mode,
  on every page; screenshots kept in `upload_batches/` as before.
- Peak RSS measured before and after (section 8).

## 10. Rollout

- Built and tested locally in this folder; the live site keeps running until the switch.
- Pushed through GitHub's web editor (about 15 new or changed text files; blob hashes
  verified against local files), then `requirements.txt` last, then a reboot of
  vesseltracker2 at share.streamlit.io (cross-module change).
- The old single-page `app.py` is kept locally in `upload_batches/2026-11-09_pre_revamp/`
  for rollback.
- README updated: new page guide, and the outdated demo table fixed.


## 11. Revision 2: SeaTrace features (added 2026-11-09)

A friend's prototype, SeaTrace (a dark three-pane analyst console built on this project's GFW
export), was reviewed. The user asked for all of its features, in the Nautical chart design.
SeaTrace is the reference for behaviour; its code is not copied. Its hand-written conclusions
are not copied either: every finding on this site is computed from our own data.

### 11.0 Design elements taken from SeaTrace
- IBM Plex Mono (tabular figures) for numbers, coordinates, times and identifiers; Newsreader and
  Public Sans stay for text.
- Status pills on ships: SURVEYING, ON STATION, IN PORT, UNDERWAY, SLOW / STOPPED, plus STALE when
  the last position is over 3 days older than the newest data.
- Priority tier pills P1 / P2 / P3 / P4 (red / amber / blue / grey, darkened to read on the light
  chart background).
- Mineral colours: nodules teal, rare-earth mud violet, cobalt crusts tan, sulphides pink, used
  everywhere a resource is named (map, pills, legends).
- Compact filter chips; "/" focuses the search box on Ships, Findings and the Review queue.
- On the Explore map: a fold-out Layers control and a live cursor-coordinates readout.
- A thin source strip above the navigation: "Real AIS from Global Fishing Watch · ISA contract
  areas · Marine Regions EEZs · updated weekly · research prototype".
- A small logo mark (a wave inside a ring with a survey-yellow dot), redrawn in the chart palette.

### 11.1 Detections, priority and "why" (the main addition)
- A **detection** is either a survey area (lawnmower, today's detector) or a **station** event
  (11.2). Each has an id `<KIND>-<VESSELCODE>-<NN>` and appears on Findings, Explore, the ship
  profile and the Review queue.
- **Confidence** (how sure the pattern is real), shown as labelled bars:
  - Survey: repeated passes, spacing regularity, reversal consistency, line overlap, progressive
    coverage, survey speed band, from the survey-block columns (`n_lines`, `spacing_cv`,
    `mean_antiparallel_dev_deg`, `mean_overlap_frac`, `progression_frac`, `survey_speed_kn`);
    headline value = the detector's own `best_confidence`.
  - Station: extended dwell, tight radius, near-zero speed, low net displacement, ship type fits
    station work, independent GFW loitering event.
  - Label: HIGH ≥ 0.8, MODERATE ≥ 0.6, else LOW.
- **Priority** (how much it matters) = weighted mean of eight factors, each 0–1 with a one-line
  reason:

| Factor | Weight | Scoring |
|---|---|---|
| Resource context | 0.22 | inside an ISA contract area: 0.9 (rare-earth mud 1.0); within 300 km of a rare-earth mud site: 0.8; within 300 km of an ISA area: 0.45; else 0.1 |
| Ship type | 0.22 | mining 1.0, drilling 0.9, geophysical/resource survey 0.75, deep-submergence support 0.75, offshore support 0.5, research 0.5, oil & gas 0.35, unknown 0.35, coast guard / government 0.25 |
| EEZ / jurisdiction | 0.16 | inside a foreign EEZ 1.0; inside a disputed / joint zone 0.75; high seas in an area sponsored by another state 0.8; within 50 km of an EEZ boundary 0.6; high seas 0.4; own EEZ 0.15 |
| Water depth | 0.10 | ≥ 1,000 m 1.0; 200–1,000 m 0.6; < 200 m 0.15; land/unknown 0.05 / 0.5 |
| Pattern of life | 0.10 | repeat visit by the same ship (> 7 days apart, < 150 km) 1.0; other ships worked the site at other times (< 50 km) 0.8; several operations on one voyage 0.6; single cycle with same-port return 0.4; single operation 0.3 |
| Ships working together | 0.08 | another ship's detection overlaps in time by > 12 h within 80 km: 1.0, else 0 |
| AIS gaps | 0.06 | an AIS gap (11.3) during or in the 7 days before: 1.0, else 0 |
| Recency | 0.06 | active 1.0; ended < 14 days ago 0.8; < 45 d 0.6; < 120 d 0.3; older 0.1 |

  Tiers: P1 ≥ 0.70, P2 ≥ 0.50, P3 ≥ 0.35, else P4. Findings are sorted by priority, then
  confidence.
- **Why**: a short list of plain-English reasons built from the same facts (e.g. "inside the
  Japanese EEZ · 4,800 m deep · Haiyang Dizhi 9 working 30 km away · 26 h AIS gap"), shown
  on every detection card.
- Ship type comes from a new hand-checked `reference_data/vessel_classes.csv` (mmsi, class,
  source); ships not listed are inferred from `ship_type` keywords and marked "(inferred)".
- New reference data (stored in the project, credited on About):
  - EEZ polygons with sovereign(s) and type (200 NM / joint regime / overlapping claim), from
    Marine Regions World EEZ v12, simplified to keep the file under 10 MB (CC BY 4.0).
  - Seabed depth: NOAA ETOPO 2022 resampled to a 5-arc-minute grid, stored as a compressed
    int16 array (public domain); depth is looked up at each detection's centre.
- ISA contract areas are **not stored** (ISA terms forbid republishing without permission): the
  server fetches them from the same public ArcGIS service the map uses, keeps them in memory for
  a day, and never writes them to disk or the repo. If the service is unreachable, the resource
  factor falls back to `resource_context.py`'s boxes and the reason says "ISA areas unavailable".
- New module `intel.py` computes all of 11.1 to 11.3 from the analysis results and the library
  tracks; it is pure Python (no Streamlit) so it is unit-testable.
- Findings page: a gallery of detection cards (tier pill, kind, ship, dates, mini track
  thumbnail, top three reasons); chips for tier, kind (survey / station), resource, country;
  click → the detection on Explore. Explore colours survey areas by tier when "Colour by
  priority" is on (default on), keeping the yellow fill for the area itself.

### 11.2 Stationkeeping detector
- New module `stationkeeping.py`: finds stretches where a ship stays on one spot at sea for at
  least 24 h: 95% of positions within 3.5 km of the median point, median speed ≤ 1.2 kn, more than
  25 km from the nearest port (world_ports.csv) and in water deeper than 200 m (an anchorage
  otherwise). Adjacent stretches less than 12 h apart merge.
- Output table `station_events` (dataset, vessel, id, start/end, hours on station, r95 km, median
  speed, net displacement, centre, nearest port km), shown alongside survey areas everywhere.
- Each station event is checked against GFW loitering events (11.4): overlapping in time and
  within 10 km = "confirmed by GFW".
- Thresholds live in a `StationConfig` dataclass with help texts, editable on Detection settings.

### 11.3 Port calls, voyages and AIS gaps
- **Port call**: at least 6 h with speed ≤ 1 kn within 5 km of a world_ports.csv port; a voyage
  runs from one call to the next; "same-port return" when it ends where it began.
- **AIS gap**: consecutive positions more than 12 h apart (hourly GFW data), with hours, distance
  between the two ends and implied speed.
- Ship status (11.0) comes from these: active detection → SURVEYING / ON STATION; open port call →
  IN PORT; last speed > 3 kn → UNDERWAY; else SLOW / STOPPED.

### 11.4 GFW registry and events
- `gfw_fetch.py` gains an `--enrich` step, run by the weekly workflow after the track pulls
  (continue-on-error like the other steps). For every library ship with an MMSI it writes:
  - `library/gfw_vessel_info.csv`: GFW vessel id(s), registry owner and owner flag, vessel type,
    length (m), gross tonnage, registry source.
  - `library/gfw_events.csv`: GFW port visits, loitering and encounter events (start, end, kind,
    lat, lon, port or partner, hours, distance) for the same 12 months.
- The workflow command changes; its schedule and secrets do not. The user does not need to do
  anything for this beyond the usual weekly run (a manual run fills it the first time).
- Ship profiles show a Registry card and GFW events on the timeline (11.5).

### 11.5 Time slider, season replay and ship timeline
- Explore gets a **time slider** (date range within the chosen window) that limits what the map
  draws, and a **Replay** button that plays the season as an animation: each ship trails its last
  four days, detections flash when they start (folium TimestampedGeoJson). Replay is a separate
  map mode without click selection.
- Ship profile gets a **timeline** (Altair): one row each for detections (coloured by kind),
  port calls, AIS gaps and GFW events, with hover details; a daily-activity histogram sits
  above the Explore slider.

### 11.6 Guided briefing
- Home has a **Start the briefing** button opening `pages/briefing.py`: Back / Next steps, a progress
  dots row, each step a short text panel beside a map.
- Steps, all computed: (1) bottom line: counts, the top P1 findings, why to trust the detector
  (validation numbers from 11.7); (2) the season: the replay map; (3) to (5) how the detector
  works, walked through on the highest-confidence survey (raw positions → straight passes →
  lawnmower block → filters passed); (6) onward: one step per P1 finding, up to four, with its
  "why"; last: "Explore it yourself" links.

### 11.7 Review queue, validation, watch items and reference events
- **Review queue** (Analyst): detections list filtered by tier, kind and status; each has a status
  (New, Reviewing, Confirmed, Dismissed, Escalated) and a note; "Next unreviewed" button. Kept for
  the visitor's session; **Export reviews** / **Import reviews** as CSV (detection id, vessel,
  status, note). Confirmed / Dismissed export directly as a Compare-models labels file.
- **Validation** (today's Compare models page, extended): benchmark results per model (today),
  agreement of station events with GFW loitering events, and precision from imported reviews,
  overall and by depth band.
- **Watch items and reference events**: `reference_data/watch_items.csv` (id, mmsi, title, window,
  basis, what to expect, source url) and `reference_data/reference_events.csv` (mmsi, date, label,
  source title, source url), written by hand and shown on ship profiles and in the briefing.
  Seeded with Chikyu's documented 2026 rare-earth mud test and its planned Feb 2027 full-scale
  test, citing the public news sources SeaTrace lists.
- Chikyu, Hakurei and Kaimei (Japanese ships SeaTrace tracks) are not in our library. Adding a ship
  needs the user to add it to the GFW vessel group in the browser (the API cannot), then a
  12-month manual run; until then their watch items show "not tracked yet".

### 11.8 Memory, testing and rollout additions
- New reference data plus `intel` and `stationkeeping` results must keep the section 8 budget;
  intel results are cached with the public results (one shared copy).
- Tests: unit tests for every priority factor and tier boundary, stationkeeping on a synthetic
  "parked 3 days" track and a "drifting in port" track, port-call and AIS-gap detection, the EEZ
  and depth lookups (a point in the Japanese EEZ, one on the high seas, one across the date line),
  CSV export/import round trip, and AppTest page tests for Findings, Briefing and Review queue.
- Rollout adds `reference_data/` files (binary: the user drags them onto GitHub's upload page) and
  a workflow edit, which is pushed last, after the site works with an empty `gfw_events.csv`.
