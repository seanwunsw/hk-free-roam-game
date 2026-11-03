"""Road network height solver tests: shared junctions, grade, overpass clearance,
short-bridge fade, edge cases, determinism. Synthetic, warp-free roads."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline import road_graph as rg  # noqa: E402
from tools.pipeline import roads as rn  # noqa: E402

J = 7  # junction node key used by the synthetic roads


def _flat(x, y):
    return np.zeros_like(np.asarray(x, dtype=float))


def _piece(points, keys, terrain_fn, mode="ground", layer=0, highway="primary"):
    out = rg.pinned_resample(np.asarray(points, dtype=float), np.asarray(keys, dtype=np.int64), rn.STEP_M)
    assert out is not None
    xy, k = out
    return rn.make_road(xy, terrain_fn(xy[:, 0], xy[:, 1]), highway, 2, mode, layer, 0.5, keys=k)


def _slope(x, y):
    return 0.30 * np.asarray(y, dtype=float) + 0.05 * np.asarray(x, dtype=float) + 20.0


def _t_junction(terrain_fn=_slope, reverse_branch=False):
    main = _piece([[-120, 0], [0, 0], [120, 0]], [-1, J, -1], terrain_fn)
    branch_pts = [[0, 0], [0, 120]]
    branch_keys = [J, -1]
    if reverse_branch:
        branch_pts, branch_keys = branch_pts[::-1], branch_keys[::-1]
    return [main, _piece(branch_pts, branch_keys, terrain_fn)]


def _design_at(road, key):
    return float(road["design"][np.flatnonzero(road["keys"] == key)[0]])


def test_pinned_resample_keeps_junction_exact():
    xy, k = rg.pinned_resample(np.array([[0, 0], [10.3, 0], [21.7, 0]]), np.array([-1, 5, -1]), 4.0)
    i = np.flatnonzero(k == 5)
    assert len(i) == 1 and np.allclose(xy[i[0]], [10.3, 0])
    assert np.all(np.hypot(*np.diff(xy, axis=0).T) <= 4.0 + 1e-9)


def test_t_junction_on_steep_slope_is_shared_and_graded():
    # Scenario 1: one height at the shared node, and every edge within the grade
    # limit up to the +-3 m corridor clamp.
    roads = _t_junction()
    stats = rg.solve_design_profiles(roads, log=lambda *_: None)
    a, b = (_design_at(r, J) for r in roads)
    assert abs(a - b) < 0.01
    spread = rg.junction_spread(roads)
    assert spread["junctions"] == 1 and spread["max_m"] < 0.01
    assert stats["max_grade_violation_m"] < 1e-6
    for r in roads:
        run = np.hypot(*np.diff(r["xy"], axis=0).T)
        assert np.all(np.abs(np.diff(r["design"])) <= rg.GRADE * run + 1e-6)


def test_reversed_digitisation_gives_same_profile():
    # Scenario 2: drawing the branch the other way must not change heights.
    fwd = _t_junction()
    rev = _t_junction(reverse_branch=True)
    rg.solve_design_profiles(fwd, log=lambda *_: None)
    rg.solve_design_profiles(rev, log=lambda *_: None)
    assert np.allclose(fwd[0]["design"], rev[0]["design"], atol=1e-6)
    assert np.allclose(fwd[1]["design"], rev[1]["design"][::-1], atol=1e-6)


def _bridge(x0, x1, layer=1):
    xy = rn.resample(np.array([[x0, 0.0], [x1, 0.0]]))
    return rn.make_road(xy, np.zeros(len(xy)), "primary", 2, "bridge", layer, 0.5)


def _deck_at(bridges, x):
    xs = np.concatenate([b["xy"][:, 0] for b in bridges])
    ds = np.concatenate([b["deck"] for b in bridges])
    order = np.argsort(xs)
    return float(np.interp(x, xs[order], ds[order]))


def _under(x):
    xy = rn.resample(np.array([[x, -60.0], [x, 60.0]]))
    return rn.make_road(xy, np.zeros(len(xy)), "primary", 2, "ground", 0, 0.5)


def test_viaduct_split_in_three_clears_unconnected_road():
    # Scenario 5: three bridge ways end to end, crossing a road 15 m from the ramp foot.
    bridges = [_bridge(-90, -30), _bridge(-30, 30), _bridge(30, 90)]
    lower = _under(-75.0)
    roads = bridges + [lower]
    rn.set_bridge_decks(roads, _flat, log=lambda *_: None)
    need = rn.ground_lift(lower["highway"]) + rn.OVERPASS_CLEARANCE_M
    assert _deck_at(bridges, -75.0) >= need - 1e-6
    # Split points carry one height and the mid span does not dip at them.
    assert abs(bridges[0]["deck"][-1] - bridges[1]["deck"][0]) < 1e-6
    assert abs(bridges[1]["deck"][-1] - bridges[2]["deck"][0]) < 1e-6
    assert min(_deck_at(bridges, x) for x in (-30.0, 30.0)) >= need


def test_overpass_on_flat_ground_gets_hard_floor():
    # Scenario 6: a long bridge crossing a road near its end, where the fade alone is too low.
    bridge = _bridge(-100, 100)
    lower = _under(-85.0)
    stats = rn.set_bridge_decks([bridge, lower], _flat, log=lambda *_: None)
    need = rn.ground_lift(lower["highway"]) + rn.OVERPASS_CLEARANCE_M
    assert _deck_at([bridge], -85.0) >= need - 1e-6
    assert stats["raised_over_crossings"] == 1
    # The floor ramps along the deck at the ramp grade, not as a step.
    run = np.hypot(*np.diff(bridge["xy"], axis=0).T)
    assert np.all(np.abs(np.diff(bridge["deck"])) <= max(rn.OVERPASS_RAMP_GRADE, 0.5) * run + 1e-6)


def test_short_bridge_reaches_full_clearance():
    # Fade = min(40 m, length / 3): a 30 m bridge is at full height in its middle.
    bridge = _bridge(-15, 15)
    rn.set_bridge_decks([bridge], _flat, log=lambda *_: None)
    clearance = max(6.0, 9.0 * bridge["height_scale"])
    mid = _deck_at([bridge], 0.0)
    assert mid >= rn.BRIDGE_LIFT_M + clearance - 0.05
    assert bridge["deck"][0] < rn.BRIDGE_LIFT_M + 0.5


def test_short_bridge_fade_takes_longest_neighbour_at_shared_end():
    long_way = _bridge(-160, 0)
    short_way = _bridge(0, 20)
    rn.set_bridge_decks([long_way, short_way], _flat, log=lambda *_: None)
    # At the shared node the fade length is the long way's 40 m, so both pieces agree there.
    assert abs(long_way["deck"][-1] - short_way["deck"][0]) < 1e-3


def test_edge_cases_do_not_crash():
    # Scenario 9: closed roundabout, repeated node, single point, zero length,
    # duplicates, one road, empty list.
    assert rg.solve_design_profiles([], log=lambda *_: None) == {}
    ang = np.linspace(0, 2 * np.pi, 13)
    ring_pts = np.column_stack([30 * np.cos(ang), 30 * np.sin(ang)])
    ring_keys = np.full(len(ring_pts), -1)
    ring_keys[0] = ring_keys[-1] = 11
    ring = _piece(ring_pts, ring_keys, _slope)
    repeat = _piece([[30, 0], [60, 0], [60, 0], [90, 0]], [11, 12, 12, -1], _slope)
    assert rg.pinned_resample(np.array([[1.0, 1.0]]), np.array([-1]), 4.0) is None
    assert rg.pinned_resample(np.array([[1.0, 1.0], [1.0, 1.0]]), np.array([3, 3]), 4.0) is None
    dup_a = _piece([[0, -50], [0, 50]], [-1, -1], _slope)
    dup_b = _piece([[0, -50], [0, 50]], [-1, -1], _slope)
    for roads in ([ring, repeat, dup_a, dup_b], [dup_a]):
        rg.solve_design_profiles(roads, log=lambda *_: None)
        for r in roads:
            assert len(r["design"]) == len(r["xy"]) >= 2
            assert np.all(np.isfinite(r["design"]))
    assert abs(ring["design"][0] - ring["design"][-1]) < 1e-9
    assert abs(_design_at(ring, 11) - _design_at(repeat, 11)) < 1e-9


def test_solver_is_deterministic():
    # Scenario 10: identical input, identical bytes out.
    a = _t_junction()
    b = _t_junction()
    rg.solve_design_profiles(a, log=lambda *_: None)
    rg.solve_design_profiles(b, log=lambda *_: None)
    for ra, rb in zip(a, b):
        assert ra["design"].tobytes() == rb["design"].tobytes()
    x = [_bridge(-90, -30), _bridge(-30, 30), _bridge(30, 90), _under(-75.0)]
    y = [_bridge(-90, -30), _bridge(-30, 30), _bridge(30, 90), _under(-75.0)]
    rn.set_bridge_decks(x, _flat, log=lambda *_: None)
    rn.set_bridge_decks(y, _flat, log=lambda *_: None)
    for ra, rb in zip(x[:3], y[:3]):
        assert ra["deck"].tobytes() == rb["deck"].tobytes()
