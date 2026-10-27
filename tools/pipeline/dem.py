"""SRTM 1-arc-second tiles covering Hong Kong (N22E113 and N22E114)."""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np

TILES = (113, 114)


def load_srtm(raw_dir: Path) -> dict[int, np.ndarray]:
    grids = {}
    for lon0 in TILES:
        path = raw_dir / f"N22E{lon0}.hgt.gz"
        if not path.exists():
            raise FileNotFoundError(path)
        with gzip.open(path, "rb") as fh:
            raw = fh.read()
        expected = 3601 * 3601 * 2
        if len(raw) != expected:
            raise ValueError(f"{path.name} decompressed to {len(raw)} bytes, expected {expected}")
        grid = np.frombuffer(raw, dtype=">i2").reshape((3601, 3601)).astype(np.float32)
        grid[grid < -1000] = 0.0
        grids[lon0] = grid
    return grids


def sample_srtm(grids: dict[int, np.ndarray], lon, lat) -> np.ndarray:
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    out = np.zeros(np.broadcast(lon, lat).shape, dtype=np.float32)
    lon_b, lat_b = np.broadcast_arrays(lon, lat)
    for lon0, grid in grids.items():
        mask = (lon_b >= lon0) & (lon_b < lon0 + 1.0) & (lat_b >= 22.0) & (lat_b <= 23.0)
        if not np.any(mask):
            continue
        fx = (lon_b[mask] - lon0) * 3600.0
        fy = (23.0 - lat_b[mask]) * 3600.0
        c0 = np.clip(np.floor(fx).astype(np.int32), 0, 3599)
        r0 = np.clip(np.floor(fy).astype(np.int32), 0, 3599)
        tx = (fx - c0).astype(np.float32)
        ty = (fy - r0).astype(np.float32)
        g00 = grid[r0, c0]
        g01 = grid[r0, c0 + 1]
        g10 = grid[r0 + 1, c0]
        g11 = grid[r0 + 1, c0 + 1]
        out[mask] = (g00 * (1 - tx) + g01 * tx) * (1 - ty) + (g10 * (1 - tx) + g11 * tx) * ty
    return out
