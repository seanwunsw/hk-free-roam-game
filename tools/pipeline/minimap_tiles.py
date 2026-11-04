"""Local minimap tiles: 1024 m squares at 2 m per pixel (512 px PNGs).

The HUD's zoomed minimap draws a 1 km window from the 2-4 tiles under it, so only a
handful of 1 MB textures are resident; the full map keeps the single 2048 px image.
Rows run north to south like the full minimap."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import numpy as np

TILE_M = 1024.0
TILE_PX = 512
SEA_RGB = (28, 78, 102)
WATER_RGB = (52, 108, 140)
BUILDING_RGB = (196, 190, 178)
BUILDING_EDGE = (150, 144, 134)
ROAD_RGB = {
    "motorway": (236, 150, 60),
    "motorway_link": (236, 150, 60),
    "trunk": (240, 176, 84),
    "trunk_link": (240, 176, 84),
    "primary": (250, 214, 110),
    "primary_link": (250, 214, 110),
    "secondary": (250, 236, 160),
    "secondary_link": (250, 236, 160),
    "tertiary": (252, 250, 230),
    "tertiary_link": (252, 250, 230),
}
ROAD_DEFAULT = (240, 240, 240)
ROAD_EDGE = (96, 96, 96)
_RANK = {h: i for i, h in enumerate(("service", "living_street", "unclassified", "residential", "tertiary_link", "tertiary",
                                       "secondary_link", "secondary", "primary_link", "primary", "trunk_link", "trunk",
                                       "motorway_link", "motorway"))}


def layout(landscape) -> dict:
    nx = int(math.ceil((landscape["max_x"] - landscape["min_x"]) / TILE_M))
    ny = int(math.ceil((landscape["max_y"] - landscape["min_y"]) / TILE_M))
    return {"min_x_m": float(landscape["min_x"]), "min_y_m": float(landscape["min_y"]), "tile_m": TILE_M, "px": TILE_PX, "nx": nx, "ny": ny}


def _bucket(items, bbox_of, grid) -> dict:
    out = defaultdict(list)
    for item in items:
        x0, y0, x1, y1 = bbox_of(item)
        i0 = max(0, int((x0 - grid["min_x_m"]) // TILE_M))
        i1 = min(grid["nx"] - 1, int((x1 - grid["min_x_m"]) // TILE_M))
        j0 = max(0, int((y0 - grid["min_y_m"]) // TILE_M))
        j1 = min(grid["ny"] - 1, int((y1 - grid["min_y_m"]) // TILE_M))
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                out[(i, j)].append(item)
    return out


def _ring_bbox(ring):
    r = np.asarray(ring)
    return float(r[:, 0].min()), float(r[:, 1].min()), float(r[:, 0].max()), float(r[:, 1].max())


def _road_bbox(road):
    xy = road["xy"]
    pad = float(np.max(road["hl"] + road["hr"]))
    return float(xy[:, 0].min()) - pad, float(xy[:, 1].min()) - pad, float(xy[:, 0].max()) + pad, float(xy[:, 1].max()) + pad


def draw_tiles(out_dir: Path, landscape, is_land: np.ndarray, height: np.ndarray, roads, buildings, waters, ground_rgb=None, extra_lines=(), log=print) -> dict:
    """ground_rgb(xs, ys) -> (n, 3) uint8 land colours, or None for the height bands.
    extra_lines: (xy, width_m, rgb) polylines drawn over buildings and under roads."""
    from PIL import Image, ImageDraw

    grid = layout(landscape)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    m_per_px = TILE_M / TILE_PX
    road_tiles = _bucket([r for r in roads if len(r["xy"]) >= 2], _road_bbox, grid)
    building_tiles = _bucket(buildings, lambda b: _ring_bbox(b["ring"]), grid)
    water_tiles = _bucket(waters, lambda w: _ring_bbox(w["ring"]), grid)
    line_tiles = _bucket(list(extra_lines), lambda l: _ring_bbox(l[0]), grid)
    ny_h, nx_h = is_land.shape
    centres = (np.arange(TILE_PX) + 0.5) * m_per_px
    written = 0
    total_bytes = 0
    for j in range(grid["ny"]):
        for i in range(grid["nx"]):
            x0 = grid["min_x_m"] + i * TILE_M
            y1 = grid["min_y_m"] + (j + 1) * TILE_M
            xs = x0 + centres
            ys = y1 - centres
            gx, gy = np.meshgrid(xs, ys)
            ci = np.clip(np.rint((gx - landscape["min_x"]) / landscape["spacing_x"]).astype(np.int64), 0, nx_h - 1)
            cj = np.clip(np.rint((gy - landscape["min_y"]) / landscape["spacing_y"]).astype(np.int64), 0, ny_h - 1)
            land = is_land[cj, ci]
            key = (i, j)
            if not land.any() and key not in road_tiles:
                continue
            rgb = np.empty((TILE_PX, TILE_PX, 3), dtype=np.uint8)
            rgb[:] = SEA_RGB
            if ground_rgb is not None:
                colours = ground_rgb(gx[land], gy[land])
                rgb[land] = colours
            else:
                h = height[cj, ci][land]
                rgb[land] = np.where((h < 40.0)[:, None], np.array([92, 110, 84], np.uint8),
                                     np.where((h < 220.0)[:, None], np.array([70, 108, 72], np.uint8), np.array([150, 146, 138], np.uint8)))
            image = Image.fromarray(rgb, mode="RGB")
            draw = ImageDraw.Draw(image)

            def px(points):
                p = np.asarray(points, dtype=np.float64)[:, :2]
                return [((x - x0) / m_per_px, (y1 - y) / m_per_px) for x, y in p]

            for water in water_tiles.get(key, ()):
                draw.polygon(px(water["ring"]), fill=WATER_RGB)
            for building in building_tiles.get(key, ()):
                draw.polygon(px(building["ring"]), fill=BUILDING_RGB, outline=BUILDING_EDGE)
            for xy, width_m, colour in line_tiles.get(key, ()):
                draw.line(px(xy), fill=colour, width=max(1, int(round(width_m / m_per_px))), joint="curve")
            ordered = sorted(road_tiles.get(key, ()), key=lambda r: (r["mode"] == "bridge", _RANK.get(r["highway"], 0)))
            for road in ordered:
                width = max(2, int(round(float(np.median(road["hl"] + road["hr"])) / m_per_px)))
                pts = px(road["xy"])
                draw.line(pts, fill=ROAD_EDGE, width=width + 2, joint="curve")
            for road in ordered:
                width = max(1, int(round(float(np.median(road["hl"] + road["hr"])) / m_per_px)))
                colour = ROAD_RGB.get(road["highway"], ROAD_DEFAULT)
                if road["mode"] == "tunnel":
                    colour = tuple(int(c * 0.75) for c in colour)
                draw.line(px(road["xy"]), fill=colour, width=width, joint="curve")
            path = out_dir / f"x{i:02d}_y{j:02d}.png"
            image.save(path, optimize=False, compress_level=6)
            written += 1
            total_bytes += path.stat().st_size
    log(f"minimap tiles {written} of {grid['nx']}x{grid['ny']}  {total_bytes / 1e6:.1f} MB  {TILE_PX}px per {TILE_M:.0f} m")
    grid.update({"dir": out_dir.name, "file_pattern": "x{i:02d}_y{j:02d}.png", "tiles": written, "bytes": total_bytes, "sea_rgb": list(SEA_RGB)})
    return grid
