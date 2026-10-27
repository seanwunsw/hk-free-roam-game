"""Smooth, strictly monotone coordinate warp from Hong Kong metres to game metres.

The map is a global diffeomorphism on the plane:

    X = G(x)
    Y = H(y) + A(x) * tanh((y - yc(x)) / W) - A(x) * tanh((0 - yc(x)) / W)

G and H are integrals of positive scale profiles, so X increases with x and, for
each fixed x, Y increases with y. The Jacobian is therefore G'(x) * dY/dy > 0
and the warp cannot fold. A(x) * tanh widens Victoria Harbour without creating
seams: A and yc are smooth.

Game axes: +X east, +Y north, metres. Unreal centimetres are metres * 100
(X east, Y north, Z up).

After build(), every query uses the lookup tables written to warp_lut.bin.
The game runtime evaluates those same tables (see shared/hk_warp.h).
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"HKWARP01"
BIN_VERSION = 1


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return repo_root() / "data" / "config" / "world.json"


def default_lut_path() -> Path:
    return repo_root() / "data" / "processed" / "warp_lut.bin"


def load_config(path: Path | None = None) -> dict:
    path = path or default_config_path()
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray | float):
    denom = edge1 - edge0
    if abs(denom) < 1e-9:
        return np.ones_like(x, dtype=np.float64) if isinstance(x, np.ndarray) else 1.0
    t = np.clip((x - edge0) / denom, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _profile(abs_m: np.ndarray | float, knots: list[list[float]]) -> np.ndarray | float:
    scalar = np.isscalar(abs_m)
    x = np.abs(np.asarray(abs_m, dtype=np.float64))
    out = np.empty(x.shape, dtype=np.float64)
    out[...] = knots[-1][1]
    out[x <= knots[0][0]] = knots[0][1]
    for (a0, s0), (a1, s1) in zip(knots[:-1], knots[1:]):
        mask = (x >= a0) & (x <= a1)
        if not np.any(mask):
            continue
        t = _smoothstep(a0, a1, x[mask])
        out[mask] = s0 + (s1 - s0) * t
    if scalar:
        return float(out)
    return out


def _metres_per_degree(lat0_deg: float) -> tuple[float, float]:
    """Constant equirectangular scale at lat0. Accurate to a few parts per thousand over HK."""
    phi = math.radians(lat0_deg)
    m_lat = 111132.92 - 559.82 * math.cos(2.0 * phi) + 1.175 * math.cos(4.0 * phi)
    m_lon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3.0 * phi) + 0.118 * math.cos(5.0 * phi)
    return m_lon, m_lat


def _integrate_scale(origin: float, step: float, samples: np.ndarray) -> np.ndarray:
    """Integral of a sampled positive function, zero at coordinate 0. samples align with the grid."""
    n = samples.shape[0]
    xs = origin + step * np.arange(n, dtype=np.float64)
    cumulative = np.zeros(n, dtype=np.float64)
    if n > 1:
        cumulative[1:] = np.cumsum(0.5 * (samples[:-1] + samples[1:]) * step)
    zero = float(np.interp(0.0, xs, cumulative))
    values = cumulative - zero
    # Positive scale => strictly increasing. Nudge if a flat numerical sample appears.
    min_delta = step * 0.02
    for i in range(1, n):
        if values[i] <= values[i - 1]:
            values[i] = values[i - 1] + min_delta
    return values


@dataclass
class WarpModel:
    """Lookup-table warp. Queries match shared/hk_warp.h."""

    origin_lon: float
    origin_lat: float
    m_per_deg_lon: float
    m_per_deg_lat: float
    harbour_w: float
    x0: float
    x_step: float
    y0: float
    y_step: float
    G: np.ndarray
    H: np.ndarray
    A: np.ndarray
    YC: np.ndarray
    config: dict

    def lonlat_to_real_m(self, lon, lat):
        x = (np.asarray(lon, dtype=np.float64) - self.origin_lon) * self.m_per_deg_lon
        y = (np.asarray(lat, dtype=np.float64) - self.origin_lat) * self.m_per_deg_lat
        return x, y

    def real_m_to_lonlat(self, x, y):
        lon = self.origin_lon + np.asarray(x, dtype=np.float64) / self.m_per_deg_lon
        lat = self.origin_lat + np.asarray(y, dtype=np.float64) / self.m_per_deg_lat
        return lon, lat

    def _lerp(self, origin: float, step: float, values: np.ndarray, x):
        x = np.asarray(x, dtype=np.float64)
        max_x = origin + step * (values.shape[0] - 1)
        f = (np.clip(x, origin, max_x) - origin) / step
        i = np.minimum(f.astype(np.int64), values.shape[0] - 2)
        t = f - i
        return values[i] * (1.0 - t) + values[i + 1] * t

    def _deriv(self, origin: float, step: float, values: np.ndarray, x):
        x = np.asarray(x, dtype=np.float64)
        max_x = origin + step * (values.shape[0] - 1)
        f = (np.clip(x, origin, max_x) - origin) / step
        i = np.minimum(f.astype(np.int64), values.shape[0] - 2)
        return (values[i + 1] - values[i]) / step

    def real_to_game_m(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        hv = self._lerp(self.y0, self.y_step, self.H, y)
        av = self._lerp(self.x0, self.x_step, self.A, x)
        yc = self._lerp(self.x0, self.x_step, self.YC, x)
        w = self.harbour_w
        gx = self._lerp(self.x0, self.x_step, self.G, x)
        gy = hv + av * np.tanh((y - yc) / w) - av * np.tanh((0.0 - yc) / w)
        return gx, gy

    def axis_scales(self, x, y):
        """dX/dx and dY/dy at real-metre coordinates. Both are positive."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        d_g = self._deriv(self.x0, self.x_step, self.G, x)
        d_h = self._deriv(self.y0, self.y_step, self.H, y)
        av = self._lerp(self.x0, self.x_step, self.A, x)
        yc = self._lerp(self.x0, self.x_step, self.YC, x)
        sech = 1.0 / np.cosh((y - yc) / self.harbour_w)
        d_y = d_h + (av / self.harbour_w) * sech * sech
        return d_g, d_y

    def horizontal_scale(self, x, y):
        dx, dy = self.axis_scales(x, y)
        return np.sqrt(np.maximum(dx, 1e-6) * np.maximum(dy, 1e-6))

    def height_scale(self, x, y):
        """Milder than horizontal compression: sqrt(geometric-mean horizontal scale)."""
        h = np.sqrt(self.horizontal_scale(x, y))
        return np.clip(h, 0.20, 1.25)

    def lonlat_to_game_m(self, lon, lat):
        x, y = self.lonlat_to_real_m(lon, lat)
        return self.real_to_game_m(x, y)

    def lonlat_to_game_cm(self, lon, lat):
        gx, gy = self.lonlat_to_game_m(lon, lat)
        return gx * 100.0, gy * 100.0

    def _invert_lut(self, origin: float, step: float, values: np.ndarray, target):
        target = np.asarray(target, dtype=np.float64)
        scalar = target.ndim == 0
        target_f = np.atleast_1d(target)
        out = np.empty(target_f.shape, dtype=np.float64)
        # values is strictly increasing
        idx = np.searchsorted(values, target_f, side="right")
        idx = np.clip(idx, 1, values.shape[0] - 1)
        lo = idx - 1
        span = values[idx] - values[lo]
        t = np.where(span != 0.0, (target_f - values[lo]) / span, 0.0)
        t = np.clip(t, 0.0, 1.0)
        out = origin + step * (lo + t)
        below = target_f <= values[0]
        above = target_f >= values[-1]
        out = np.where(below, origin, out)
        out = np.where(above, origin + step * (values.shape[0] - 1), out)
        return float(out[0]) if scalar else out

    def game_to_real_m(self, game_x, game_y, iterations: int = 60):
        """Inverse of real_to_game_m. X inverts with the G table; Y is a 1D bisection."""
        game_x = np.asarray(game_x, dtype=np.float64)
        game_y = np.asarray(game_y, dtype=np.float64)
        scalar = game_x.ndim == 0 and game_y.ndim == 0
        gx = np.atleast_1d(game_x).astype(np.float64)
        gy = np.atleast_1d(game_y).astype(np.float64)
        if gx.shape != gy.shape:
            gx, gy = np.broadcast_arrays(gx, gy)
            gx = np.array(gx, copy=True)
            gy = np.array(gy, copy=True)
        x = self._invert_lut(self.x0, self.x_step, self.G, gx)
        lo = np.full(x.shape, self.y0, dtype=np.float64)
        hi = np.full(x.shape, self.y0 + self.y_step * (self.H.shape[0] - 1), dtype=np.float64)
        for _ in range(iterations):
            mid = 0.5 * (lo + hi)
            _, y_mid = self.real_to_game_m(x, mid)
            go_lo = y_mid < gy
            lo = np.where(go_lo, mid, lo)
            hi = np.where(go_lo, hi, mid)
        y = 0.5 * (lo + hi)
        if scalar:
            return float(np.reshape(x, (-1))[0]), float(np.reshape(y, (-1))[0])
        return x, y

    def game_m_to_lonlat(self, game_x, game_y):
        x, y = self.game_to_real_m(game_x, game_y)
        return self.real_m_to_lonlat(x, y)

    def game_cm_to_lonlat(self, x_cm, y_cm):
        return self.game_m_to_lonlat(np.asarray(x_cm, dtype=np.float64) / 100.0, np.asarray(y_cm, dtype=np.float64) / 100.0)

    def geographic_extent_m(self, samples: int = 90) -> dict:
        bounds = self.config["bounds"]
        lons = np.linspace(bounds["min_lon"], bounds["max_lon"], samples)
        lats = np.linspace(bounds["min_lat"], bounds["max_lat"], samples)
        lon_g, lat_g = np.meshgrid(lons, lats)
        gx, gy = self.lonlat_to_game_m(lon_g, lat_g)
        min_x, max_x = float(gx.min()), float(gx.max())
        min_y, max_y = float(gy.min()), float(gy.max())
        return {
            "min_x_m": min_x,
            "max_x_m": max_x,
            "min_y_m": min_y,
            "max_y_m": max_y,
            "width_m": max_x - min_x,
            "height_m": max_y - min_y,
            "long_axis_m": max(max_x - min_x, max_y - min_y),
        }

    def save_bin(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        parts = [
            MAGIC,
            struct.pack("<I", BIN_VERSION),
            struct.pack("<d", self.origin_lon),
            struct.pack("<d", self.origin_lat),
            struct.pack("<d", self.m_per_deg_lon),
            struct.pack("<d", self.m_per_deg_lat),
            struct.pack("<d", self.harbour_w),
            struct.pack("<d", self.x0),
            struct.pack("<d", self.x_step),
            struct.pack("<I", self.G.shape[0]),
            struct.pack("<d", self.y0),
            struct.pack("<d", self.y_step),
            struct.pack("<I", self.H.shape[0]),
            self.G.astype("<f8").tobytes(),
            self.H.astype("<f8").tobytes(),
            self.A.astype("<f8").tobytes(),
            self.YC.astype("<f8").tobytes(),
        ]
        path.write_bytes(b"".join(parts))

    def write_golden(self, path: Path, count: int = 64) -> None:
        """Deterministic samples so the C++ evaluator can be checked against Python."""
        rng = np.random.default_rng(20261027)
        bounds = self.config["bounds"]
        lon = rng.uniform(bounds["min_lon"], bounds["max_lon"], count)
        lat = rng.uniform(bounds["min_lat"], bounds["max_lat"], count)
        # Always include the origin and a few known places.
        extra_lon = [self.origin_lon, 114.1583, 113.9146, 114.2730]
        extra_lat = [self.origin_lat, 22.2849, 22.3089, 22.3816]
        lon = np.concatenate([lon, extra_lon])
        lat = np.concatenate([lat, extra_lat])
        gx, gy = self.lonlat_to_game_m(lon, lat)
        lines = ["kind,a,b,c,d"]
        for lo, la, x, y in zip(lon, lat, gx, gy):
            lines.append(f"F,{lo:.10f},{la:.10f},{x:.6f},{y:.6f}")
            lon2, lat2 = self.game_m_to_lonlat(x, y)
            lines.append(f"I,{x:.6f},{y:.6f},{float(lon2):.10f},{float(lat2):.10f}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_warp(config: dict | None = None) -> WarpModel:
    config = config or load_config()
    m_lon, m_lat = _metres_per_degree(config["origin_lat"])
    step = float(config["lut_step_m"])
    x0 = float(config["lut_x0_m"])
    x1 = float(config["lut_x1_m"])
    y0 = float(config["lut_y0_m"])
    y1 = float(config["lut_y1_m"])
    xs = np.arange(x0, x1 + step * 0.5, step, dtype=np.float64)
    ys = np.arange(y0, y1 + step * 0.5, step, dtype=np.float64)

    sx = _profile(np.abs(xs), config["scale_x_knots_m"])
    sy = _profile(np.abs(ys), config["scale_y_knots_m"])
    g = _integrate_scale(x0, step, np.asarray(sx, dtype=np.float64))
    h = _integrate_scale(y0, step, np.asarray(sy, dtype=np.float64))

    centre = np.asarray(config["harbour_centerline_lonlat"], dtype=np.float64)
    cx = (centre[:, 0] - config["origin_lon"]) * m_lon
    cy = (centre[:, 1] - config["origin_lat"]) * m_lat
    order = np.argsort(cx)
    cx, cy = cx[order], cy[order]
    # Drop duplicated eastings so np.interp is well defined.
    keep = np.concatenate([[True], np.diff(cx) > 1.0])
    cx, cy = cx[keep], cy[keep]
    left, right = float(cx[0]), float(cx[-1])
    fade = float(config["harbour_fade_m"])
    amp = float(config["harbour_amplitude_m"])
    t_left = _smoothstep(left - fade, left, xs)
    t_right = 1.0 - _smoothstep(right, right + fade, xs)
    inside = (xs >= left) & (xs <= right)
    window = np.where(inside, 1.0, np.where(xs < left, t_left, t_right))
    a = amp * window
    yc = np.interp(xs, cx, cy)

    return WarpModel(
        origin_lon=float(config["origin_lon"]),
        origin_lat=float(config["origin_lat"]),
        m_per_deg_lon=m_lon,
        m_per_deg_lat=m_lat,
        harbour_w=float(config["harbour_tanh_width_m"]),
        x0=float(xs[0]),
        x_step=step,
        y0=float(ys[0]),
        y_step=step,
        G=g,
        H=h,
        A=a,
        YC=yc,
        config=config,
    )


def load_lut(path: Path) -> WarpModel:
    data = path.read_bytes()
    if data[:8] != MAGIC:
        raise ValueError(f"{path} is not an HKWARP01 file")
    offset = 8
    (version,) = struct.unpack_from("<I", data, offset)
    offset += 4
    if version != BIN_VERSION:
        raise ValueError(f"unsupported warp lut version {version}")
    nums = struct.unpack_from("<6d", data, offset)
    offset += 8 * 6
    origin_lon, origin_lat, m_lon, m_lat, harbour_w, x0 = nums
    (x_step,) = struct.unpack_from("<d", data, offset)
    offset += 8
    (nx,) = struct.unpack_from("<I", data, offset)
    offset += 4
    (y0,) = struct.unpack_from("<d", data, offset)
    offset += 8
    (y_step,) = struct.unpack_from("<d", data, offset)
    offset += 8
    (ny,) = struct.unpack_from("<I", data, offset)
    offset += 4

    def take(n: int) -> np.ndarray:
        nonlocal offset
        arr = np.frombuffer(data, dtype="<f8", count=n, offset=offset).astype(np.float64, copy=True)
        offset += 8 * n
        return arr

    g = take(nx)
    h = take(ny)
    a = take(nx)
    yc = take(nx)
    config = load_config()
    return WarpModel(
        origin_lon=origin_lon,
        origin_lat=origin_lat,
        m_per_deg_lon=m_lon,
        m_per_deg_lat=m_lat,
        harbour_w=harbour_w,
        x0=x0,
        x_step=x_step,
        y0=y0,
        y_step=y_step,
        G=g,
        H=h,
        A=a,
        YC=yc,
        config=config,
    )


def load_warp(path: Path | None = None) -> WarpModel:
    """Load the baked lut when it exists so CLI results match the game; otherwise build from config."""
    path = path or default_lut_path()
    if path.exists():
        return load_lut(path)
    return build_warp()
