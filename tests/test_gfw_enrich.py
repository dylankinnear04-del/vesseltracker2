"""gfw_fetch --enrich: registry info and events, parsed from recorded GFW responses (no network)."""
import json
from pathlib import Path

import pandas as pd

import gfw_fetch

FIX = Path(__file__).resolve().parent / "fixtures"
SEARCH = json.loads((FIX / "gfw_search_432522000.json").read_text())
EVENTS = json.loads((FIX / "gfw_events_432522000.json").read_text())


def test_enrich_parses_identity():
    info, ids = gfw_fetch.parse_identity("432522000", SEARCH)
    assert set(ids) == {"10c55eed1-1a70-5c79-04eb-09ad1746ba5c", "1a0cd619d-dd9f-3f08-f734-9e13bc1c36e6"}
    assert info["mmsi"] == "432522000" and info["vessel_type"] == "OTHER_NON_FISHING"
    assert round(info["length_m"]) == 162 and info["gross_tonnage"] == 56752
    assert info["owner"] == "JAMSTEC"               # from the second GFW identity record


def test_enrich_parses_events():
    ev = gfw_fetch.parse_events("432522000", EVENTS)
    assert len(ev) == 19 and set(ev["kind"]) == {"loitering", "port_visit"}
    lo = ev[ev["kind"] == "loitering"].iloc[0]
    assert abs(lo["hours"] - 497.94) < 0.1 and abs(lo["lat"] - 37.9178) < 1e-4
    pv = ev[ev["kind"] == "port_visit"]
    assert (pv["port"] != "").all() and {"Sendai", "Shimizu"} <= set(pv["port"])


def test_enrich_merge_no_duplicates(tmp_path):
    ev = gfw_fetch.parse_events("432522000", EVENTS)
    path = tmp_path / "gfw_events.csv"
    gfw_fetch.merge_csv(path, ev, key=["event_id"])
    gfw_fetch.merge_csv(path, ev, key=["event_id"])
    assert len(pd.read_csv(path)) == 19


def test_enrich_info_merge_replaces_row(tmp_path):
    path = tmp_path / "gfw_vessel_info.csv"
    info, _ = gfw_fetch.parse_identity("432522000", SEARCH)
    gfw_fetch.merge_csv(path, pd.DataFrame([info]), key=["mmsi"])
    gfw_fetch.merge_csv(path, pd.DataFrame([{**info, "gross_tonnage": 1}]), key=["mmsi"])
    t = pd.read_csv(path, dtype={"mmsi": str})
    assert len(t) == 1 and t.iloc[0]["gross_tonnage"] == 1


GAPS = json.loads((FIX / "gfw_gaps_sample.json").read_text())


def test_enrich_parses_loitering_details():
    lo = gfw_fetch.parse_events("432522000", EVENTS)
    lo = lo[lo["kind"] == "loitering"].iloc[0]
    assert abs(lo["kn"] - 0.0142) < 0.001 and lo["shore_km"] == 294 and round(lo["port_km"]) == 302
    assert lo["high_seas"] in (0, False)


def test_enrich_parses_gaps():
    g = gfw_fetch.parse_events(GAPS["mmsi"], GAPS)
    g = g[g["kind"] == "gap"].iloc[0]
    assert abs(g["km"] - 395.65) < 0.1 and abs(g["kn"] - 1.76) < 0.01 and bool(g["intent"]) is True
    assert abs(g["off_lat"] - 21.5619) < 1e-3 and abs(g["on_lon"] - 151.1932) < 1e-3


def test_gap_dataset_requested():
    assert "public-global-gaps-events:latest" in gfw_fetch.EVENT_DATASETS
