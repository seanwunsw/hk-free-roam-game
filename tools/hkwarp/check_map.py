"""Print warp extent, district scales, and Victoria Harbour width. Exits non-zero if targets fail."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hkwarp.warp import build_warp, load_config  # noqa: E402


def load_dem():
    tiles = {}
    for lon0, name in ((113, "N22E113.hgt.gz"), (114, "N22E114.hgt.gz")):
        path = ROOT / "data" / "raw" / name
        if not path.exists():
            return None
        with gzip.open(path, "rb") as fh:
            raw = fh.read()
        tiles[lon0] = np.frombuffer(raw, dtype=">i2").reshape((3601, 3601)).astype(np.float32)
        tiles[lon0][tiles[lon0] < -1000] = 0.0
    return tiles


def sample_dem(tiles, lon, lat):
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    out = np.zeros(lon.shape, dtype=np.float64)
    for lon0, grid in tiles.items():
        mask = (lon >= lon0) & (lon < lon0 + 1.0) & (lat >= 22.0) & (lat <= 23.0)
        if not np.any(mask):
            continue
        fx = (lon[mask] - lon0) * 3600.0
        fy = (23.0 - lat[mask]) * 3600.0
        c0 = np.floor(fx).astype(np.int32)
        r0 = np.floor(fy).astype(np.int32)
        c0 = np.clip(c0, 0, 3599)
        r0 = np.clip(r0, 0, 3599)
        tx = fx - c0
        ty = fy - r0
        g00 = grid[r0, c0]
        g01 = grid[r0, c0 + 1]
        g10 = grid[r0 + 1, c0]
        g11 = grid[r0 + 1, c0 + 1]
        out[mask] = (g00 * (1 - tx) + g01 * tx) * (1 - ty) + (g10 * (1 - tx) + g11 * tx) * ty
    return out


def measure_harbour(warp, tiles, land_m: float = 1.2) -> list[dict]:
    """Walk the harbour centreline and measure game-space width between DEM shores."""
    centre = np.asarray(warp.config["harbour_centerline_lonlat"], dtype=np.float64)
    # Densify in lon/lat.
    samples = []
    for (lon0, lat0), (lon1, lat1) in zip(centre[:-1], centre[1:]):
        for t in np.linspace(0.0, 1.0, 8, endpoint=False):
            samples.append((lon0 + (lon1 - lon0) * t, lat0 + (lat1 - lat0) * t))
    samples.append(tuple(centre[-1]))
    rows = []
    for lon, lat in samples:
        x, y = warp.lonlat_to_real_m(lon, lat)
        x = float(x)
        y = float(y)
        # Tangent from neighbouring real metres, then a north-ish normal.
        ahead_lon = lon + 0.002
        ax, ay = warp.lonlat_to_real_m(ahead_lon, lat)
        tx, ty = float(ax) - x, float(ay) - y
        norm = math_hypot(tx, ty) or 1.0
        tx, ty = tx / norm, ty / norm
        nx, ny = -ty, tx
        # Prefer the normal that points roughly north.
        if ny < 0:
            nx, ny = -nx, -ny

        def find_land(sign: float) -> float | None:
            for dist in np.linspace(30.0, 3500.0, 180):
                px = x + sign * nx * dist
                py = y + sign * ny * dist
                plon, plat = warp.real_m_to_lonlat(px, py)
                elev = float(sample_dem(tiles, plon, plat))
                if elev > land_m:
                    return dist
            return None

        north = find_land(1.0)
        south = find_land(-1.0)
        if north is None or south is None:
            continue
        if float(sample_dem(tiles, lon, lat)) > land_m:
            continue
        sx, sy = x - nx * south, y - ny * south
        nx_, ny_ = x + nx * north, y + ny * north
        gx0, gy0 = warp.real_to_game_m(sx, sy)
        gx1, gy1 = warp.real_to_game_m(nx_, ny_)
        width = math_hypot(float(gx1) - float(gx0), float(gy1) - float(gy0))
        rows.append({"lon": lon, "lat": lat, "real_width_m": north + south, "game_width_m": width})
    return rows


def math_hypot(a: float, b: float) -> float:
    return float(np.hypot(a, b))


def main() -> int:
    config = load_config()
    warp = build_warp(config)
    extent = warp.geographic_extent_m()
    print(
        f"extent width {extent['width_m']:.0f} m  height {extent['height_m']:.0f} m  "
        f"long_axis {extent['long_axis_m']:.0f} m"
    )
    print("--- places ---")
    for place in config["places"]:
        if place.get("kind") == "helipad":
            continue
        x, y = warp.lonlat_to_real_m(place["lon"], place["lat"])
        dx, dy = warp.axis_scales(x, y)
        horiz = float(warp.horizontal_scale(x, y))
        gx, gy = warp.real_to_game_m(x, y)
        print(
            f"{place['id']:16} game_km ({float(gx)/1000:7.2f},{float(gy)/1000:7.2f})  "
            f"scale_e {float(dx):.3f} scale_n {float(np.asarray(dy)):.3f} horiz {horiz:.3f}  "
            f"height {float(warp.height_scale(x, y)):.3f}"
        )
    # Jacobian grid over the territory.
    bounds = config["bounds"]
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], 40)
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], 30)
    lon_g, lat_g = np.meshgrid(lons, lats)
    rx, ry = warp.lonlat_to_real_m(lon_g, lat_g)
    dx, dy = warp.axis_scales(rx, ry)
    min_j = float(np.min(dx * dy))
    print(f"min jacobian {min_j:.5f}  min_dx {float(dx.min()):.4f}  min_dy {float(dy.min()):.4f}")

    tiles = load_dem()
    failed = False
    if min_j <= 0.0:
        print("FAIL jacobian not positive")
        failed = True
    long_axis = extent["long_axis_m"]
    if not (config["target_long_axis_min_m"] <= long_axis <= config["target_long_axis_max_m"]):
        print("FAIL long axis outside target")
        failed = True
    if tiles is None:
        print("DEM missing; harbour width not measured")
        return 1 if failed else 0
    rows = measure_harbour(warp, tiles)
    if not rows:
        print("FAIL harbour measurement found no water sections")
        return 1
    widths = [row["game_width_m"] for row in rows]
    print(f"harbour sections {len(rows)}  game width min {min(widths):.0f} m  median {np.median(widths):.0f} m  max {max(widths):.0f} m")
    narrow = sorted(rows, key=lambda row: row["game_width_m"])[:6]
    for row in narrow:
        print(
            f"  lon {row['lon']:.4f} lat {row['lat']:.4f}  real {row['real_width_m']:.0f} m  game {row['game_width_m']:.0f} m"
        )
    if min(widths) < config["min_harbour_width_m"]:
        print("FAIL harbour narrower than minimum")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
