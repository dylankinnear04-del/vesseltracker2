"""cables.py: TeleGeography submarine cables, distance to a cable, and the cable watch on a ship's track."""
import numpy as np
import pandas as pd
import pytest

import cables


def live():
    return [c for c in cables.load_cables() if not c["planned"]]


def test_cables_loaded():
    cs = cables.load_cables()
    assert len(cs) > 500 and all(c["lines"] for c in cs)


def test_near_cable_on_a_route():
    c = next(c for c in live() if len(c["lines"][0]) > 3)
    lat, lon = c["lines"][0][len(c["lines"][0]) // 2]
    assert any(h["id"] == c["id"] and h["km"] < 1 for h in cables.near_cable(lat, lon))


def test_near_cable_between_vertices():          # distance to the line, not to its vertices
    for c in live():
        seg = next(((a, b) for a, b in zip(c["lines"][0], c["lines"][0][1:])
                    if cables._seg_km(a, b) > 50 and abs(a[1] - b[1]) < 90), None)
        if seg:
            break
    a, b = seg
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert any(h["id"] == c["id"] for h in cables.near_cable(*mid))


def test_near_cable_far_from_any():
    assert cables.near_cable(-60.0, -120.0) == []           # Southern Ocean


def test_near_cable_lists_at_most_three_nearest_first():
    for c in live():
        for line in c["lines"]:
            for lat, lon in line:
                hits = cables.near_cable(lat, lon)
                if len(hits) > 1:
                    assert len(hits) <= 3 and [h["km"] for h in hits] == sorted(h["km"] for h in hits)
                    return
    pytest.skip("no cable junction found")


def test_near_cable_longitude_written_either_way():
    c = next(c for c in live() if any(abs(p[1]) > 170 for l in c["lines"] for p in l))
    lat, lon = next(p for l in c["lines"] for p in l if abs(p[1]) > 170)
    other = lon - 360 if lon > 0 else lon + 360
    assert any(h["id"] == c["id"] for h in cables.near_cable(lat, other))


def test_segment_across_the_antimeridian():
    for c in live():
        for l in c["lines"]:
            for a, b in zip(l, l[1:]):
                if abs(a[1]) > 170 and abs(b[1]) > 170 and a[1] * b[1] < 0:
                    lat = (a[0] + b[0]) / 2
                    assert any(h["id"] == c["id"] for h in cables.near_cable(lat, 180.0, km=30))
                    return
    pytest.skip("no route crosses the antimeridian between two vertices")


def test_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cables, "CABLES_FILE", tmp_path / "none.geojson")
    cables.load_cables.cache_clear(); cables._index.cache_clear()
    try:
        assert cables.load_cables() == [] and cables.near_cable(0, 0) == []
    finally:
        cables.load_cables.cache_clear(); cables._index.cache_clear()


def test_landing_points():
    lp = cables.landing_points()
    assert lp.shape[1] == 2 and len(lp) > 1000


# ---------- cable watch -------------------------------------------------------------------------------------------

def _away_from_landings(lat, lon, km=50):
    lp = cables.landing_points()
    d = 2 * cables.EARTH_KM * np.arcsin(np.clip(np.linalg.norm(cables._xyz(lp[:, 0], lp[:, 1]) - cables._xyz(lat, lon), axis=1) / 2, 0, 1))
    return d.min() > km


@pytest.fixture(scope="module")
def P():
    """A point on an east-west stretch of a lone built cable, far from any landing (ships cross it north-south)."""
    for c in live():
        for l in c["lines"]:
            for a, b in zip(l, l[1:]):
                if abs(b[1] - a[1]) < 30 and abs(b[0] - a[0]) < 0.3 * abs(b[1] - a[1]) and cables._seg_km(a, b) > 100:
                    p = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    if (_away_from_landings(*p, 100) and abs(p[0]) < 60
                            and {h["id"] for h in cables.near_cable(*p, km=150)} == {c["id"]}):   # one cable, not a corridor
                        return p
    pytest.skip("no suitable cable stretch")


def track(points, speeds, hours=None, start="2026-06-01"):
    t0 = pd.Timestamp(start, tz="UTC")
    hours = list(range(len(points))) if hours is None else hours
    return pd.DataFrame({"time": [t0 + pd.Timedelta(hours=h) for h in hours], "lat": [p[0] for p in points],
                         "lon": [p[1] for p in points], "speed_kn": speeds})


NO_PORTS = np.empty((0, 2))
STEP = 0.1666                      # 10 kn for an hour, in degrees of latitude


def transit(P, n=5):
    return [(P[0] + k * STEP, P[1]) for k in range(-n, n + 1)]


def test_crossing_at_speed_is_not_an_episode(P):
    tr = track(transit(P), [10] * 11)
    assert cables.watch(tr, NO_PORTS) == []
    assert cables.crossing_hours(tr, NO_PORTS) == [1.0]


def test_three_hours_slow_on_cable(P):
    tr = track([(P[0] + 0.005 * k, P[1]) for k in range(4)], [1.0] * 4)
    eps = cables.watch(tr, NO_PORTS)
    assert len(eps) == 1 and eps[0]["kind"] == "slow" and eps[0]["hours"] >= 2
    assert eps[0]["cables"] and eps[0]["cables"][0]["km"] < 5 and not eps[0]["cable_ship"]


def test_stopped_kind(P):
    eps = cables.watch(track([(P[0], P[1])] * 4, [0.1] * 4), NO_PORTS)
    assert [e["kind"] for e in eps] == ["stopped"]


def test_single_slow_fix_is_not_an_episode(P):
    sp = [10] * 11
    sp[5] = 0.0
    assert cables.watch(track(transit(P), sp), NO_PORTS) == []


def test_near_port_is_ignored(P):
    tr = track([(P[0], P[1])] * 4, [0.5] * 4)
    assert cables.watch(tr, np.array([[P[0] + 0.054, P[1]]])) == []        # a port 6 km away


def test_near_landing_point_is_ignored():
    lp = cables.landing_points()
    for lat, lon in lp:
        if cables.near_cable(lat + 0.02, lon, km=3):
            tr = track([(lat + 0.02, lon)] * 4, [0.2] * 4)
            assert cables.watch(tr, NO_PORTS)                 # on a cable...
            assert cables.watch(tr, lp) == []                 # ...but at a landing: not an episode
            return
    pytest.skip("no landing point with a cable 2 km offshore")


def test_dark_gap_on_cable(P):
    far = (P[0] + 0.54, P[1])
    eps = cables.watch(track([P, far], [8, 8], hours=[0, 7]), NO_PORTS)
    assert [e["kind"] for e in eps] == ["dark"] and eps[0]["hours"] == 7
    assert cables.watch(track([P, far], [8, 8], hours=[0, 4]), NO_PORTS) == []


def test_cable_ship_marked(P):
    assert cables.is_cable_ship("Cable Innovator", "", "") and cables.is_cable_ship("X", "Cable Layer", "")
    assert not cables.is_cable_ship("Da Yang Hao", "Research", "")
    eps = cables.watch(track([(P[0], P[1])] * 4, [0.1] * 4), NO_PORTS, cable_ship=True)
    assert eps and all(e["cable_ship"] for e in eps)


def test_missing_speed_is_derived(P):
    tr = track(transit(P), [np.nan] * 11)
    assert cables.watch(tr, NO_PORTS) == []                  # 18 km an hour: not slow
