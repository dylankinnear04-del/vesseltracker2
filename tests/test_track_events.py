"""track_events: port calls, voyages, AIS gaps and ship status from an hourly track."""
import pandas as pd

import track_events as te

PORTS = pd.DataFrame({"port": ["Qingdao", "Shanghai"], "country": ["China", "China"],
                      "lat": [36.07, 31.23], "lon": [120.32, 121.47]})
T0 = pd.Timestamp("2026-05-01T00:00Z")


def track(rows):
    """rows: (hours from T0, lat, lon, speed)."""
    return pd.DataFrame([{"time": T0 + pd.Timedelta(hours=h), "lat": la, "lon": lo, "speed_kn": s}
                         for h, la, lo, s in rows])


def stay(start_h, hours, lat, lon, speed=0.2):
    return [(start_h + k, lat, lon, speed) for k in range(hours + 1)]


def sail(start_h, hours, lat0, lon0, lat1, lon1, speed=10.0):
    return [(start_h + k, lat0 + (lat1 - lat0) * k / hours, lon0 + (lon1 - lon0) * k / hours, speed)
            for k in range(1, hours)]


def test_ten_hour_stop_is_a_port_call():
    t = track(sail(0, 5, 34.0, 122.0, 36.07, 120.32) + stay(5, 10, 36.07, 120.32) + sail(15, 5, 36.07, 120.32, 34, 122))
    calls = te.port_calls(t, PORTS)
    assert len(calls) == 1 and calls.iloc[0]["port"] == "Qingdao"
    assert calls.iloc[0]["hours"] == 10 and not calls.iloc[0]["open"]


def test_three_hour_stop_is_not():
    t = track(sail(0, 5, 34.0, 122.0, 36.07, 120.32) + stay(5, 3, 36.07, 120.32) + sail(8, 5, 36.07, 120.32, 34, 122))
    assert te.port_calls(t, PORTS).empty


def test_stop_far_from_port_is_not():
    assert te.port_calls(track(stay(0, 30, 20.0, 140.0)), PORTS).empty


def test_open_call_at_end():
    t = track(sail(0, 5, 34.0, 122.0, 36.07, 120.32) + stay(5, 12, 36.07, 120.32))
    assert te.port_calls(t, PORTS).iloc[0]["open"]


def test_same_port_return():
    rows = (stay(0, 8, 36.07, 120.32) + sail(8, 48, 36.07, 120.32, 30, 125)
            + sail(56, 48, 30, 125, 36.07, 120.32) + stay(104, 8, 36.07, 120.32))
    t = track(rows)
    calls = te.port_calls(t, PORTS)
    v = te.voyages(calls, t["time"].max())
    assert len(v) == 1 and v.iloc[0]["same_port"] and v.iloc[0]["from_port"] == "Qingdao"


def test_shipyard_month_is_one_call_no_gaps():
    t = track(stay(0, 24 * 30, 31.23, 121.47))
    calls = te.port_calls(t, PORTS)
    assert len(calls) == 1 and calls.iloc[0]["hours"] == 720
    assert te.ais_gaps(t).empty


def test_twenty_hour_hole_is_a_gap():
    t = track(sail(0, 10, 20, 130, 20, 131) + sail(30, 10, 20.5, 131.5, 21, 132))
    g = te.ais_gaps(t)
    assert len(g) == 1 and g.iloc[0]["hours"] == 22 and g.iloc[0]["km"] > 0


def test_eleven_hour_hole_is_not_a_gap():
    t = track(sail(0, 10, 20, 130, 20, 131) + sail(20, 10, 20.5, 131.5, 21, 132))
    assert te.ais_gaps(t).empty


def test_status_rules():
    newest = T0 + pd.Timedelta(hours=100)
    moving = track(sail(0, 101, 20, 130, 21, 131))
    assert te.ship_status(moving, te.port_calls(moving, PORTS), set(), newest) == ("UNDERWAY", False)
    assert te.ship_status(moving, pd.DataFrame(), {"survey"}, newest) == ("SURVEYING", False)
    assert te.ship_status(moving, pd.DataFrame(), {"station"}, newest) == ("ON STATION", False)
    parked = track(stay(0, 100, 20.0, 140.0))
    assert te.ship_status(parked, pd.DataFrame(), set(), newest) == ("SLOW / STOPPED", False)
    in_port = track(stay(0, 100, 36.07, 120.32))
    assert te.ship_status(in_port, te.port_calls(in_port, PORTS), set(), newest)[0] == "IN PORT"
    old = track(sail(0, 10, 20, 130, 21, 131))
    assert te.ship_status(old, pd.DataFrame(), set(), newest + pd.Timedelta(days=4))[1] is True


def test_gaps_inside_port_dropped():
    rows = []
    for day in range(30):                       # a month alongside in Shanghai, AIS on for 6 h a day
        rows += stay(day * 24, 6, 31.23, 121.47)
    t = track(rows)
    assert len(te.ais_gaps(t)) > 0                         # without ports: the holes look like gaps
    assert te.ais_gaps(t, ports=PORTS).empty               # with ports: a port stay, not going dark


def test_gap_at_sea_kept_with_ports():
    t = track(sail(0, 10, 20, 130, 20, 131) + sail(30, 10, 20.5, 131.5, 21, 132))
    assert len(te.ais_gaps(t, ports=PORTS)) == 1
