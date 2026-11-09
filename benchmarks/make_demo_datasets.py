#!/usr/bin/env python3
"""
DEMO DATASETS: where the Line-Chain (baseline) and Sweep models differ
=====================================================================

Writes three synthetic datasets (fake ships, invented tracks) into
benchmarks/, each with a labels file (vessel, is_survey) for the app's
"Compare models" section:

  demo1_hourly_patrols.csv   hourly GFW-style data: one real survey, two patrols
  demo2_dense_short.csv      1-minute MarineTraffic-style data: short and long surveys
  demo3_curved_and_gaps.csv  curved contour-following survey, shuttle, station work

    python benchmarks/make_demo_datasets.py

Same seed, same files every time. Ships are fictional (MMSI 999xxxxxx).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KM_PER_NM = 1.852
START = pd.Timestamp("2026-06-01 00:00:00")
rng = np.random.default_rng(42)


def seed(n):
    """A fixed random stream per ship, so each ship's track never changes."""
    global rng
    rng = np.random.default_rng(n)


# ---------------------------------------------------------------------------
# geometry helpers: build a path in km around a centre, then sample it in time
# ---------------------------------------------------------------------------

def lawnmower(n_lines, length_km, spacing_km, axis_deg=90.0, turn_radius=None, start=(0.0, 0.0)):
    """Waypoints (x, y km) of a lawnmower with semicircular turns."""
    a = math.radians(axis_deg)
    u = np.array([math.sin(a), math.cos(a)])            # along the lines
    n = np.array([u[1], -u[0]])                          # across (to starboard of the first line)
    r = spacing_km / 2 if turn_radius is None else turn_radius
    pts, p = [], np.array(start, float)
    for i in range(n_lines):
        d = u if i % 2 == 0 else -u
        a0, a1 = p, p + d * length_km
        pts += [a0, a1]
        if i < n_lines - 1:                              # turn across by one spacing
            centre = a1 + n * spacing_km / 2
            for t in np.linspace(0, math.pi, 9)[1:-1]:
                pts.append(centre - n * (spacing_km / 2) * math.cos(t) + d * r * math.sin(t))
            p = a1 + n * spacing_km
    return np.array(pts)


def curved_lawnmower(n_lines, arc_deg, radius_km, spacing_km, centre=(0.0, 0.0)):
    """Concentric arcs (lines following a seamount's depth contours), alternating direction."""
    pts = []
    for i in range(n_lines):
        r = radius_km + i * spacing_km
        ts = np.radians(np.linspace(-arc_deg / 2, arc_deg / 2, 40))
        if i % 2:
            ts = ts[::-1]
        pts += [np.array(centre) + r * np.array([math.sin(t), math.cos(t)]) for t in ts]
    return np.array(pts)


def sample(waypoints, speed_kn, dt_min, t0=START, noise_km=0.0):
    """Positions every dt_min minutes moving along the waypoints at speed_kn."""
    seg = np.diff(waypoints, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0], np.cumsum(seg_len)])
    step = speed_kn * KM_PER_NM * dt_min / 60
    s = np.arange(0, cum[-1], step)
    x = np.interp(s, cum, waypoints[:, 0]) + rng.normal(0, noise_km, len(s))
    y = np.interp(s, cum, waypoints[:, 1]) + rng.normal(0, noise_km, len(s))
    t = [t0 + pd.Timedelta(minutes=dt_min * i) for i in range(len(s))]
    return x, y, t


def to_frame(x, y, t, lat0, lon0, mmsi, name, flag, speed_kn, snap=False):
    lat = lat0 + np.degrees(np.asarray(y) / 6371.0088)
    lon = lon0 + np.degrees(np.asarray(x) / (6371.0088 * math.cos(math.radians(lat0))))
    if snap:                                              # GFW-style ~1 km grid
        lat, lon = np.round(lat, 2), np.round(lon, 2)
    dx, dy = np.diff(x, append=x[-1]), np.diff(y, append=y[-1])
    course = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    spd = np.full(len(lat), float(speed_kn)) + rng.normal(0, 0.2, len(lat))
    return pd.DataFrame({"Timestamp": [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in t],
                         "Latitude": np.round(lat, 6), "Longitude": np.round(lon, 6),
                         "Speed": np.round(spd, 1), "Course": np.round(course, 1),
                         "MMSI": mmsi, "ShipName": name, "Flag": flag})


def transit(frm, to, speed_kn, dt_min):
    return sample(np.array([frm, to], float), speed_kn, dt_min)


def write(name, frames, labels):
    pd.concat(frames, ignore_index=True).to_csv(HERE / f"{name}.csv", index=False)
    pd.DataFrame(labels, columns=["vessel", "is_survey"]).to_csv(HERE / f"{name}_labels.csv", index=False)
    print(f"wrote benchmarks/{name}.csv and {name}_labels.csv")


# ---------------------------------------------------------------------------
# DEMO 1: hourly, ~1 km-snapped data (like Global Fishing Watch)
#   a real deep-sea survey and two patrols that only LOOK like lawnmowers
# ---------------------------------------------------------------------------

def demo1():
    frames = []
    seed(1)
    # 1a. nodule survey in the CCZ: 12 lines x 45 km, 5 km apart, 9 kn, hourly fixes
    wp = lawnmower(12, 45, 5.0, axis_deg=90)
    frames.append(to_frame(*sample(wp, 9, 60), 12.0, -135.0, 999000001, "DEMO DEEP MAPPER",
                           "China", 9, snap=True))
    # 1b. coast-guard style patrol: back and forth over one 30 km strip, drifting a
    #     random ~1 km sideways each time (so legs overlap and cross), for ~5 days
    seed(0)
    pts, y = [], 0.0
    for i in range(30):
        y = float(np.clip(y + rng.normal(0, 0.8), -2.5, 2.5))
        x0, x1 = (0, 30) if i % 2 == 0 else (30, 0)
        pts += [(x0 + rng.normal(0, 1.5), y), (x1 + rng.normal(0, 1.5), y + rng.normal(0, 0.5))]
    frames.append(to_frame(*sample(np.array(pts), 8, 60), 15.15, 117.75, 999000002,
                           "DEMO PATROL ONE", "China", 8, snap=True))
    # 1c. zig-zag patrol: 35 km legs, each starting where the last ended and turning
    #     back 16 degrees short of exactly opposite (V shapes), ~4 days
    seed(0)
    pts, p = [(0.0, 0.0)], np.array([0.0, 0.0])
    for i in range(24):
        heading = math.radians((82 if i % 2 == 0 else 278) + rng.normal(0, 3))
        p = p + 35 * np.array([math.sin(heading), math.cos(heading)])
        pts.append(tuple(p))
    frames.append(to_frame(*sample(np.array(pts), 8, 60), 16.8, 112.6, 999000003,
                           "DEMO PATROL TWO", "China", 8, snap=True))
    write("demo1_hourly_patrols", frames,
          [(999000001, 1), (999000002, 0), (999000003, 0)])


# ---------------------------------------------------------------------------
# DEMO 2: dense 1-minute data (like a MarineTraffic export)
#   a short survey box (a few hours) and a full survey
# ---------------------------------------------------------------------------

def demo2():
    frames = []
    seed(2)
    # 2a. short site survey: 4 lines x 12 km, 1 km apart, 6 kn: about 5 hours
    wp = lawnmower(4, 12, 1.0, axis_deg=0)
    x, y, t = sample(wp, 6, 1, noise_km=0.02)
    tx, ty, tt = transit((-40, -30), (0, 0), 11, 1)       # arrives from port
    frames.append(to_frame(np.r_[tx, x], np.r_[ty, y], tt + [tt[-1] + pd.Timedelta(minutes=1 + i)
                                                             for i in range(len(t))],
                           27.8, -91.0, 999000011, "DEMO SITE SURVEYOR", "United States", 6))
    # 2b. full survey: 9 lines x 25 km, 2 km apart, 5 kn: about 1.5 days
    wp = lawnmower(9, 25, 2.0, axis_deg=90)
    frames.append(to_frame(*sample(wp, 5, 1, noise_km=0.02), 11.5, -128.0, 999000012,
                           "DEMO NODULE SURVEYOR", "Germany", 5))
    # 2c. plain transit: never a survey
    frames.append(to_frame(*transit((0, 0), (300, 120), 13, 1), 20.0, -150.0, 999000013,
                           "DEMO CARGO RUNNER", "Panama", 13))
    write("demo2_dense_short", frames,
          [(999000011, 1), (999000012, 1), (999000013, 0)])


# ---------------------------------------------------------------------------
# DEMO 3: a curved survey with reporting gaps, a shuttle, and station work
# ---------------------------------------------------------------------------

def demo3():
    frames = []
    seed(0)
    # 3a. crust survey around a seamount: 9 concentric arcs (70 degrees of a 35-59 km
    #     radius, following the depth contours), 3 km apart, hourly fixes with some
    #     reports missing
    wp = curved_lawnmower(9, 70, 35, 3.0)
    x, y, t = sample(wp, 8, 60)
    keep = rng.random(len(x)) > 0.15                     # 15% of hourly reports lost
    frames.append(to_frame(x[keep], y[keep], list(np.array(t)[keep]), 18.5, 156.0, 999000021,
                           "DEMO SEAMOUNT MAPPER", "Japan", 8, snap=True))
    seed(3)
    # 3b. shuttle: runs the same 30 km line back and forth (supply run, ferry)
    pts = [(0, 0), (30, 0)] * 10
    frames.append(to_frame(*sample(np.array(pts, float), 10, 30, noise_km=0.15), 10.0, -140.0,
                           999000022, "DEMO SHUTTLE", "Marshall Islands", 10, snap=True))
    # 3c. station work (ROV dives / collector test): almost stationary for 4 days,
    #     with short slow moves between stations: a lawnmower detector cannot see it
    pts = []
    for k in range(8):
        cx, cy = k * 2.0, (k % 2) * 1.5
        pts += [(cx + rng.normal(0, 0.05), cy + rng.normal(0, 0.05)) for _ in range(10)]
    x, y, t = sample(np.array(pts), 0.6, 30)
    frames.append(to_frame(x, y, t, 13.5, -116.5, 999000023, "DEMO STATION KEEPER", "Belgium", 0.6))
    write("demo3_curved_and_gaps", frames,
          [(999000021, 1), (999000022, 0), (999000023, 0)])


if __name__ == "__main__":
    demo1()
    demo2()
    demo3()
