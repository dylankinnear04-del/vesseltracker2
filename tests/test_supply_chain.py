"""supply_chain: ship -> owner -> parent -> US restricted lists, and area -> minerals (no network)."""
from pathlib import Path

import pytest

import supply_chain as sc

FIX = Path(__file__).resolve().parent / "fixtures" / "screening_sample.csv"


@pytest.fixture(scope="module")
def lst():
    return sc.load_list(FIX)


def lists(hits):
    return {h["list"] for h in hits}


def test_normalise_strips_legal_suffixes():
    assert sc.normalise("Yuzhmorgeologiya JSC") == sc.normalise("YUZHMORGEOLOGIYA AO") == "YUZHMORGEOLOGIYA"
    assert sc.normalise("CNOOC Limited") == "CNOOC"
    assert sc.normalise("Co., Ltd.") == ""


def test_exact_owner_name_is_a_likely_sdn_hit(lst):
    hits = sc.screen("YUZHMORGEOLOGIYA JSC", lst)
    assert lists(hits) == {"SDN"} and {h["level"] for h in hits} == {"likely"}
    assert all(h["url"] or h["source"] for h in hits)


def test_team_verified_list_is_confirmed(lst):
    hits = sc.screen("China National Offshore Oil Corporation", lst, {"CMIC"})
    assert any(h["list"] == "CMIC" and h["level"] == "confirmed" for h in hits)


def test_truncated_registry_name_prefix_matches(lst):
    hits = sc.screen("CHINA NATIONAL OFFSHORE OIL CO", lst)
    assert "CMIC" in lists(hits) and all(h["level"] == "likely" for h in hits)


def test_near_miss_is_possible(lst):
    hits = sc.screen("Yuzhmorgeologia", lst)
    assert hits and all(h["level"] == "possible" and 0.88 <= h["score"] < 1 for h in hits)


def test_government_and_short_names_never_match(lst):
    assert sc.screen("UNITED STATES GOVT NAVY", lst) == []
    assert sc.screen("MD II", lst) == []
    assert sc.screen("Co Ltd", lst) == []


def test_missing_list_file_gives_no_hits(tmp_path):
    empty = sc.load_list(tmp_path / "missing.csv.gz")
    assert len(empty) == 0 and sc.screen("YUZHMORGEOLOGIYA", empty) == []


def test_list_short_names(lst):
    assert lists(sc.screen("CNOOC Limited", lst)) == {"CMIC", "Entity List"}


def _list_of(*entries):
    import io
    import pandas as pd
    row = {c: "" for c in sc.LIST_COLUMNS}
    buf = io.StringIO()
    pd.DataFrame([dict(row, name=n, source=src) for n, src in entries]).to_csv(buf, index=False)
    buf.seek(0)
    return sc.load_list(buf)


def test_full_name_does_not_prefix_match_longer_entries():
    """Only names cut short by the registry (~30 characters) may match by prefix."""
    lst = _list_of(("Chinese Academy of Sciences Changchun Institute of Optics", "Entity List (EL) - Bureau of Industry and Security"))
    assert not any(h["level"] == "likely" for h in sc.screen("Chinese Academy of Sciences", lst))


def test_names_differing_by_an_ordinal_do_not_match():
    lst = _list_of(("Second Institute of Oceanography, Ministry of Natural Resources",
                    "Military End User (MEU) List - Bureau of Industry and Security"))
    assert sc.screen("Third Institute of Oceanography, Ministry of Natural Resources", lst) == []
    assert sc.screen("Second Institute of Oceanography, Ministry of Natural Resources", lst)[0]["level"] == "likely"
