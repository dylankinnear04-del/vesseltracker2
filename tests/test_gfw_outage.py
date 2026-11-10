"""gfw_fetch during a GFW outage: keep what downloaded, record why, don't fail the weekly run (no network)."""
import datetime as dt
import io
import json
import urllib.error

import pytest

import gfw_fetch

D = dt.date


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(gfw_fetch.time, "sleep", lambda s: None)
    gfw_fetch.OUTAGES.clear()
    yield
    gfw_fetch.OUTAGES.clear()


@pytest.fixture
def status_file(tmp_path, monkeypatch):
    path = tmp_path / "gfw_status.json"
    monkeypatch.setattr(gfw_fetch, "STATUS_FILE", path)
    return path


def test_temporarily_unavailable_is_an_outage(monkeypatch):
    def down(req, timeout=0):
        raise http_error(404, '{"message": "4wings report is temporarily unavailable. Please try again later"}')
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", down)
    with pytest.raises(gfw_fetch.GFWUnavailable):
        gfw_fetch.report("tok", D(2026, 10, 1), D(2026, 11, 1))


def test_server_errors_after_retries_are_an_outage(monkeypatch):
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(http_error(503, "busy")))
    with pytest.raises(gfw_fetch.GFWUnavailable):
        gfw_fetch.report("tok", D(2026, 10, 1), D(2026, 11, 1))


def test_bad_token_still_fails_hard(monkeypatch):
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(http_error(401, "bad token")))
    with pytest.raises(SystemExit) as e:
        gfw_fetch.report("tok", D(2026, 10, 1), D(2026, 11, 1))
    assert "401" in str(e.value)


def test_fetch_keeps_months_that_downloaded(monkeypatch):
    def report(tok, a, b, **q):
        if a.month == 11:
            raise gfw_fetch.GFWUnavailable("GFW API error 404: temporarily unavailable")
        return [{"mmsi": "1", "month": a.month}]
    monkeypatch.setattr(gfw_fetch, "report", report)
    gfw_fetch.OUTAGES.clear()
    df = gfw_fetch.fetch("tok", D(2026, 10, 1), D(2026, 11, 20), "test")
    assert list(df["month"]) == [10]
    assert gfw_fetch.OUTAGES and "temporarily unavailable" in gfw_fetch.OUTAGES[0]


def test_status_records_outage_and_keeps_last_success(status_file):
    gfw_fetch.write_status("mining", None, today=D(2026, 10, 27))
    gfw_fetch.write_status("mining", "GFW API error 404: temporarily unavailable", today=D(2026, 11, 3))
    s = json.loads(status_file.read_text())["mining"]
    assert s["ok"] is False and s["last_success"] == "2026-10-27" and s["last_attempt"] == "2026-11-03"
    assert "temporarily unavailable" in s["error"] and s["down_since"] == "2026-11-03"
    gfw_fetch.write_status("mining", "still down", today=D(2026, 11, 10))
    assert json.loads(status_file.read_text())["mining"]["down_since"] == "2026-11-03"
    gfw_fetch.write_status("mining", None, today=D(2026, 11, 17))
    s = json.loads(status_file.read_text())["mining"]
    assert s["ok"] is True and s["last_success"] == "2026-11-17" and "error" not in s and "down_since" not in s


def test_main_outage_exits_cleanly_and_writes_status(status_file, monkeypatch):
    monkeypatch.setattr(gfw_fetch, "token", lambda: "tok")
    monkeypatch.setattr(gfw_fetch, "report", lambda *a, **k: (_ for _ in ()).throw(gfw_fetch.GFWUnavailable("GFW API error 404: temporarily unavailable")))
    monkeypatch.setattr(gfw_fetch, "save", lambda df, names=None: (0, 0))
    monkeypatch.setattr("sys.argv", ["gfw_fetch.py", "--months", "2", "--status-key", "china"])
    gfw_fetch.main()                                             # no SystemExit: the run carries on
    assert json.loads(status_file.read_text())["china"]["ok"] is False


def test_later_pulls_skip_once_gfw_is_down(monkeypatch):
    calls = []
    monkeypatch.setattr(gfw_fetch, "report", lambda *a, **k: calls.append(1) or [])
    gfw_fetch.OUTAGES[:] = ["GFW API error 404: temporarily unavailable"]
    assert gfw_fetch.fetch("tok", D(2026, 10, 1), D(2026, 11, 20), "group").empty and calls == []
    gfw_fetch.OUTAGES.clear()


# ---------------------------------------------------------------- the website's notice
from webapp import console  # noqa: E402

TODAY = D(2026, 11, 10)


def test_notice_says_gfw_is_down(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"mining": {"ok": False, "down_since": "2026-11-03", "last_success": "2026-10-27",
                                        "error": "GFW API error 404: temporarily unavailable"},
                             "china": {"ok": True, "last_success": "2026-11-03"}}))
    msg = console.track_notice(D(2026, 10, 23), f, TODAY)
    assert "Global Fishing Watch" in msg and "unavailable since 3 Nov" in msg and "23 Oct 2026" in msg


def test_notice_when_late_without_known_cause(tmp_path):
    msg = console.track_notice(D(2026, 10, 23), tmp_path / "missing.json", TODAY)
    assert msg.startswith("Ship data last updated 23 Oct 2026")


def test_no_notice_when_current(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"mining": {"ok": True}}))
    assert console.track_notice(D(2026, 11, 6), f, TODAY) is None
