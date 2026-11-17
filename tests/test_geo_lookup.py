"""geo_lookup: EEZ, boundary distance, seabed depth and ship class at a point."""
import geo_lookup as g


def test_eez_japan():
    z = g.eez_at(25.0, 131.0)
    assert z is not None and "Japan" in z["sovereigns"]


def test_eez_high_seas():
    assert g.eez_at(10.0, -140.0) is None


def test_eez_dateline_both_sides():
    east, west = g.eez_at(-17.0, 179.9), g.eez_at(-17.0, -179.9)
    assert east is not None and west is not None
    assert "Fiji" in east["sovereigns"] and "Fiji" in west["sovereigns"]
    assert g.eez_at(-17.0, 180.1) == west          # longitudes beyond 180 wrap


def test_eez_type_reported():
    z = g.eez_at(25.0, 131.0)
    assert z["type"] in ("200NM", "Joint regime", "Overlapping claim")


def test_depth_ccz_deep():
    assert g.depth_m(12.0, -130.0) < -3500


def test_depth_chikyu_site():
    assert -6200 < g.depth_m(23.058, 154.209) < -5000


def test_depth_land():
    assert g.depth_m(39.9, 116.4) >= 0             # Beijing


def test_boundary_china_japan():
    km, name = g.nearest_boundary_km(28.0, 126.5)
    assert km < 150 and ("China" in name or "Japan" in name)


def test_boundary_far_from_any_neighbour():
    km, _ = g.nearest_boundary_km(-60.0, -120.0)      # Southern Ocean
    assert km > 1000


def test_vessel_class_listed():
    assert g.vessel_class("432522000", "Other (GFW)") == ("DRILLING", False)


def test_vessel_class_inferred():
    assert g.vessel_class("", "Drilling ship") == ("DRILLING", True)
    assert g.vessel_class("", "Research vessel") == ("RESEARCH", True)
    assert g.vessel_class("", "Coast guard") == ("GOV", True)
    assert g.vessel_class("", "Offshore oil & gas seismic vessel") == ("ENERGY", True)
    assert g.vessel_class("", "Cargo (GFW)") == ("UNK", True)


def test_seafloor_emperor_seamount():
    s = g.seafloor_at(43.388, 170.05)
    assert s["kind"] == "seamount" and s["crust_depth"] and s["rise_m"] >= 1000


def test_seafloor_abyssal_plain():
    assert g.seafloor_at(9.33, -156.62)["kind"] is None


def test_seafloor_southwest_indian_ridge():
    assert g.seafloor_at(-37.94, 49.26)["kind"] == "ridge"


def test_seafloor_island_is_not_a_seamount():
    assert g.seafloor_at(19.0, -155.5)["kind"] is None


def test_seafloor_shelf():
    assert g.seafloor_at(30.5, 122.5)["kind"] is None      # East China Sea shelf


def test_seafloor_dateline_and_pole_do_not_crash():
    for lat, lon in ((43.0, 179.95), (43.0, -179.95), (85.0, 10.0), (-81.0, 0.0)):
        assert isinstance(g.seafloor_at(lat, lon), dict)


def test_seafloor_dateline_sees_both_sides():
    east, west = g.seafloor_at(43.0, 179.99), g.seafloor_at(43.0, -179.99)
    assert abs(east["summit_m"] - west["summit_m"]) < 300


def test_seafloor_without_grid(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "DEPTH_FILE", tmp_path / "none.npz")
    g._depth.cache_clear()
    try:
        assert g.seafloor_at(43.388, 170.05) is None
    finally:
        g._depth.cache_clear()
