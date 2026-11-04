"""Buildings must not cover drivable road after the warp, the lane-width floor
and footprint simplification, and must not poke through bridge decks."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline import build_world as bw  # noqa: E402
from tools.pipeline import roads as rn  # noqa: E402


def _log(_message: str) -> None:
    pass


def _road(x0, y0, x1, y1, mode="ground", deck=0.0):
    xy = rn.resample(np.array([[x0, y0], [x1, y1]], dtype=float))
    road = rn.make_road(xy, np.zeros(len(xy)), "primary", 4, mode, 1 if mode == "bridge" else 0, 1.0)
    road["center"] = np.column_stack([xy, np.full(len(xy), deck)])
    return road


def _building(ring, z=0.0, height=20.0, elevated=False):
    ring = np.asarray(ring, dtype=float)
    return {
        "ring": ring, "kind": "roof" if elevated else "yes", "elevated": elevated,
        "z": z, "height": height, "area": abs(bw.signed_area(ring)),
        "cx": float(ring[:, 0].mean()), "cy": float(ring[:, 1].mean()), "horizontal": 0.4, "color": (1, 1, 1),
    }


# A run13 Tuen Mun footprint and the padded ribbon that cuts an L-shaped bite out of it
# (game metres, recentred). The cut ring has 28 vertices; keeping every k-th vertex to
# reach 14 put 49 m2 of the building back on the road.
RUN13_RING = [[-24.61, -16.32], [-18.48, -25.36], [-8.63, -30.3], [20.93, 2.02], [23.26, 10.44], [21.32, 16.5],
              [14.56, 21.54], [8.16, 21.7], [4.24, 19.98], [-20.47, -6.99], [-20.27, -13.21]]
RUN13_CUTTER = [[-1.72, -24.34], [-5.12, -23.01], [-8.53, -21.68], [-11.93, -20.34], [-16.46, -18.56], [-18.5, -14.07],
                [-18.49, -9.77], [-18.49, -6.11], [-12.49, -6.12], [-12.49, -9.78], [-12.5, -12.78], [-12.01, -13.87],
                [-9.74, -14.76], [-6.34, -16.09], [-2.93, -17.42], [0.47, -18.76]]


def test_run13_cut_stays_off_the_cutter():
    import shapely

    cutter = shapely.Polygon(RUN13_CUTTER)
    cut = bw.cut_buildings([_building(RUN13_RING)], [cutter], shapely.STRtree([cutter]), _log)
    assert len(cut) == 1
    assert shapely.intersection(shapely.Polygon(cut[0]["ring"]), cutter).area < 0.5


def test_building_poking_through_a_bridge_deck_is_cut():
    bridge = _road(-60.0, 0.0, 60.0, 0.0, mode="bridge", deck=10.0)
    square = [[-8, -8], [8, -8], [8, 8], [-8, 8]]
    tall = _building(square, z=0.0, height=15.0)
    low = _building(square, z=0.0, height=6.0)
    before = bw.building_road_overlap([tall], [bridge])
    assert before["bridge"]["buildings"] == 1
    out = bw.clip_under_bridges([tall, low], [bridge], _log)
    assert bw.building_road_overlap(out, [bridge])["buildings"] == 0
    # The low one fits under the deck and is untouched.
    assert any(np.array_equal(b["ring"], low["ring"]) for b in out)


def test_elevated_roof_over_a_bridge_is_removed():
    bridge = _road(-60.0, 0.0, 60.0, 0.0, mode="bridge", deck=10.0)
    canopy = _building([[-30, -5], [30, -5], [30, 5], [-30, 5]], z=0.0, height=4.0, elevated=True)
    assert bw.clip_under_bridges([canopy], [bridge], _log) == []


def test_noise_enclosure_roof_over_motorway_leaves_no_median_wall():
    # Tuen Mun Road at 22.3800 N 113.9835 E: r14438730 (building=roof, building:min_level=2,
    # roof=noise_barrier) spans one carriageway plus the 0.8 m median. Cutting the padded
    # ribbon out left a 0.7 x 8 m strip that was extruded 4 m from the ground on the median.
    import shapely

    roof = [[-40, -6], [40, -6], [40, 1.2], [-40, 1.2]]
    cutter = shapely.Polygon([[-60, -4.5], [60, -4.5], [60, 0.4], [-60, 0.4]])
    out = bw.cut_buildings([_building(roof, height=4.0, elevated=True)], [cutter], shapely.STRtree([cutter]), _log)
    assert out == []


def test_cut_remnant_thinner_than_sliver_limit_is_dropped():
    import shapely

    block = [[-10, 0], [10, 0], [10, 11.5], [-10, 11.5]]
    cutter = shapely.Polygon([[-30, -5], [30, -5], [30, 10], [-30, 10]])
    out = bw.cut_buildings([_building(block)], [cutter], shapely.STRtree([cutter]), _log)
    assert out == []
    wide = [[-10, 0], [10, 0], [10, 16], [-10, 16]]
    out = bw.cut_buildings([_building(wide)], [cutter], shapely.STRtree([cutter]), _log)
    assert len(out) == 1


def test_road_ending_inside_a_footprint_does_not_fill_back_in():
    """Stage IGC: a covered road running into a block leaves a hole that extruding the
    exterior ring would cover again. The cut must open the building over it."""
    import shapely

    road = _road(-5.0, 0.0, 60.0, 0.0)
    block = _building([[-40, -30], [40, -30], [40, 30], [-40, 30]])
    cutters = [shapely.make_valid(shapely.polygons(r)) for r in rn.edge_polygons([road], bw.CUT_PAD_M)]
    out = bw.cut_buildings([block], cutters, shapely.STRtree(cutters), _log)
    assert out
    assert bw.building_road_overlap(out, [road])["carriageway"]["buildings"] == 0
    # Both arms beside the passage survive as separate buildings.
    assert sum(b["area"] for b in out) > 0.8 * 80 * 60 - 65 * 20


def test_road_through_a_courtyard_is_cleared():
    import shapely

    road = _road(-10.0, 0.0, 10.0, 0.0)
    block = _building([[-30, -30], [30, -30], [30, 30], [-30, 30]])
    cutters = [shapely.make_valid(shapely.polygons(r)) for r in rn.edge_polygons([road], bw.CUT_PAD_M)]
    out = bw.cut_buildings([block], cutters, shapely.STRtree(cutters), _log)
    assert bw.building_road_overlap(out, [road])["ground"]["buildings"] == 0
    for b in out:
        assert shapely.Polygon(b["ring"]).is_valid


def test_overlap_checks_fail_on_carriageway_and_warn_on_service():
    clean = {"carriageway": {"buildings": 0}, "bridge": {"buildings": 0}, "service": {"area_m2": 100.0, "max_m2": 50.0}, "thin_beside_road": 3}
    ok, warnings = bw.overlap_checks(clean, {})
    assert ok and not warnings
    ok, _ = bw.overlap_checks(dict(clean, carriageway={"buildings": 1}), {})
    assert not ok
    ok, warnings = bw.overlap_checks(dict(clean, service={"area_m2": 3000.0, "max_m2": 800.0}, thin_beside_road=60), {})
    assert ok and len(warnings) == 3


def test_service_road_counts_apart_from_carriageway():
    xy = rn.resample(np.array([[-30.0, 0.0], [30.0, 0.0]]))
    lane = rn.make_road(xy, np.zeros(len(xy)), "service", 1, "ground", 0, 1.0)
    lane["center"] = np.column_stack([xy, np.zeros(len(xy))])
    podium = _building([[-10, -10], [10, -10], [10, 10], [-10, 10]])
    result = bw.building_road_overlap([podium], [lane])
    assert result["carriageway"]["buildings"] == 0
    assert result["service"]["buildings"] == 1


def test_tight_bend_cutter_covers_the_inside_of_the_bend():
    """A hairpin tighter than the half width loops the outline ring; the cutter must still
    cover the whole swept ribbon."""
    import shapely

    xy = rn.resample(np.array([[-40.0, 0.0], [0.0, 0.0], [4.0, 3.0], [0.0, 6.0], [-40.0, 6.0]]))
    road = rn.make_road(xy, np.zeros(len(xy)), "residential", 2, "ground", 0, 1.0)
    road["center"] = np.column_stack([xy, np.zeros(len(xy))])
    house = _building([[-6, 1], [0, 1], [0, 5], [-6, 5]])
    buffers, tree = bw._road_buffers([road], _log)
    out = bw.cut_buildings([house], buffers, tree, _log)
    assert bw.building_road_overlap(out, [road])["carriageway"]["buildings"] == 0
