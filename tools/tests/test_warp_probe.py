"""Warp-effect probes: lane floor, bridge-end steps, Tuen Mun Road gap. No OSM."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline.warp_probe import bridge_end_steps, height_gap, lane_widths  # noqa: E402


class _IdentityWarp:
    def lonlat_to_game_m(self, lon, lat):
        return lon, lat


def _piece(xy, z, mode="ground", name_en="", name_zh="", end_dist=None, highway="primary", half=4.0):
    xy = np.asarray(xy, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    n = len(xy)
    road = {
        "xy": xy,
        "center": np.column_stack([xy, z]),
        "hl": np.full(n, half),
        "hr": np.full(n, half),
        "lanes": 2,
        "own_l": 1,
        "own_r": 1,
        "base_half": half,
        "highway": highway,
        "mode": mode,
        "name_en": name_en,
        "name_zh": name_zh,
    }
    if end_dist is not None:
        road["end_dist"] = np.asarray(end_dist, dtype=np.float64)
    return road


def test_lane_width_uses_the_merged_ribbon():
    road = _piece([[0.0, 0.0], [20.0, 0.0]], [1.0, 1.0], half=1.5)
    stats = lane_widths([road])
    # Two lanes across a 3 m ribbon: 1.5 m each, which is the narrowest piece.
    assert stats["narrowest_lane_m"] == 1.5
    assert stats["narrowest_ribbon_m"] == 3.0
    assert stats["floor_m"] == 3.0


def test_bridge_end_step_counts_only_ground_terminals():
    ground = _piece([[0.0, 0.0], [10.0, 0.0]], [4.0, 4.0])
    # Foot at x=0 is 2 m above the ground road. The far end is mid-viaduct.
    bridge = _piece(
        [[0.0, 0.5], [30.0, 0.5]],
        [6.0, 12.0],
        mode="bridge",
        end_dist=[0.0, 80.0],
    )
    # A smooth foot must not count.
    smooth = _piece(
        [[100.0, 0.0], [130.0, 0.0]],
        [4.1, 9.0],
        mode="bridge",
        end_dist=[0.0, 40.0],
    )
    ground_far = _piece([[100.0, 0.2], [110.0, 0.2]], [4.0, 4.0])
    fixed = _piece(
        [[0.0, 5.0], [10.0, 5.0]],
        [20.0, 20.0],
        mode="bridge",
        end_dist=[0.0, 0.0],
    )
    fixed["deck_fixed"] = fixed["center"][:, 2].copy()
    stats = bridge_end_steps([ground, ground_far, bridge, smooth, fixed])
    assert stats["terminals_matched"] == 2
    assert stats["steps_ge_0_45m"] == 1
    assert stats["max_m"] == 2.0


def test_height_ratio_at_the_probe():
    tuen = _piece([[0.0, 2.0], [10.0, 2.0]], [15.0, 16.0], mode="bridge", name_en="Tuen Mun Road", name_zh="屯門公路")
    castle = _piece([[1.0, -3.0], [12.0, -3.0]], [5.0, 5.5], name_en="Castle Peak Road - Castle Peak Bay", name_zh="青山公路－青山灣段")
    other = _piece([[0.0, 0.0], [4.0, 0.0]], [1.0, 1.0], name_en="Other Road")
    # Probe constants are lon/lat; the identity warp treats them as game metres,
    # so place the samples on the probe coordinate.
    from tools.pipeline.warp_probe import PROBE_LAT, PROBE_LON

    tuen["xy"] = tuen["xy"] + np.array([PROBE_LON, PROBE_LAT])
    tuen["center"][:, :2] = tuen["xy"]
    castle["xy"] = castle["xy"] + np.array([PROBE_LON, PROBE_LAT])
    castle["center"][:, :2] = castle["xy"]
    gap = height_gap([other, tuen, castle], _IdentityWarp())
    assert gap["pair"] == "bridge_over_castle_peak"
    assert gap["tuen_mun_road"]["z_m"] == 15.0
    assert gap["castle_peak_road"]["z_m"] == 5.0
    assert gap["vertical_gap_m"] == 10.0
    assert gap["height_ratio"] == 3.0
