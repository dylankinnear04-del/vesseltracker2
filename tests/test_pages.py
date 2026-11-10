"""The site's pages (SeaTrace console + Analyst pages), run through Streamlit's AppTest."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from webapp import data, seatrace_export as sx

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = ["views/console.py", "views/analyst_upload.py", "views/analyst_settings.py",
         "views/analyst_compare.py", "views/analyst_data.py"]


def open_page(page, params=None, state=None):
    at = AppTest.from_file(APP, default_timeout=900)
    for k, v in (params or {}).items():
        at.query_params[k] = v
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    if page != "views/console.py":
        at.switch_page(page).run()
    return at


def iframes(at):
    return at.get("iframe")


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page):
    at = open_page(page)
    assert not at.exception, [e.value for e in at.exception]


def test_console_shows_seatrace_with_live_data():
    at = open_page("views/console.py")
    assert len(iframes(at)) == 1
    html = iframes(at)[0].proto.srcdoc if hasattr(iframes(at)[0].proto, "srcdoc") else str(iframes(at)[0].proto)
    assert "SeaTrace" in html and "Survey Detector" in html


def test_console_payload_built_once_for_everyone(monkeypatch):
    calls = {"n": 0}
    real = sx.build_blob

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(sx, "build_blob", counting)
    data._payload.clear()
    open_page("views/console.py", {"group": "china", "time": "30d"})
    open_page("views/console.py", {"group": "china", "time": "30d"})      # another visitor
    assert calls["n"] == 1


def test_custom_settings_payload_once_per_visitor(monkeypatch):
    calls = {"n": 0}
    real = sx.build_blob

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(sx, "build_blob", counting)
    custom = {**data.default_settings(), "min_lines_per_block": 6}
    at = open_page("views/console.py", {"group": "china", "time": "30d"}, {"settings": custom})
    at.run()                                                              # the same visitor clicks again
    assert calls["n"] == 1 and not at.exception


def test_console_group_without_data(monkeypatch):
    monkeypatch.setattr(data, "public_payload", lambda *a, **k: None)
    at = open_page("views/console.py")
    assert not iframes(at) and any("No ship in this group" in m.value for m in at.markdown)


def test_upload_sample_opens_in_seatrace():
    at = open_page("views/analyst_upload.py")
    [b for b in at.button if b.label.startswith("Try a sample")][0].click().run()
    assert not at.exception
    [b for b in at.button if "Open in SeaTrace" in b.label][0].click().run()
    assert not at.exception and at.session_state["upload_payload"] is not None


def test_settings_change_marks_session_custom():
    at = open_page("views/analyst_settings.py")
    at.number_input(key="cfg_min_lines_per_block").set_value(6).run()
    assert at.session_state["settings"]["min_lines_per_block"] == 6
    assert any("Custom settings are active" in i.value for i in at.info)


def test_compare_models_runs_on_benchmark():
    at = open_page("views/analyst_compare.py")
    at.selectbox(key="val-data").select("Benchmark: synthetic 10 ships (with labels)").run()
    [b for b in at.button if b.label == "Run comparison"][0].click().run()
    assert not at.exception
    assert {"model", "precision", "recall"} <= set(at.dataframe[0].value.columns)


def test_data_page_downloads():
    at = open_page("views/analyst_data.py")
    assert not at.exception
    labels = [b.proto.label for b in at.get("download_button")] + [b.label for b in at.button]
    assert any("ZIP" in l for l in labels) and any("Excel" in l for l in labels)
    for df in at.dataframe:
        assert len(df.value) <= 1000


def test_analyst_pages_link_back_to_seatrace():
    at = open_page("views/analyst_data.py")
    assert any("SeaTrace" in pl.proto.label for pl in at.get("page_link"))


def _console_html(at):
    f = iframes(at)[0].proto
    return getattr(f, "srcdoc", "") or str(f)


def test_console_notices_isa_and_empty_season(monkeypatch):
    from webapp import seatrace_export
    blob = '{"events":[],"zones":[]}'
    monkeypatch.setattr(data, "public_payload", lambda *a, **k: (blob, "b", "s"))
    monkeypatch.setattr(data, "isa_zones", lambda: None)
    html = _console_html(open_page("views/console.py"))
    assert "ISA contract areas unavailable" in html and "No detections in this season" in html
