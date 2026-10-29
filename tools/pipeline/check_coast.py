"""Land/sea agreement between a terrain.r16 and the OSM coastline mask.

    python -m tools.pipeline.check_coast [--terrain other.r16] [--processed DIR]

For every landscape vertex: is it land in data/processed/land_mask.png, and is
the stored height above or below the sea plane (Z = 0)?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEABED_M = 2.0


def _pct(num, den) -> float:
    return round(100.0 * float(num) / float(den), 3) if den else 0.0


def agreement(height: np.ndarray, is_land: np.ndarray, inside: np.ndarray | None = None) -> dict:
    """Percentages over vertices (optionally only where `inside`)."""
    sel = np.ones(height.shape, dtype=bool) if inside is None else inside
    sea = sel & ~is_land
    land = sel & is_land
    return {
        "vertices": int(sel.sum()),
        "osm_sea_vertices": int(sea.sum()),
        "osm_land_vertices": int(land.sum()),
        "sea_below_0_pct": _pct((height[sea] < 0.0).sum(), sea.sum()),
        "sea_below_seabed_pct": _pct((height[sea] <= -SEABED_M + 0.02).sum(), sea.sum()),
        "land_above_0_pct": _pct((height[land] > 0.0).sum(), land.sum()),
        "agree_pct": _pct((height[sea] < 0.0).sum() + (height[land] > 0.0).sum(), sea.sum() + land.sum()),
    }


def vertex_lonlat(processed: Path):
    from tools.hkwarp.warp import build_warp, load_config
    from tools.pipeline.build_world import _invert_columns

    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    ls = manifest["landscape"]
    warp = build_warp(load_config())
    xs = ls["min_x_m"] + np.arange(ls["verts_x"]) * ls["spacing_x_m"]
    ys = ls["min_y_m"] + np.arange(ls["verts_y"]) * ls["spacing_y_m"]
    x_real, y_real = _invert_columns(warp, xs, ys, lambda *_: None)
    lon = np.broadcast_to(warp.origin_lon + x_real[None, :] / warp.m_per_deg_lon, y_real.shape)
    lat = warp.origin_lat + y_real / warp.m_per_deg_lat
    return ls, lon, lat


def main(argv=None) -> int:
    from tools.pipeline.coast import LandMask, land_at, read_poly
    from tools.pipeline.surface import decode_r16

    parser = argparse.ArgumentParser()
    parser.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    parser.add_argument("--terrain", default=None)
    args = parser.parse_args(argv)
    processed = Path(args.processed)
    ls, lon, lat = vertex_lonlat(processed)
    raw = np.fromfile(args.terrain or processed / "terrain.r16", dtype="<u2").reshape(ls["verts_y"], ls["verts_x"])
    height = decode_r16(raw)
    is_land = LandMask(processed).is_land(lon, lat)
    import shapely

    extract = read_poly(ROOT / "data" / "config" / "hong-kong.poly")
    inside = land_at(shapely.box(-180, -90, 180, 90), extract, lon, lat)
    out = {"all": agreement(height, is_land), "inside_extract": agreement(height, is_land, inside)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
