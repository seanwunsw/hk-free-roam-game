"""Ground colour from OSM landuse, natural, leisure and water areas.

One RGB raster over the landscape (about 6 m per pixel, 4096 x 4096) that M_Terrain
samples by world XY and the minimap tiles reuse as their background."""

from __future__ import annotations

from pathlib import Path

import numpy as np

GROUND_PX = 4096
FILE_NAME = "ground_color.png"
SEA_RGB = (28, 78, 102)
# Linear-ish sRGB colours chosen to read from a car: built-up greys, park greens, hill
# greens and browns. Keys are "tag=value".
CLASSES = {
    "landuse=residential": (150, 146, 140),
    "landuse=commercial": (162, 150, 146),
    "landuse=retail": (166, 148, 140),
    "landuse=industrial": (150, 144, 152),
    "landuse=railway": (128, 122, 116),
    "landuse=construction": (170, 156, 120),
    "landuse=brownfield": (162, 150, 118),
    "landuse=education": (166, 156, 132),
    "landuse=institutional": (160, 150, 136),
    "landuse=religious": (160, 150, 136),
    "landuse=military": (140, 140, 120),
    "landuse=cemetery": (120, 140, 112),
    "landuse=grass": (104, 150, 84),
    "landuse=recreation_ground": (110, 156, 92),
    "landuse=village_green": (110, 156, 92),
    "landuse=farmland": (150, 160, 96),
    "landuse=orchard": (118, 150, 84),
    "landuse=meadow": (126, 158, 90),
    "landuse=forest": (52, 96, 52),
    "landuse=reservoir": (52, 108, 140),
    "landuse=basin": (52, 108, 140),
    "landuse=aquaculture": (60, 112, 130),
    "natural=wood": (48, 92, 50),
    "natural=scrub": (86, 116, 66),
    "natural=grassland": (122, 150, 88),
    "natural=heath": (120, 132, 84),
    "natural=wetland": (84, 120, 104),
    "natural=mangrove": (60, 100, 72),
    "natural=beach": (214, 200, 160),
    "natural=sand": (210, 196, 152),
    "natural=bare_rock": (140, 132, 120),
    "natural=scree": (150, 142, 130),
    "natural=water": (52, 108, 140),
    "leisure=park": (96, 150, 80),
    "leisure=garden": (100, 152, 84),
    "leisure=golf_course": (120, 170, 96),
    "leisure=pitch": (96, 154, 92),
    "leisure=stadium": (118, 150, 104),
    "leisure=sports_centre": (150, 148, 132),
    "leisure=playground": (150, 140, 110),
    "leisure=track": (170, 110, 90),
    "amenity=parking": (120, 120, 122),
}
_KEYS = ("natural", "leisure", "landuse", "amenity")


def classify(tags) -> str | None:
    for key in _KEYS:
        value = tags.get(key)
        if value:
            name = f"{key}={value}"
            if name in CLASSES:
                return name
    if tags.get("water"):
        return "natural=water"
    return None


def layout(landscape) -> dict:
    return {
        "min_x_m": float(landscape["min_x"]),
        "min_y_m": float(landscape["min_y"]),
        "max_x_m": float(landscape["max_x"]),
        "max_y_m": float(landscape["max_y"]),
        "width_px": GROUND_PX,
        "height_px": GROUND_PX,
    }


def rasterise(path: Path, landscape, is_land: np.ndarray, height: np.ndarray, areas: list[tuple[str, np.ndarray]], log=print) -> tuple[dict, np.ndarray]:
    """areas: (class, game-metre ring). Larger areas are drawn first so a park inside a
    residential zone or a pitch inside a park stays visible. Returns (manifest block, rgb)."""
    from PIL import Image, ImageDraw

    grid = layout(landscape)
    w = h = GROUND_PX
    sx = (grid["max_x_m"] - grid["min_x_m"]) / w
    sy = (grid["max_y_m"] - grid["min_y_m"]) / h
    # Base: hill bands on land, sea elsewhere (row 0 is north).
    ny, nx = is_land.shape
    xs = grid["min_x_m"] + (np.arange(w) + 0.5) * sx
    ys = grid["max_y_m"] - (np.arange(h) + 0.5) * sy
    ci = np.clip(np.rint((xs - landscape["min_x"]) / landscape["spacing_x"]).astype(np.int64), 0, nx - 1)
    cj = np.clip(np.rint((ys - landscape["min_y"]) / landscape["spacing_y"]).astype(np.int64), 0, ny - 1)
    land = is_land[cj][:, ci]
    z = height[cj][:, ci]
    rgb = np.empty((h, w, 3), dtype=np.uint8)
    rgb[:] = SEA_RGB
    low = np.array([96, 120, 82], np.uint8)
    mid = np.array([70, 106, 64], np.uint8)
    high = np.array([118, 116, 96], np.uint8)
    band = np.where((z < 60.0)[..., None], low, np.where((z < 300.0)[..., None], mid, high))
    rgb[land] = band[land]
    del z, band
    image = Image.fromarray(rgb, mode="RGB")
    del rgb
    draw = ImageDraw.Draw(image)
    def area_of(ring):
        return 0.5 * abs(float(np.dot(ring[:, 0], np.roll(ring[:, 1], -1)) - np.dot(ring[:, 1], np.roll(ring[:, 0], -1))))
    ordered = sorted(areas, key=lambda item: -area_of(item[1]))
    drawn = 0
    counts: dict[str, int] = {}
    for name, ring in ordered:
        if len(ring) < 3:
            continue
        px = [((x - grid["min_x_m"]) / sx, (grid["max_y_m"] - y) / sy) for x, y in ring]
        draw.polygon(px, fill=CLASSES[name])
        drawn += 1
        counts[name.split("=")[0]] = counts.get(name.split("=")[0], 0) + 1
    out = np.asarray(image)
    # Sea stays sea: coastal landuse polygons overrun the coastline.
    out = np.where(land[..., None], out, np.array(SEA_RGB, np.uint8)).astype(np.uint8)
    Image.fromarray(out, mode="RGB").save(path, optimize=False, compress_level=6)
    grid.update({"file": path.name, "areas": drawn, "by_key": counts, "m_per_px_x": round(sx, 3), "m_per_px_y": round(sy, 3), "bytes": path.stat().st_size})
    log(f"ground colour {w}x{h}  {sx:.2f} x {sy:.2f} m/px  areas {drawn} {counts}  {grid['bytes'] / 1e6:.1f} MB")
    return grid, out


def sampler(grid: dict, rgb: np.ndarray):
    """Nearest-pixel colour lookup by game metres, for the minimap tiles."""
    h, w = rgb.shape[:2]
    sx = (grid["max_x_m"] - grid["min_x_m"]) / w
    sy = (grid["max_y_m"] - grid["min_y_m"]) / h

    def at(xs, ys):
        i = np.clip(((np.asarray(xs) - grid["min_x_m"]) / sx).astype(np.int64), 0, w - 1)
        j = np.clip(((grid["max_y_m"] - np.asarray(ys)) / sy).astype(np.int64), 0, h - 1)
        return rgb[j, i]

    return at
