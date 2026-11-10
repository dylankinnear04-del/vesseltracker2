"""webapp.mapping.pick_at: which survey area or ship a map click landed on."""
from webapp.mapping import pick_at


def _area(ring, ds="ds", vessel="v", area_id=1):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"layer": "survey_area", "dataset": ds, "vessel": vessel, "area_id": area_id}}


def _track(coords, ds="ds", vessel="v"):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"layer": "track", "dataset": ds, "vessel": vessel}}


SQUARE = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]
LABELS = ((("ds", "v", 1), 3),)          # area 1 of (ds, v) is number 3 in the list


def test_pick_at_inside_area():
    g = {"features": [_area(SQUARE)]}
    assert pick_at(10.5, 10.5, g, LABELS, c=0.0) == ("area", 3)


def test_pick_at_outside_returns_none():
    g = {"features": [_area(SQUARE)]}
    assert pick_at(20.0, 20.0, g, LABELS, c=0.0) is None


def test_pick_at_across_dateline():
    ring = [[179.5, -17], [-179.5, -17], [-179.5, -16], [179.5, -16], [179.5, -17]]
    g = {"features": [_area(ring)]}
    assert pick_at(-16.5, -179.8, g, LABELS, c=180.0) == ("area", 3)
    assert pick_at(-16.5, 180.2, g, LABELS, c=180.0) == ("area", 3)
    assert pick_at(-16.5, 179.8, g, LABELS, c=0.0) == ("area", 3)


def test_pick_at_ship_track_within_20km():
    g = {"features": [_track([[0, 0], [1, 0]], ds="a", vessel="ship1")]}
    assert pick_at(0.1, 0.95, g, (), c=0.0) == ("ship", ("a", "ship1"))    # ~12 km from the vertex at (0, 1)


def test_pick_at_ship_track_beyond_20km_none():
    g = {"features": [_track([[0, 0], [1, 0]], ds="a", vessel="ship1")]}
    assert pick_at(1.0, 0.5, g, (), c=0.0) is None                           # ~111 km away


def test_area_wins_over_track():
    g = {"features": [_track([[10.5, 10.5], [10.6, 10.5]]), _area(SQUARE)]}
    assert pick_at(10.5, 10.5, g, LABELS, c=0.0) == ("area", 3)
