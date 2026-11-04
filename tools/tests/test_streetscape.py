"""Road visuals: one-way tags, lane layout codes, warp width scale, junction
fills, pavement bands, glb UV1 and parked-car rest pose."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline import roads as rn  # noqa: E402
from tools.pipeline import streetscape as ss  # noqa: E402
from tools.pipeline.build_world import oneway_direction, perpendicular_scale  # noqa: E402
from tools.pipeline.glbutil import read_hkgm_primitives, write_glb  # noqa: E402


def _line(x0, y0, x1, y1):
    return rn.resample(np.array([[x0, y0], [x1, y1]], dtype=float))


def _road(xy, highway="secondary", lanes=2, oneway=False, key_at=None):
    road = rn.make_road(xy, np.zeros(len(xy)), highway, lanes, "ground", 0, 1.0, oneway=oneway)
    if key_at is not None:
        road["keys"][key_at] = 7
    return road


def test_oneway_tags():
    assert oneway_direction({"oneway": "yes"}) == 1
    assert oneway_direction({"oneway": "true"}) == 1
    assert oneway_direction({"oneway": "1"}) == 1
    assert oneway_direction({"oneway": "-1"}) == -1
    assert oneway_direction({"oneway": "no"}) == 0
    assert oneway_direction({"junction": "roundabout"}) == 1
    assert oneway_direction({"highway": "motorway"}) == 1
    assert oneway_direction({"highway": "motorway", "oneway": "no"}) == 0
    assert oneway_direction({"highway": "residential"}) == 0


def test_perpendicular_scale_uses_the_axis_across_the_road():
    east_west = np.array([[0.0, 0.0], [100.0, 0.0]])
    north_south = np.array([[0.0, 0.0], [0.0, 100.0]])
    assert abs(perpendicular_scale(east_west, 0.3, 0.5) - 0.5) < 1e-9
    assert abs(perpendicular_scale(north_south, 0.3, 0.5) - 0.3) < 1e-9


def test_lane_layout_and_marking_code():
    two = _road(_line(0, 0, 100, 0), lanes=2)
    width, split, ll, lr = rn.lane_layout(two)
    assert np.allclose(split, two["hl"]) and ll[0] == 1 and lr[0] == 1
    one = _road(_line(0, 0, 100, 0), lanes=2, oneway=True)
    width, split, ll, lr = rn.lane_layout(one)
    assert np.allclose(split, width) and ll[0] == 2 and lr[0] == 0
    code = rn.marking_code(np.array([3.25]), np.array([2]), np.array([1]))[0]
    assert abs(code - (3.25 + 128 + 1024)) < 1e-9
    # The shader decode.
    assert int(code // 64) % 16 == 2 and int(code // 1024) == 1 and abs(code - 64 * (code // 64) - 3.25) < 1e-6
    # float32 keeps the split to better than 1 mm.
    c32 = float(np.float32(code))
    assert abs(c32 - 64 * (c32 // 64) - 3.25) < 1e-3


def _tee():
    # A runs west-east through the junction at (0, 0); B ends there from the north.
    a = _road(_line(-60, 0, 60, 0))
    mid = int(np.argmin(np.hypot(a["xy"][:, 0], a["xy"][:, 1])))
    a["xy"][mid] = (0.0, 0.0)
    a["keys"][mid] = 7
    b = _road(_line(0, 60, 0, 0))
    b["keys"][-1] = 7
    return [a, b]


def test_junction_detection_fade_and_fill():
    roads = _tee()
    junctions = ss.junction_nodes(roads)
    assert len(junctions) == 1
    stats = ss.apply_marking_fade(roads, junctions)
    assert stats["centreline_points_unmarked"] > 0
    near = np.hypot(*roads[0]["xy"].T) < junctions[0]["radius"]
    assert np.all(roads[0]["fade"][near] == 0) and np.all(roads[0]["fade"][~near] == 1)
    fills = ss.junction_fill_rings(roads, junctions)
    assert len(fills) == 1
    mesh = ss.junction_fill_mesh(fills, lambda x, y: np.zeros(np.shape(x)))
    v = mesh["verts"]
    assert np.allclose(v[:, 2], rn.ground_lift("secondary") - ss.FILL_BELOW_M)
    gl = np.column_stack([v[:, 0], v[:, 2], v[:, 1]])
    a, b, c = gl[mesh["tris"][:, 0]], gl[mesh["tris"][:, 1]], gl[mesh["tris"][:, 2]]
    assert np.all(np.cross(b - a, c - a)[:, 1] >= -1e-9)
    gap = ss.junction_gap_report(roads, fills)
    assert gap["gap_closed_m2"] > 0
    # A plain end-to-end join is not a junction.
    c1 = _road(_line(0, 0, 50, 0))
    c2 = _road(_line(50, 0, 100, 0))
    c1["keys"][-1] = 3
    c2["keys"][0] = 3
    assert ss.junction_nodes([c1, c2]) == []


def test_pavement_band_kerb_and_culling():
    roads = _tee()
    junctions = ss.junction_nodes(roads)
    fills = ss.junction_fill_rings(roads, junctions)
    discs = [(j["xy"], j["radius"] + ss.PAVEMENT_M) for j in junctions]
    flat = lambda x, y: np.full(np.shape(x), 2.0)  # noqa: E731
    blockers = ss.Blockers(ss.ribbon_outlines(roads) + [f["ring"] for f in fills], discs)
    mesh, stats = ss.pavement_bands(roads, blockers, flat)
    assert 0 < stats["kept"] < stats["segments"]
    z = mesh["verts"][:, 2]
    lift = rn.ground_lift("secondary")
    assert np.isclose(z.max(), 2.0 + lift + ss.KERB_M)
    assert np.all(mesh["color"][:, 1] == 1.0) and mesh["material"] == 4
    # Nothing of the band lies on a ribbon.
    import shapely

    polys = shapely.union_all([shapely.polygons(r) for r in ss.ribbon_outlines(roads)])
    tops = mesh["verts"][np.isclose(z, 2.0 + lift + ss.KERB_M)]
    inside = shapely.contains_xy(polys.buffer(-0.05), tops[:, 0], tops[:, 1])
    assert not inside.any()


def test_glb_uv1_roundtrip(tmp_path):
    prim = {
        "positions": np.random.rand(4, 3).astype(np.float32),
        "normals": np.tile([0, 1, 0], (4, 1)).astype(np.float32),
        "uvs": np.random.rand(4, 2).astype(np.float32),
        "uvs1": np.array([[6.0, 1155.25]] * 4, dtype=np.float32),
        "colors": np.ones((4, 4), dtype=np.float32),
        "indices": np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32),
        "material": 1,
    }
    plain = dict(prim, uvs1=None, material=0)
    write_glb(tmp_path / "t.glb", [prim, plain])
    out = read_hkgm_primitives(tmp_path / "t.glb")
    assert out[0]["flags"] == 3 and np.allclose(out[0]["uvs1"], prim["uvs1"])
    assert np.allclose(out[0]["colors"], 1.0) and np.allclose(out[0]["uvs"], prim["uvs"])
    assert out[1]["flags"] == 1 and out[1]["uvs1"] is None
