# SeaTrace Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the site's pages with SeaTrace's console, embedded in Streamlit and fed by the live
Survey Detector pipeline, keeping every Survey Detector feature.

**Architecture:** SeaTrace's HTML/CSS/JS is copied verbatim into `views/seatrace/`, then changed in
small commits. `webapp/seatrace_export.py` turns our results into SeaTrace's data blob; `views/seatrace.py`
injects it and shows the console full-viewport in an `st.iframe`. Analyst pages stay Streamlit, restyled dark.

**Tech Stack:** Streamlit 1.67, SeaTrace JS (Leaflet 1.9.4), pandas, pytest + AppTest, a headless
browser (Playwright via the playwright-cli skill, or the browser pane) for JS checks.

**Spec:** `docs/superpowers/specs/2026-11-09-seatrace-console-design.md`

## Global Constraints

- Source of truth for look and behaviour: `~/Downloads/SeaTrace.html`. Copy first, change after.
- Every deviation from SeaTrace's code is in its own commit with a message saying what and why.
- ISA zones are never written to disk or the repo (payload built in memory only).
- `survey_pattern_detector.py`, `port_intel.py`, `resource_context.py`, `models/` stay unchanged.
- Payload ≤ 6 MB for all ships over 6 months; `_public` keeps ≤ 3 group/season payloads; country-filtered runs are not cached in `_public`.
- Stable detection ids: `SURVEY-<CODE>-<YYYYMMDD>` / `STATION-<CODE>-<YYYYMMDD>`, `-b`/`-c` on clashes.
- Vessel ids as SeaTrace: lower-case name with letters and digits only (`Hai Da Hao` → `haidahao`).

## Review Focus

1. **A season without the ships the briefing talks about** (e.g. Last 30 days): every briefing step builds or is skipped, none throws → JS smoke test in Task 4.
2. **Reviews made last week, imported or still in localStorage, after the window slides**: they stay on the same detection or are reported as unknown → tests in Tasks 1, 5.
3. **Payload with zero detections or zero ships with data** (e.g. Chinese research, Last 30 days): console opens with an empty queue and a toast, no JS error → JS smoke test in Task 4.
4. **Leaflet / world-outline CDN blocked**: SeaTrace's own fallback note shows; tracks still draw → manual check in Task 7.
5. **Ship names with HTML or quotes in uploaded files**: SeaTrace's `esc()` covers names in the UI; our injected payload must not break out of the `<script type="application/json">` tag (`</script>` inside a name) → test in Task 2.

---

### Task 0: SeaTrace copied verbatim, shown in Streamlit

**Files:** Create `views/seatrace/console.html`, `views/seatrace/engine.js`, `views/seatrace/ui.js`, `views/seatrace/reference_blob.json` (SeaTrace's own data, for the parity check only, not shipped to visitors), `views/seatrace.py`; Modify `app.py` (add the page, default).

- [ ] **Step 1:** Split `SeaTrace.html` without changing a character: lines 1–482 + closing markup → `console.html` with the data `<script>` replaced by the slot `<script type="application/json" id="seatrace-data">{{DATA}}</script>` and the two inline scripts replaced by `<script>{{ENGINE}}</script><script>{{UI}}</script>`; engine IIFE → `engine.js`; UI IIFE → `ui.js`; data blob → `reference_blob.json`.
- [ ] **Step 2: Test** `tests/test_seatrace_page.py::test_split_rebuilds_original`: re-assembling the three files with the reference blob reproduces `SeaTrace.html` byte for byte (skipped when the original is not on disk).
- [ ] **Step 3:** `views/seatrace.py`: `render(blob: str)` assembles the HTML (JSON-escaped blob: `</` → `<\/`) and shows it with `st.iframe(html, height=…)`; CSS hides Streamlit's header/padding and sizes the iframe to `100vh`. For now it renders the reference blob.
- [ ] **Step 4:** Browser check: the page looks and behaves like `SeaTrace.html` opened directly (header, panes, map, briefing, gallery, timeline, sheets, time bar). Screenshot pair into `upload_batches/2026-11-09_seatrace/`.
- [ ] **Step 5:** Commit "SeaTrace copied verbatim".

### Task 1: Data-side fixes from the review (spec §6b)

**Files:** Modify `intel.py`, `track_events.py`, `stationkeeping.py`, `webapp/data.py`, `views/analyst_compare.py`; Tests in the matching `tests/test_*.py`.

- [ ] **Step 1: Failing tests:** `test_ids_stable_by_start_date` (ids `SURVEY-HAIDAHAO-20260601`; same-day clash gets `-b`; dropping an older detection does not change the others' ids); `test_gaps_inside_port_dropped` (a month in port with 24–48 h holes → no gaps); `test_centre_across_dateline` (fixes at 179.99 and -179.99 → station found, centre near ±180); `test_blank_flag_is_unknown` (strategic factor 0.5, "flag unknown"); `test_isa_failure_not_cached` (offline once, then online → zones returned); `test_prepare_empty_areas_has_columns`; `test_gfw_tables_malformed_events` (header without `start` → empty frame); `test_labels_upload_without_is_survey` (AppTest: error message, no exception).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement each (spec §6b). **Step 4:** Run those files → PASS. **Step 5:** Commit.

### Task 2: `webapp/seatrace_export.py`

**Interfaces — Produces:** `build_blob(res: dict, lib: pd.DataFrame, isa_features: list | None, extras: bool = True) -> dict` (SeaTrace schema + `extras`), `to_json(blob) -> str` (safe for a `<script>` tag), helpers `vessel_id(name) -> str`, `encode_track(track, t0) -> list[int]`, `decode_track(enc, t0) -> pd.DataFrame` (test only).

- [ ] **Step 1: Failing tests** in `tests/test_seatrace_export.py`:
  - `test_schema_matches_seatrace`: for every top-level key and every record type (vessel, call, gap, gfw, event L, event S, zone, port, ree, hotspot, screened, eezLine, gfwVal) the keys and value types equal those in `reference_blob.json` (extra keys allowed only under `extras`).
  - `test_vessel_ids_match_seatrace`: for ships in both, our ids equal SeaTrace's.
  - `test_track_roundtrip`: decode(encode(track)) within 0.01° and 30 min.
  - `test_blob_size_under_6mb` (all ships, 6 months).
  - `test_script_tag_safe`: a ship named `</script><b>x` survives `to_json` and does not contain `</script`.
  - `test_isa_not_written`: building the blob creates no file containing ISA ContractIDs under the project.
  - `test_event_ids_are_stable_ids`: every event carries the intel id.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (field mapping in spec §4; `L` from survey_blocks / survey_lines / areas; `S` from intel stations plus r50, onFrac, cells, cloud; `gfwVal` from stations vs GFW loitering). **Step 4:** PASS. **Step 5:** Commit.

### Task 3: Live data in the console; engine and hard-coded content

**Files:** Modify `views/seatrace.py`, `views/seatrace/engine.js`, `views/seatrace/ui.js`; `webapp/data.py` (`public_payload(group, window, settings=None, station=None) -> str`, cached).

- [ ] **Step 1:** `engine.js`: use `r.id` from the payload when present (stable ids); `REFERENCE`, `WATCH`, `REGRESSION` read from `RAW.extras` (built from `reference_events.csv`, `watch_items.csv`, GFW events, and the benchmark run), keeping SeaTrace's object shapes.
- [ ] **Step 2:** `ui.js` briefing: each judgment step is pushed only when its data exists (guards around `ecs`, `jp`, `fe`, `cdm`, the Chikyu site); bottom-line text counts what exists.
- [ ] **Step 3:** Branding: header subtitle and banner from the payload (data window, sources); "JMU capstone prototype" credit moved to the Method sheet.
- [ ] **Step 4:** `views/seatrace.py` renders `public_payload(group, window)` (spinner while building; dark error panel on failure).
- [ ] **Step 5:** Commit (engine / briefing / branding as separate commits).

### Task 4: JS smoke tests in a real browser

**Files:** Create `tests/js/smoke.py` (headless Chromium via Playwright, or the browser pane when Playwright is unavailable: rulings ledgered).

- [ ] **Step 1:** For payloads (mining 6m, all 6m, china 30d, all all, an empty-detections payload): load the assembled HTML, collect console errors, run every briefing step (`brief(i)` for all i), switch Map/Gallery/Timeline, open Validation and Method sheets, press play and SEASON.
- [ ] **Step 2:** Assert: no console errors; detections > 0 except the empty payload; tiers present; briefing steps all render.
- [ ] **Step 3:** Fix what fails (each fix a commit with a test). **Step 4:** Commit.

### Task 5: Survey Detector extras inside the console (spec §5)

**Files:** Modify `views/seatrace/ui.js`, `console.html` (CSS in SeaTrace's tokens), `webapp/seatrace_export.py` (extras), `views/seatrace.py`.

- [ ] **Step 1: Failing tests:** export tests for `extras.ports` (home / rare-earth ports per detection with km and route coordinates), `extras.target`, `extras.pred` (predicted lines), `extras.watchlistNoData`; JS smoke assertions for the new DOM (season selector, Ports section, three new layers, queue export/import buttons, analyst menu, hash restore).
- [ ] **Step 2:** Implement in order, one commit each: season/group selector (links `?group=&time=` with `target="_top"`); Ports section + routes layer; Likely surveying for; Predicted lines layer + Seabed resource regions layer; queue CSV export / import / labels (Blob download in JS; import via file input; unknown ids reported in a toast); URL-hash state + Copy link; Analyst menu; watchlist-without-data rows; custom-settings and stale-data toasts.
- [ ] **Step 3:** Run tests + JS smoke → PASS.

### Task 6: Analyst pages, navigation, caching, removals

**Files:** Modify `app.py`, `views/analyst_*.py`, `webapp/ui.py`, `webapp/data.py`, `.streamlit/config.toml` (dark theme with SeaTrace tokens and IBM Plex fonts); Delete `views/home.py, explore.py, findings.py, ships.py, ship_profile.py, hotspots.py, how_it_works.py, about.py, briefing.py, analyst_review.py` and their tests.

- [ ] **Step 1: Failing tests:** AppTest renders SeaTrace (default) and each Analyst page; Upload's "Open in console" builds a payload from the sample file; custom settings cache one payload per session (second render does not call `analyse`); `_public` max 3 entries.
- [ ] **Step 2:** Implement; Analyst pages get a slim SeaTrace-style header with a "← Back to SeaTrace" link. **Step 3:** PASS. **Step 4:** Commit.

### Task 7: Verify, memory, docs, final review

- [ ] **Step 1:** Full suite PASS; JS smoke PASS.
- [ ] **Step 2:** `tests/measure_rss.py` updated for the new page; peak ≤ 1425 MB (old baseline, same harness); record it.
- [ ] **Step 3:** Browser pass of every console control and Analyst page (desktop; narrow width as far as SeaTrace's CSS allows); CDN-blocked check (Review Focus 4); screenshots.
- [ ] **Step 4:** README: SeaTrace section, credits; About text in the Method sheet.
- [ ] **Step 5:** Final whole-branch review (fresh reviewer), fix Critical/Important with tests.
- [ ] **Step 6:** Stop: report to the user and ask before publishing.
