"""Sample the landscape height field the way Unreal triangulates it.

Unreal splits every landscape quad along the diagonal from vertex (x, y) to
(x + 1, y + 1) in landscape space. Landscape +Y points south (row 0 of the
height map is the north edge), so the diagonal runs NW -> SE. Our height grids
are stored with row 0 = south, so in (column i, row j) terms the diagonal joins
(i, j + 1) and (i + 1, j); a cell splits along u + v = 1.
"""

from __future__ import annotations

import numpy as np

R16_ZERO = 32768
R16_METRES_PER_UNIT = 0.04


def decode_r16(raw: np.ndarray) -> np.ndarray:
    return (raw.astype(np.float64) - R16_ZERO) * R16_METRES_PER_UNIT


def quantize_r16(height: np.ndarray) -> np.ndarray:
    """Round heights to what terrain.r16 stores, so samples match the engine."""
    return np.clip(np.round(height / R16_METRES_PER_UNIT), -R16_ZERO, 65535 - R16_ZERO) * R16_METRES_PER_UNIT


def sample_ue(height: np.ndarray, min_x: float, min_y: float, sx: float, sy: float, x, y) -> np.ndarray:
    """Height at world (x, y) on Unreal's triangulated landscape surface."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ny, nx = height.shape
    fx = np.clip((x - min_x) / sx, 0.0, nx - 1.000001)
    fy = np.clip((y - min_y) / sy, 0.0, ny - 1.000001)
    i = np.floor(fx).astype(np.int64)
    j = np.floor(fy).astype(np.int64)
    u = fx - i
    v = fy - j
    z00 = height[j, i]
    z10 = height[j, i + 1]
    z01 = height[j + 1, i]
    z11 = height[j + 1, i + 1]
    lower = z00 + u * (z10 - z00) + v * (z01 - z00)
    upper = z11 + (1.0 - u) * (z01 - z11) + (1.0 - v) * (z10 - z11)
    return np.where(u + v <= 1.0, lower, upper)
