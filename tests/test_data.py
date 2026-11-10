import datetime
import io

import pandas as pd
import pytest

import survey_pattern_detector as spd
from webapp import data


@pytest.fixture(scope="module")
def lib():
    return data.library()


def test_select_ships_mining_matches_watchlist(lib):
    mining = data.select_ships(lib, "mining")
    watch = data.watchlist_mmsi(data.WATCHLIST.stat().st_mtime)
    assert len(mining) > 0
    assert set(mining["mmsi"]) <= set(watch)
    assert "412018330" in set(mining["mmsi"])          # Xue Long
    assert mining["has_data"].all()


def test_select_ships_unknown_group_falls_back(lib):
    assert data.select_ships(lib, "foo")["mmsi"].tolist() == data.select_ships(lib, "mining")["mmsi"].tolist()


def test_select_ships_country_filter(lib):
    china = data.select_ships(lib, "all", ("China",))
    assert len(china) > 0 and (china["flag"] == "China").all()


def _span(csv_bytes: bytes):
    std, _ = spd.standardize(pd.read_csv(io.BytesIO(csv_bytes)), "t")
    t = std["time"].dropna()
    return t.min().date(), t.max().date()


def test_build_groups_window_6m(lib):
    chosen = data.select_ships(lib, "mining")
    groups, identities, quiet = data.build_groups(chosen, "6m")
    end = max(d for d in chosen["data_to"] if d)
    start = end - datetime.timedelta(days=181)
    assert len(groups) + len(quiet) == len(chosen)
    assert len(identities) == len(groups)
    for _, files in groups:
        first, last = _span(files[0][1])
        assert first >= start and last <= end


def test_public_results_empty_window_returns_none(monkeypatch):
    """No chosen ship has positions in the window: no analysis, None back."""
    def boom(*a, **k):
        raise AssertionError("analyse must not run when no ship has data in the window")
    monkeypatch.setattr(data, "analyse", boom)
    monkeypatch.setattr(data, "_run_analysis", boom)
    data._public.clear()
    monkeypatch.setattr(data, "build_groups", lambda chosen, window: ((), (), list(chosen["name"])))
    try:
        assert data.public_results("mining", "6m") is None
    finally:
        data._public.clear()        # the shared cache outlives the test: don't leave this None in it


def test_public_results_default_has_numbered_areas():
    out = data.public_results("mining", "6m")
    areas = out["areas"]
    assert len(areas) > 0
    assert areas["number"].tolist() == list(range(1, len(areas) + 1))
    live = areas["live"].tolist()
    assert live == sorted(live, reverse=True)          # surveys still running come first
    assert {"vessels", "ports", "areas", "preds", "hotspots", "linked", "home", "labels", "res"} <= set(out)


def test_default_settings_build_a_config():
    s = data.default_settings()
    assert s["model"] == "baseline" and s["port_country"] == "flag"
    spd.Config(**{k: v for k, v in s.items() if k in spd.Config.__dataclass_fields__})


def test_public_results_carry_intel():
    out = data.public_results("mining", "6m")
    intel = out["intel"]
    det = intel["detections"]
    assert len(det) >= len(out["areas"])                       # every survey area, plus any stations
    assert set(det["tier"]) <= {"P1", "P2", "P3", "P4"}
    assert det["priority"].is_monotonic_decreasing
    surveys = det[det["kind"] == "survey"]
    assert sorted(surveys["area_number"].astype(int)) == sorted(out["areas"]["number"].astype(int))
    assert {"dataset", "vessel", "status", "stale"} <= set(intel["status"].columns)


def test_isa_zones_failure_returns_none(monkeypatch):
    def offline(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(data.urllib.request, "urlopen", offline)
    data.isa_zones.clear()
    try:
        assert data.isa_zones() is None
    finally:
        data.isa_zones.clear()


def test_public_groups_leave_out_demo_ships(lib):
    demo = lib[lib["ship_type"].str.lower().str.startswith("demo")]
    assert len(demo) > 0
    for group in data.GROUPS:
        assert not set(demo["name"]) & set(data.select_ships(lib, group)["name"])


def test_groups_from_uploads_separate_and_combined():
    files = [("a.csv", b"x"), ("a.csv", b"y"), ("b.csv", b"z")]
    sep = data.groups_from_uploads(files, combine=False)
    assert [g[0] for g in sep] == ["a", "a (2)", "b"]
    comb = data.groups_from_uploads(files, combine=True)
    assert len(comb) == 1 and comb[0][0] == "Combined upload" and len(comb[0][1]) == 3


def test_run_upload_junk_gives_message():
    res, err = data.run_upload((("junk", (("junk.csv", b"hello\nthis is not ais\n"),)),), ())
    assert res is None and err


def test_run_upload_benchmark():
    path = data.HERE / "benchmarks" / "demo1_hourly_patrols.csv"
    res, err = data.run_upload((("demo1", ((path.name, path.read_bytes()),)),), ())
    assert err is None and "intel" in res and len(res["vessels"]) > 0


def test_isa_failure_not_cached(monkeypatch):
    import io, json as _json
    calls = {"n": 0}

    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("no network")
        return io.BytesIO(_json.dumps({"features": [{"type": "Feature", "properties": {"ContractID": "X"},
                                                     "geometry": None}]}).encode())
    monkeypatch.setattr(data.urllib.request, "urlopen", flaky)
    data.isa_zones.clear()
    try:
        assert data.isa_zones() is None            # outage
        data._ISA_DOWN_UNTIL = 0.0                 # the quiet period after a failure is over (not monkeypatch: it would restore the outage)
        assert data.isa_zones() is not None        # back: fetched again, not the cached failure
    finally:
        data.isa_zones.clear()


def test_prepare_empty_areas_has_columns():
    res = {"tables": {k: pd.DataFrame() for k in data.TABLES}}
    out = data.prepare(res)
    for col in ("dataset", "vessel", "area_id", "number", "live", "end_time", "start_time"):
        assert col in out["areas"].columns


def test_gfw_tables_malformed_events(tmp_path, monkeypatch):
    bad = tmp_path / "gfw_events.csv"
    bad.write_text("mmsi,kind\n1,loitering\n")
    monkeypatch.setattr(data, "GFW_EVENTS", bad)
    data.gfw_tables.clear()
    try:
        info, ev = data.gfw_tables((0.0, 1.0))
        assert ev.empty and {"start", "end"} <= set(ev.columns)
    finally:
        data.gfw_tables.clear()


def test_parse_labels():
    ok, err = data.parse_labels(b"vessel,is_survey\na,1\nb,0\n")
    assert ok == {"a": 1, "b": 0} and err is None
    none, err = data.parse_labels(b"id,vessel,status,note\nX,a,Confirmed,\n")
    assert none is None and "is_survey" in err
    none, err = data.parse_labels(b"vessel,is_survey\na,maybe\n")
    assert none is None and "1 or 0" in err


def test_console_payload_does_not_keep_analysis_results(monkeypatch):
    """The console only needs the finished JSON: building it must not fill the shared results cache."""
    def no_shared_results(*a, **k):
        raise AssertionError("payload build went through the cached _public results")
    monkeypatch.setattr(data, "_public", no_shared_results)
    data._payload.clear()
    try:
        out = data.public_payload("china", "30d")
        assert out is None or out[0].startswith("{")
    finally:
        data._payload.clear()


def test_isa_failure_remembered_for_a_while(monkeypatch):
    calls = {"n": 0}

    def offline(*a, **k):
        calls["n"] += 1
        raise OSError("no network")
    monkeypatch.setattr(data.urllib.request, "urlopen", offline)
    data.isa_zones.clear()
    try:
        assert data.isa_zones() is None and data.isa_zones() is None
        assert calls["n"] == 1                                   # the second visitor does not wait again
        data._ISA_DOWN_UNTIL = 0.0                                 # the quiet period is over (not monkeypatch: it would restore it)
        assert data.isa_zones() is None and calls["n"] == 2
    finally:
        data.isa_zones.clear()
