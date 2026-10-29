"""Land/sea mask from OSM coastline direction, and its agreement with the terrain."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

shapely = pytest.importorskip("shapely")

from tools.pipeline import coast  # noqa: E402
from tools.pipeline.check_coast import agreement  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


def _square():
    return shapely.box(0.0, 0.0, 10.0, 10.0)


def test_open_coastline_crossing_extract_is_land_on_the_left():
    # Runs east across the extract and beyond it, like a Geofabrik clipped way.
    shore = np.array([[-1.0, 5.0], [4.0, 5.2], [11.0, 5.0]])
    island = np.array([[2.0, 1.0], [3.0, 1.0], [3.0, 2.0], [2.0, 2.0], [2.0, 1.0]])  # CCW = land inside
    land, stats = coast.build_land([shore, island], _square())
    assert stats["unlabelled_faces"] == 0
    assert land.contains(shapely.Point(5.0, 8.0))
    assert not land.contains(shapely.Point(5.0, 3.0))
    assert land.contains(shapely.Point(2.5, 1.5))
    north = 100.0 - (0.5 * (5.04 + 5.2) * 4.0 + 0.5 * (5.2 + 5.2 - 6.0 * 0.2 / 7.0) * 6.0)  # above the bent shore
    assert land.area == pytest.approx(north + 1.0, abs=0.01)


def test_reversed_coastline_flips_land_and_sea():
    shore = np.array([[11.0, 5.0], [4.0, 5.2], [-1.0, 5.0]])
    land, _ = coast.build_land([shore], _square())
    assert land.contains(shapely.Point(5.0, 3.0))
    assert not land.contains(shapely.Point(5.0, 8.0))


def test_dem_decides_outside_extract():
    shore = np.array([[-1.0, 5.0], [11.0, 5.0]])
    land, _ = coast.build_land([shore], _square())
    lon = np.array([5.0, 5.0, 20.0, 20.0])
    lat = np.array([8.0, 3.0, 8.0, 3.0])
    dem = np.array([-5.0, 50.0, 30.0, 0.0])  # contradicts OSM inside the extract on purpose
    out = coast.land_at(land, _square(), lon, lat, dem_elev=dem)
    assert out.tolist() == [True, False, True, False]


def test_agreement_counts_both_directions():
    is_land = np.array([[True, True, False, False]])
    height = np.array([[5.0, -1.0, -3.0, 0.5]])
    out = agreement(height, is_land)
    assert out["land_above_0_pct"] == 50.0
    assert out["sea_below_0_pct"] == 50.0
    assert out["sea_below_seabed_pct"] == 50.0


@pytest.mark.skipif(not (PROCESSED / "land_mask.json").exists(), reason="pipeline not run")
def test_processed_terrain_follows_osm_coast_and_harbour_stays_wide():
    report = json.loads((PROCESSED / "logs" / "report.json").read_text(encoding="utf-8"))
    coast_report = report["coast"]
    assert coast_report["sea_below_seabed_pct"] >= 99.0
    assert coast_report["land_above_0_pct"] >= 99.0
    assert not coast_report["spawns_over_sea"]
    mask = coast.LandMask(PROCESSED)
    # Central, TST, Hung Hom are land; the harbour off Hung Hom/Causeway Bay (the old SRTM land bridge) is sea.
    assert mask.is_land(114.158, 22.282) and mask.is_land(114.171, 22.297) and mask.is_land(114.188, 22.303)
    assert not mask.is_land(114.190, 22.291) and not mask.is_land(114.168, 22.288)
    config = json.loads((ROOT / "data" / "config" / "world.json").read_text(encoding="utf-8"))
    assert coast_report["harbour_clearance"]["min_m"] >= config["min_harbour_width_m"]


def test_roads_over_open_sea_become_fixed_decks():
    from tools.pipeline.roads import deck_over_sea

    xs = np.linspace(0.0, 400.0, 41)
    road = {
        "mode": "tunnel",
        "layer": 0,
        "highway": "primary",
        "width": 10.0,
        "xy": np.column_stack([xs, np.zeros_like(xs)]),
        "terrain": np.zeros_like(xs),
        "design": np.full_like(xs, 2.0),
    }
    out = deck_over_sea([road], lambda x, y: (np.asarray(x) > 100) & (np.asarray(x) < 300), log=lambda *_: None)
    decks = [r for r in out if r["mode"] == "bridge"]
    assert len(decks) == 1
    assert decks[0]["xy"][0, 0] < 110 and decks[0]["xy"][-1, 0] > 290
    assert np.all(decks[0]["deck_fixed"] >= 2.0)
    assert {r["mode"] for r in out} == {"tunnel", "bridge"}
