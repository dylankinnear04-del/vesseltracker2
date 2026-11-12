# Supply-chain linking — design

Date: 2026-11-12 · Status: approved in conversation, awaiting written-spec review

## Purpose

The project is a proof of concept for NGA, who asked for the supply-chain angle: for a detected survey, show
the whole chain from the ship to the minerals it is prospecting, and flag where a US-restricted or state-linked
entity sits in that chain. Success: an analyst opening a detection can read, in one place and with sources,

> ship → owner → parent / ultimate owner (state-owned?) → US restricted-list status
> area → ISA contractor & sponsoring state → minerals → US import reliance → where those minerals are processed

and can see, across all detections, which parent companies and states are behind the most surveys.

What the user said: full chain; per-detection card plus an Entities view; approach A (automatic list
matching plus a hand-checked links file). Data licensing is settled; this is a proof of concept.

Assumptions (correct if wrong): name matching is advisory — the analyst decides; no change to detection
priority scores in this step.

## Data

### `library/screening_list.csv.gz` (new, refreshed weekly)
A slim copy of the US government's Consolidated Screening List
(`https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv`, ~26k rows, 17 MB).
Kept: rows whose `type` is an entity or vessel (individuals dropped). Columns kept: `name, alt_names, source,
programs, start_date, source_list_url, source_information_url, type, call_sign, vessel_flag, ids`.
Written by `gfw_fetch.py --screening` (new flag; no GFW token needed) in the weekly workflow. On download
failure the previous file is kept and the run shows a warning, as for GFW outages.

### `reference_data/entity_links.csv` (new, hand-kept by the team)
Columns: `match_name, parent, ultimate_owner, state_owned, country, confirmed_lists, note, source`.
- `match_name`: an owner name as it appears in the GFW registry or the catalog's `operator` (matched after
  normalisation, see below).
- `parent` / `ultimate_owner`: company names; `state_owned`: `yes`/`no`/blank; `country`: ISO3.
- `confirmed_lists`: `;`-separated screening-list sources the team has verified for this entity or its parent
  (e.g. `CMIC;Entity List`), which makes the result **Confirmed**.
- Also holds DoD Section 1260H "Chinese military companies" entries (not in the screening list) as
  `confirmed_lists = DoD 1260H`.
Seeded with links documented from public sources for owners in our data (e.g. China Oilfield Services →
CNOOC, state-owned, CMIC + Entity List), each with a `source` URL. Malformed rows are skipped and reported.

### `reference_data/mineral_import_reliance.csv` (new)
Columns: `mineral, net_import_reliance_pct, top_sources, us_critical_mineral, year, source`.
Rows for the minerals our resource regions and ISA contract types name: nickel, cobalt, copper, manganese,
rare earths, zinc, gold/silver (sulphides), tellurium, platinum (crusts). From USGS Mineral Commodity Summaries.

Existing data used: GFW registry owners (`library/gfw_vessel_info.csv`, 54 of 92 ships have one), catalog
`operator`, `ISA_CONTRACTORS` (contract → contractor, sponsor), `isa_contracts.mineral_of`,
`reference_data/seabed_resources.csv` (region → commodities), `reference_data/ree_sites.csv` (processing).

## Matching — new module `supply_chain.py`

Pure functions, no Streamlit, no network.

- `normalise(name)`: upper-case, strip punctuation and legal suffixes (JSC, AO, CO, LTD, LIMITED, CORP,
  CORPORATION, INC, LLC, GROUP, CO LTD…), collapse spaces. Registry names are truncated (≈30 chars), so a
  registry name also matches a list name that *starts with* it.
- `screen(name, lst)` → list of hits `{list, program, entry, score, level, url, date}` where `level` is
  - `likely`: normalised exact match, or prefix match of a truncated registry name, against `name` or any
    `alt_names`;
  - `possible`: similarity ≥ 0.88 (difflib ratio on normalised names), not exact;
  - promoted to `confirmed` when the entity's `confirmed_lists` in `entity_links.csv` names that list.
- `ship_chain(ship, owner_row, links, lst)` → `{ship_hits, owner, owner_source, parent, ultimate_owner,
  state_owned, country, hits, notes}`. Ship hits come from the list's vessel rows by IMO in `ids` or exact
  normalised name. Owner: GFW registry owner, else catalog `operator`, else none ("Owner unknown").
  Owner, parent and ultimate owner are each screened; hits record which of the three matched.
- `area_chain(event, zones_by_id, resources, reliance, ree_sites)` → `{contract, contractor, sponsor,
  region, minerals: [{name, reliance_pct, top_sources, critical}], processing: [{site, operator, country}]}`.
  Contract: the event's ISA zone, else its nearest zone if within 300 km (as the engine does), else the
  resource region containing the event. Processing: `ree_sites` rows handling any of the minerals.
- `entities(chains, events)` → one row per parent (or owner when no parent; or state when state-owned with
  no parent): ships, detections, high-priority detections, list levels, minerals surveyed.

## Where it runs

`webapp/seatrace_export.py` adds `extras.supply = {ships: {vesselId: ship_chain}, areas: {eventId:
area_chain}, entities: [...], listDate}` while the console data is built (so it is in `prebuilt/` and costs
visitors nothing). `data.stamp_inputs()` gains `supply_chain.py`, `library/screening_list.csv.gz` and the two
new reference files, so a list or links update rebuilds the console data. `library/screening_list.csv.gz`
is added to the Build console data workflow's paths.

## Console

`views/seatrace/addons.js`, in SeaTrace's style:
- **Supply chain card** in each detection's intel panel (beside Ports & target): the chain top to bottom,
  each link with its source; Confirmed red, Likely amber, Possible grey "verify"; "No restricted-list match
  for owner or parents" when clean; missing pieces said plainly ("Owner unknown: no owner in GFW registry").
  Each hit links to the list's source page and shows the list date.
- **Entities tab** beside Fleet and Alert queue: rows per entity (ships, detections, high-priority, list
  flags, minerals), sorted by list level then detections; click a row to show its ships; click a ship to
  focus it on the map; "Download CSV".

## Errors

List download fails → previous list kept, warning in the run, card shows the list's date. No list file at
all → screening section reads "Screening list not loaded". No ISA contract or region → area half says so.
Malformed `entity_links.csv` rows skipped and logged at build time.

## Testing

- `normalise` and `screen` on real names: YUZHMORGEOLOGIYA JSC → SDN (likely); China Oilfield Services →
  parent CNOOC → CMIC + Entity List (confirmed via links file); a truncated registry name prefix-matches;
  a near-miss is `possible`; an unrelated name has no hit. Uses a small fixture extract of the list.
- `ship_chain`: owner from registry, from catalog, and unknown. `area_chain`: in a contract, near one,
  region only, none. `entities` counts and sort order.
- Export: `extras.supply` present for every vessel and event in a real build; strict JSON.
- Console smoke (tests/js): card renders for an event, Entities tab opens and focuses a ship, no JS errors.
- Fingerprint includes the new files.

## Out of scope

Network graph; live re-screening in the browser; changing detection priority from list hits (later, separate
step, since it changes scores); individuals on the list.
