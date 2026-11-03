"""Road network shaping tests: parallel merge, carving, ribbons, UE sampling, spawns."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline import roads as rn  # noqa: E402
from tools.pipeline.check_roads import raster_triangles  # noqa: E402
from tools.pipeline.spawns import SurfaceIndex  # noqa: E402
from tools.pipeline.surface import quantize_r16, sample_ue  # noqa: E402


def _line(x0, y0, x1, y1):
    return rn.resample(np.array([[x0, y0], [x1, y1]], dtype=float))


def _road(xy, highway="primary", mode="ground", lanes=2, terrain=None, layer=0):
    t = np.zeros(len(xy)) if terrain is None else terrain
    return rn.make_road(xy, t, highway, lanes, mode, layer, 0.5)


def _landscape(n=64, spacing=8.0, origin=-256.0):
    return {"min_x": origin, "min_y": origin, "spacing_x": spacing, "spacing_y": spacing, "max_x": origin + spacing * (n - 1), "max_y": origin + spacing * (n - 1)}


def test_ue_sampling_uses_nw_se_diagonal():
    # Row 0 is south. Heights: SW=0, SE=0, NW=0, NE=4. On the NW-SE diagonal
    # split the SW triangle is flat, so its centre stays 0; a SW-NE split
    # would give 1.0 there.
    h = np.array([[0.0, 0.0], [0.0, 4.0]])
    z_sw = sample_ue(h, 0.0, 0.0, 1.0, 1.0, 0.25, 0.25)
    z_ne = sample_ue(h, 0.0, 0.0, 1.0, 1.0, 0.75, 0.75)
    assert abs(float(z_sw)) < 1e-9
    assert abs(float(z_ne) - 2.0) < 1e-9
    # Corners are exact.
    assert abs(float(sample_ue(h, 0.0, 0.0, 1.0, 1.0, 0.999999, 0.999999)) - 4.0) < 1e-4


def test_quantize_r16_matches_4cm_steps():
    q = quantize_r16(np.array([0.0, 0.019, 0.021, -2.03]))
    assert np.allclose(q, [0.0, 0.0, 0.04, -2.04])


def test_dual_carriageway_merges_into_one_wider_ribbon():
    a = _road(_line(0, 0, 200, 0), lanes=2)
    b = _road(_line(200, 5, 0, 5), lanes=2)  # opposite direction, 5 m apart, 2 x 3 m lanes each
    out = rn.merge_parallel([a, b], log=lambda *_: None)
    assert len(out) == 1
    kept = out[0]
    # The kept ribbon now spans both carriageways on its left side.
    half = a["base_half"]
    assert kept["hl"][len(kept["hl"]) // 2] >= 5.0 + half - 1e-6
    assert np.allclose(kept["hr"], half)
    # The absorbed lanes count toward the left block of the lane layout.
    width, split, lanes_l, lanes_r = rn.lane_layout(kept)
    mid = len(width) // 2
    assert lanes_l[mid] == 3 and lanes_r[mid] == 1


def test_crossing_road_is_not_merged():
    a = _road(_line(0, 0, 200, 0))
    b = _road(_line(100, -100, 100, 100), highway="secondary")
    out = rn.merge_parallel([a, b], log=lambda *_: None)
    assert len(out) == 2
    assert all(np.allclose(r["hl"], r["base_half"]) for r in out)


def test_partial_overlap_keeps_connected_remainder():
    a = _road(_line(0, 0, 200, 0))
    # Runs alongside A for 100 m, then turns away.
    xy = rn.resample(np.array([[0.0, 5.0], [100.0, 5.0], [100.0, 150.0]]))
    b = _road(xy, highway="secondary")
    out = rn.merge_parallel([a, b], log=lambda *_: None)
    assert len(out) == 2
    rest = [r for r in out if r["highway"] == "secondary"][0]
    # The remainder starts inside A's widened ribbon so the two still connect.
    assert rest["xy"][0, 1] < 6.0
    assert rest["xy"][-1, 1] > 140.0


def test_bridge_layers_do_not_merge():
    a = _road(_line(0, 0, 200, 0), mode="bridge", layer=1)
    b = _road(_line(0, 2, 200, 2), mode="bridge", layer=2)
    out = rn.merge_parallel([a, b], log=lambda *_: None)
    assert len(out) == 2


def test_carve_blends_junction_without_steps():
    land = _landscape()
    n = 64
    height = np.full((n, n), 5.0, dtype=np.float32)
    a = _road(_line(-200, 0, 200, 0))
    b = _road(_line(0, -200, 0, 200), highway="secondary")
    a["design"] = np.full(len(a["xy"]), 2.0)
    b["design"] = np.full(len(b["xy"]), 4.0)
    carved = rn.carve_terrain(height, [a, b], land, log=lambda *_: None)
    # Neighbouring nodes along A change smoothly (no nearest-seed flip of 2 m).
    row = carved[32]
    assert np.max(np.abs(np.diff(row[16:48]))) < 1.0
    # Far from both roads the terrain is untouched.
    assert abs(float(carved[2, 2]) - 5.0) < 1e-6
    # On A away from the junction the carve reaches the design height.
    assert abs(float(carved[32, 8]) - 2.0) < 0.05


def test_ribbon_sits_on_surface_and_faces_up():
    land = _landscape()
    yy, xx = np.mgrid[0:64, 0:64]
    height = quantize_r16(0.05 * xx + 0.02 * yy)

    def surface(x, y):
        return sample_ue(height, land["min_x"], land["min_y"], 8.0, 8.0, x, y)

    road = _road(_line(-100, 3, 100, 40))
    rib = rn.build_ribbon(road, surface)
    lift = rn.ground_lift("primary")
    v = rib["verts"]
    assert np.allclose(v[:, 2] - surface(v[:, 0], v[:, 1]), lift)
    # Narrow ribbons are one quad across; uv.y is metres from the left edge.
    assert np.allclose(np.unique(rib["uv"][:, 1]), [0.0, road["hl"][0] + road["hr"][0]])
    assert rib["uv1"].shape == (len(v), 2) and rib["material"] == 1
    gl = np.column_stack([v[:, 0], v[:, 2], v[:, 1]])
    a, b, c = gl[rib["tris"][:, 0]], gl[rib["tris"][:, 1]], gl[rib["tris"][:, 2]]
    assert np.all(np.cross(b - a, c - a)[:, 1] > 0)


def test_bridge_deck_stays_up_between_split_ways():
    flat = lambda x, y: np.zeros(np.shape(x))  # noqa: E731
    a = _road(_line(0, 0, 200, 0), mode="bridge", layer=1)
    b = _road(_line(200, 0, 400, 0), mode="bridge", layer=1)
    rn.set_bridge_decks([a, b], flat)
    # The shared middle end is not a ground end, so the deck stays high there.
    assert a["deck"][-1] > 5.0 and b["deck"][0] > 5.0
    # The outer ends ramp down to the ground.
    assert a["deck"][0] < 0.5 and b["deck"][-1] < 0.5


def test_raster_triangles_covers_area():
    xy = np.array([[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]], [[0.0, 0.0], [10.0, 10.0], [0.0, 10.0]]])
    z = np.ones((2, 3))
    ix, iy, zz, tri = raster_triangles(xy, z, 0.5)
    cells = set(zip(ix.tolist(), iy.tolist()))
    assert len(cells) == 400
    assert np.allclose(zz, 1.0)


def test_spawn_index_sees_overhead_deck():
    flat = lambda x, y: np.zeros(np.shape(x))  # noqa: E731
    ground = rn.build_ribbon(_road(_line(-50, 0, 50, 0)), flat)
    deck = {"verts": ground["verts"] + np.array([0.0, 0.0, 3.0]), "tris": ground["tris"], "uv": ground["uv"], "alpha": 0.5}
    index = SurfaceIndex([ground, deck], [], flat)
    z, on_road = index.top_surface(0.0, 0.0, near_z=0.2)
    assert on_road and abs(z - rn.ground_lift("primary")) < 1e-6
    assert not index.clear(np.array([[0.0, 0.0]]), z)
    assert index.clear(np.array([[0.0, 0.0]]), 3.1)


def test_car_spawns_in_left_lane_with_player_beside_it():
    from tools.pipeline.spawns import build_spawns, nearby_centerlines, spawn_lane_report

    flat = lambda x, y: np.zeros(np.shape(x))  # noqa: E731
    road = _road(_line(-80, 0, 80, 0))
    road["center"] = np.column_stack([road["xy"], np.full(len(road["xy"]), rn.ground_lift("primary"))])
    index = SurfaceIndex([rn.build_ribbon(road, flat)], [], flat)

    class Warp:
        def lonlat_to_game_m(self, lon, lat):
            return lon, lat

    config = {"places": [{"id": "A", "lon": 0.0, "lat": 0.0, "player_start": True, "cars": 1}]}
    spawns, _, _ = build_spawns(config, Warp(), [road], index, lambda x, y: (x, y, 0.0), log=lambda *_: None)
    car = spawns["cars"][0]
    hl = float(road["hl"][0])
    # Drawn west to east: the left lane is north of the centreline, heading east.
    assert abs(car["yaw_deg"]) < 1e-6
    assert car["y_m"] > 0.5 and car["y_m"] + 1.0 <= hl + 1e-6
    player = spawns["player"]
    assert abs(np.hypot(player["x_m"] - car["x_m"], player["y_m"] - car["y_m"]) - 3.0) < 1e-6
    report = spawn_lane_report(spawns, nearby_centerlines([road], spawns))
    assert report["body_off_ribbon"] == 0 and report["max_heading_err_deg"] < 1e-6
    assert abs(report["max_centerline_m"] - car["y_m"]) < 1e-6
    assert abs(report["player_to_first_car_m"] - 3.0) < 1e-6


def test_car_spawn_avoids_junction_box():
    from tools.pipeline.spawns import JUNCTION_CLEAR_M, build_spawns

    flat = lambda x, y: np.zeros(np.shape(x))  # noqa: E731
    main = _road(_line(-80, 0, 80, 0))
    side = _road(_line(0, 0, 0, 80))
    for r in (main, side):
        r["center"] = np.column_stack([r["xy"], np.full(len(r["xy"]), rn.ground_lift("primary"))])
    index = SurfaceIndex([rn.build_ribbon(main, flat), rn.build_ribbon(side, flat)], [], flat)

    class Warp:
        def lonlat_to_game_m(self, lon, lat):
            return lon, lat

    config = {"places": [{"id": "A", "lon": 0.0, "lat": 1.0, "player_start": True, "cars": 1}]}
    spawns, _, _ = build_spawns(config, Warp(), [main, side], index, lambda x, y: (x, y, 0.0), log=lambda *_: None)
    car = spawns["cars"][0]
    # Not inside the crossing: clear of the other road's ribbon by the junction margin.
    if abs(car["yaw_deg"]) < 45 or abs(abs(car["yaw_deg"]) - 180) < 45:
        assert abs(car["x_m"]) >= float(side["hl"][0]) + JUNCTION_CLEAR_M - 4.0
    else:
        assert car["y_m"] >= float(main["hl"][0]) + JUNCTION_CLEAR_M - 4.0


def test_merge_parallel_never_absorbs_into_a_dropped_piece():
    # A 5 m primary stub is too short to emit a ribbon. The secondary running
    # under it must keep its own ribbon there instead of vanishing.
    stub = _road(np.array([[0.0, 0.0], [5.0, 0.0]]), highway="primary")
    long_way = _road(_line(-60, 0.5, 60, 0.5), highway="secondary")
    out = rn.merge_parallel([stub, long_way], log=lambda *_: None)
    spans = sorted((float(r["xy"][:, 0].min()), float(r["xy"][:, 0].max())) for r in out if r["highway"] == "secondary")
    reach = spans[0][1]
    for lo, hi in spans[1:]:
        assert lo <= reach + 1e-6, (lo, reach)
        reach = max(reach, hi)
    assert spans[0][0] <= -60 + 1e-6 and reach >= 60 - 1e-6
