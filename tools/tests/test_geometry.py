"""Mesh helper tests that do not need OSM."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline.geometry import (  # noqa: E402
    MeshAccum,
    append_extrusion,
    append_ribbon,
    ear_clip,
    road_game_width,
    signed_area,
)
from tools.pipeline.glbutil import read_hkgm_primitives, write_glb  # noqa: E402


def test_lane_minimums():
    width, lanes = road_game_width("secondary", 2, 0.5)
    assert lanes == 2
    assert width >= 8.0
    width, lanes = road_game_width("unclassified", 1, 0.1)
    assert lanes == 1
    assert width >= 3.2
    width, lanes = road_game_width("motorway", 3, 1.0)
    assert lanes == 3
    assert width >= 9.6


def test_ear_clip_square_and_l():
    square = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], dtype=np.float64)
    tris = ear_clip(square)
    assert tris is not None and len(tris) == 2
    ell = np.array([[0, 0], [6, 0], [6, 2], [2, 2], [2, 5], [0, 5]], dtype=np.float64)
    tris = ear_clip(ell)
    assert tris is not None and len(tris) == 4
    assert signed_area(square) > 0


def test_extrusion_and_glb_roundtrip(tmp_path: Path):
    accum = MeshAccum()
    ring = np.array([[0, 0], [10, 0], [10, 6], [0, 6]], dtype=np.float64)
    assert append_extrusion(accum, ring, 1.0, 12.0, (0.6, 0.6, 0.55), (0.0, 0.0))
    ribbon = MeshAccum()
    center = np.array([[0, 0, 1], [20, 0, 1.2], [40, 5, 1.4]], dtype=np.float64)
    append_ribbon(ribbon, center, 8.0, (0.0, 0.0))
    path = tmp_path / "tile.glb"
    write_glb(
        path,
        [accum.primitive(0), ribbon.primitive(1)],
    )
    prims = read_hkgm_primitives(path)
    assert len(prims) == 2
    assert prims[0]["material"] == 0
    assert prims[1]["material"] == 1
    # Roof vertices sit at glTF Y = building top.
    assert prims[0]["positions"][:, 1].max() == np.float32(12.0)
    # A corner at game (10, 6) is glTF (10, z, 6).
    assert np.any(np.isclose(prims[0]["positions"][:, 0], 10.0))
    assert np.any(np.isclose(prims[0]["positions"][:, 2], 6.0))
