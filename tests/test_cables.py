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
