"""gfw_fetch --screening: the weekly slim copy of the US Consolidated Screening List (no network in tests)."""
import gzip
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

import gfw_fetch

KEPT = ["name", "alt_names", "source", "programs", "start_date", "source_list_url", "source_information_url",
        "type", "call_sign", "vessel_flag", "ids"]


def sample():
    row = {c: "" for c in KEPT}
    rows = [dict(row, name="ACME SHIPPING", type="Entity", source="SDN"),
            dict(row, name="BLUE VESSEL", type="Vessel", source="SDN", ids="IMO 1234567"),
            dict(row, name="SOME LAB", type="", source="Entity List (EL) - Bureau of Industry and Security"),
            dict(row, name="JOHN DOE", type="Individual", source="SDN"),
            dict(row, name="AIR 1", type="Aircraft", source="SDN")]
    return pd.DataFrame(rows).assign(extra_column="x")


def test_slim_drops_individuals_aircraft_and_columns():
    out = gfw_fetch.slim_screening(sample())
    assert list(out["name"]) == ["ACME SHIPPING", "BLUE VESSEL", "SOME LAB"]
    assert list(out.columns) == KEPT


def test_fetch_screening_keeps_old_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "screening_list.csv.gz"
    path.write_bytes(b"old")
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", path)
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("down")))
    assert gfw_fetch.fetch_screening() is False and path.read_bytes() == b"old"


def test_fetch_screening_writes_slim_gzip(tmp_path, monkeypatch):
    import io
    path = tmp_path / "screening_list.csv.gz"
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", path)
    raw = sample().to_csv(index=False).encode()
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(raw))
    assert gfw_fetch.fetch_screening() is True
    out = pd.read_csv(path, dtype=str)
    assert len(out) == 3 and gzip.decompress(path.read_bytes())


def test_main_screening_flag_needs_no_token(monkeypatch):
    calls = []
    monkeypatch.setattr(gfw_fetch, "fetch_screening", lambda: calls.append(1) or True)
    monkeypatch.setattr(gfw_fetch, "token", lambda: (_ for _ in ()).throw(AssertionError("token needed")))
    monkeypatch.setattr("sys.argv", ["gfw_fetch.py", "--screening"])
    gfw_fetch.main()
    assert calls == [1]


def test_fetch_rejects_a_list_with_blank_names(tmp_path, monkeypatch):
    import io
    path = tmp_path / "screening_list.csv.gz"
    path.write_bytes(b"old")
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", path)
    raw = sample().rename(columns={"name": "entity_name"}).to_csv(index=False).encode()
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(raw))
    assert gfw_fetch.fetch_screening() is False and path.read_bytes() == b"old"


def test_fetch_rejects_a_list_far_smaller_than_last_week(tmp_path, monkeypatch):
    import io
    path = tmp_path / "screening_list.csv.gz"
    big = pd.concat([sample()] * 10)
    path.write_bytes(gzip.compress(gfw_fetch.slim_screening(big).to_csv(index=False).encode()))
    before = path.read_bytes()
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", path)
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(sample().to_csv(index=False).encode()))
    assert gfw_fetch.fetch_screening() is False and path.read_bytes() == before


def test_fetch_records_the_download_date(tmp_path, monkeypatch):
    import io
    import json
    path = tmp_path / "screening_list.csv.gz"
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", path)
    monkeypatch.setattr(gfw_fetch, "SCREENING_META", tmp_path / "screening_list.json")
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(sample().to_csv(index=False).encode()))
    assert gfw_fetch.fetch_screening() is True
    meta = json.loads((tmp_path / "screening_list.json").read_text())
    assert meta["rows"] == 3 and len(meta["fetched"]) == 10


def test_tests_never_write_the_real_meta_file(tmp_path, monkeypatch):
    """A test that only redirects the list file must not overwrite library/screening_list.json."""
    import io
    real = Path(gfw_fetch.__file__).resolve().parent / "library" / "screening_list.json"
    before = real.read_bytes() if real.exists() else None
    monkeypatch.setattr(gfw_fetch, "SCREENING_FILE", tmp_path / "screening_list.csv.gz")
    monkeypatch.setattr(gfw_fetch.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(sample().to_csv(index=False).encode()))
    assert gfw_fetch.fetch_screening() is True
    assert (real.read_bytes() if real.exists() else None) == before
