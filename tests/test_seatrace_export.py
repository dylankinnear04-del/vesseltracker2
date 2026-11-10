"""webapp.seatrace_export: our results in SeaTrace's data format (checked against SeaTrace's own data)."""
import json

import numpy as np
import pandas as pd
import pytest

from tests import seatrace_ref as ref
from webapp import data, seatrace_export as sx

needs_original = pytest.mark.skipif(not ref.available(), reason="SeaTrace.html not in ~/Downloads")
T0 = pd.Timestamp("2026-05-01T00:00Z")


@pytest.fixture(scope="module")
def blob():
    res = data.public_results("all", "6m")
    return sx.build_blob(res, data.library(), data.isa_zones())


@pytest.fixture(scope="module")
def reference():
    return json.loads(ref.blob())


def _keys(records, field=None):
    recs = [r for r in records if field is None or r.get(field) is not None]
    return set().union(*[set(r) for r in recs]) if recs else set()


@needs_original
def test_top_level_keys(blob, reference):
    assert set(reference) <= set(blob) and set(blob) - set(reference) <= {"extras"}


@needs_original
@pytest.mark.parametrize("key", ["vessels", "ports", "zones", "ree", "hotspots", "screened", "eezLines"])
def test_record_fields(blob, reference, key):
    if key == "zones" and not blob[key]:
        pytest.skip("ISA service unreachable during this run (zones are read live)")
    assert blob[key], key
    assert _keys(reference[key]) <= _keys(blob[key]), (key, _keys(reference[key]) - _keys(blob[key]))


@needs_original
def test_vessel_nested_fields(blob, reference):
    for field in ("calls", "gaps"):
        want = _keys([x for v in reference["vessels"] for x in v[field]])
        got = _keys([x for v in blob["vessels"] for x in v[field]])
        assert want <= got, (field, want - got)
    want = _keys([v["gfw"] for v in reference["vessels"] if v.get("gfw")])
    assert want <= _keys([v["gfw"] for v in blob["vessels"] if v.get("gfw")])
    want = _keys([e for v in reference["vessels"] if v.get("gfw") for e in v["gfw"]["events"]])
    assert want <= _keys([e for v in blob["vessels"] if v.get("gfw") for e in v["gfw"]["events"]])


@needs_original
def test_event_fields(blob, reference):
    for part in ("L", "S"):
        want = _keys([e for e in reference["events"] if part in e])
        got = _keys([e for e in blob["events"] if part in e])
        assert want - {"areaId", "status"} <= got, (part, want - got)
        assert _keys([e[part] for e in reference["events"] if part in e]) <= _keys([e[part] for e in blob["events"] if part in e])
    assert _keys([l for e in reference["events"] if "L" in e for l in e["L"]["lines"]]) <= \
        _keys([l for e in blob["events"] if "L" in e for l in e["L"]["lines"]])


@needs_original
def test_gfwval_fields(blob, reference):
    assert set(reference["gfwVal"]) <= set(blob["gfwVal"])


@needs_original
def test_vessel_ids_match_seatrace(blob, reference):
    theirs = {str(v["mmsi"]): v["id"] for v in reference["vessels"]}
    ours = {str(v["mmsi"]): v["id"] for v in blob["vessels"]}
    common = set(theirs) & set(ours)
    assert len(common) > 30 and all(theirs[m] == ours[m] for m in common)


def test_vessel_id_rule():
    assert sx.vessel_id("Hai Da Hao") == "haidahao" and sx.vessel_id("R.V Dong Fang Hong 2") == "rvdongfanghong2"


def test_track_roundtrip():
    tr = pd.DataFrame({"time": [T0 + pd.Timedelta(minutes=30 * k) for k in (0, 1, 2, 5, 9)],
                       "lat": [10.0, 10.013, 10.02, -5.5, -5.51], "lon": [150.0, 150.004, 150.009, 179.99, -179.98],
                       "speed_kn": [8.1, 8.0, 0.2, 12.3, 0.0]})
    back = sx.decode_track(sx.encode_track(tr, T0), T0)
    assert np.allclose(back["lat"], tr["lat"], atol=0.006) and np.allclose(back["lon"], tr["lon"], atol=0.006)
    assert (abs(back["time"] - tr["time"]) <= pd.Timedelta(minutes=30)).all()


def test_blob_size_under_6mb(blob):
    assert len(sx.to_json(blob).encode()) < 6_000_000


def test_script_tag_safe():
    text = sx.to_json({"vessels": [{"name": "</script><b>x"}]})
    assert "</script" not in text and json.loads(text)["vessels"][0]["name"] == "</script><b>x"


def test_event_ids_are_stable_ids(blob):
    res = data.public_results("all", "6m")
    assert {e["id"] for e in blob["events"]} == set(res["intel"]["detections"]["id"])


def test_events_reference_known_vessels_and_ports(blob):
    ids = {v["id"] for v in blob["vessels"]}
    assert all(e["vessel"] in ids for e in blob["events"])
    n = len(blob["ports"])
    assert all(0 <= c["port"] < n for v in blob["vessels"] for c in v["calls"])
    assert all(p["id"] == i for i, p in enumerate(blob["ports"]))


def test_isa_not_written(blob, tmp_path):
    import subprocess
    if not blob["zones"]:
        pytest.skip("ISA service unreachable")
    cid = blob["zones"][0]["id"]
    hits = subprocess.run(["git", "grep", "-l", f'"id": "{cid}"', "--", "."], capture_output=True, text=True,
                          cwd=data.HERE).stdout.strip()
    assert hits == ""


def test_extras_reference_case(blob):
    ref_ = blob["extras"]["reference"]
    assert "chikyu" in ref_
    c = ref_["chikyu"]
    assert [e["label"] for e in c["events"]][0].startswith("Departed Shimizu")
    site = c["gfw"]["site"]
    # GFW's loitering record for the Jan-Feb 2026 test: 17 Jan to 8 Feb, about 5,500 m deep
    assert pd.Timestamp(site["t0"], unit="ms", tz="UTC").date().isoformat() == "2026-01-17"
    assert pd.Timestamp(site["t1"], unit="ms", tz="UTC").date().isoformat() == "2026-02-08"
    assert -6200 < site["depth"] < -5000 and len(site["bbox"]) == 4 and c["sources"]


def test_extras_watch(blob):
    w = blob["extras"]["watch"]
    assert w and w[0]["vessel"] == "chikyu" and {"id", "title", "window", "basis", "expect"} <= set(w[0])


def test_extras_regression(blob):
    rg = blob["extras"]["regression"]
    rows, s = rg["rows"], rg["survey"]
    assert rows and all(len(r) == 5 for r in rows) and rg["note"]
    assert s["tp"] + s["fn"] == sum(1 for r in rows if r[1] == "Survey")
    assert s["tp"] + s["fp"] + s["fn"] + s["tn"] == len(rows)


def test_json_has_no_nan_or_infinity():
    text = sx.to_json({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": np.float64("nan")}, "e": pd.NA, "f": pd.NaT})
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {"a": None, "b": [1.0, None], "c": {"d": None}, "e": None, "f": None}


def test_real_blob_is_strict_json(blob):
    text = sx.to_json(blob)
    json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


# ---------------------------------------------------------------- Survey Detector extras (Task 5)
def test_extras_ports_and_routes(blob):
    ports, routes = blob["extras"]["ports"], blob["extras"]["routes"]
    surveys = [e["id"] for e in blob["events"] if e["model"] == "LAWNMOWER_SURVEY"]
    assert surveys and any(eid in ports for eid in surveys)
    some = next(ports[e] for e in surveys if e in ports)
    item = (some["home"] or some["near"])[0]
    assert {"name", "country", "km", "h", "cat"} <= set(item)
    rid = next(e for e in surveys if e in routes)
    assert all(len(r["c"]) >= 2 and len(r["c"][0]) == 2 for r in routes[rid])


def test_extras_target_for_every_event(blob):
    t = blob["extras"]["target"]
    assert set(t) == {e["id"] for e in blob["events"]} and all(v["likely"] for v in t.values())


def test_extras_regions_watch_view(blob):
    x = blob["extras"]
    assert x["regions"] and len(x["regions"][0]["box"]) == 4
    assert isinstance(x["pred"], list) and isinstance(x["watchNoData"], list)
    assert all({"name", "country"} <= set(w) for w in x["watchNoData"])
    assert x["view"]["groups"] and x["view"]["windows"]
    assert set(x["analysisVessel"]) == {v["id"] for v in blob["vessels"]}


def test_json_has_no_raw_less_than():
    text = sx.to_json({"name": "<!--<script>x</script>"})
    assert "<" not in text and json.loads(text)["name"] == "<!--<script>x</script>"


def test_header_says_when_isa_missing():
    banner, _ = sx.header_text({"T0": "2026-05-01T00:00:00+00:00", "AS_OF": 100.0, "zones": []})
    assert "ISA contract areas unavailable" in banner
    banner, _ = sx.header_text({"T0": "2026-05-01T00:00:00+00:00", "AS_OF": 100.0, "zones": [{"id": "X"}]})
    assert "ISA contract areas (live)" in banner


def test_gfwval_counts_and_pull_date(blob):
    g = blob["gfwVal"]
    assert g["pulled"] and len(g["missed"]) == g["gfwMissed"]


def test_regression_read_from_file_without_running_the_detector(monkeypatch):
    def no_run(*a, **k):
        raise AssertionError("the page must not run the detector on the benchmarks")
    monkeypatch.setattr(data, "analyse", no_run)
    monkeypatch.setattr(data, "_run_analysis", no_run)
    sx._REGRESSION_CACHE.clear()
    rg = sx.regression()
    assert rg["rows"] and rg["note"]


def test_regression_file_is_current():
    """benchmarks/regression_results.json matches the detector and benchmarks as they are now
    (rebuild with: python scripts/build_regression.py)."""
    stored = json.loads(sx.REGRESSION_FILE.read_text())
    assert stored["stamp"] == sx.regression_stamp()
    fresh = sx.compute_regression()
    assert fresh["rows"] == stored["rows"] and fresh["survey"] == stored["survey"]
