import json
import math
import struct

import numpy as np

from tools.pipeline import props


def _glb(path, positions, indices, color=(1.0, 0.5, 0.25, 1.0), translation=(0.0, 0.0, 0.0)):
    pos = np.asarray(positions, np.float32).tobytes()
    idx = np.asarray(indices, np.uint32).tobytes()
    blob = pos + idx
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": list(translation)}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color)}}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
            {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    text = json.dumps(doc).encode()
    text += b" " * ((-len(text)) % 4)
    blob += b"\0" * ((-len(blob)) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + blob
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def test_flatten_applies_node_transform_material_colour_and_makes_normals(tmp_path):
    path = tmp_path / "m.glb"
    _glb(path, [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [0, 1, 2], translation=(5.0, 0.0, 0.0))
    mesh = props.flatten_glb(path)
    assert np.allclose(mesh["positions"][:, 0], [5, 6, 5])
    assert np.allclose(mesh["colors"][0], [1.0, 0.5, 0.25, 1.0])
    assert np.allclose(mesh["normals"][0] / np.linalg.norm(mesh["normals"][0]), [0, 0, 1])


def test_prepare_assets_scales_to_height_and_skips_missing_models(tmp_path):
    root = tmp_path / "repo"
    (root / "data" / "props" / "hk_traffic_light").mkdir(parents=True)
    _glb(root / "data" / "props" / "hk_traffic_light" / "light.glb",
         [[0, 0, 0], [0.2, 0, 0], [0, 10, 0], [0.2, 10, 0.1]], [0, 1, 2, 1, 3, 2])
    lines = []
    assets = props.prepare_assets(root, tmp_path / "out", log=lines.append)
    assert set(assets) == {"hk_traffic_light"}
    assert assets["hk_traffic_light"]["height_m"] == props.ASSETS["hk_traffic_light"]["height_m"]
    assert (tmp_path / "out" / "props" / "hk_traffic_light.glb").exists()
    assert any("no GLB in data/props/hk_safe_island" in line for line in lines)


class _Warp:
    def lonlat_to_game_m(self, lon, lat):
        return np.asarray(lon, float), np.asarray(lat, float)


def _road():
    xy = np.column_stack([np.linspace(-100, 100, 41), np.zeros(41)])
    return {"xy": xy, "hl": np.full(41, 5.0), "hr": np.full(41, 5.0), "center": np.column_stack([xy, np.full(41, 3.0)])}


def test_signal_sits_at_the_left_kerb_facing_oncoming_traffic():
    # Eastbound traffic arriving at a signal at (0, 0): HK drives on the left, so the kerb
    # on the driver's left is the north side, and the signal faces west (yaw 180).
    extracted = {"signal_approaches": [{"id": 1, "lon": 0.0, "lat": 0.0, "from_lon": -20.0, "from_lat": 0.0}]}
    placed, stats = props.place(_Warp(), extracted, [_road()], (-1e4, -1e4, 1e4, 1e4), log=lambda m: None)
    assert stats["signals"] == 1
    (signal,) = placed
    assert signal["asset"] == props.SIGNAL_ASSET
    assert math.isclose(signal["y"], 5.0 + props.KERB_OUT_M, abs_tol=1e-6)
    assert math.isclose(signal["x"], -props.STOP_BACK_M, abs_tol=1e-6)
    assert abs(abs(signal["yaw"]) - 180.0) < 1e-6
    assert signal["z"] == 3.0


def test_two_way_signal_gets_one_head_per_approach_and_islands_sit_on_the_centreline(tmp_path):
    extracted = {
        "signal_approaches": [
            {"id": 1, "lon": 0.0, "lat": 0.0, "from_lon": -20.0, "from_lat": 0.0},
            {"id": 1, "lon": 0.0, "lat": 0.0, "from_lon": 20.0, "from_lat": 0.0},
            {"id": 1, "lon": 0.0, "lat": 0.0, "from_lon": -30.0, "from_lat": 1.0},  # same approach again
        ],
        "island_nodes": [{"lon": 40.0, "lat": 2.0}],
    }
    placed, stats = props.place(_Warp(), extracted, [_road()], (-1e4, -1e4, 1e4, 1e4), log=lambda m: None)
    signals = [p for p in placed if p["asset"] == props.SIGNAL_ASSET]
    assert len(signals) == 2 and sorted(round(s["y"], 1) for s in signals) == [-5.6, 5.6]
    (island,) = [p for p in placed if p["asset"] == props.ISLAND_ASSET]
    assert island["y"] == 0.0 and abs(island["x"] - 40.0) <= 5.0
    files = props.write_tiles(tmp_path, placed, {"min_x": -200.0, "min_y": -200.0, "max_x": 200.0, "max_y": 200.0}, 256.0)
    assert sum(len(json.loads((tmp_path / rel.split("/")[-1]).read_text())["props"]) for rel in files.values()) == 3


def test_real_traffic_light_stands_on_its_pole_with_the_lenses_facing_east(tmp_path):
    import pytest
    from pathlib import Path

    from tools.pipeline.glbutil import read_hkgm_primitives

    root = Path(__file__).resolve().parents[2]
    if not list((root / "data" / "props" / "hk_traffic_light").glob("*.glb")):
        pytest.skip("Sketchfab GLBs not downloaded")
    assets = props.prepare_assets(root, tmp_path, log=lambda m: None)
    prim = read_hkgm_primitives(tmp_path / assets["hk_traffic_light"]["file"])[0]
    p = np.asarray(prim["positions"])
    c = np.asarray(prim["colors"])[:, :3]
    assert abs(p[:, 1].min()) < 1e-4 and abs(p[:, 1].max() - 3.6) < 1e-3
    green = np.all(np.abs(c - (0.267, 0.588, 0.282)) < 0.01, axis=1)
    assert green.any() and p[green, 0].mean() > 0.2 and abs(p[green, 2].mean()) < 0.05
    foot = p[p[:, 1] < 0.1]
    assert np.abs(foot[:, [0, 2]].mean(axis=0)).max() < 0.05
