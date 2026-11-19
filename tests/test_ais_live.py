"""ais_live.py: near-shore positions from aisstream.io, recorded every 2 hours and merged daily after GFW's last date."""
import asyncio
import json

import pandas as pd
import pytest

import ais_live

MMSI = "412018330"


def msg(kind="PositionReport", lat=22.5, lon=114.1, sog=4.2, cog=90.0, mmsi=MMSI,
        time_utc="2026-11-19 10:15:30.123456789 +0000 UTC"):
    meta = {"MMSI": int(mmsi), "ShipName": "XUE LONG  ", "latitude": lat, "longitude": lon}
    if time_utc:
        meta["time_utc"] = time_utc
    return {"MessageType": kind, "MetaData": meta, "Message": {kind: {"Sog": sog, "Cog": cog, "Latitude": lat, "Longitude": lon}}}


def test_subscription():
    sub = ais_live.subscription("KEY", [MMSI, "123456789"])
    assert sub["APIKey"] == "KEY" and sub["BoundingBoxes"] == [[[-90, -180], [90, 180]]]
    assert sub["FiltersShipMMSI"] == [MMSI, "123456789"]
    assert "PositionReport" in sub["FilterMessageTypes"] and "StandardClassBPositionReport" in sub["FilterMessageTypes"]


def test_subscription_caps_at_200_ships():
    assert len(ais_live.subscription("K", [f"{100000000 + i}" for i in range(250)])["FiltersShipMMSI"]) == 200


def test_parse_position_report():
    p = ais_live.parse(msg(), {MMSI})
    assert p["mmsi"] == MMSI and p["lat"] == 22.5 and p["lon"] == 114.1 and p["speed"] == 4.2 and p["course"] == 90.0
    assert p["time"] == pd.Timestamp("2026-11-19 10:15:30", tz="UTC") and p["name"] == "XUE LONG"


def test_parse_class_b():
    assert ais_live.parse(msg(kind="StandardClassBPositionReport"), {MMSI})["lat"] == 22.5


def test_parse_rejects_unavailable_position_and_other_ships():
    assert ais_live.parse(msg(lat=91.0), {MMSI}) is None              # AIS "not available"
    assert ais_live.parse(msg(lon=181.0), {MMSI}) is None
    assert ais_live.parse(msg(mmsi="999999999"), {MMSI}) is None
    assert ais_live.parse({"MessageType": "Error", "error": "bad key"}, {MMSI}) is None


def test_parse_without_time_uses_receive_time():
    now = pd.Timestamp("2026-11-19 12:00", tz="UTC")
    assert ais_live.parse(msg(time_utc=None), {MMSI}, received=now)["time"] == now


def test_speed_not_available_is_blank():
    assert pd.isna(ais_live.parse(msg(sog=102.3), {MMSI})["speed"])


def test_hourly_keeps_latest_per_ship_hour():
    t = pd.Timestamp("2026-11-19 10:05", tz="UTC")
    rows = [dict(ais_live.parse(msg(), {MMSI}), time=t + pd.Timedelta(minutes=m), lat=10 + m) for m in (0, 20, 50, 70)]
    h = ais_live.hourly(rows)
    assert list(h["lat"]) == [60.0, 80.0]                 # 10:55 for hour 10, 11:15 for hour 11


def test_record_with_a_fake_stream():
    sent = []

    class Fake:
        def __init__(self, msgs): self.msgs = list(msgs)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, text): sent.append(json.loads(text))
        def __aiter__(self): return self
        async def __anext__(self):
            if not self.msgs:
                raise StopAsyncIteration
            return json.dumps(self.msgs.pop(0)).encode()

    rows = asyncio.run(ais_live.record("KEY", [MMSI], seconds=1, connect=lambda url: Fake([msg(), msg(mmsi="999999999")])))
    assert sent and sent[0]["APIKey"] == "KEY" and len(rows) == 1 and rows[0]["mmsi"] == MMSI


# ---------- buffer and daily merge ---------------------------------------------------------------------------------

def _lib(tmp_path, track_file="gfw_412018330.csv", gfw_until="2026-10-29 23:30:00"):
    lib = tmp_path / "library"
    (lib / "tracks").mkdir(parents=True)
    pd.DataFrame([{"name": "Xue Long", "flag": "China", "mmsi": MMSI, "track_file": track_file}]).to_csv(lib / "vessels.csv", index=False)
    if track_file.startswith("gfw_"):
        pd.DataFrame({"Timestamp": ["2026-10-29 22:30:00", gfw_until], "Latitude": [20.0, 20.1], "Longitude": [110.0, 110.1],
                      "Speed": [10.0, 9.0], "MMSI": [MMSI, MMSI]}).to_csv(lib / "tracks" / track_file, index=False)
    return lib


def _pos(ts, lat=22.0):
    return {"mmsi": MMSI, "time": pd.Timestamp(ts, tz="UTC"), "lat": lat, "lon": 114.0, "speed": 1.0, "course": 0.0, "name": "XUE LONG"}


def test_buffer_append_and_read(tmp_path):
    buf = tmp_path / "positions.csv.gz"
    ais_live.append_buffer(buf, [_pos("2026-11-19 10:10")])
    ais_live.append_buffer(buf, [_pos("2026-11-19 10:10"), _pos("2026-11-19 12:10")])
    got = ais_live.read_buffer(buf)
    assert len(got) == 2 and set(got["mmsi"]) == {MMSI}


def test_merge_appends_only_after_gfw(tmp_path):
    lib = _lib(tmp_path)
    buf = tmp_path / "positions.csv.gz"
    ais_live.append_buffer(buf, [_pos("2026-10-29 20:10"), _pos("2026-11-19 10:10"), _pos("2026-11-19 12:10")])
    n = ais_live.merge_into_library(buf, lib)
    tr = pd.read_csv(lib / "tracks" / "gfw_412018330.csv", dtype=str)
    assert n == {"ships": 1, "positions": 2}
    assert list(tr["Source"].fillna("")) == ["", "", "aisstream", "aisstream"]
    assert not buf.exists()                                    # buffer cleared once merged


def test_merge_creates_a_track_for_a_ship_without_one(tmp_path):
    lib = _lib(tmp_path, track_file="")
    buf = tmp_path / "positions.csv.gz"
    ais_live.append_buffer(buf, [_pos("2026-11-19 10:10")])
    ais_live.merge_into_library(buf, lib)
    assert pd.read_csv(lib / "vessels.csv", dtype=str).fillna("")["track_file"][0] == "gfw_412018330.csv"
    assert (lib / "tracks" / "gfw_412018330.csv").exists()


def test_merge_leaves_hand_made_tracks_alone(tmp_path):
    lib = _lib(tmp_path, track_file="arctic_survey_2026-08.csv")
    buf = tmp_path / "positions.csv.gz"
    ais_live.append_buffer(buf, [_pos("2026-11-19 10:10")])
    assert ais_live.merge_into_library(buf, lib) == {"ships": 0, "positions": 0}
    assert not (lib / "tracks" / "gfw_412018330.csv").exists()


def test_prefer_gfw_drops_aisstream_where_gfw_has_data():
    tr = pd.DataFrame({"Timestamp": ["2026-11-01 10:10:00", "2026-11-02 10:30:00", "2026-11-03 09:00:00"],
                       "Source": ["aisstream", "", "aisstream"]})
    assert list(ais_live.prefer_gfw(tr)["Timestamp"]) == ["2026-11-02 10:30:00", "2026-11-03 09:00:00"]


def test_gfw_save_replaces_aisstream_it_covers(tmp_path, monkeypatch):
    import gfw_fetch
    lib = _lib(tmp_path)
    buf = tmp_path / "positions.csv.gz"
    ais_live.append_buffer(buf, [_pos("2026-11-05 10:10"), _pos("2026-11-19 10:10")])
    ais_live.merge_into_library(buf, lib)
    monkeypatch.setattr(gfw_fetch, "LIBRARY", lib)
    gfw = pd.DataFrame({"mmsi": [MMSI], "date": ["2026-11-10 00:00:00"], "lat": [21.0], "lon": [111.0], "speed": [5.0],
                        "shipName": ["XUE LONG"], "flag": ["CHN"]})
    gfw_fetch.save(gfw)
    tr = pd.read_csv(lib / "tracks" / "gfw_412018330.csv", dtype=str).fillna("")
    assert "2026-11-05 10:10:00" not in set(tr["Timestamp"])           # GFW now covers that day
    assert "2026-11-19 10:10:00" in set(tr["Timestamp"])               # after GFW's newest: kept


def test_main_without_key_exits_quietly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    monkeypatch.setattr(ais_live, "STATUS_FILE", tmp_path / "ais_status.json")
    assert ais_live.main(["--seconds", "1"]) == 0
    assert "AISSTREAM_API_KEY" in capsys.readouterr().out


def test_followed_mmsis(tmp_path):
    lib = _lib(tmp_path)
    assert ais_live.followed_mmsis(lib) == [MMSI]
