"""stationkeeping: ships holding one spot at sea for a day or more."""
import numpy as np
import pandas as pd

import stationkeeping as sk

PORTS = pd.DataFrame({"port": ["Shimizu"], "country": ["Japan"], "lat": [35.0], "lon": [138.5]})
T0 = pd.Timestamp("2026-01-17T00:00Z")
DEEP = lambda lat, lon: -4000.0          # noqa: E731  (test seabed: 4,000 m everywhere)
SHELF = lambda lat, lon: -100.0          # noqa: E731


def parked(hours, lat=23.05, lon=154.2, wobble_km=0.5, speed=0.1, start_h=0, seed=0):
    rng = np.random.default_rng(seed)
    d = wobble_km / 111.0
    return [{"time": T0 + pd.Timedelta(hours=start_h + k), "lat": lat + rng.uniform(-d, d),
             "lon": lon + rng.uniform(-d, d), "speed_kn": speed} for k in range(hours + 1)]


def moving(hours, lat0, lon0, dlat, start_h, speed=10.0):
    return [{"time": T0 + pd.Timedelta(hours=start_h + k), "lat": lat0 + dlat * k, "lon": lon0,
             "speed_kn": speed} for k in range(1, hours)]


def test_parked_three_days_at_sea_is_one_station():
    st = sk.detect_stations(pd.DataFrame(parked(72)), PORTS, depth=DEEP)
    assert len(st) == 1
    assert 71 <= st.iloc[0]["hours"] <= 72
    assert st.iloc[0]["r95_km"] < 1.5 and st.iloc[0]["port_km"] > 25 and st.iloc[0]["depth_m"] == -4000


def test_parked_in_port_is_not():
    assert sk.detect_stations(pd.DataFrame(parked(72, lat=35.0, lon=138.5)), PORTS, depth=DEEP).empty


def test_drifting_at_two_knots_is_not():
    assert sk.detect_stations(pd.DataFrame(parked(72, speed=2.0)), PORTS, depth=DEEP).empty


def test_wide_wander_is_not():
    assert sk.detect_stations(pd.DataFrame(parked(72, wobble_km=15)), PORTS, depth=DEEP).empty


def test_on_the_shelf_is_not():
    assert sk.detect_stations(pd.DataFrame(parked(72)), PORTS, depth=SHELF).empty


def test_short_stay_is_not():
    assert sk.detect_stations(pd.DataFrame(parked(20)), PORTS, depth=DEEP).empty


def test_two_stays_six_hours_apart_merge():
    rows = parked(20) + moving(6, 23.05, 154.2, 0.0, 20, speed=0.5) + parked(20, start_h=26, seed=1)
    st = sk.detect_stations(pd.DataFrame(rows), PORTS, depth=DEEP)
    assert len(st) == 1 and st.iloc[0]["hours"] >= 45


def test_two_stays_far_apart_stay_separate():
    rows = parked(30) + moving(40, 23.05, 154.2, 0.05, 30) + parked(30, lat=25.0, start_h=70)
    assert len(sk.detect_stations(pd.DataFrame(rows), PORTS, depth=DEEP)) == 2


def test_match_loitering():
    st = sk.detect_stations(pd.DataFrame(parked(72)), PORTS, depth=DEEP)
    ev = pd.DataFrame([
        {"kind": "loitering", "start": T0 + pd.Timedelta(hours=2), "end": T0 + pd.Timedelta(hours=70),
         "lat": 23.06, "lon": 154.21, "hours": 68.0},
        {"kind": "loitering", "start": T0, "end": T0 + pd.Timedelta(hours=72), "lat": 23.5, "lon": 154.2, "hours": 72.0},
        {"kind": "port_visit", "start": T0, "end": T0 + pd.Timedelta(hours=72), "lat": 23.05, "lon": 154.2, "hours": 72.0},
    ])
    m = sk.match_loitering(st, ev)
    assert m.iloc[0] is not None and m.iloc[0]["hours"] == 68.0 and m.iloc[0]["km"] < 10
    assert 0.9 < m.iloc[0]["overlap"] <= 1.0


def test_match_loitering_far_is_none():
    st = sk.detect_stations(pd.DataFrame(parked(72)), PORTS, depth=DEEP)
    ev = pd.DataFrame([{"kind": "loitering", "start": T0, "end": T0 + pd.Timedelta(hours=72),
                        "lat": 23.5, "lon": 154.2, "hours": 72.0}])
    assert sk.match_loitering(st, ev).iloc[0] is None


def test_match_loitering_no_events():
    st = sk.detect_stations(pd.DataFrame(parked(72)), PORTS, depth=DEEP)
    assert sk.match_loitering(st, pd.DataFrame()).iloc[0] is None


def test_station_across_dateline():
    rows = [{"time": T0 + pd.Timedelta(hours=k), "lat": -17.0 + 0.001 * (k % 3),
             "lon": 179.995 if k % 2 else -179.995, "speed_kn": 0.1} for k in range(72)]
    st = sk.detect_stations(pd.DataFrame(rows), PORTS, depth=DEEP)
    assert len(st) == 1 and abs(abs(st.iloc[0]["lon"]) - 180) < 0.05 and st.iloc[0]["r95_km"] < 2
