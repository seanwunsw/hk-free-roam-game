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
