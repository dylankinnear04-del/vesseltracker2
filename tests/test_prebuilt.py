"""Console data built ahead of time (scripts/build_console_data.py) and read by the site without running the detector."""
import gzip
import json

import pytest

from webapp import data

FAKE_ZONES = [{"type": "Feature", "properties": {"ContractID": "ZZ-TEST", "Contractor": "Test"},
               "geometry": {"type": "Polygon", "coordinates": [[[-150, 10], [-149, 10], [-149, 11], [-150, 10]]]}}]


def fake_blob(group, window):
    return {"T0": "2026-05-01T00:00:00+00:00", "AS_OF": 100.0, "events": [{"id": "SURVEY-X-20260501"}],
            "vessels": [], "zones": [{"id": "ZZ-TEST", "name": "poly"}], "view": {"group": group, "time": window}}


@pytest.fixture
def prebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "PREBUILT", tmp_path)
    monkeypatch.setattr(data, "_console_blob", fake_blob)
    monkeypatch.setattr(data, "isa_zones", lambda: FAKE_ZONES)
    data._prebuilt_payload.clear()
    data._payload.clear()
    yield tmp_path
    data._prebuilt_payload.clear()


def no_run(*a, **k):
    raise AssertionError("the site must not run the detector when the data was built ahead of time")


def test_written_file_has_no_isa_polygons(prebuilt):
    path = data.write_prebuilt("mining", "6m")
    text = gzip.decompress(path.read_bytes()).decode()
    meta = json.loads(text)
    assert meta["stamp"] == data.inputs_stamp() and meta["isa"] is True
    assert meta["blob"]["zones"] == [] and "poly" not in text


def test_site_reads_prebuilt_without_running_detector(prebuilt, monkeypatch):
    data.write_prebuilt("mining", "6m")
    monkeypatch.setattr(data, "_console_blob", no_run)
    blob, banner, _ = data.public_payload("mining", "6m")
    out = json.loads(blob)
    assert out["events"][0]["id"] == "SURVEY-X-20260501"
    assert [z["id"] for z in out["zones"]] == ["ZZ-TEST"]          # live ISA areas added at page load
    assert "ISA contract areas (live)" in banner


def test_stale_file_is_ignored(prebuilt, monkeypatch):
    data.write_prebuilt("mining", "6m")
    monkeypatch.setattr(data, "inputs_stamp", lambda: "something-else")
    calls = []
    monkeypatch.setattr(data, "_console_blob", lambda g, w: calls.append(1) or fake_blob(g, w))
    assert data.public_payload("mining", "6m") is not None and calls == [1]


def test_built_without_isa_rebuilt_live_once_isa_is_back(prebuilt, monkeypatch):
    monkeypatch.setattr(data, "isa_zones", lambda: None)
    data.write_prebuilt("mining", "6m")
    monkeypatch.setattr(data, "isa_zones", lambda: FAKE_ZONES)
    assert data._read_prebuilt("mining", "6m", data.inputs_stamp(), True) is None
    assert data._read_prebuilt("mining", "6m", data.inputs_stamp(), False) is not None


def test_group_without_ships_is_prebuilt_too(prebuilt, monkeypatch):
    monkeypatch.setattr(data, "_console_blob", lambda g, w: None)
    data.write_prebuilt("china", "30d")
    monkeypatch.setattr(data, "_console_blob", no_run)
    assert data.public_payload("china", "30d") is None


def test_stamp_changes_with_detector_code(monkeypatch):
    before = data.inputs_stamp()
    files = data.stamp_inputs()
    names = {p.name for p in files}
    assert {"vessels.csv", "survey_pattern_detector.py", "intel.py", "seatrace_export.py"} <= names
    assert before == data.inputs_stamp()                          # stable between calls


def test_console_page_opens_from_prebuilt_file(prebuilt, monkeypatch):
    from tests.test_pages import open_page, _console_html
    data.write_prebuilt("mining", "6m")
    monkeypatch.setattr(data, "_console_blob", no_run)
    at = open_page("views/console.py", {"group": "mining", "time": "6m"})
    assert not at.exception and "SURVEY-X-20260501" in _console_html(at)
