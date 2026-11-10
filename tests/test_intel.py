"""intel: detections, confidence, priority (spec §11.1) and plain-English reasons."""
import pandas as pd
import pytest

import intel

T = pd.Timestamp("2026-06-01T00:00Z")
D = pd.Timedelta(days=1)
H = pd.Timedelta(hours=1)


# ---------------------------------------------------------------- tiers and labels
@pytest.mark.parametrize("score,tier", [(0.70, "P1"), (0.6999, "P2"), (0.50, "P2"), (0.4999, "P3"),
                                        (0.35, "P3"), (0.3499, "P4"), (0.0, "P4")])
def test_tier_boundaries(score, tier):
    assert intel.tier_of(score) == tier


@pytest.mark.parametrize("score,label", [(0.8, "HIGH"), (0.7999, "MODERATE"), (0.6, "MODERATE"), (0.5999, "LOW")])
def test_conf_label(score, label):
    assert intel.conf_label(score) == label


def test_factor_weights_match_spec():
    assert {k: w for k, _, w in intel.FACTORS} == {
        "resource": 0.22, "capability": 0.22, "strategic": 0.16, "depth": 0.10,
        "pattern": 0.10, "coord": 0.08, "dark": 0.06, "recency": 0.06}


# ---------------------------------------------------------------- the eight factors
ISA = intel.isa_index([{"type": "Feature", "properties": {"ContractID": "COMRAPMN1"},
                        "geometry": {"type": "Polygon", "coordinates": [[[-150, 10], [-148, 10], [-148, 12], [-150, 12], [-150, 10]]]}}])


def test_resource_inside_isa():
    v, detail, kind = intel.resource_factor(11.0, -149.0, ISA)
    assert v == 0.9 and "COMRA" in detail and kind == "nodules"


def test_resource_near_isa():
    v, detail, _ = intel.resource_factor(11.0, -146.0, ISA)        # ~220 km east
    assert v == 0.45 and "km from ISA" in detail


def test_resource_rare_earth_mud():
    v, detail, kind = intel.resource_factor(24.3, 154.0, ISA)       # Minamitorishima
    assert v == 0.8 and kind == "ree"


def test_resource_nothing():
    assert intel.resource_factor(50.0, -30.0, ISA)[0] == 0.1


def test_resource_isa_unavailable_falls_back():
    v, detail, kind = intel.resource_factor(11.0, -140.0, None)    # in the CCZ box
    assert "ISA areas unavailable" in detail and v == 0.45 and kind == "nodules"


@pytest.mark.parametrize("cls,v", [("MINING", 1.0), ("DRILLING", 0.9), ("GEO", 0.75), ("DEEP", 0.75),
                                   ("SUPPORT", 0.5), ("RESEARCH", 0.5), ("ENERGY", 0.35), ("UNK", 0.35), ("GOV", 0.25)])
def test_capability(cls, v):
    assert intel.CLASS_WEIGHT[cls] == v


JP = {"name": "Japanese Exclusive Economic Zone", "sovereigns": ("Japan",), "type": "200NM"}


def test_strategic_foreign_eez():
    assert intel.strategic_factor(JP, None, "China", None)[0] == 1.0


def test_strategic_joint_zone():
    z = {"name": "Joint regime area Japan / South Korea", "sovereigns": ("Japan", "South Korea"), "type": "Joint regime"}
    assert intel.strategic_factor(z, None, "Japan", None)[0] == 0.75


def test_strategic_own_eez_near_boundary():
    v, detail = intel.strategic_factor(JP, (30.0, "China - Japan"), "Japan", None)
    assert v == 0.6 and "China - Japan" in detail


def test_strategic_own_eez():
    assert intel.strategic_factor(JP, (300.0, "x"), "Japan", None)[0] == 0.15


def test_strategic_high_seas_sponsored_by_other():
    assert intel.strategic_factor(None, None, "China", "Japan")[0] == 0.8


def test_strategic_high_seas_near_boundary():
    assert intel.strategic_factor(None, (20.0, "x"), "China", None)[0] == 0.6


def test_strategic_high_seas():
    assert intel.strategic_factor(None, (500.0, "x"), "China", None)[0] == 0.4


@pytest.mark.parametrize("depth,v", [(-4800, 1.0), (-1000, 1.0), (-999, 0.6), (-200, 0.6), (-199, 0.15),
                                     (5, 0.05), (None, 0.5)])
def test_depth_factor(depth, v):
    assert intel.depth_factor(depth)[0] == v


@pytest.mark.parametrize("active,ended_days,v", [(True, 0, 1.0), (False, 13, 0.8), (False, 44, 0.6),
                                                 (False, 119, 0.3), (False, 200, 0.1)])
def test_recency(active, ended_days, v):
    assert intel.recency_factor(active, T - ended_days * D, T)[0] == v


# ---------------------------------------------------------------- relations between detections
def det(i, vessel, start, hours, lat, lon, kind="survey"):
    return {"key": i, "kind": kind, "vessel": vessel, "dataset": vessel, "start": start, "end": start + hours * H,
            "lat": lat, "lon": lon}


def test_coordination_needs_12h_overlap_within_80km():
    a = det(1, "A", T, 48, 20.0, 130.0)
    b = det(2, "B", T + 30 * H, 48, 20.3, 130.3)       # 18 h overlap, ~46 km
    c = det(3, "C", T + 40 * H, 48, 20.3, 130.3)       # 8 h overlap
    d = det(4, "D", T, 48, 22.0, 130.0)                # 222 km away
    rel = intel.relations([a, b, c, d])
    assert rel[1]["coord"] == [2] and 1 not in rel[3]["coord"]      # C overlaps A by 8 h only
    assert rel[4]["coord"] == []


def test_revisit_same_ship_7_days_150km():
    a = det(1, "A", T, 24, 20.0, 130.0)
    b = det(2, "A", T + 10 * D, 24, 20.5, 130.5)       # ~75 km, 10 days later
    c = det(3, "A", T + 2 * D, 24, 20.1, 130.1)        # same voyage
    rel = intel.relations([a, b, c])
    assert 2 in rel[1]["revisits"] and 3 not in rel[1]["revisits"]
    assert 3 in rel[1]["same_trip"]


def test_pattern_factor_order():
    assert intel.pattern_factor({"revisits": [2], "others": [], "same_trip": []}, False)[0] == 1.0
    assert intel.pattern_factor({"revisits": [], "others": [5], "same_trip": []}, False)[0] == 0.8
    assert intel.pattern_factor({"revisits": [], "others": [], "same_trip": [3]}, False)[0] == 0.6
    assert intel.pattern_factor({"revisits": [], "others": [], "same_trip": []}, True)[0] == 0.4
    assert intel.pattern_factor({"revisits": [], "others": [], "same_trip": []}, False)[0] == 0.3


# ---------------------------------------------------------------- whole build
def tiny_prepared():
    areas = pd.DataFrame([{"dataset": "Hai Da", "vessel": "Hai Da", "area_id": 1, "number": 1, "live": False,
                           "status": "completed", "n_lines": 10, "best_confidence": "high", "block_ids": "1",
                           "area_km2": 900.0, "centroid_lat": 25.0, "centroid_lon": 131.0,
                           "start_time": str(T), "end_time": str(T + 3 * D)}])
    blocks = pd.DataFrame([{"dataset": "Hai Da", "vessel": "Hai Da", "block_id": 1, "n_lines": 10, "score": 0.9,
                            "spacing_cv": 0.1, "mean_antiparallel_dev_deg": 4.0, "mean_overlap_frac": 0.8,
                            "progression_frac": 0.9, "survey_speed_kn": 5.0}])
    vessels = pd.DataFrame([{"dataset": "Hai Da", "vessel": "Hai Da", "name": "Hai Da Hao", "mmsi": "413328590",
                             "flag": "China", "ship_type": "Research vessel"}])
    return {"areas": areas, "vessels": vessels, "res": {"tables": {"survey_blocks": blocks}}}


def tiny_track():
    return pd.DataFrame({"time": [T + k * H for k in range(80)], "lat": 25.0, "lon": 131.0, "speed_kn": 5.0})


def test_build_survey_detection():
    out = intel.build(tiny_prepared(), {("Hai Da", "Hai Da"): tiny_track()}, ports=pd.DataFrame(),
                      gfw_info=pd.DataFrame(), gfw_events=pd.DataFrame(), isa=ISA, newest=T + 4 * D,
                      eez=lambda lat, lon: JP, boundary=lambda lat, lon: (400.0, "x"), depth=lambda lat, lon: -4800)
    d = out["detections"]
    assert len(d) == 1
    row = d.iloc[0]
    assert row["id"] == "SURVEY-HAIDAHAO-20260601" and row["kind"] == "survey" and row["area_number"] == 1
    assert row["confidence"] == 0.9 and row["conf_label"] == "HIGH"
    assert row["tier"] in ("P1", "P2", "P3", "P4")
    assert any("Japanese" in w for w in row["why"]) and any("4,800 m" in w for w in row["why"])
    assert [p[0] for p in row["pri_parts"]] == [k for k, _, _ in intel.FACTORS]
    assert {"detections", "stations", "calls", "gaps", "status"} <= set(out)


def test_build_missing_gfw_files_ok():
    out = intel.build(tiny_prepared(), {}, ports=pd.DataFrame(), gfw_info=None, gfw_events=None, isa=None,
                      newest=T + 4 * D, eez=lambda a, b: None, boundary=lambda a, b: None, depth=lambda a, b: None)
    assert len(out["detections"]) == 1
    assert any("ISA areas unavailable" in p[4] for p in out["detections"].iloc[0]["pri_parts"])


def test_ids_stable_by_start_date():
    p = tiny_prepared()
    second = p["areas"].iloc[0].copy()
    second.update({"area_id": 2, "number": 2, "start_time": str(T - 20 * D), "end_time": str(T - 18 * D)})
    p["areas"] = pd.concat([p["areas"], second.to_frame().T], ignore_index=True)
    kw = dict(ports=pd.DataFrame(), gfw_info=None, gfw_events=None, isa=ISA, newest=T + 4 * D,
              eez=lambda a, b: None, boundary=lambda a, b: None, depth=lambda a, b: -3000)
    out = intel.build(p, {}, **kw)
    ids = dict(zip(out["detections"]["area_number"], out["detections"]["id"]))
    assert ids[1] == "SURVEY-HAIDAHAO-20260601" and ids[2] == "SURVEY-HAIDAHAO-20260512"
    # the older survey drops out of the window: the other keeps its id
    p["areas"] = p["areas"].iloc[[0]]
    assert intel.build(p, {}, **kw)["detections"].iloc[0]["id"] == "SURVEY-HAIDAHAO-20260601"


def test_ids_same_day_clash_gets_suffix():
    p = tiny_prepared()
    second = p["areas"].iloc[0].copy()
    second.update({"area_id": 2, "number": 2, "start_time": str(T + 3 * H)})
    p["areas"] = pd.concat([p["areas"], second.to_frame().T], ignore_index=True)
    out = intel.build(p, {}, ports=pd.DataFrame(), gfw_info=None, gfw_events=None, isa=ISA, newest=T + 4 * D,
                      eez=lambda a, b: None, boundary=lambda a, b: None, depth=lambda a, b: -3000)
    assert sorted(out["detections"]["id"]) == ["SURVEY-HAIDAHAO-20260601", "SURVEY-HAIDAHAO-20260601-b"]


def test_blank_flag_is_unknown():
    v, detail = intel.strategic_factor(JP, None, "", None)
    assert v == 0.5 and "flag unknown" in detail.lower()
def test_why_always_says_where_and_how_deep():
    out = intel.build(tiny_prepared(), {}, ports=pd.DataFrame(), gfw_info=None, gfw_events=None, isa=ISA,
                      newest=T + 400 * D, eez=lambda a, b: {"name": "Japanese Exclusive Economic Zone",
                                                             "sovereigns": ("China",), "type": "200NM"},
                      boundary=lambda a, b: (900.0, "x"), depth=lambda a, b: -150)
    why = out["detections"].iloc[0]["why"]
    assert len(why) >= 3
    assert any("own flag" in w for w in why)            # low-scoring jurisdiction is still stated
    assert any("150 m" in w for w in why)               # shallow depth is still stated
