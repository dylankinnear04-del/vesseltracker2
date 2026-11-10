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
