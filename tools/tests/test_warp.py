"""Warp invariants: monotone, invertible, harbour and map size when DEM is present."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hkwarp.check_map import load_dem, measure_harbour  # noqa: E402
from tools.hkwarp.warp import build_warp, load_config, load_lut  # noqa: E402


def test_jacobian_positive_and_roundtrip():
    warp = build_warp(load_config())
    bounds = warp.config["bounds"]
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], 25)
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], 18)
    lon_g, lat_g = np.meshgrid(lons, lats)
    rx, ry = warp.lonlat_to_real_m(lon_g, lat_g)
    dx, dy = warp.axis_scales(rx, ry)
    assert np.all(dx > 0.05)
    assert np.all(dy > 0.05)
    gx, gy = warp.lonlat_to_game_m(lon_g, lat_g)
    lon2, lat2 = warp.game_m_to_lonlat(gx, gy)
    assert np.max(np.abs(lon2 - lon_g)) < 2e-5
    assert np.max(np.abs(lat2 - lat_g)) < 2e-5


def test_origin_and_monotonic_axes():
    warp = build_warp(load_config())
    gx, gy = warp.lonlat_to_game_m(warp.origin_lon, warp.origin_lat)
    assert abs(float(gx)) < 1.0
    assert abs(float(gy)) < 1.0
    xs = np.linspace(-40000, 40000, 40)
    g = warp._lerp(warp.x0, warp.x_step, warp.G, xs)
    assert np.all(np.diff(g) > 0)
    ys = np.linspace(-30000, 30000, 40)
    _, gy = warp.real_to_game_m(np.zeros_like(ys), ys)
    assert np.all(np.diff(gy) > 0)


def test_long_axis_and_harbour():
    warp = build_warp(load_config())
    extent = warp.geographic_extent_m()
    assert warp.config["target_long_axis_min_m"] <= extent["long_axis_m"] <= warp.config["target_long_axis_max_m"]
    tiles = load_dem()
    if tiles is None:
        return
    rows = measure_harbour(warp, tiles)
    assert rows, "expected harbour cross-sections"
    assert min(row["game_width_m"] for row in rows) >= warp.config["min_harbour_width_m"]


def test_lut_roundtrip_file(tmp_path: Path):
    warp = build_warp(load_config())
    path = tmp_path / "warp_lut.bin"
    warp.save_bin(path)
    loaded = load_lut(path)
    lon = np.array([114.1583, 113.92, 114.40])
    lat = np.array([22.2849, 22.31, 22.20])
    a = np.stack(warp.lonlat_to_game_m(lon, lat))
    b = np.stack(loaded.lonlat_to_game_m(lon, lat))
    assert np.allclose(a, b, atol=1e-6)


def test_unreal_axes_put_north_at_negative_y():
    from tools.hkwarp.warp import game_m_to_unreal_cm, unreal_cm_to_game_m

    # Unreal is left-handed: facing +X (east) with +Z up, +Y is on the right, which is south.
    x_cm, y_cm = game_m_to_unreal_cm(250.0, 1000.0)
    assert (float(x_cm), float(y_cm)) == (25000.0, -100000.0)
    east, north = unreal_cm_to_game_m(x_cm, y_cm)
    assert (float(east), float(north)) == (250.0, 1000.0)


def test_unreal_cm_lonlat_roundtrip_and_orientation():
    warp = build_warp(load_config())
    lat, lon = 22.2849, 114.1583
    x_cm, y_cm = warp.lonlat_to_unreal_cm(lon, lat)
    gx, gy = warp.lonlat_to_game_m(lon, lat)
    assert np.isclose(x_cm, gx * 100.0) and np.isclose(y_cm, -gy * 100.0)
    lon2, lat2 = warp.unreal_cm_to_lonlat(x_cm, y_cm)
    assert abs(float(lon2) - lon) < 2e-5 and abs(float(lat2) - lat) < 2e-5
    _, y_north = warp.lonlat_to_unreal_cm(lon, lat + 0.01)
    x_east, _ = warp.lonlat_to_unreal_cm(lon + 0.01, lat)
    assert y_north < y_cm
    assert x_east > x_cm
