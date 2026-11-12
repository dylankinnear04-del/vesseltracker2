# Supply-chain linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every detection, show ship → owner → parent/state → US restricted-list status and area → ISA contractor/sponsor → minerals → US import reliance → processing, plus an Entities tab across detections.

**Architecture:** A pure module `supply_chain.py` does matching from three data files (a weekly slim copy of the US Consolidated Screening List, a hand-kept `entity_links.csv`, a USGS `mineral_import_reliance.csv`). `webapp/seatrace_export.py` puts the result in `extras.supply` while the console data is built ahead of time; `views/seatrace/addons.js` renders a card and a tab.

**Tech Stack:** Python 3.12, pandas, difflib (stdlib); vanilla JS in SeaTrace's addons.js; pytest; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-12-supply-chain-design.md`

## Global Constraints

- Screening list source: `https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv`; keep only entity and vessel rows (drop individuals).
- Kept list columns: `name, alt_names, source, programs, start_date, source_list_url, source_information_url, type, call_sign, vessel_flag, ids`.
- `entity_links.csv` columns: `match_name, parent, ultimate_owner, state_owned, country, confirmed_lists, note, source`.
- `mineral_import_reliance.csv` columns: `mineral, net_import_reliance_pct, top_sources, us_critical_mineral, year, source`.
- Levels: `confirmed` (team-verified in entity_links), `likely` (normalised exact / alt-name / truncated-prefix match), `possible` (difflib ratio ≥ 0.88, not exact). Matching is advisory; detection priority scores do not change.
- Near-contract distance: 300 km (same as the engine).
- Card colours: Confirmed red, Likely amber, Possible grey with "verify".
- Never write ISA polygons to disk (existing rule); network only in `gfw_fetch.py --screening`, never at page load.
- Run tests with the scratchpad venv: `$PY -m pytest` where `PY=/private/tmp/claude-501/-Users-dylankinnear-Desktop-Survey-Detector/cd9f4a68-4a94-4186-a867-8e42804c399e/scratchpad/venv/bin/python` (recreate from requirements.txt + pytest if missing).
- Publish with `git pull --rebase && git push` on `main`.

## Review Focus

- Owner names that normalise to empty or very short strings (e.g. "MD II", "CO LTD") must not match anything: require ≥ 4 characters after normalisation for any match, and ≥ 8 for a prefix match. → test in Task 2.
- Registry owners that are plain government bodies ("UNITED STATES GOVT NAVY") must produce no hit and no parent row. → test in Task 2.
- A ship whose owner is blank in the registry but present in the catalog `operator` must use the operator. → test in Task 3.
- An event with no zone, no near zone and outside every resource region must still produce an area chain with `contract: None` and an explicit note. → test in Task 3.
- Screening list file missing (first deploy before the weekly job) must not break the build: `extras.supply.listDate` is `None` and hits are empty. → test in Task 4.

---

### Task 1: Data files and the weekly screening-list refresh

**Files:**
- Create: `reference_data/entity_links.csv`, `reference_data/mineral_import_reliance.csv`, `library/screening_list.csv.gz`
- Modify: `gfw_fetch.py` (new `--screening` flag), `.github/workflows/gfw_weekly.yml`, `.github/workflows/build_console_data.yml` (paths)
- Test: `tests/test_screening_fetch.py`

**Interfaces:**
- Produces: `gfw_fetch.SCREENING_URL: str`, `gfw_fetch.SCREENING_FILE = LIBRARY / "screening_list.csv.gz"`, `gfw_fetch.slim_screening(df: pd.DataFrame) -> pd.DataFrame` (rows with `type` in {"Entity", "Vessel"} — check the real values with `value_counts()` and keep the entity/vessel ones — and the kept columns only), `gfw_fetch.fetch_screening() -> bool` (download, slim, write gzip with `mtime=0`; on any network/parse error print `::warning::...`, keep the old file, return False).

- [ ] **Step 1: Write failing tests** — `test_slim_drops_individuals_and_columns` (a 3-row frame: one Entity, one Vessel, one Individual, plus an extra column → 2 rows, exactly the kept columns); `test_fetch_screening_keeps_old_file_on_failure` (monkeypatch `urllib.request.urlopen` to raise `URLError`, existing file bytes unchanged, returns False); `test_main_screening_flag_needs_no_token` (monkeypatch `fetch_screening` to record a call and `token` to raise; `sys.argv=["gfw_fetch.py","--screening"]`; `main()` calls it and does not call `token`).
- [ ] **Step 2: Run** `$PY -m pytest tests/test_screening_fetch.py -v` — expect FAIL (attributes missing).
- [ ] **Step 3: Implement** the interfaces above in `gfw_fetch.py`; in `main()`, `--screening` runs before `token()` and returns.
- [ ] **Step 4: Run** the tests — expect PASS. Then run `$PY gfw_fetch.py --screening` once for real and check `library/screening_list.csv.gz` exists, ~1–3 MB, and contains `YUZHMORGEOLOGIYA` and `China National Offshore Oil Corporation`.
- [ ] **Step 5: Write `reference_data/mineral_import_reliance.csv`** with rows for nickel, cobalt, copper, manganese, rare earths, zinc, gold, silver, tellurium, platinum. Take `net_import_reliance_pct` and `top_sources` from the latest USGS Mineral Commodity Summaries (summary table "U.S. net import reliance"), `year` = that edition's year, `source` = the USGS URL; `us_critical_mineral` yes/no from the 2022 USGS critical minerals list (copper: check the 2025 final list). Do not estimate: leave a cell blank if USGS gives "W" or nothing.
- [ ] **Step 6: Write `reference_data/entity_links.csv`** seeded for owners in `library/gfw_vessel_info.csv` that have documentable parents, each row with a `source` URL: CHINA OILFIELD SERVICES → China National Offshore Oil Corporation (state_owned yes, CHN, confirmed_lists `CMIC;Entity List` after checking both appear for CNOOC in the slim list); YUZHMORGEOLOGIYA JSC → JSC Rosgeologia (yes, RUS, `SDN`); SINOPEC OFFSHORE OILFIELD SERV → China Petrochemical Corporation (yes, CHN); GUANGZHOU MARINE GEOLOGICAL and CHINA GOVT GUANGZHOU MARINE → China Geological Survey, Ministry of Natural Resources (yes, CHN); CHINA GOVT NORTH SEA → Ministry of Natural Resources (yes, CHN); OCEANOLOGY ACADEMIC SCIENCES → Chinese Academy of Sciences (yes, CHN); OCEAN UNIVERSITY OF CHINA → Ministry of Education (yes, CHN); CHINA GOVT POLAR RESEARCH → Ministry of Natural Resources (yes, CHN). Add DoD 1260H rows only for parents above that appear on the current 1260H list (`confirmed_lists` gains `DoD 1260H`, `source` = the DoD notice URL). Only list what the source states.
- [ ] **Step 7: Workflows** — in `gfw_weekly.yml` add a step `Screening list (US Consolidated Screening List)` with `id: screening`, `continue-on-error: true`, `run: python gfw_fetch.py --screening`, placed before the console build; `git add library/screening_list.csv.gz`; include `steps.screening.outcome` in the failure report. In `build_console_data.yml` paths add `supply_chain.py` (already covered by `*.py`) — nothing else needed since `library/**` and `reference_data/**` are covered; confirm.
- [ ] **Step 8: Commit** — `git add` the files above; `git commit -m "Screening list refresh and supply-chain reference data"`.

### Task 2: Name matching (`normalise`, `screen`)

**Files:**
- Create: `supply_chain.py`, `tests/fixtures/screening_sample.csv` (≈15 real rows extracted from the slim list: both YUZHMORGEOLOGIYA rows, the three CNOOC rows, JSC ROSGEOLOGIA, two CHINA STATE SHIPBUILDING rows, one vessel row with an IMO in `ids`, and 5 unrelated rows)
- Test: `tests/test_supply_chain.py`

**Interfaces:**
- Produces: `supply_chain.load_list(path: Path) -> pd.DataFrame` (empty frame with the kept columns if missing; adds a `norm` column and a `norm_alts: list[str]` column); `supply_chain.normalise(name: str) -> str`; `supply_chain.screen(name: str, lst: pd.DataFrame, confirmed: set[str] = frozenset()) -> list[dict]` where each hit is `{"list": short_list_name, "source": full source, "program": str, "entry": str, "score": float, "level": "confirmed"|"likely"|"possible", "url": str, "date": str}`; `short_list_name` maps the source to `SDN`, `Entity List`, `CMIC`, `MEU`, `SSI`, `UVL`, `DPL`, `ITAR Debarred`, `Nonproliferation`, else the source text. A hit is `confirmed` when its short list name is in `confirmed`.

- [ ] **Step 1: Write failing tests** —
  `normalise("Yuzhmorgeologiya JSC") == normalise("YUZHMORGEOLOGIYA AO") == "YUZHMORGEOLOGIYA"`;
  `normalise("CNOOC Limited") == "CNOOC"`; `normalise("Co., Ltd.") == ""`;
  `{h["list"] for h in screen("YUZHMORGEOLOGIYA JSC", lst)} == {"SDN"}` and all levels `likely`;
  `screen("China National Offshore Oil Corporation", lst, {"CMIC"})` has a `confirmed` CMIC hit;
  truncated prefix: `screen("CHINA NATIONAL OFFSHORE OIL CO", lst)` is `likely`;
  near-miss: `screen("Yuzhmorgeologia", lst)` gives `possible` with `0.88 <= score < 1`;
  `screen("UNITED STATES GOVT NAVY", lst) == []`; `screen("MD II", lst) == []` (Review Focus: <4 chars);
  `screen("anything", load_list(tmp_path / "missing.csv.gz")) == []`.
- [ ] **Step 2: Run** `$PY -m pytest tests/test_supply_chain.py -v` — FAIL (module missing).
- [ ] **Step 3: Implement** in `supply_chain.py`. Suffixes to strip (whole words, after removing punctuation): `JSC, AO, OAO, ZAO, PJSC, CO, COMPANY, LTD, LIMITED, CORP, CORPORATION, INC, LLC, PLC, GROUP, HOLDINGS, SA, AG, GMBH`. Match order per list row: exact normalised name or any alt → `likely` (score 1.0); query ≥ 8 chars and a list name/alt starts with it → `likely` (score 0.95); else best difflib ratio over name+alts ≥ 0.88 → `possible`. Skip queries < 4 chars after normalisation. Precompute `norm`/`norm_alts` once in `load_list`; for the ratio pass, prefilter rows sharing the first 3 characters of any word to keep it fast on ~6k rows.
- [ ] **Step 4: Run** the tests — PASS.
- [ ] **Step 5: Commit** — `git commit -m "supply_chain: name normalisation and screening"`.

### Task 3: Chains and entities

**Files:**
- Modify: `supply_chain.py`
- Test: `tests/test_supply_chain.py`

**Interfaces:**
- Consumes: `screen`, `normalise`, `load_list` (Task 2); `isa_contracts.ISA_CONTRACTORS: dict[str, tuple[str, str]]`, `isa_contracts.mineral_of(cid) -> "nodules"|"sulphides"|"crusts"`; `resource_context.regions_at(lat, lon) -> pd.DataFrame` (columns include `name, commodities`).
- Produces:
  - `load_links(path) -> pd.DataFrame` (adds `norm`; drops rows missing `match_name` with a printed warning).
  - `ship_chain(ship: dict, registry_owner: str, links: pd.DataFrame, lst: pd.DataFrame) -> dict` — `ship` has `name, imo, flag, operator`; returns `{"ship_hits": [...], "owner": str|None, "owner_source": "GFW registry"|"catalog"|None, "parent": str|None, "ultimate_owner": str|None, "state_owned": bool|None, "country": str|None, "hits": [{**hit, "matched": "owner"|"parent"|"ultimate_owner"}], "notes": [str], "link_source": str|None}`.
  - `MINERALS = {"nodules": ["nickel","cobalt","copper","manganese"], "sulphides": ["copper","zinc","gold","silver"], "crusts": ["cobalt","manganese","nickel","tellurium","platinum","rare earths"]}`; commodity text from `seabed_resources.csv` maps via `{"Ni":"nickel","Co":"cobalt","Cu":"copper","Mn":"manganese","REE":"rare earths","Zn":"zinc","Au":"gold","Ag":"silver","Te":"tellurium","Pt":"platinum"}`.
  - `area_chain(event: dict, reliance: pd.DataFrame, ree_sites: pd.DataFrame) -> dict` — `event` has `zone, nearZone, nearZoneKm, center`; returns `{"contract", "contractor", "sponsor", "basis": "inside"|"near"|"region"|None, "region", "minerals": [{"name","reliance_pct","top_sources","critical"}], "processing": [{"site","operator","country"}], "notes": [str]}`.
  - `entities(ships: dict[str, dict], events: list[dict]) -> list[dict]` — row `{"name", "kind": "parent"|"owner"|"state", "country", "state_owned", "levels": [..], "lists": [..], "ships": [vesselId], "detections": int, "high": int, "minerals": [..]}`; `events` items have `vessel, priority` ("high" counts `priority == "HIGH"` — check the blob's actual tier field name in `build_blob` and use it), plus the area minerals. Sort: best level (confirmed > likely > possible > none), then detections desc, then name.

- [ ] **Step 1: Write failing tests** —
  ship with registry owner "CHINA OILFIELD SERVICES" and the seeded links → `parent == "China National Offshore Oil Corporation"`, `state_owned is True`, a `confirmed` CMIC hit with `matched == "parent"`;
  registry owner blank, `operator="Yuzhmorgeologiya JSC"` → `owner_source == "catalog"` and an SDN hit (Review Focus);
  no owner anywhere → `owner is None` and `"Owner unknown"` in a note;
  `area_chain({"zone":"COMRA-PMN", ...})` (use a real `ISA_CONTRACTORS` key) → `basis == "inside"`, sponsor filled, minerals = nodules list with reliance from the CSV;
  `nearZone` at 120 km → `basis == "near"`; at 450 km and in the CCZ box → `basis == "region"` with CCZ commodities;
  outside everything → `contract is None`, `basis is None`, a note (Review Focus);
  `entities` on two ships sharing a parent → one row with both ships, counts summed, confirmed row sorted first.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the interfaces. Processing sites: `ree_sites` rows of type processing whose notes or operator relate to the minerals — keep it simple: include all `processing` rows when "rare earths" is among the minerals, none otherwise.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "supply_chain: ship and area chains, entities"`.

### Task 4: Into the console data

**Files:**
- Modify: `webapp/seatrace_export.py` (`add_extras` / `survey_detector_extras`), `webapp/data.py` (`stamp_inputs`)
- Test: `tests/test_seatrace_export.py`, `tests/test_prebuilt.py`

**Interfaces:**
- Consumes: Task 3 functions; `data.GFW_INFO` registry owners by MMSI; catalog `operator`.
- Produces: `blob["extras"]["supply"] = {"ships": {vesselId: ship_chain}, "areas": {eventId: area_chain}, "entities": [...], "listDate": "YYYY-MM-DD"|None}`; `listDate` = the latest `start_date` in the list (taken from the data, not the file's modified time, so rebuilds stay byte-identical). Lists/links/reliance loaded once per build.

- [ ] **Step 1: Write failing tests** — in `test_seatrace_export.py`: `test_extras_supply` (every blob vessel id is in `supply["ships"]`, every event id in `supply["areas"]`, `entities` non-empty, `to_json` strict); `test_supply_without_list_file` (monkeypatch `supply_chain` list path to a missing file → `listDate is None`, all `hits == []`, build succeeds — Review Focus). In `test_prebuilt.py`: `{"supply_chain.py", "screening_list.csv.gz", "entity_links.csv", "mineral_import_reliance.csv"} <= names`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** — add `"supply_chain.py"` and `"library/screening_list.csv.gz"` to `data._STAMP_CODE` (reference_data files are already included by the rglob — confirm); build `extras.supply` in `add_extras` when `vid is not None`.
- [ ] **Step 4: Run** `$PY -m pytest tests/test_seatrace_export.py tests/test_prebuilt.py -v` — PASS.
- [ ] **Step 5: Commit** — `git commit -m "Console data carries the supply chain"`.

### Task 5: Card and Entities tab

**Files:**
- Modify: `views/seatrace/addons.js`, `tests/js/build_smoke.py` (driver also clicks `tab-entities` and an entity row)
- Test: `tests/test_pages.py`, smoke pages in a browser

**Interfaces:**
- Consumes: `window.SEATRACE` (`E, D, store, renderIntel, focusVessel, toast, esc`), `E.EXTRAS.supply`.
- Produces: DOM — intel section `.sec.stx-supply` titled "Supply chain"; tab button `#tab-entities` ("Entities" with count `#ct-entities`) inserted after `#tab-alerts`; panel `#entities` sharing the fleet/alerts panel area; a "Download CSV" button `#ent-csv`.

- [ ] **Step 1: Write the failing page test** — `test_console_has_supply_chain_code`: the console HTML contains `stx-supply` and `tab-entities` (they live in addons.js, so this fails until written).
- [ ] **Step 2: Implement** in addons.js, following the existing `decorateIntel`/MutationObserver pattern: the card (ship → owner [source] → parent → ultimate owner, state-owned badge; hits as coloured chips `Confirmed`/`Likely`/`Possible · verify`, each linking `url` and showing `date`; "No restricted-list match for owner or parents"; notes as plain lines; then contract/contractor/sponsor or region, minerals with "US import reliance N% (USGS YEAR)" and critical badge, processing sites; footer "Screening list as of LISTDATE"). Tab switching mirrors Fleet/Alert queue (`aria-selected`, hide the others); rows show name, country, state-owned, list chips, ships, detections, high; click toggles the row's ship list; ship click calls `focusVessel`; CSV columns `name,kind,country,state_owned,lists,levels,ships,detections,high,minerals`. Everything through `esc()`. Colours from SeaTrace's existing CSS variables for alert/warn/muted.
- [ ] **Step 3: Run** `$PY -m pytest tests/test_pages.py -v` — PASS.
- [ ] **Step 4: Smoke** — `$PY tests/js/build_smoke.py $SCRATCH/smoke`, open each page in the browser pane, read `document.title` JSON: `ok: true`, no errors; screenshot one detection's card and the Entities tab for the report.
- [ ] **Step 5: Commit** — `git commit -m "SeaTrace: supply-chain card and Entities tab"`.

### Task 6: Ship it

- [ ] **Step 1:** `$PY -m pytest -q -p no:warnings tests` — all pass.
- [ ] **Step 2:** `git pull --rebase && git push`; the Build console data workflow rebuilds `prebuilt/` using the list file committed in Task 1. Watch the run to `completed success`.
- [ ] **Step 3:** Open the live site, open a Chinese detection (e.g. a Hai Yang Shi You ship) and confirm the card shows CNOOC Confirmed; open the Entities tab; page load still ~5 s.
- [ ] **Step 4:** Update the README "Web app: SeaTrace" section with a short "Supply chain" paragraph (data files, levels, how to add a link row) and push.
