# Survey Pattern Detector (v3)

Finds "lawnmower" seafloor-survey patterns in AIS vessel tracks: runs of long,
straight, parallel lines driven in alternating directions. For surveys still
underway at the last position, it projects where the next lines will fall. Each
survey is matched to nearby ports, and ports linked to rare-earth processing,
mining or rare-earth cargo are highlighted.

Ships that only *look* like they are surveying (ferries, patrols, coastal
shuttles going back and forth) are filtered out. A block of parallel lines
counts as a survey only if it:

- runs line after line, with no more than a few hours between one line and the next
  (the same leg repeated days apart is a repeat trip);
- keeps laying lines on new ground: a progressive lawnmower that advances steadily
  across the area with even spacing, or an interleaved / racetrack survey (3D
  seismic) whose lines fill the width of the area at towed-seismic speed;
- stays offshore: the lines lie at least 5 km from the coast and do not keep
  turning at the shoreline;
- runs at survey speed (2-12 kn) and has at least 4 lines.

Rejected blocks and the reasons are listed in `rejected_blocks.csv` (the
"Rejected patterns" tab in the web app). Survey areas of any ships that overlap
or lie within 25 km of each other form a **survey hotspot**; hotspots show on
the map with the number of ships, and whether ships were there at the same time.

- `survey_pattern_detector.py`: the detector (command line or imported)
- `port_intel.py`: nearby ports, rare-earth links, flag from MMSI, AIS ship types
- `reference_data/world_ports.csv`: about 3,800 ports from the NGA World Port Index (public domain)
- `reference_data/coastline_ne10m.npz`: the Natural Earth 1:10m coastline (public
  domain) as points every 2 km, for the distance-from-coast check
- `reference_data/landmask_ne10m.npz`: Natural Earth 1:10m land and minor islands
  (public domain) as a 1/40 degree land/sea grid. Routes to ports follow shipping
  lanes (searoute) and every stretch that would cross land is re-routed through
  the water around it; for nearby ports the shortest way around land is used when
  the lanes make a detour. Where no over-water route is found, the port keeps its
  straight-line distance but no line is drawn.
- `reference_data/ree_sites.csv`: rare-earth processing plants, magnet plants, mines,
  cargo ports and seabed-mineral areas. Curated, with approximate locations; add or
  correct rows freely.
- `app.py`: web app with a world map of every uploaded dataset
- `run_survey_workbook.py`: Excel workflow (`Survey_Detector.xlsx`)
- `Survey Detector.pyt`: ArcGIS Pro toolbox
- `library/`: the ship library the web app opens with: `vessels.csv` (catalog) and
  `tracks/` (one position file per ship)

## Web app: SeaTrace

The site is **SeaTrace**: the analyst console from SeaTrace (a JMU capstone prototype), embedded in
Streamlit and fed by this project's live pipeline. Its files are in `views/seatrace/`
(`console.html`, `engine.js`, `ui.js`: SeaTrace's code with small, commented changes; `addons.js`: the
Survey Detector features added in SeaTrace's style). `views/console.py` shows it full-window;
`webapp/seatrace_export.py` turns the pipeline's results into SeaTrace's data format.

| Part | What it does |
|---|---|
| **Header** | Live stats, **Briefing** (bottom line, the season on fast-forward, how the detector works, the key judgments), **Map / Gallery / Timeline**, **Validation**, **Method & data**; plus ship group and season selectors and the **Analyst** menu. |
| **Fleet** (left) | Every ship, by country, with search ("/"), filter chips and status; watchlist ships without data at the bottom. |
| **Alert queue** (left) | Detections ranked P1–P4 with reasons; each has a case status and note (kept in your browser). **Export / Import reviews** and **Download as labels** (for Compare models). |
| **Map** (centre) | Tracks, surveys, stations, AIS gaps, port calls, GFW loitering, EEZ boundaries, ISA contract areas (live), rare-earth sites, hotspots, plus port routes, predicted next lines and seabed resource regions; time bar with play and **SEASON ▸** replay. |
| **Assessment** (right) | The selected detection: priority with its eight factors, confidence, reasons, operation cycle, context, **ports & likely target**, GFW registry and events, documented events and watch items, case review, and **Copy link** (the address keeps the selection). |
| Analyst ▸ **Upload your own track** | Run both detectors on your files (or the sample) and **Open in SeaTrace**. |
| Analyst ▸ **Detection settings** | Model, thresholds, station thresholds, port matching: for your visit only. |
| Analyst ▸ **Compare models** | Benchmarks with labels, your uploads or the mining ships; precision / recall. |
| Analyst ▸ **Data & downloads** | Every table, Excel / ZIP / GeoJSON / HTML map, findings as CSV. |

**Two detectors.** The lawnmower survey detector (`survey_pattern_detector.py`, models in
`models/`) and the stationkeeping detector (`stationkeeping.py`: a ship holding one spot for
24 h or more, away from ports, over water deeper than 200 m). On real data it finds Chikyu's
2026 rare-earth mud test (17 Jan – 8 Feb) to within an hour of GFW's own loitering record.

**Priority.** `intel.py` scores each detection on eight factors (resource area, ship type,
EEZ / jurisdiction, depth, pattern of life, ships working together, AIS gaps, recency) into
P1–P4 and writes the reasons. It uses `reference_data/` files built by
`scripts/build_reference.py` (Marine Regions EEZs, ETOPO 2022 depth), the hand-checked
`vessel_classes.csv`, and the ISA contract areas read live (never stored).

**Ship library.** `library/vessels.csv` (catalog) plus `library/tracks/`; the weekly job also
writes `library/gfw_vessel_info.csv` and `library/gfw_events.csv` (`gfw_fetch.py --enrich`).
Watch items and documented events are hand-written in `reference_data/watch_items.csv` and
`reference_data/reference_events.csv`.

**Flag-state ports.** Each survey is also matched to the nearest ports of its
vessel's flag state (Chinese ships to Chinese ports, American ships to American
ports, and so on), including that country's nearest rare-earth linked port. The
flag comes from a flag column in the data, or else from the first three digits of
the MMSI. China includes Hong Kong and Macau; the United States, France, the
Netherlands and Norway include their territories. In the sidebar, **Port matching**
can instead match every vessel to one chosen country, or turn this off, and the
**Vessel flags** filter limits the map and tables to, say, Chinese vessels only.
A ship registered under a flag of convenience (Panama, Liberia...) is matched to
that flag; AIS does not carry ownership.

**Files without an MMSI or flag** (such as MarineTraffic's per-vessel position
export: Timestamp, Source, Speed, Course, Latitude, Longitude, Heading) cannot say
which ship they are. Either:

- put the MMSI in the file name, e.g. `413123456_MarineTraffic_Vessel_positions_Export.csv`
  (the detector reads a 9-digit MMSI, or `IMO1234567`, from the name of a
  single-vessel file); or
- in the web app, open **Identify vessels with an unknown flag**, enter the MMSI
  from the vessel's MarineTraffic page (or pick its flag), and press
  **Apply and re-run**.

A port is **rare-earth linked** when it is a known rare-earth cargo port, or lies
within 300 km of a rare-earth processing or magnet plant or a mine. Port distances
follow shipping lanes (searoute package). Where that network has no sensible
route (it breaks around the 180° line, e.g. in the Bering Strait), the
straight-line distance is used and labelled as such.

### Put it online (Streamlit Community Cloud, free)

1. Create a GitHub repository (Private is fine).
2. Upload only these:
   - `app.py`
   - `survey_pattern_detector.py`
   - `port_intel.py`
   - `requirements.txt`
   - `README.md`
   - the `reference_data` folder
   - the `library` folder

   Leave out `Survey_Detector.xlsx`, `input_files/` and `survey_results/`: they
   hold your own data.
3. At <https://share.streamlit.io> click **Create app**, choose the repository,
   branch `main`, main file `app.py`, and **Deploy**.
4. Under the app's **Settings → Sharing**, choose who can open it.

To replace an existing app, upload these files into its repository instead (the
old app has no `port_intel.py` or `reference_data`, so add those too). The app
redeploys by itself.

### Run it on your own computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Pulling Chinese survey-vessel tracks (Global Fishing Watch)

```bash
python gfw_fetch.py              # last 12 months, every Chinese "survey"-class vessel
python gfw_fetch.py --months 3   # or --start 2025-01-01 --end 2025-06-30
```

Uses the Global Fishing Watch API (free, non-commercial use only; token in
`gfw_token.txt`, never uploaded). It writes one hourly track per vessel to
`library/tracks/gfw_<MMSI>.csv`, links existing library ships and adds new ones to
`library/vessels.csv`. Re-run it to extend the tracks; new months are merged in.
Tracks are hourly positions on a ~1 km grid, from satellite and coastal AIS
worldwide, so survey lines closer than ~1-2 km apart blur together. GFW's
"survey" class also includes some coast guard and oil-industry vessels.
Data: Powered by Global Fishing Watch (https://globalfishingwatch.org), CC BY-NC 4.0.

## Models: try your own detector

Each file in `models/` is one detection model. The app's sidebar has a **Model**
dropdown to switch between them, and the **Compare models** tab runs
several on the same data side by side. When it knows which vessels really are
surveying, it also scores each model: precision (how many flagged vessels were
real surveys) and recall (how many real surveys were found): upload a CSV with
columns `vessel, is_survey`. `benchmarks/` holds a synthetic test set with its
labels for quick checks from the command line (see below).

- `models/baseline.py`: the original detector, unchanged. Everything is compared to it.
- `models/example_strict.py`: the baseline with stricter rules, a minimal example.
- `models/sweep.py`: a second, different detector built for hourly Global Fishing
  Watch tracks (see **The Sweep model** below).
- `models/_template.py`: copy this to start yours. It has three options: change
  the settings (A), write your own pattern recogniser and keep the rest of the
  pipeline (B), or build a completely different approach (C).

**Adding your model**

1. Make a branch: `git checkout -b <yourname>-model`
2. Copy `models/_template.py` to `models/<yourname>.py` and fill it in.
3. Test it: `streamlit run app.py`, or
   `python survey_pattern_detector.py benchmarks/synthetic_10_ships.csv --model <yourname>`
4. Commit only your own file, push your branch and open a pull request.

Everyone edits only their own file in `models/`, so merges don't conflict. A
model that crashes on import shows a warning in the sidebar instead of breaking
the app.

### The Sweep model (`models/sweep.py`)

The baseline finds long straight lines first and then chains neighbours. On
hourly, ~1 km-snapped GFW tracks a survey line can be just two or three fixes,
and patrols that go back and forth over one spot also chain into "blocks".
Sweep works the other way round:

1. **Heading signature.** Over a sliding 24 h window it measures whether the
   ship moves along one axis (axial strength) but not net one way (directional
   strength). High axial + low directional = back and forth = candidate survey.
2. **Legs.** Each run of fixes heading the same way along the axis is a leg; no
   straightness test, so curved lines count and a leg may be one hourly step.
3. **Coverage regularity.** Legs only form a block if they lie side by side,
   evenly spaced (at least 1 km, GFW's grid), overlap, never cross, keep their
   gap from end to end (no V shapes or fans), number 5+ and last 12 h+.

Note: the baseline has since gained its own patrol / ferry filter (rejected_blocks.csv),
which closes much of this gap; on the 94-ship library of Nov 2026 the baseline flags 31
ships and Sweep 36. Sweep keeps that filter except its spacing test (it runs its own).

On the 62 library ships (Oct 2026), compared with the baseline:

| | Baseline | Sweep |
|---|---|---|
| Survey blocks found | 626 | 218 |
| Coast guard ships flagged (6 in library) | 6, 124 blocks | 6, 30 blocks |
| Research / survey ships flagged (46) | 42 | 17 |
| Synthetic benchmark (4 surveyors, 6 others) | 4 / 4, no false alarms | 4 / 4, no false alarms |
| Arctic MarineTraffic export (dense, 1 fix/min) | 8 blocks | 3 blocks |

Sweep is much stricter: it drops most patrol zig-zags and short noise, and
keeps the long systematic surveys (e.g. Xiang Yang Hong 01, 412360000), but on
dense exports like the Arctic file the baseline finds more of the real lines.
Neither model can see surveys run by an AUV or towed sled while the ship
barely moves. With no labelled real data yet, these are counts, not accuracy:
labelling a few dozen real blocks is the next step to say which is better.

### Demo datasets: where the two models differ

`benchmarks/` has three small synthetic datasets (fake ships, MMSI 999xxxxxx),
each with a labels file, built by `benchmarks/make_demo_datasets.py`. In
**Analyst ▸ Validation** pick a benchmark (its labels load automatically) and press
**Run comparison**. `benchmarks/demo_comparison.png`
shows both models on the key ships.

| Dataset | Ship | Truth | Line-Chain (baseline) | Sweep |
|---|---|---|---|---|
| 1 hourly patrols | Deep Mapper: 12-line survey | survey | found | found |
| | Patrol One: criss-cross patrol | not | correct (patrol filter) | correct |
| | Patrol Two: zig-zag patrol | not | correct (patrol filter) | correct |
| 2 dense, short | Site Surveyor: 4 lines, 5 hours | survey | found | **missed** |
| | Nodule Surveyor: 9 lines, 1.5 days | survey | found | found |
| | Cargo Runner: transit | not | correct | correct |
| 3 curved, gaps | Seamount Mapper: 9 curved lines, 15% of reports missing | survey | **missed** | found |
| | Shuttle: same line back and forth | not | correct | correct |
| | Station Keeper: near-stationary work | not a lawnmower | correct | correct |

## What is the ship likely surveying for?

Each survey area gets a **likely target** from where it lies and who the ship
is (`resource_context.py`, data in `reference_data/seabed_resources.csv`):
polymetallic nodules (CCZ, Peru Basin, Cook Islands, Central Indian Ocean),
rare-earth mud (Minamitorishima), cobalt crusts (Prime Crust Zone, Rio Grande
Rise), seafloor sulphides (mid-ocean ridges, Okinawa Trough, Manus Basin),
phosphorite, placers (diamonds, tin, iron sand), gas hydrates, oil and gas
basins, and scientific / shelf-claim mapping (Central Arctic, Southern Ocean).
Coast guard ships are labelled as patrols, and oil and gas ships as oil and
gas. The vessel panel shows it under each survey area, the Survey areas table
has the columns, and the map's layer menu has **What surveys here look for**.
The regions are rough boxes for indication only; edit the CSV to refine them.
Sources: ISA exploration areas; Hein et al. 2013, Ore Geology Reviews 51;
Kato et al. 2011, Nature Geoscience (REE mud); national seabed-mining reviews.

## Your own copy on GitHub, and merging later

A separate repository under your own account changes nothing in the team's:

1. On GitHub: **New repository**, e.g. `vesseltracker-quinn`, with no README
   (it must start empty).
2. Push this folder's branch to it as its `main`:
   `git remote add mine https://github.com/<you>/vesseltracker-quinn.git` then
   `git push mine quinn-models:main`.
3. At <https://share.streamlit.io> **Create app** from that repository, main file
   `app.py`: your own link, with every model in the dropdown.
4. Later, to merge: the branch already contains the team's history, so it can
   be merged into the team repository (or opened as a pull request) whenever
   the team agrees. To pick up the team's newer work meanwhile:
   `git fetch origin && git merge origin/main`.

Uploading files through the GitHub website works too, but it replaces whole
files; git merges line by line, so two people's edits to `app.py` combine.

**Keys.** Never commit `gfw_token.txt` (it is in `.gitignore`). On Streamlit
Cloud put secrets under the app's **Settings -> Secrets**, not in the repo.
Global Fishing Watch data is CC BY-NC (non-commercial): a commercial product
needs GFW's permission or another data source.

**Plugging in live data.** The app reads the ship library fresh on every run,
so any updater (GFW, a live AIS feed, a simulator) only needs to write
position files into `library/tracks/` and rows into `library/vessels.csv`
(`track_file` = the file name), as `gfw_fetch.py` does. Models never read files
themselves, so every model works on new data unchanged.

## Command line

```bash
python survey_pattern_detector.py fleet_a.csv fleet_b.csv --out results
```

Each file or folder given is a separate dataset. Results go to `results/`:
`vessels.csv`, `nearby_ports.csv`, `survey_hotspots.csv`, `survey_areas.csv`,
`survey_blocks.csv`, `rejected_blocks.csv`, `survey_lines.csv`, `predictions.csv`,
`positions_processed.csv`,
`survey_results.geojson` (plus one GeoJSON per layer in `arcgis/`) and `maps/`.
Every setting in `Config` is also a command-line flag, e.g. `--min-lines-per-block 4`.
`--port-country China` matches every vessel to Chinese ports (`flag`, the default,
uses each vessel's own flag; `none` turns it off). In the Excel workbook, add a
`port_country` row to the Settings sheet.
