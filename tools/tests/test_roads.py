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
    b = _road(_line(200, 5, 0, 5), lanes=2)  # opposite direction, 5 m apart, 8 m wide each
    out = rn.merge_parallel([a, b], log=lambda *_: None)
    assert len(out) == 1
    kept = out[0]
    # The kept ribbon now spans both carriageways on its left side.
    assert kept["hl"][len(kept["hl"]) // 2] >= 5.0 + 4.0 - 1e-6
    assert np.allclose(kept["hr"], 4.0)


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
    # Quads are at most 4 m along and across.
    assert len(np.unique(rib["uv"][:, 1])) >= 3
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
