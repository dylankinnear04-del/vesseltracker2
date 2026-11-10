# Survey Detector Website Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-page Streamlit app (sidebar + 7 tabs) with a multi-page, public-first
website in the "Nautical chart" style, with an Analyst menu for the expert tools.

**Architecture:** `app.py` becomes a short `st.navigation(position="top")` entry point. Today's
`app.py` code is **moved** (not rewritten) into a `webapp/` package (data, mapping, ui, state),
and each page is one small file in `pages/`. Public pages share one cached analysis per
(ship group, time window) with the default settings; analyst settings are per session.

**Tech Stack:** Python 3.13, Streamlit ≥ 1.50 (`st.navigation`, `st.pills`, `st.query_params`),
folium + `streamlit-folium`, pandas, pytest + `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-11-09-website-revamp-design.md`

## Global Constraints

- Do not change `survey_pattern_detector.py`, `port_intel.py`, `resource_context.py`, `models/`,
  `gfw_fetch.py`, `.github/`, `library/`, `reference_data/`, `benchmarks/`.
- Theme stays in `.streamlit/config.toml` (Nautical chart: primary `#A3166E`, Newsreader headings,
  Public Sans body). Extra CSS lives only in `webapp/ui.py`.
- Public pages never use the sidebar. Analyst pages may.
- Defaults: group `mining`, window `6m` (= 182 days ending at the chosen ships' newest position).
- Windows: `30d` = 30, `6m` = 182, `1y` = 365, `all` = everything (shared window for all ships).
- Groups: `mining` = MMSI on `library/watchlist_deep_sea_mining.csv`; `china` = flag "China" and
  `ship_kind` "Research / survey ship"; `all` = every catalog row with data.
- Bump `MAP_STYLE` whenever `build_map` changes.
- Public `analyse` cache: `max_entries=4`. Tables shown capped at 1,000 rows.
- Peak RSS for Home → Explore → Ship profile ≤ today's default view on the same harness.
- Shared footer carries `CREDITS` (incl. "Powered by Global Fishing Watch") on every page.
- No git repo exists locally: Task 0 creates a **local-only** repo for checkpoints (never pushed;
  the user publishes through GitHub's web UI as before).

## Review Focus

1. **Survey areas across the date line** (Pacific ships near 180°): clicking an area must select
   it even though the map wraps longitudes around a central meridian → test in Task 3.
2. **Malformed or stale links** (`?area=abc`, `?area=999`, `?mmsi=123`, `?group=foo`): fall back to
   defaults or a friendly not-found, never a traceback → tests in Tasks 2, 6, 7.
3. **A filter with no ship data in the window** (e.g. `group=china&time=30d` when nobody reported):
   empty state with "widen" buttons, `analyse` is not called with zero groups → test in Task 1 & 6.
4. **Analyst custom settings leaking into the shared public cache** or vanishing between pages:
   custom settings must change only that session's results, and the banner must follow them across
   pages → test in Task 10.
5. **Cold first visit after a deploy** (All ships analysis can take a minute+): a spinner with plain
   words ("Reading 50 ships' tracks — about a minute the first time"), not a blank page → check in
   Task 12.

---

### Task 0: Workspace, backup and local checkpoints

**Files:**
- Create: `upload_batches/2026-11-09_pre_revamp/` (copy of `app.py`, `requirements.txt`, `README.md`)
- Modify: `.claude/launch.json` (point at the new venv), `requirements.txt`
- Create: `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1:** Copy `app.py`, `requirements.txt`, `README.md` to `upload_batches/2026-11-09_pre_revamp/`.
- [ ] **Step 2:** Create the venv: `python3 -m venv --system-site-packages <scratchpad>/venv` then
  `<venv>/bin/pip install streamlit folium searoute streamlit-folium pytest`. Record the installed
  Streamlit and streamlit-folium versions.
- [ ] **Step 3:** Confirm the Streamlit APIs this plan relies on exist in that version:
  `st.navigation(..., position="top")`, `st.Page(..., url_path=..., visibility="hidden")`,
  `st.pills`, `st.switch_page(page, query_params=...)`. Any missing → stop and report.
- [ ] **Step 4:** Add `streamlit-folium>=0.24` to `requirements.txt`. Update `.claude/launch.json`
  `runtimeExecutable` to the new venv's python.
- [ ] **Step 5:** `tests/conftest.py`: put the project root on `sys.path`; fixture `app_test(page)`
  returning `AppTest.from_file("app.py", default_timeout=300)` with `query_params` settable.
- [ ] **Step 6:** Measure the baseline: run today's `app.py` default view under AppTest and record
  peak RSS (`resource.getrusage(...).ru_maxrss`) in `upload_batches/2026-11-09_pre_revamp/rss.txt`.
- [ ] **Step 7:** `git init` (local only), add `.gitignore`-respecting files, commit "baseline before revamp".

### Task 1: `webapp/data.py` — library, analysis and public results

**Files:**
- Create: `webapp/__init__.py`, `webapp/data.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Moves from `app.py` unchanged: `HERE, LIBRARY, UPLOAD_TYPES, TABLES, SETTINGS, WATCHLIST`,
  `analyse`, `on_request`, `_excel`, `_zip_folder`, `library_files`, `load_library`,
  `library_track`, `safe_name`, `watchlist_mmsi`, `ship_kind`, `KIND_ORDER`.
- Produces:
  - `GROUPS: dict[str, str]` = `{"mining": "Mining ships", "china": "Chinese research", "all": "All ships"}`
  - `WINDOWS: dict[str, tuple[str, int | None]]` = `{"30d": ("Last 30 days", 30), "6m": ("Last 6 months", 182), "1y": ("Last year", 365), "all": ("All data", None)}`
  - `default_settings() -> dict` = `{**asdict(spd.Config()), "model": <models default key>, "port_country": "flag"}`
  - `select_ships(lib: pd.DataFrame, group: str, countries: tuple[str, ...] = ()) -> pd.DataFrame` — rows with `has_data`; unknown group → `"mining"`.
  - `build_groups(chosen: pd.DataFrame, window: str) -> tuple[tuple, tuple, list[str]]` — `(groups, identities, quiet_names)`, the sidebar logic from `app.py:1157-1197` with one shared window.
  - `prepare(res: dict) -> dict` — the table clean-up and area numbering from `app.py:1293-1340`; returns `{"vessels", "ports", "areas", "preds", "hotspots", "linked", "home", "labels", "res"}` (`areas` has `number`, `live`).
  - `public_results(group: str, window: str, countries: tuple = (), settings: dict | None = None) -> dict | None` — `None` when no ship has data in the window; otherwise `prepare(analyse(...))`. `settings=None` means default settings (shared cache).
  - `last_updated(lib) -> datetime.date | None` — newest `data_to`.

- [ ] **Step 1: Write failing tests** in `tests/test_data.py`:
  - `test_select_ships_mining_matches_watchlist`: every returned MMSI is in `watchlist_mmsi(...)`, and Xue Long `412018330` is included.
  - `test_select_ships_unknown_group_falls_back`: `select_ships(lib, "foo")` equals `select_ships(lib, "mining")`.
  - `test_build_groups_window_6m`: every track cut covers ≤ 182 days ending at `chosen.data_to.max()`.
  - `test_public_results_empty_window_returns_none`: a `chosen` set whose tracks all end before the window → `public_results` returns `None` without calling `analyse` (monkeypatch `analyse` to raise).
  - `test_public_results_default_has_numbered_areas`: `public_results("mining", "6m")["areas"]["number"]` is `1..n` with live areas first.
- [ ] **Step 2:** Run `pytest tests/test_data.py -v` → FAIL (module missing).
- [ ] **Step 3:** Create `webapp/data.py`: move the listed code from `app.py`, then add the new functions with the signatures above. `st.cache_data` decorators stay as in `app.py`.
- [ ] **Step 4:** Run `pytest tests/test_data.py -v` → PASS.
- [ ] **Step 5:** Commit "webapp.data: library and analysis moved, public results".

### Task 2: `webapp/state.py` — shareable URL state and session settings

**Files:** Create `webapp/state.py`; Test `tests/test_state.py`

**Interfaces:**
- Produces:
  - `param(name: str, allowed: Iterable[str] | None, default: str) -> str` — reads `st.query_params`; value not allowed → default.
  - `int_param(name: str, default: int | None = None) -> int | None` — non-integer → default.
  - `set_params(**kw: str | int | None) -> None` — `None` removes the key.
  - `settings() -> dict` — this session's detection settings (`session_state["settings"]`, default `data.default_settings()`).
  - `is_custom() -> bool`, `reset_settings() -> None`.

- [ ] **Step 1: Write failing tests** (run inside a minimal AppTest script so `st.query_params` works):
  - `test_param_rejects_unknown_value`: `?group=foo` → `param("group", GROUPS, "mining") == "mining"`.
  - `test_int_param_bad_value`: `?area=abc` → `int_param("area") is None`.
  - `test_set_params_none_removes_key`.
  - `test_is_custom_after_change_and_reset`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 3: `webapp/mapping.py` — the map, clickable

**Files:** Create `webapp/mapping.py`; Test `tests/test_mapping.py`

**Interfaces:**
- Moves unchanged from `app.py`: colour constants, `ISA_*`, `CCZ_OUTLINE`, `NATIONAL_SEABED`,
  `MINERAL_COLORS`, `CHINA_OUTLINE`, `LiveSeabedAreas`, `_wrap`, `_unwrap`, `_polyline`,
  `_central_lon`, `_rows`, `_km`, `_vessel_popup`, `_match`, `build_map`, `map_html`, `MAP_STYLE` (bump to 7).
- Produces:
  - `pick_at(lat: float, lon: float, geojson: dict, labels: tuple, c: float) -> tuple[str, object] | None` —
    `("area", number)` if the point lies inside a survey-area polygon (`matplotlib.path.Path.contains_point`,
    longitudes normalised with `_wrap(lon, c)` on both sides); else `("ship", (dataset, vessel))` for the
    nearest track vertex within 20 km; else `None`.
  - `show_map(geojson, vessels, labels, focus=None, focus_area=None, key: str = "map", height: int = 620) -> tuple[str, object] | None` —
    renders with `st_folium(build_map(...), returned_objects=["last_object_clicked"], key=key, height=height, use_container_width=True)`
    and returns `pick_at(...)` for a new click (remember the last handled click in session state so a rerun does not re-fire).
  - `static_map(...)` — today's `components.html(map_html(...))` path, used for the Home preview and as the fallback.

- [ ] **Step 1: Write failing tests:**
  - `test_pick_at_inside_area` / `test_pick_at_outside_returns_none` on a small hand-made geojson.
  - `test_pick_at_across_dateline`: an area spanning lon 179.5 → -179.5, central lon `c=180`, click at lon `-179.8` and at `180.2` → both `("area", 1)`.
  - `test_pick_at_ship_track_within_20km` / `..._beyond_20km_none`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Manual check in the browser pane (throwaway script): ISA live layers still draw under `st_folium`. If not, note it; Explore will use `static_map` for that layer per the spec fallback.
- [ ] **Step 6:** Commit.

### Task 4: `webapp/ui.py` + navigation shell

**Files:** Create `webapp/ui.py`, `pages/*.py` (stubs for all 11 pages); Replace `app.py`; Test `tests/test_pages.py`

**Interfaces:**
- Moves from `app.py`: `FLAG_CODES`, `flag_emoji`, `vessel_label`, `dataset_note`, `WHAT_IS_IT`, `CREDITS`, `_masthead_svg`, `port_table`, `PORT_VIEW`, `first_port`, `list_name`.
- Produces:
  - `inject_css() -> None` — one `<style>` block: cards, pills row, hero with chart-grid background, stat tiles, details panel, ship-card grid, footer; `@media (max-width: 760px)` stacks columns.
  - `hero(eyebrow: str, title: str, lede: str) -> None`, `page_header(title: str, lede: str = "") -> None`
  - `stat_tiles(items: list[tuple[str, str, str | None]]) -> None` — (value, label, help)
  - `ship_card(row: pd.Series, n_areas: int, live: bool) -> str` — HTML `<a class="ship-card" href="ship_profile?mmsi=…">`
  - `empty_state(message: str, actions: list[tuple[str, dict]]) -> None` — each action a button that calls `state.set_params(**params)` and reruns.
  - `banners(lib) -> None` — stale-data banner when `last_updated` is > 10 days old; custom-settings banner with a Reset button when `state.is_custom()`.
  - `footer(next_label: str | None = None, next_page: str | None = None) -> None`
- `app.py`: `set_page_config(page_title="Survey Detector", page_icon=":ship:", layout="wide")`, `inject_css()`,
  `st.navigation({"": [home, explore, ships, hotspots, how, about], "Analyst": [upload, compare, data, settings]}, position="top")`,
  plus `ship_profile` as `st.Page(..., url_path="ship_profile", visibility="hidden")`; `banners()`; `page.run()`.

- [ ] **Step 1: Write failing tests** `test_every_page_renders`: parametrised over the 11 page paths, `AppTest` switches to each (`at.switch_page(...)`) and asserts `not at.exception`; `test_stale_banner`: monkeypatch `last_updated` to 11 days ago → "Ship data last updated" shown, 9 days → not shown.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `ui.py`, the new `app.py`, and stub pages that call `page_header` + `footer`. **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 5: Home page

**Files:** Modify `pages/home.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing test** `test_home_shows_stats_and_buttons`: markdown contains "Spotting the ships that quietly map the seafloor"; four stat tiles ("ships tracked", "survey areas found", "surveying now", "last updated"); links to Explore map and How it works.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per spec 4.1: `hero("SEAFLOOR SURVEY WATCH", "Spotting the ships that quietly map the seafloor", "We read public ship-tracking data and flag the back-and-forth “lawnmower” patterns that survey ships leave behind.")`; `st.page_link` buttons; stats from `public_results("mining", "6m")` + `load_library`; `static_map` preview (height 360); "Recently surveying" = up to 4 `ship_card`s by newest area `end_time`; three "What you can do here" cards; `footer("Explore the map", "pages/explore.py")`.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 6: Explore map page

**Files:** Modify `pages/explore.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:**
  - `test_explore_default_lists_areas`: with no params, the panel shows "What you're looking at" and a list with one entry per area.
  - `test_explore_area_param_selects_area`: `?area=1` → panel shows "SURVEY AREA 1", "Likely surveying for", "View ship profile".
  - `test_explore_bad_area_param`: `?area=999` and `?area=abc` → default panel, no exception.
  - `test_explore_empty_filter_shows_widen`: monkeypatch `public_results` → `None`; page shows "No survey patterns" and buttons "Try last year" and "Show all ships".
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per spec 4.2: `st.pills` for group (`GROUPS`) and time (`WINDOWS`) and a country `st.multiselect`, all synced with `state.set_params`; columns `[7, 3]`: left `show_map(...)`, right the details panel. Panel content for an area reuses today's Ships-tab area panel text (`app.py:1577-1630`: dates, lines, km², `resource_context` "Likely surveying for", `first_port` of `home` and `linked`). Buttons: "Zoom to area" (sets `focus_area`), "View ship profile →" (`st.switch_page("pages/ship_profile.py", query_params={"mmsi": …})`). A click from `show_map` writes `area` / `mmsi` to the URL and reruns; with `mmsi` selected the panel shows that ship's flag, name, kind, survey-area count, last seen and "View ship profile →". Pink-predictions caption kept when any ship is surveying now. Spinner text: "Reading the ships' tracks — about a minute the first time".
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 7: Ships gallery and Ship profile

**Files:** Modify `pages/ships.py`, `pages/ship_profile.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:**
  - `test_ships_search_filters_cards`: search "Xue Long" → exactly one card, linking `ship_profile?mmsi=412018330`.
  - `test_ships_watchlist_without_data_collapsed`: an expander "On our watchlist, no tracking data yet" exists and is collapsed.
  - `test_profile_known_ship`: `?mmsi=412018330` → header contains "Xue Long", "IMO 8877899", key-facts tiles render.
  - `test_profile_unknown_ship`: `?mmsi=123` and no `mmsi` → "We couldn't find that ship" + link to Ships.
  - `test_profile_ship_without_surveys`: a ship with data but no areas → "No survey patterns found for this ship in the last 6 months" (no exception).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per spec 4.3 and 4.4. Ships: `st.text_input` search over name/MMSI/IMO/operator, pills for group and country, "has surveys" toggle, a CSS grid of `ship_card`s (counts from `public_results("all", "6m")`). Profile: catalog row by MMSI; analysis = `public_results("all", "6m")` filtered to this ship (no separate analysis run); `show_map(..., focus=(dataset, vessel))`; area list as in Explore's panel; "Surveyed alongside" = hotspots whose `vessels` include this ship, linking `hotspots?hotspot=N`. Fixes the known "Zoom to a ship" repeated-name label by using `vessel_label` once.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 8: Hotspots page

**Files:** Modify `pages/hotspots.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:** `test_hotspots_ranked_by_ships` (first card has the max `n_vessels`); `test_hotspot_param_selects` (`?hotspot=1` highlights card 1 and the map zooms to it); `test_hotspot_bad_param` (`?hotspot=x` → no exception).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per spec 4.5 on `public_results("all", "1y")` (hotspots need several ships): cards with ships (links to profiles), date span, likely resource; selecting sets `?hotspot=` and `show_map(focus_area=...)` below. Caption text reused from today's Hotspots tab (`app.py:1658`).
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 9: How it works and About & data

**Files:** Modify `pages/how_it_works.py`, `pages/about.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:** `test_how_it_works_has_four_steps_and_limits` (headings "1." … "4." and "What this can't tell you"); `test_about_has_credits` (contains "Powered by Global Fishing Watch", "CC BY-NC 4.0", "Natural Earth", "Marine Regions").
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement per spec 4.6/4.7. Four inline-SVG step illustrations in the chart style (reuse `_masthead_svg` lawnmower for step 2). Filter sentences come from the `SETTINGS` help texts for `max_turn_hours`, `min_new_track_frac`, `min_offshore_km`, `min/max_survey_speed_kn`, `min_lines_per_block`, rewritten as one plain sentence each. Limits include coast-guard patrols near unmapped shoals (e.g. Scarborough Shoal). About: sources, licences, weekly Monday update, non-commercial note, contact.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 10: Analyst — Detection settings and Data & downloads

**Files:** Modify `pages/analyst_settings.py`, `pages/analyst_data.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:**
  - `test_settings_change_shows_banner_everywhere`: change `min_lines_per_block` on the settings page → banner "Custom detection settings active" on Explore; Reset removes it.
  - `test_custom_settings_do_not_touch_public_cache`: after a custom change in one AppTest session, a fresh session's Explore area count equals the default count.
  - `test_data_page_downloads`: download buttons for Excel and ZIP present; tables capped at 1,000 rows.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Settings page = today's sidebar "Detection model" + "Advanced settings" + port-country radio (`app.py:1210-1250`), writing to `state.settings()`. Data page = today's Data & downloads tab (`app.py:1760-1799`) + "Notes on the data" + the rare-earth port table from today's Ports tab (`app.py:1687-1700`), run on `public_results(group, window, settings=state.settings() if state.is_custom() else None)` with group/window pills. Public pages also pass custom settings when `is_custom()`.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 11: Analyst — Upload your own track and Compare models

**Files:** Modify `pages/analyst_upload.py`, `pages/analyst_compare.py`; Test `tests/test_pages.py`

- [ ] **Step 1: Failing tests:** `test_upload_runs_on_benchmark_file` (upload `benchmarks/demo1_hourly_patrols.csv` → map + area list render, no exception); `test_upload_unreadable_file_shows_error` (a text file of junk → one error box); `test_compare_models_runs` (pick `benchmarks/synthetic_10_ships.csv` + its labels → precision/recall table).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Upload = today's uploader, "combine files" toggle and identity form (`app.py:1201-1265`, `1483-1515`), results shown with the Explore layout (map `[7,3]` panel) via `prepare(analyse(...))`. Compare = today's Compare models tab (`app.py:1700-1745`) unchanged.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Run the benchmark check: default-model results on `benchmarks/` match the numbers before the revamp (run the same comparison on the backup `app.py` and diff).
- [ ] **Step 6:** Commit.

### Task 12: Memory, browser check, README

**Files:** Modify `README.md`; Create `upload_batches/2026-11-09_revamp/` (screenshots)

- [ ] **Step 1:** Full suite: `pytest -v` → all PASS.
- [ ] **Step 2:** Peak RSS for Home → Explore → Ship profile under AppTest ≤ Task 0 baseline. Over budget → stop and ask the user about the spec §8 fallback (precomputed results in the weekly job).
- [ ] **Step 3:** `preview_start survey-app-v2`; click through every page at desktop and 375 px widths, light and dark; cold-start spinner text visible; screenshot each page into `upload_batches/2026-11-09_revamp/`.
- [ ] **Step 4:** README: new page guide, Analyst menu, and the outdated demo table corrected (Line-Chain now rejects the patrols).
- [ ] **Step 5:** Commit.

### Task 13: Publish

- [ ] **Step 1:** List every new/changed file with its `git hash-object` (≈ `app.py`, `requirements.txt`, `README.md`, `.gitignore`, `webapp/*.py`, `pages/*.py`, `tests/*.py`).
- [ ] **Step 2:** With the user's go-ahead, push through GitHub's web editor in the browser pane: `webapp/` and `pages/` first (inert until `app.py` changes), then `app.py`, then `requirements.txt` last; verify blob hashes via the API tree.
- [ ] **Step 3:** Reboot vesseltracker2 at share.streamlit.io (cross-module change), then check every page on the live site and the memory graph.
- [ ] **Step 4:** Update the project memory file with the new layout.

---

## Revision 2: SeaTrace features (spec §11)

**Execution order:** 0, 1, 2, 3, **14, 15, 16, 17**, 4 (with Task 18's design elements folded into
`ui.py`), 5 + 19, 6 + 20, **21**, 7 + 22, 8, 9, 10, 11 + 23, **24**, 12, 13. A task "+ N" means
both briefs are done together on the same page file.

**Global constraints added:**
- ISA contract areas are never written to disk or the repo; server-side copies live in memory
  (`st.cache_data(ttl=86400)`), falling back to `resource_context.py` boxes.
- `intel.py`, `stationkeeping.py`, `track_events.py`, `geo_lookup.py` import no Streamlit.
- Priority weights, tier cut-offs and station thresholds use the exact values in spec §11.1 / §11.2.
- Fonts: add IBM Plex Mono (Google Fonts, in `ui.inject_css`) for `.num`, `.mono`, coordinates,
  identifiers and times.

**Review Focus added:**
6. **Detections at the date line or exactly on an EEZ edge**: lookups must wrap longitude and
   treat the polygon edge as inside → tests in Task 14.
7. **Ships in port for weeks** (shipyard stays): no station event, one long port call, no
   AIS-gap flood → tests in Tasks 15–16.
8. **GFW enrich files missing or empty** (first deploy, API outage): profiles and priority still
   render; registry card says "Not in the GFW registry yet" → tests in Tasks 17, 22.
9. **Imported review CSV from another week** (ids that no longer exist, unknown statuses): unknown
   rows reported and skipped, nothing crashes → test in Task 23.

### Task 14: Reference data and lookups (EEZ, depth, vessel classes)

**Files:** Create `scripts/build_reference.py`, `geo_lookup.py`, `reference_data/eez_v12_simplified.geojson`,
`reference_data/depth_etopo2022_5min.npz`, `reference_data/vessel_classes.csv`; Test `tests/test_geo_lookup.py`

**Interfaces — Produces:**
- `geo_lookup.eez_at(lat: float, lon: float) -> dict | None` — `{"name", "sovereigns": tuple[str, ...], "type": "200NM" | "Joint regime" | "Overlapping claim"}`; edges count as inside; longitude wrapped.
- `geo_lookup.nearest_boundary_km(lat, lon) -> tuple[float, str] | None` — distance to the nearest EEZ boundary line and its name.
- `geo_lookup.depth_m(lat, lon) -> float | None` — negative below sea level (ETOPO convention).
- `geo_lookup.vessel_class(mmsi: str, ship_type: str, gfw_type: str = "") -> tuple[str, bool]` — (class key, inferred?) with keys `MINING, DRILLING, GEO, DEEP, SUPPORT, ENERGY, RESEARCH, GOV, UNK`.

- [ ] **Step 1:** `scripts/build_reference.py` downloads Marine Regions World EEZ v12 (low-res) and ETOPO 2022 60 s, writes the two reference files (EEZ simplified to < 10 MB; depth block-averaged to 5′, int16, `np.savez_compressed`). Run it once; record sizes and sources. Write `vessel_classes.csv` by hand for every library ship with data (class from operator/ship type/notes; `source` column).
- [ ] **Step 2: Failing tests:** `test_eez_japan` (25.0 N, 131.0 E → sovereign Japan), `test_eez_high_seas` (10 N, 140 W → None), `test_eez_dateline` (Fiji EEZ at 179.9 E and -179.9 E both Fiji), `test_depth_ccz_deep` (12 N, 130 W < -3500), `test_depth_land` (Beijing ≥ 0), `test_boundary_china_japan` (East China Sea point near 28 N, 126 E → < 100 km), `test_vessel_class_inferred` ("Drilling ship" → `("DRILLING", True)`), `test_vessel_class_listed` (a listed MMSI → `inferred False`).
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implement `geo_lookup.py` (matplotlib `Path` point-in-polygon with bbox prefilter; boundaries = polygon edges shared by two EEZs, cKDTree on densified vertices). **Step 5:** Run → PASS. **Step 6:** Commit.

### Task 15: Port calls, voyages and AIS gaps

**Files:** Create `track_events.py`; Test `tests/test_track_events.py`

**Interfaces — Produces:**
- `port_calls(track: pd.DataFrame, ports: pd.DataFrame) -> pd.DataFrame` — columns `port, country, lat, lon, start, end, hours, open` (≥ 6 h at ≤ 1 kn within 5 km; `open` = still in port at the last fix). `track` has `time, lat, lon, speed_kn` (from `spd.standardize`).
- `voyages(calls: pd.DataFrame, track_end) -> pd.DataFrame` — `from_port, to_port, start, end, days, same_port, at_sea`.
- `ais_gaps(track: pd.DataFrame, min_hours: float = 12) -> pd.DataFrame` — `start, end, hours, km, implied_kn, lat0, lon0, lat1, lon1`.
- `ship_status(track, calls, active_kinds: set[str], newest_time) -> tuple[str, bool]` — (one of SURVEYING / ON STATION / IN PORT / UNDERWAY / SLOW / STOPPED, stale?) per spec §11.0/§11.3.

- [ ] **Step 1: Failing tests** on synthetic tracks: a 10 h stop at Qingdao → one call; a 3 h stop → none; two calls at the same port → `same_port`; a 30-day shipyard stay → one call, no gaps; a 20 h hole → one gap with `hours == 20`; status rules incl. stale (last fix 4 days before `newest_time`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 16: Stationkeeping detector

**Files:** Create `stationkeeping.py`; Test `tests/test_stationkeeping.py`

**Interfaces — Produces:**
- `StationConfig` dataclass: `min_hours=24, r95_km=3.5, max_median_kn=1.2, min_port_km=25, min_depth_m=200, merge_gap_hours=12`, each with a help text in `STATION_HELP: dict[str, str]`.
- `detect_stations(track, ports, cfg=StationConfig(), depth=geo_lookup.depth_m) -> pd.DataFrame` — `start, end, hours, r95_km, median_kn, net_km, lat, lon, port_km, depth_m`.
- `match_loitering(stations: pd.DataFrame, gfw_events: pd.DataFrame) -> pd.Series` — per station: dict `{hours, overlap, km}` or `None` (overlap in time and ≤ 10 km).

- [ ] **Step 1: Failing tests:** synthetic "parked 3 days 1 km wobble, 4,000 m deep, 300 km from port" → 1 event, hours ≈ 72; "parked in port" → 0; "drifting 2 kn" → 0; "two 20 h stays 6 h apart" → 1 merged event; shelf (100 m) → 0; loitering match within 10 km and overlapping → dict, 50 km away → None.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 17: `intel.py` — detections, confidence, priority, why

**Files:** Create `intel.py`; Modify `webapp/data.py` (`prepare` adds intel); Test `tests/test_intel.py`

**Interfaces:**
- Consumes: Tasks 14–16; `prepare()` output; library tracks; `library/gfw_vessel_info.csv`, `library/gfw_events.csv` (optional); ISA zones via `isa_zones() -> list[dict] | None`.
- Produces:
  - `FACTORS` (key, label, weight) exactly as spec §11.1; `tier_of(score) -> str`; `conf_label(score) -> str`.
  - `build(prepared: dict, tracks: dict[tuple[str, str], pd.DataFrame], lib: pd.DataFrame, gfw_info: pd.DataFrame, gfw_events: pd.DataFrame, isa: list | None, newest) -> dict` returning
    `{"detections": DataFrame, "stations": DataFrame, "calls": DataFrame, "gaps": DataFrame, "status": DataFrame}`.
    `detections` columns: `id, kind ("survey"|"station"), dataset, vessel, mmsi, name, flag, start, end, active, lat, lon, area_number, confidence, conf_label, conf_parts (list of (label, value, detail)), priority, tier, pri_parts (list of (key, label, value, weight, detail)), why (list[str]), resource, eez, depth_m, coord (list of ids), gfw_confirmed`.
  - `webapp.data.prepare` adds key `"intel"` (computed once per shared result; tracks are the analysed window).

- [ ] **Step 1: Failing tests:** one test per factor's scoring bands (exact values from §11.1, incl. boundaries 0.70/0.50/0.35 and conf 0.8/0.6), `test_coordination_needs_12h_overlap_within_80km`, `test_revisit_same_ship_7_days_150km`, `test_why_mentions_foreign_eez_and_depth`, `test_isa_unavailable_falls_back` (reason contains "ISA areas unavailable"), `test_missing_gfw_files_ok`, `test_ids_stable` (`SURVEY-<CODE>-01` numbering by start time).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; `isa_zones()` lives in `webapp/data.py` (Streamlit cache, in-memory only). **Step 4:** Run → PASS; rerun `tests/test_data.py`. **Step 5:** Commit.

### Task 18: SeaTrace design elements in `ui.py` (done inside Task 4)

- Add to Task 4's `ui.py`: `status_pill(status, stale) -> str`, `tier_pill(tier) -> str`, `mineral_pill(kind) -> str`, `source_strip() -> None`, `logo_svg() -> str`, the IBM Plex Mono font and `.num/.mono` classes, colour tokens `TIER_COLORS = {"P1": "#C8322B", "P2": "#B86E0B", "P3": "#2F78A8", "P4": "#66798A"}`, `MINERAL_COLORS_UI = {"nodules": "#1F9E8F", "ree": "#7C5CD6", "crusts": "#A96A35", "sulphides": "#C24D86"}`, and a "/" key handler (small `st.html` script) focusing the first search input.
- Tests (in `tests/test_pages.py`): `test_source_strip_on_every_page`; `test_tier_pill_colours` (exact hex per tier).

### Task 19: Home additions (with Task 5)
- "Start the briefing" primary button next to "Explore the map"; stat tile "P1 findings"; "Recently surveying" cards show status pills. Test: `test_home_has_briefing_button`.

### Task 20: Explore additions (with Task 6)
- "Colour by priority" toggle (default on) passing tiers to `build_map` (survey-area outline colour = tier colour, fill stays yellow; station events drawn as violet-outlined rings); layers for EEZ boundaries, AIS gaps (dashed red), port calls (anchor dots), GFW events; `folium.plugins.MousePosition` coordinates readout; date-range `st.slider` filtering what is drawn; daily-activity histogram (Altair) above it; **Replay** button → `mapping.replay_map(intel, tracks, window) -> folium.Map` (TimestampedGeoJson, 4-day trails, 1 day/step) shown via `static_map`. Bump `MAP_STYLE`.
- Panel shows tier pill, priority score, confidence bars and the "why" list for the selected detection.
- Tests: `test_explore_priority_panel` (`?area=1` shows a tier pill and ≥ 3 reasons); `test_explore_slider_limits_list` (narrow range → fewer list rows); `test_replay_map_has_timestamped_layer`.

### Task 21: Findings page
**Files:** Create `pages/findings.py`; add to navigation after Explore.
- Gallery of detection cards (CSS grid): tier pill, kind, ship + flag, dates, mini track thumbnail (inline SVG polyline of the detection's positions, 120×70), top three reasons, link `explore?area=N` / `explore?station=ID`. Chips: tier, kind, resource, country; "/" search.
- Tests: `test_findings_sorted_by_priority`, `test_findings_tier_filter`, `test_findings_card_links_to_explore`.

### Task 22: Ship profile additions (with Task 7)
- Status pill; Registry card (owner, owner flag, type, length, GT, source) or "Not in the GFW registry yet"; Altair timeline (rows: detections, port calls, AIS gaps, GFW events; hover tooltips); voyages table with same-port returns; watch items and reference events from the two CSVs with source links; station events listed with survey areas.
- Tests: `test_profile_registry_missing_ok`, `test_profile_timeline_rows`, `test_profile_watch_items_for_listed_mmsi` (seed a temp CSV).

### Task 23: Review queue and validation (with Task 11)
**Files:** Create `pages/analyst_review.py`; Modify `pages/analyst_compare.py`; create `webapp/reviews.py`.
- `reviews.py`: `STATUSES = ("New", "Reviewing", "Confirmed", "Dismissed", "Escalated")`, `get(id) -> dict`, `set(id, status, note)`, `to_csv(detections) -> bytes`, `from_csv(data: bytes, detections) -> tuple[int, list[str]]` (applied count, skipped ids/statuses), `to_labels_csv() -> bytes` (`vessel,is_survey` from Confirmed=1 / Dismissed=0).
- Review page: filters, list, status buttons, note box, "Next unreviewed", export/import, "Download as labels for Compare models".
- Validation additions: GFW loitering agreement (`n stations confirmed / n`), precision from reviews overall and by depth band (< 200, 200–1,000, ≥ 1,000 m).
- Tests: `test_review_roundtrip_csv`, `test_import_skips_unknown_ids_and_statuses`, `test_labels_csv_from_reviews`, `test_next_unreviewed_skips_confirmed_and_dismissed`.

### Task 24: Briefing page and GFW enrich
**Files:** Create `pages/briefing.py` (hidden page), `reference_data/watch_items.csv`, `reference_data/reference_events.csv`; Modify `gfw_fetch.py` (`--enrich`), `.github/workflows/gfw_weekly.yml` (one added step, continue-on-error).
- Briefing steps exactly as spec §11.6, from `intel` + `public_results("all", "6m")`; Back/Next with `?step=N`; progress dots; last step links to Explore and Findings.
- `gfw_fetch.py --enrich`: for each library MMSI: `/v3/vessels/search?query=<mmsi>&datasets[0]=public-global-vessel-identity:latest` → info row; `/v3/events?datasets[0]=public-global-port-visits-events:latest` (+ loitering, encounters) by GFW vessel id for the same months → events rows; writes the two CSVs (merge, no duplicates). Token handling and User-Agent as in the existing script.
- Tests: `test_briefing_steps_count` (≥ 6 steps; bad `?step=99` → last step), `test_enrich_parses_fixture` (recorded JSON fixtures in `tests/fixtures/gfw_*.json`, no network), `test_enrich_merge_no_duplicates`.
- Live check (needs the user's token, local only): `python gfw_fetch.py --enrich --months 12` writes non-empty files.
