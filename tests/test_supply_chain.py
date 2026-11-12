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


# ---------------------------------------------------------------- chains (Task 3)
import pandas as pd  # noqa: E402

LINKS = sc.load_links(Path(__file__).resolve().parents[1] / "reference_data" / "entity_links.csv")
RELIANCE = pd.read_csv(Path(__file__).resolve().parents[1] / "reference_data" / "mineral_import_reliance.csv", dtype=str)
REE = pd.read_csv(Path(__file__).resolve().parents[1] / "reference_data" / "ree_sites.csv", dtype=str)


def ship(name="Hai Yang Shi You 719", operator="", imo="", flag="China"):
    return {"name": name, "imo": imo, "flag": flag, "operator": operator}


def test_owner_with_parent_on_lists_is_confirmed(lst):
    c = sc.ship_chain(ship(), "CHINA OILFIELD SERVICES", LINKS, lst)
    assert c["owner_source"] == "GFW registry" and c["parent"] == "China National Offshore Oil Corporation"
    assert c["state_owned"] is True and c["country"] == "CHN"
    assert any(h["list"] == "CMIC" and h["level"] == "confirmed" and h["matched"] == "parent" for h in c["hits"])
    assert "DoD 1260H" in c["verified_lists"]


def test_catalog_operator_used_when_registry_has_no_owner(lst):
    c = sc.ship_chain(ship("Gelendzhik", operator="Yuzhmorgeologiya JSC", flag="Russia"), "", LINKS, lst)
    assert c["owner_source"] == "catalog" and c["parent"] == "JSC Rosgeologia"
    assert any(h["list"] == "SDN" and h["matched"] == "owner" for h in c["hits"])


def test_unknown_owner_is_said(lst):
    c = sc.ship_chain(ship("Some Ship"), "", LINKS, lst)
    assert c["owner"] is None and any("Owner unknown" in n for n in c["notes"]) and c["hits"] == []


def test_ship_name_checked_against_listed_vessels_only(lst):
    c = sc.ship_chain(ship("Yuzhmorgeologiya", flag="Russia"), "", LINKS, lst)
    assert [h["list"] for h in c["ship_hits"]] == ["SDN"]
    c2 = sc.ship_chain(ship("CNOOC Limited"), "", LINKS, lst)       # a company name used as a ship name
    assert c2["ship_hits"] == []


def test_area_inside_contract():
    a = sc.area_chain({"zone": "COMRAPMN1", "nearZone": None, "nearZoneKm": None, "center": [10.0, -150.0]}, RELIANCE, REE)
    assert a["basis"] == "inside" and a["sponsor"] == "China" and "COMRA" in a["contractor"]
    assert [m["name"] for m in a["minerals"]] == ["nickel", "cobalt", "copper", "manganese"]
    assert next(m for m in a["minerals"] if m["name"] == "manganese")["reliance_pct"] == "100"


def test_area_near_contract_within_300_km():
    a = sc.area_chain({"zone": None, "nearZone": "COMRACRFC1", "nearZoneKm": 120.0, "center": [20.0, 155.0]}, RELIANCE, REE)
    assert a["basis"] == "near" and "rare earths" in [m["name"] for m in a["minerals"]] and a["processing"]


def test_area_far_from_contract_uses_region():
    a = sc.area_chain({"zone": None, "nearZone": "COMRAPMN1", "nearZoneKm": 450.0, "center": [12.0, -140.0]}, RELIANCE, REE)
    assert a["basis"] == "region" and a["contract"] is None and "Clarion" in a["region"]
    assert {"nickel", "cobalt"} <= {m["name"] for m in a["minerals"]}


def test_area_outside_everything():
    a = sc.area_chain({"zone": None, "nearZone": None, "nearZoneKm": None, "center": [60.0, -30.0]}, RELIANCE, REE)
    assert a["contract"] is None and a["basis"] is None and a["minerals"] == [] and a["notes"]


def test_entities_group_ships_by_parent(lst):
    ships = {"hysy719": sc.ship_chain(ship(), "CHINA OILFIELD SERVICES", LINKS, lst),
             "hysy720": sc.ship_chain(ship("Haiyangshiyou720"), "CHINA OILFIELD SERVICES", LINKS, lst),
             "other": sc.ship_chain(ship("Sonne", flag="Germany"), "GERMANY GOVT BILDUNG", LINKS, lst)}
    events = [{"id": "E1", "vessel": "hysy719"}, {"id": "E2", "vessel": "hysy720"}, {"id": "E3", "vessel": "other"}]
    areas = {"E1": {"minerals": [{"name": "nickel"}]}, "E2": {"minerals": [{"name": "cobalt"}]}, "E3": {"minerals": []}}
    rows = sc.entities(ships, events, areas)
    top = rows[0]
    assert top["name"] == "China National Offshore Oil Corporation" and top["kind"] == "parent"
    assert top["ships"] == ["hysy719", "hysy720"] and top["events"] == ["E1", "E2"] and top["detections"] == 2
    assert top["minerals"] == ["cobalt", "nickel"] and top["best"] == "confirmed"
    assert any(r["name"] == "GERMANY GOVT BILDUNG" and r["kind"] == "owner" and r["best"] is None for r in rows)
