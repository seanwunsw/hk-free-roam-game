"""Bake a fixed Hong Kong layout from OSM + SRTM into data/processed.

Runtime Unreal code does not rebuild the map. This script is the only place
that reads OpenStreetMap and the height tiles. Outputs:

- warp_lut.bin / golden_warp.csv
- terrain.r16 (uint16, row 0 = south, x = east)
- tiles/b_IX_IY.glb, r_IX_IY.glb, w_IX_IY.glb
- minimap.png, previews, spawns.json, landmarks.json, manifest.json
- logs/pipeline.log and logs/report.json
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np

from tools.hkwarp.check_map import harbour_clearance, load_dem, measure_harbour
from tools.hkwarp.warp import build_warp, repo_root
from tools.pipeline.dem import load_srtm, sample_srtm
from tools.pipeline.geometry import (
    ROAD_CLASSES,
    MeshAccum,
    append_extrusion,
    clean_ring,
    douglas_peucker,
    ensure_ccw,
    point_in_ring,
    signed_area,
)
from tools.pipeline.glbutil import write_glb
from tools.pipeline import coast as coastmask
from tools.pipeline import roads as roadnet
from tools.pipeline import spawns as spawn_rules
from tools.pipeline.surface import quantize_r16, sample_ue

ROAD_CLASS_SET = set(ROAD_CLASSES)
SEABED_DROP_M = 2.0
# OSM coastline decides land and sea. Land never dips under this (low SRTM shore
# cells would flood); sea slopes from -SEABED_DROP_M at the shore to SHELF_DEPTH_M.
LAND_MIN_M = 0.6
SHELF_DEPTH_M = 10.0
SHELF_FALLOFF_M = 120.0
DEM_SEA_M = 1.5
MASK_STEP_DEG = 0.0001
HEIGHT_BY_KIND = {
    "house": 8.5,
    "detached": 9.0,
    "semidetached_house": 9.0,
    "terrace": 12.0,
    "bungalow": 6.5,
    "residential": 48.0,
    "apartments": 52.0,
    "dormitory": 36.0,
    "commercial": 28.0,
    "retail": 16.0,
    "office": 60.0,
    "hotel": 70.0,
    "industrial": 12.0,
    "warehouse": 10.0,
    "school": 16.0,
    "university": 24.0,
    "hospital": 28.0,
    "public": 22.0,
    "civic": 20.0,
    "train_station": 16.0,
    "transportation": 14.0,
    "church": 18.0,
    "temple": 16.0,
    "garage": 4.0,
    "garages": 4.0,
    "shed": 3.5,
    "roof": 4.0,
    "kiosk": 3.5,
    "service": 8.0,
    "parking": 12.0,
}
COLOR_BY_KIND = {
    "house": (0.76, 0.68, 0.55),
    "residential": (0.72, 0.64, 0.56),
    "apartments": (0.70, 0.66, 0.60),
    "commercial": (0.62, 0.64, 0.68),
    "retail": (0.76, 0.58, 0.50),
    "office": (0.50, 0.60, 0.70),
    "hotel": (0.66, 0.56, 0.62),
    "industrial": (0.55, 0.54, 0.50),
    "school": (0.80, 0.74, 0.58),
    "hospital": (0.82, 0.82, 0.80),
    "temple": (0.72, 0.62, 0.48),
    "church": (0.70, 0.66, 0.60),
}
ROAD_DRAW = {
    "motorway": (40, 40, 46),
    "motorway_link": (50, 50, 56),
    "trunk": (48, 46, 42),
    "trunk_link": (58, 54, 48),
    "primary": (70, 64, 52),
    "primary_link": (80, 72, 58),
    "secondary": (90, 88, 80),
    "secondary_link": (100, 96, 88),
    "tertiary": (110, 108, 100),
    "tertiary_link": (120, 116, 108),
    "unclassified": (130, 128, 120),
}


class Log:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("w", encoding="utf-8")

    def __call__(self, message: str) -> None:
        line = time.strftime("%H:%M:%S") + " " + message
        print(line, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def parse_metres(text) -> float | None:
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw or raw in {"no", "none", "nan"}:
        return None
    feet = "'" in raw or raw.endswith("ft")
    raw = raw.replace("metres", " ").replace("meters", " ").replace("meter", " ")
    raw = raw.replace("ft", " ").replace("'", " ").replace("m", " ")
    raw = raw.split(";")[0].split("~")[-1].strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if feet:
        value *= 0.3048
    if value <= 0.0 or value > 900.0:
        return None
    return value


def parse_levels(text) -> float | None:
    if text is None:
        return None
    raw = str(text).split(";")[0].split("-")[-1].strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0.0 or value > 160.0:
        return None
    return value * 3.15


def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "no", "false", "0"}


def _layer_value(tags) -> int:
    raw = tags.get("layer")
    if raw is None:
        return 0
    try:
        return int(float(str(raw).split(";")[0]))
    except ValueError:
        return 0


def encode_height(z_m: np.ndarray) -> np.ndarray:
    """UE landscape: z_cm = (h16 - 32768) * ScaleZ / 128, ScaleZ = 512 -> 4 cm per unit."""
    units = np.asarray(z_m, dtype=np.float64) / 0.04 + 32768.0
    return np.clip(np.rint(units), 0, 65535).astype("<u2")


def largest_ring(geom) -> np.ndarray | None:
    if geom is None or geom.is_empty:
        return None
    kind = geom.geom_type
    if kind == "Polygon":
        coords = np.asarray(geom.exterior.coords, dtype=np.float64)
        if len(coords) >= 2 and np.allclose(coords[0], coords[-1]):
            coords = coords[:-1]
        return coords if len(coords) >= 3 else None
    if kind == "MultiPolygon":
        part = max(geom.geoms, key=lambda item: item.area)
        return largest_ring(part)
    if kind == "GeometryCollection":
        parts = [item for item in geom.geoms if item.geom_type in {"Polygon", "MultiPolygon"} and not item.is_empty]
        if not parts:
            return None
        return largest_ring(max(parts, key=lambda item: item.area))
    return None


def _ring_nodes(ring) -> np.ndarray | None:
    points = []
    for node in ring:
        if not node.location.valid():
            return None
        points.append((node.lon, node.lat))
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        return None
    return np.asarray(points, dtype=np.float64)


def _way_nodes(way) -> np.ndarray | None:
    points = []
    for node in way.nodes:
        if not node.location.valid():
            if len(points) >= 2:
                break
            points.clear()
            continue
        points.append((node.lon, node.lat))
    if len(points) < 2:
        return None
    return np.asarray(points, dtype=np.float64)


def extract_osm(path: Path, log: Log) -> dict:
    import osmium

    buildings_ll = []
    building_meta = []
    roads = []
    waters_ll = []
    coasts = []
    seen = 0
    processor = osmium.FileProcessor(str(path)).with_locations().with_areas()
    for obj in processor:
        seen += 1
        if seen % 500000 == 0:
            log(f"osm scan {seen}  buildings {len(buildings_ll)}  roads {len(roads)}  water {len(waters_ll)}")
        try:
            if obj.is_area():
                tags = obj.tags
                kind = tags.get("building")
                if kind and kind != "no" and tags.get("location") not in {"underground", "indoor"}:
                    outer = None
                    for ring in obj.outer_rings():
                        outer = _ring_nodes(ring)
                        if outer is not None:
                            break
                    if outer is None:
                        continue
                    height = parse_metres(tags.get("height"))
                    if height is None:
                        height = parse_metres(tags.get("building:height"))
                    if height is None:
                        height = parse_metres(tags.get("est_height"))
                    if height is None:
                        height = parse_levels(tags.get("building:levels"))
                    buildings_ll.append(outer)
                    building_meta.append((kind, height))
                elif (
                    tags.get("natural") == "water"
                    or tags.get("landuse") in {"reservoir", "basin"}
                    or tags.get("water") in {"lake", "reservoir", "pond", "canal", "river"}
                ):
                    for ring in obj.outer_rings():
                        outer = _ring_nodes(ring)
                        if outer is not None and len(outer) <= 8000:
                            waters_ll.append(outer)
                            break
            elif obj.is_way():
                tags = obj.tags
                highway = tags.get("highway")
                if highway in ROAD_CLASS_SET:
                    line = _way_nodes(obj)
                    if line is None:
                        continue
                    lanes = None
                    if tags.get("lanes"):
                        try:
                            lanes = max(1, int(float(str(tags.get("lanes")).split(";")[0])))
                        except ValueError:
                            lanes = None
                    layer = _layer_value(tags)
                    tunnel = _truthy(tags.get("tunnel")) or layer < 0
                    bridge = _truthy(tags.get("bridge")) or layer > 0
                    roads.append(
                        {
                            "ll": line,
                            "highway": highway,
                            "lanes": lanes,
                            "tunnel": tunnel and not bridge,
                            "bridge": bridge and not tunnel,
                            "layer": layer,
                        }
                    )
                elif tags.get("natural") == "coastline":
                    line = _way_nodes(obj)
                    if line is None:
                        continue
                    if len(line) > 1600:
                        line = line[:: max(1, len(line) // 1200)]
                    coasts.append(line)
        except Exception:
            continue
    log(
        f"osm done records {seen}  buildings {len(buildings_ll)}  roads {len(roads)}  "
        f"water {len(waters_ll)}  coast {len(coasts)}"
    )
    return {
        "buildings_ll": buildings_ll,
        "building_meta": building_meta,
        "roads": roads,
        "waters_ll": waters_ll,
        "coasts": coasts,
    }


def _batch_project(warp, rings: list[np.ndarray]) -> list[np.ndarray]:
    if not rings:
        return []
    counts = np.array([len(ring) for ring in rings], dtype=np.int64)
    lon = np.concatenate([ring[:, 0] for ring in rings])
    lat = np.concatenate([ring[:, 1] for ring in rings])
    gx, gy = warp.lonlat_to_game_m(lon, lat)
    out = []
    cursor = 0
    for count in counts:
        out.append(np.column_stack([gx[cursor : cursor + count], gy[cursor : cursor + count]]))
        cursor += int(count)
    return out


def _simplify_ring(ring: np.ndarray, tolerance: float, limit: int) -> np.ndarray:
    ring = ensure_ccw(clean_ring(ring, 0.15))
    if len(ring) > limit:
        closed = np.vstack([ring, ring[:1]])
        ring = douglas_peucker(closed, tolerance)[:-1]
        ring = ensure_ccw(clean_ring(ring, 0.15))
    if len(ring) > limit:
        ring = ring[:: max(1, int(math.ceil(len(ring) / limit)))]
        ring = ensure_ccw(clean_ring(ring, 0.05))
    return ring


def _color_for(kind: str, jitter: float) -> tuple[float, float, float]:
    base = COLOR_BY_KIND.get(kind, (0.68, 0.64, 0.58))
    scale = 0.88 + 0.24 * jitter
    return tuple(float(np.clip(channel * scale, 0.15, 0.95)) for channel in base)


def _jitter(cx: float, cy: float) -> float:
    digest = hashlib.md5(f"{cx:.2f},{cy:.2f}".encode("ascii")).digest()
    return int.from_bytes(digest[:2], "little") / 65535.0


def _heuristic_height(kind: str, horizontal: float) -> float:
    if kind in {"yes", "building"}:
        return 42.0 if horizontal >= 0.40 else 16.0
    if kind in HEIGHT_BY_KIND:
        return HEIGHT_BY_KIND[kind]
    return 24.0 if horizontal >= 0.40 else 12.0


def prepare_buildings(warp, extracted, bounds, log: Log) -> list[dict]:
    log("projecting buildings")
    rings = _batch_project(warp, extracted["buildings_ll"])
    pending = []
    for ring, meta in zip(rings, extracted["building_meta"]):
        if len(ring) < 3:
            continue
        min_xy = ring.min(axis=0)
        max_xy = ring.max(axis=0)
        if max_xy[0] < bounds[0] or min_xy[0] > bounds[2] or max_xy[1] < bounds[1] or min_xy[1] > bounds[3]:
            continue
        area = abs(signed_area(ring))
        if area < 4.0:
            continue
        pending.append((ring, meta, area, float(ring[:, 0].mean()), float(ring[:, 1].mean())))
    log(f"building centroids to scale {len(pending)}")
    if pending:
        cx = np.array([item[3] for item in pending])
        cy = np.array([item[4] for item in pending])
        rx, ry = warp.game_to_real_m(cx, cy)
        dx, dy = warp.axis_scales(rx, ry)
        horizontal_all = np.sqrt(np.maximum(dx, 1e-6) * np.maximum(dy, 1e-6))
    else:
        horizontal_all = np.zeros(0)
    kept = []
    dropped_area = 0
    for (ring, (kind, tagged_height), area, cx, cy), horizontal in zip(pending, horizontal_all):
        horizontal = float(horizontal)
        real_area = area / max(horizontal * horizontal, 1e-4)
        if real_area < 12.0:
            dropped_area += 1
            continue
        ring = _simplify_ring(ring, 1.1, 12)
        if len(ring) < 3 or abs(signed_area(ring)) < 4.0:
            dropped_area += 1
            continue
        if tagged_height is None:
            real_h = _heuristic_height(kind, horizontal)
        else:
            real_h = min(tagged_height, 520.0)
        jitter = _jitter(cx, cy)
        real_h *= 0.85 + 0.30 * jitter
        height_scale = float(np.clip(math.sqrt(max(horizontal, 1e-4)), 0.20, 1.25))
        game_h = float(np.clip(real_h * height_scale, 4.0, 600.0))
        kept.append(
            {
                "ring": ring,
                "kind": kind,
                "height": game_h,
                "horizontal": horizontal,
                "area": abs(signed_area(ring)),
                "cx": float(ring[:, 0].mean()),
                "cy": float(ring[:, 1].mean()),
                "color": _color_for(kind, jitter),
            }
        )
    log(f"buildings inside map {len(kept)}  dropped small {dropped_area}")
    merged = _merge_small(kept, log)
    culled = _cull_overlaps(merged, log)
    return culled


def _merge_small(buildings: list[dict], log: Log) -> list[dict]:
    cells: dict[tuple, list] = defaultdict(list)
    kept = []
    for building in buildings:
        suburban = building["horizontal"] < 0.25 and building["area"] < 200.0 and building["height"] < 36.0
        small = building["area"] < 45.0 and building["height"] < 28.0
        if not small and not suburban:
            kept.append(building)
            continue
        cell = 16.0 if building["horizontal"] < 0.25 else 10.0
        key = (round(building["cx"] / cell), round(building["cy"] / cell), cell)
        cells[key].append(building)
    merged = 0
    for group in cells.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        points = np.vstack([item["ring"] for item in group])
        min_xy = points.min(axis=0)
        max_xy = points.max(axis=0)
        if max_xy[0] - min_xy[0] < 2.0:
            max_xy[0] = min_xy[0] + 2.0
        if max_xy[1] - min_xy[1] < 2.0:
            max_xy[1] = min_xy[1] + 2.0
        ring = np.array(
            [[min_xy[0], min_xy[1]], [max_xy[0], min_xy[1]], [max_xy[0], max_xy[1]], [min_xy[0], max_xy[1]]],
            dtype=np.float64,
        )
        tallest = max(group, key=lambda item: item["height"])
        kept.append(
            {
                "ring": ring,
                "kind": tallest["kind"],
                "height": tallest["height"],
                "horizontal": tallest["horizontal"],
                "area": abs(signed_area(ring)),
                "cx": float(ring[:, 0].mean()),
                "cy": float(ring[:, 1].mean()),
                "color": tallest["color"],
            }
        )
        merged += len(group) - 1
    log(f"merged {merged} small buildings -> {len(kept)} footprints")
    return kept


def _cull_overlaps(buildings: list[dict], log: Log) -> list[dict]:
    grid = defaultdict(list)
    for index, building in enumerate(buildings):
        grid[(int(math.floor(building["cx"] / 40.0)), int(math.floor(building["cy"] / 40.0)))].append(index)
    drop = set()
    for index, building in enumerate(buildings):
        if index in drop:
            continue
        cx = int(math.floor(building["cx"] / 40.0))
        cy = int(math.floor(building["cy"] / 40.0))
        for ix in range(cx - 1, cx + 2):
            for iy in range(cy - 1, cy + 2):
                for other_index in grid.get((ix, iy), []):
                    if other_index <= index or other_index in drop:
                        continue
                    other = buildings[other_index]
                    if building["area"] >= other["area"]:
                        larger, smaller, smaller_index = building, other, other_index
                    else:
                        larger, smaller, smaller_index = other, building, index
                    if smaller["height"] > larger["height"] + 1.0:
                        continue
                    if point_in_ring(np.array([smaller["cx"], smaller["cy"]]), larger["ring"]):
                        drop.add(smaller_index)
                        if smaller_index == index:
                            break
                if index in drop:
                    break
    kept = [building for index, building in enumerate(buildings) if index not in drop]
    log(f"overlap cull dropped {len(drop)}  remaining {len(kept)}")
    return kept


def _landscape_shape(extent: dict, config: dict) -> dict:
    margin = float(config["map_margin_m"])
    min_x = extent["min_x_m"] - margin
    max_x = extent["max_x_m"] + margin
    min_y = extent["min_y_m"] - margin
    max_y = extent["max_y_m"] + margin
    quads = int(config["landscape_quads_per_section"])
    target = float(config["landscape_target_spacing_m"])
    comp_x = max(1, int(round((max_x - min_x) / (target * quads))))
    comp_y = max(1, int(round((max_y - min_y) / (target * quads))))
    verts_x = comp_x * quads + 1
    verts_y = comp_y * quads + 1
    spacing_x = (max_x - min_x) / (verts_x - 1)
    spacing_y = (max_y - min_y) / (verts_y - 1)
    return {
        "min_x": min_x,
        "max_x": min_x + spacing_x * (verts_x - 1),
        "min_y": min_y,
        "max_y": min_y + spacing_y * (verts_y - 1),
        "spacing_x": spacing_x,
        "spacing_y": spacing_y,
        "verts_x": verts_x,
        "verts_y": verts_y,
        "components_x": comp_x,
        "components_y": comp_y,
        "quads_per_section": quads,
        "sections_per_component": int(config["landscape_sections_per_component"]),
        "z_scale_cm": int(config["landscape_z_scale_cm"]),
    }


def _invert_columns(warp, xs: np.ndarray, ys: np.ndarray, log: Log) -> tuple[np.ndarray, np.ndarray]:
    x_real = np.asarray(warp._invert_lut(warp.x0, warp.x_step, warp.G, xs), dtype=np.float64)
    y_lo = -45000.0
    y_hi = 55000.0
    samples = np.linspace(y_lo, y_hi, 4800)
    y_real = np.empty((len(ys), len(xs)), dtype=np.float32)
    chunk = 200
    for start in range(0, len(xs), chunk):
        end = min(len(xs), start + chunk)
        xr = x_real[start:end]
        _, gy = warp.real_to_game_m(xr[:, None], samples[None, :])
        gy = np.maximum.accumulate(np.asarray(gy, dtype=np.float64), axis=1)
        gy[:, 1:] = np.maximum(gy[:, 1:], gy[:, :-1] + 1e-4)
        for local in range(end - start):
            y_real[:, start + local] = np.interp(ys, gy[local], samples).astype(np.float32)
        if start % 800 == 0:
            log(f"inverse warp columns {end}/{len(xs)}")
    return x_real.astype(np.float32), y_real


def build_terrain(warp, grids, landscape, log: Log, land=None, extract=None) -> tuple[np.ndarray, np.ndarray]:
    """Height grid (row 0 = south) and the land mask it was built from.

    With `land`/`extract` the OSM coastline decides land and sea inside the
    extract polygon; outside it, and without them, SRTM above DEM_SEA_M is land.
    """
    from scipy.ndimage import distance_transform_edt, gaussian_filter

    nx = landscape["verts_x"]
    ny = landscape["verts_y"]
    xs = landscape["min_x"] + np.arange(nx) * landscape["spacing_x"]
    ys = landscape["min_y"] + np.arange(ny) * landscape["spacing_y"]
    log(f"terrain grid {nx} x {ny}  spacing {landscape['spacing_x']:.2f} x {landscape['spacing_y']:.2f} m")
    x_real, y_real = _invert_columns(warp, xs, ys, log)
    height = np.empty((ny, nx), dtype=np.float32)
    is_land = np.empty((ny, nx), dtype=bool)
    rows = 160
    for start in range(0, ny, rows):
        end = min(ny, start + rows)
        yr = y_real[start:end]
        lon = np.broadcast_to(warp.origin_lon + x_real[None, :] / warp.m_per_deg_lon, yr.shape)
        lat = warp.origin_lat + yr / warp.m_per_deg_lat
        elev = sample_srtm(grids, lon, lat).astype(np.float32)
        dx, dy = warp.axis_scales(
            np.broadcast_to(x_real, yr.shape).astype(np.float64),
            yr.astype(np.float64),
        )
        horizontal = np.sqrt(np.maximum(dx, 1e-6) * np.maximum(dy, 1e-6))
        height_scale = np.clip(np.sqrt(horizontal), 0.20, 1.25).astype(np.float32)
        if land is not None:
            chunk_land = coastmask.land_at(land, extract, lon, lat, dem_elev=elev, dem_land_m=DEM_SEA_M)
        else:
            chunk_land = elev > DEM_SEA_M
        is_land[start:end] = chunk_land
        height[start:end] = np.where(chunk_land, np.maximum(elev * height_scale, LAND_MIN_M), np.minimum(elev, 0.0) * 0.35)
        if start % 640 == 0:
            log(f"sampled elevation rows {end}/{ny}")
    # Continental shelf: -SEABED_DROP_M at the shore, easing to -SHELF_DEPTH_M offshore.
    dist = distance_transform_edt(~is_land, sampling=(landscape["spacing_y"], landscape["spacing_x"])).astype(np.float32)
    shelf = -(SEABED_DROP_M + (SHELF_DEPTH_M - SEABED_DROP_M) * (1.0 - np.exp(-np.maximum(dist - landscape["spacing_x"], 0.0) / SHELF_FALLOFF_M)))
    height = np.where(is_land, height, np.minimum(height, shelf)).astype(np.float32)
    height = gaussian_filter(height, sigma=0.7).astype(np.float32)
    # Smoothing must not move the shoreline: land stays above the sea plane,
    # sea stays at least SEABED_DROP_M under it so nothing pokes through the water.
    height = np.where(is_land, np.maximum(height, LAND_MIN_M), np.minimum(height, -SEABED_DROP_M)).astype(np.float32)
    log(f"land cells {int(is_land.sum())}  sea cells {int((~is_land).sum())} pushed to <= -{SEABED_DROP_M} m")
    return height, is_land


def bilinear(grid: np.ndarray, xs, ys, landscape) -> np.ndarray:
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    fx = np.clip((xs - landscape["min_x"]) / landscape["spacing_x"], 0.0, grid.shape[1] - 1.001)
    fy = np.clip((ys - landscape["min_y"]) / landscape["spacing_y"], 0.0, grid.shape[0] - 1.001)
    x0 = np.floor(fx).astype(np.int32)
    y0 = np.floor(fy).astype(np.int32)
    tx = (fx - x0).astype(np.float32)
    ty = (fy - y0).astype(np.float32)
    g00 = grid[y0, x0]
    g10 = grid[y0, np.minimum(x0 + 1, grid.shape[1] - 1)]
    g01 = grid[np.minimum(y0 + 1, grid.shape[0] - 1), x0]
    g11 = grid[np.minimum(y0 + 1, grid.shape[0] - 1), np.minimum(x0 + 1, grid.shape[1] - 1)]
    return (g00 * (1.0 - tx) + g10 * tx) * (1.0 - ty) + (g01 * (1.0 - tx) + g11 * tx) * ty


def prepare_roads(warp, extracted, height, landscape, log: Log) -> list[dict]:
    log(f"preparing {len(extracted['roads'])} roads")
    prepared = []
    wet_samples = 0
    for road in extracted["roads"]:
        ll = road["ll"]
        gx, gy = warp.lonlat_to_game_m(ll[:, 0], ll[:, 1])
        xy = np.column_stack([gx, gy])
        if len(xy) > 8:
            xy = douglas_peucker(xy, 2.5)
        xy = roadnet.resample(xy, roadnet.STEP_M)
        if len(xy) < 2:
            continue
        min_xy = xy.min(axis=0)
        max_xy = xy.max(axis=0)
        if max_xy[0] < landscape["min_x"] or min_xy[0] > landscape["max_x"]:
            continue
        if max_xy[1] < landscape["min_y"] or min_xy[1] > landscape["max_y"]:
            continue
        rx, ry = warp.game_to_real_m(float(xy[len(xy) // 2, 0]), float(xy[len(xy) // 2, 1]))
        horizontal = float(warp.horizontal_scale(rx, ry))
        terrain_z = np.asarray(bilinear(height, xy[:, 0], xy[:, 1], landscape), dtype=np.float64)
        real_step = np.hypot(np.diff(ll[:, 0]) * warp.m_per_deg_lon, np.diff(ll[:, 1]) * warp.m_per_deg_lat)
        real_length = float(real_step.sum())
        mode = "ground"
        if road["tunnel"] and real_length >= 90.0:
            mode = "tunnel"
        elif road["bridge"]:
            mode = "bridge"
        if mode == "ground":
            # A ground road whose samples land on seabed is a seawall, pier or
            # causeway thinner than the terrain grid: keep it at shore height.
            wet = terrain_z < LAND_MIN_M
            wet_samples += int(wet.sum())
            terrain_z = np.where(wet, LAND_MIN_M, terrain_z)
        prepared.append(roadnet.make_road(xy, terrain_z, road["highway"], road["lanes"], mode, road.get("layer", 0), horizontal))
    tunnels = sum(1 for road in prepared if road["mode"] == "tunnel")
    bridges = sum(1 for road in prepared if road["mode"] == "bridge")
    log(f"roads kept {len(prepared)}  bridges {bridges}  open-cut tunnels {tunnels}  ground samples lifted to shore {wet_samples}")
    return prepared


def _road_buffers(roads: list[dict], log: Log):
    """Drivable ribbon outlines (with their merged widths) plus 1.5 m, for cutting buildings."""
    import shapely

    rings = roadnet.edge_polygons(roads, 1.5)
    if not rings:
        return [], None
    log(f"outlining {len(rings)} drivable ribbons")
    polys = shapely.make_valid(np.asarray([shapely.polygons(ring) for ring in rings], dtype=object))
    buffers = [geom for geom in polys if geom is not None and not geom.is_empty]
    tree = shapely.STRtree(buffers)
    return buffers, tree


def cut_buildings(buildings: list[dict], buffers, tree, log: Log) -> list[dict]:
    import shapely

    if tree is None or not buildings:
        return buildings
    geoms = []
    for building in buildings:
        poly = shapely.polygons(np.asarray(building["ring"], dtype=np.float64))
        if poly is None or poly.is_empty:
            geoms.append(shapely.Polygon())
        elif not poly.is_valid:
            geoms.append(shapely.make_valid(poly))
        else:
            geoms.append(poly)
    hits: dict[int, list[int]] = defaultdict(list)
    batch = 3000
    for start in range(0, len(geoms), batch):
        chunk = geoms[start : start + batch]
        pairs = tree.query(chunk, predicate="intersects")
        if getattr(pairs, "size", 0) == 0:
            continue
        if pairs.ndim == 1:
            for buffer_index in np.atleast_1d(pairs):
                hits[start].append(int(buffer_index))
        else:
            for local, buffer_index in zip(pairs[0], pairs[1]):
                hits[start + int(local)].append(int(buffer_index))
        if start % 15000 == 0:
            log(f"road overlap query {min(start + batch, len(geoms))}/{len(geoms)}")
    log(f"buildings overlapping roads {len(hits)}")
    kept = []
    cut = 0
    removed = 0
    for index, building in enumerate(buildings):
        chosen = hits.get(index)
        if not chosen:
            kept.append(building)
            continue
        cutter = buffers[chosen[0]] if len(chosen) == 1 else shapely.union_all([buffers[item] for item in chosen])
        diff = shapely.difference(geoms[index], cutter)
        ring = largest_ring(diff)
        if ring is None or abs(signed_area(ring)) < 6.0:
            removed += 1
            continue
        ring = _simplify_ring(ring, 0.8, 14)
        if len(ring) < 3:
            removed += 1
            continue
        building = dict(building)
        building["ring"] = ring
        building["area"] = abs(signed_area(ring))
        building["cx"] = float(ring[:, 0].mean())
        building["cy"] = float(ring[:, 1].mean())
        kept.append(building)
        cut += 1
    log(f"cut {cut} footprints  removed {removed}  remaining {len(kept)}")
    return kept


def repair_rings(buildings: list[dict], log: Log) -> list[dict]:
    """Decimated footprints can cross themselves; their triangulated roofs and walls
    then spill over roads while point-in-polygon spawn checks miss them. Replace each
    self-intersecting ring with its largest valid part, or drop it."""
    import shapely

    kept = []
    fixed = dropped = 0
    for building in buildings:
        poly = shapely.polygons(np.asarray(building["ring"], dtype=np.float64))
        if poly.is_valid:
            kept.append(building)
            continue
        ring = largest_ring(shapely.make_valid(poly))
        if ring is not None:
            ring = largest_ring(shapely.simplify(shapely.polygons(ring), 0.3, preserve_topology=True))
        if ring is not None:
            ring = ensure_ccw(clean_ring(ring, 0.15))
        if ring is None or len(ring) < 3 or abs(signed_area(ring)) < 6.0 or not shapely.polygons(ring).is_valid:
            dropped += 1
            continue
        building = dict(building)
        building["ring"] = ring
        building["area"] = abs(signed_area(ring))
        building["cx"] = float(ring[:, 0].mean())
        building["cy"] = float(ring[:, 1].mean())
        kept.append(building)
        fixed += 1
    log(f"self-intersecting footprints repaired {fixed}  dropped {dropped}")
    return kept


def assign_building_z(buildings: list[dict], surface_at, log: Log) -> list[dict]:
    """Base each building on the lowest landscape point under its footprint so no
    wall floats on a slope; keep the roof where the centroid rule put it."""
    if not buildings:
        return []
    kept = []
    dropped = 0
    for building in buildings:
        ring = np.asarray(building["ring"], dtype=np.float64)
        xs = np.append(ring[:, 0], building["cx"])
        ys = np.append(ring[:, 1], building["cy"])
        zs = surface_at(xs, ys)
        centre = float(zs[-1])
        # Open water sits SEABED_DROP_M lower than it used to, so this is the
        # old "centre below -0.5 m" rule shifted by the same amount.
        if centre < -0.5 - SEABED_DROP_M:
            dropped += 1
            continue
        top = max(centre, 0.2) + float(building["height"])
        base = max(float(zs.min()), -3.0)
        building = dict(building)
        building["z"] = base
        building["height"] = top - base
        kept.append(building)
    log(f"buildings on land {len(kept)}  dropped in water {dropped}")
    return kept


def prepare_water(warp, extracted, height, landscape, log: Log) -> list[dict]:
    if not extracted["waters_ll"]:
        return []
    log(f"projecting water {len(extracted['waters_ll'])}")
    rings = _batch_project(warp, extracted["waters_ll"])
    kept = []
    for ring in rings:
        if len(ring) < 3:
            continue
        area = abs(signed_area(ring))
        if area < 80.0 or area > 1.5e6:
            continue
        ring = _simplify_ring(ring, 6.0, 48)
        if len(ring) < 3:
            continue
        cx = float(ring[:, 0].mean())
        cy = float(ring[:, 1].mean())
        if cx < landscape["min_x"] or cx > landscape["max_x"] or cy < landscape["min_y"] or cy > landscape["max_y"]:
            continue
        z = float(bilinear(height, cx, cy, landscape))
        if z < 1.5:
            continue
        kept.append({"ring": ring, "z": z + 0.15})
    log(f"inland water polygons {len(kept)}")
    return kept


def _tile_index(x: float, y: float, landscape, tile: float) -> tuple[int, int]:
    ix = int(math.floor((x - landscape["min_x"]) / tile))
    iy = int(math.floor((y - landscape["min_y"]) / tile))
    max_ix = max(0, int(math.floor((landscape["max_x"] - landscape["min_x"] - 1e-3) / tile)))
    max_iy = max(0, int(math.floor((landscape["max_y"] - landscape["min_y"] - 1e-3) / tile)))
    return max(0, min(max_ix, ix)), max(0, min(max_iy, iy))


def _road_tile_prims(ribbons: list[dict], landscape, tile: float) -> dict:
    """Split the world-space ribbons into one road primitive per tile by triangle centroid."""
    if not ribbons:
        return {}
    verts, uvs, alphas, tris = [], [], [], []
    base = 0
    for rib in ribbons:
        verts.append(rib["verts"])
        uvs.append(rib["uv"])
        alphas.append(np.full(len(rib["verts"]), rib["alpha"]))
        tris.append(rib["tris"] + base)
        base += len(rib["verts"])
    verts = np.concatenate(verts)
    uvs = np.concatenate(uvs)
    alphas = np.concatenate(alphas)
    tris = np.concatenate(tris)
    centroid = verts[tris].mean(axis=1)
    max_ix = max(0, int(math.floor((landscape["max_x"] - landscape["min_x"] - 1e-3) / tile)))
    max_iy = max(0, int(math.floor((landscape["max_y"] - landscape["min_y"] - 1e-3) / tile)))
    tix = np.clip(np.floor((centroid[:, 0] - landscape["min_x"]) / tile).astype(np.int64), 0, max_ix)
    tiy = np.clip(np.floor((centroid[:, 1] - landscape["min_y"]) / tile).astype(np.int64), 0, max_iy)
    key = tix * 100000 + tiy
    order = np.argsort(key, kind="stable")
    key_sorted = key[order]
    starts = np.flatnonzero(np.r_[True, key_sorted[1:] != key_sorted[:-1]])
    ends = np.r_[starts[1:], len(order)]
    out = {}
    for start, end in zip(starts, ends):
        ix, iy = int(key_sorted[start] // 100000), int(key_sorted[start] % 100000)
        ox = landscape["min_x"] + ix * tile
        oy = landscape["min_y"] + iy * tile
        tile_tris = tris[order[start:end]]
        used, local = np.unique(tile_tris, return_inverse=True)
        local = local.reshape(-1, 3)
        v = verts[used]
        gl = np.column_stack([v[:, 0] - ox, v[:, 2], v[:, 1] - oy])
        color = np.empty((len(used), 4), dtype=np.float32)
        color[:, :3] = (0.85, 0.85, 0.82)
        color[:, 3] = alphas[used]
        out[(ix, iy)] = {
            "positions": gl.astype(np.float32),
            "normals": roadnet.vertex_normals_gltf(gl, local).astype(np.float32),
            "uvs": uvs[used].astype(np.float32),
            "colors": color,
            "indices": local.reshape(-1).astype(np.uint32),
            "material": 1,
        }
    return out


def _write_tile_meshes(tile_dir: Path, tiles: dict, roads, waters, landscape, tile: float, log: Log) -> dict:
    road_tiles = _road_tile_prims(roads, landscape, tile)
    water_index = defaultdict(list)
    for water in waters:
        ix, iy = _tile_index(float(water["ring"][:, 0].mean()), float(water["ring"][:, 1].mean()), landscape, tile)
        water_index[(ix, iy)].append(water)
    keys = set(tiles) | set(road_tiles) | set(water_index)
    records = []
    tris = 0
    written = 0
    for index, (ix, iy) in enumerate(sorted(keys)):
      try:
        origin = (landscape["min_x"] + ix * tile, landscape["min_y"] + iy * tile)
        record = {"ix": ix, "iy": iy, "origin_x_m": origin[0], "origin_y_m": origin[1]}
        buildings = tiles.get((ix, iy), [])
        if buildings:
            prims = []
            for building in buildings:
                accum = MeshAccum()
                if append_extrusion(
                    accum,
                    building["ring"],
                    building["z"],
                    building["z"] + building["height"],
                    building["color"],
                    origin,
                ):
                    prim = accum.primitive(0)
                    if prim is not None:
                        prims.append(prim)
            if prims:
                path = tile_dir / f"b_{ix}_{iy}.glb"
                write_glb(path, prims)
                record["buildings"] = f"tiles/{path.name}"
                tris += sum(len(prim["indices"]) // 3 for prim in prims)
        prim = road_tiles.get((ix, iy))
        if prim is not None:
            path = tile_dir / f"r_{ix}_{iy}.glb"
            write_glb(path, [prim])
            record["roads"] = f"tiles/{path.name}"
            tris += len(prim["indices"]) // 3
        accum = MeshAccum()
        for water in water_index.get((ix, iy), []):
            append_extrusion(
                accum,
                water["ring"],
                water["z"],
                water["z"] + 0.4,
                (0.25, 0.45, 0.55),
                origin,
                min_height=0.35,
            )
        prim = accum.primitive(2)
        if prim is not None:
            path = tile_dir / f"w_{ix}_{iy}.glb"
            write_glb(path, [prim])
            record["water"] = f"tiles/{path.name}"
            tris += len(prim["indices"]) // 3
        if "buildings" in record or "roads" in record or "water" in record:
            records.append(record)
            written += 1
        if index and index % 400 == 0:
            log(f"wrote tiles {index}/{len(keys)}")
      except Exception:
            log(f"tile {ix},{iy} failed\n" + traceback.format_exc())
    log(f"tile files referenced {written}  triangles {tris}")
    return {"tiles": records, "triangles": tris}


def _find_pad(x: float, y: float, height: np.ndarray, landscape) -> tuple[float, float, float]:
    spacing = landscape["spacing_x"]
    radius = 300.0
    ix = int(round((x - landscape["min_x"]) / landscape["spacing_x"]))
    iy = int(round((y - landscape["min_y"]) / landscape["spacing_y"]))
    reach = int(radius / spacing)
    best = None
    best_d = 1.0e18
    ny, nx = height.shape
    for row in range(max(1, iy - reach), min(ny - 1, iy + reach)):
        for col in range(max(1, ix - reach), min(nx - 1, ix + reach)):
            z = float(height[row, col])
            if z < 1.0 or z > 40.0:
                continue
            slope = max(
                abs(float(height[row, col] - height[row + 1, col])),
                abs(float(height[row, col] - height[row, col + 1])),
                abs(float(height[row, col] - height[row - 1, col])),
                abs(float(height[row, col] - height[row, col - 1])),
            )
            if slope > 2.5:
                continue
            px = landscape["min_x"] + col * landscape["spacing_x"]
            py = landscape["min_y"] + row * landscape["spacing_y"]
            dist = (px - x) ** 2 + (py - y) ** 2
            if dist < best_d:
                best_d = dist
                best = (px, py, z)
    if best is not None:
        return best
    z = float(bilinear(height, x, y, landscape))
    return x, y, max(z, 1.0)


def build_land_mask(root: Path, pbf: Path, extracted, grids, log: Log):
    """OSM land polygon (lon/lat) inside the extract polygon, minus sea-level water.

    OSM water polygons that sit at sea level in SRTM (tidal channels, nullahs,
    fish ponds) become sea so the sea plane shows in them; raised reservoirs
    stay land and get their own water plane from prepare_water.
    """
    import shapely

    poly_path = root / "data" / "config" / "hong-kong.poly"
    extract = coastmask.read_poly(poly_path)
    coastlines = coastmask.load_coastlines(pbf)
    land, stats = coastmask.build_land(coastlines, extract)
    log(
        f"coastline ways {stats['coastline_ways']}  faces {stats['faces']}  land {stats['land_faces']}  "
        f"sea {stats['sea_faces']}  unlabelled {stats['unlabelled_faces']}"
    )
    low = []
    for ring in extracted["waters_ll"]:
        if len(ring) < 4:
            continue
        poly = shapely.make_valid(shapely.Polygon(ring))
        if poly.is_empty or poly.area <= 0.0:
            continue
        probe = shapely.get_coordinates(shapely.point_on_surface(poly))
        elev = float(sample_srtm(grids, probe[:, 0], probe[:, 1])[0])
        if elev <= DEM_SEA_M:
            low.append(poly)
    if low:
        land = shapely.difference(land, shapely.union_all(low))
    km2 = shapely.area(land) * (111_320.0 * 110_570.0 * math.cos(math.radians(22.35))) / 1e6
    log(f"land mask {km2:.1f} km^2 inside extract  sea-level water polygons {len(low)}")
    stats["land_km2_in_extract"] = round(km2, 1)
    stats["sea_level_water_polygons"] = len(low)
    return land, extract, stats


def write_land_mask(out: Path, config, land, extract, grids, log: Log):
    """North-up lon/lat land raster over the map bounds, for check_map and tools."""
    b = config["bounds"]
    lons = np.arange(b["min_lon"], b["max_lon"] + MASK_STEP_DEG * 0.5, MASK_STEP_DEG)
    lats = np.arange(b["min_lat"], b["max_lat"] + MASK_STEP_DEG * 0.5, MASK_STEP_DEG)
    mask = np.empty((len(lats), len(lons)), dtype=bool)
    rows = 400
    for start in range(0, len(lats), rows):
        lat = lats[start : start + rows]
        lon_g, lat_g = np.meshgrid(lons, lat)
        mask[start : start + rows] = coastmask.land_at(
            land, extract, lon_g, lat_g, dem_elev=sample_srtm(grids, lon_g, lat_g), dem_land_m=DEM_SEA_M
        )
    bounds = {"min_lon": float(lons[0]), "min_lat": float(lats[0]), "max_lon": float(lons[-1]), "max_lat": float(lats[-1])}
    coastmask.write_mask(out, mask, bounds, MASK_STEP_DEG)
    log(f"land mask {mask.shape[1]} x {mask.shape[0]}  land {mask.mean() * 100:.1f}%")
    return coastmask.LandMask(out)


def coast_agreement(stored: np.ndarray, is_land: np.ndarray, landscape, warp, extract, spawns, log: Log) -> dict:
    """How well the stored terrain matches the OSM land/sea mask on the landscape grid."""
    from tools.pipeline.check_coast import agreement

    import shapely

    lon, lat = _vertex_lonlat(warp, landscape)
    inside = coastmask.land_at(shapely.box(-180, -90, 180, 90), extract, lon, lat)
    result = agreement(stored, is_land, inside=inside)
    wet = []
    for group in ("cars", "helicopters"):
        for item in spawns.get(group, []):
            if not _land_at_game(is_land, landscape, item["x_m"], item["y_m"]):
                wet.append(item["id"])
    player = spawns.get("player")
    if player and not _land_at_game(is_land, landscape, player["x_m"], player["y_m"]):
        wet.append(player["id"])
    result["spawns_over_sea"] = wet
    log(
        f"coast agreement: OSM sea below 0 {result['sea_below_0_pct']}%  <= -{SEABED_DROP_M:g} m {result['sea_below_seabed_pct']}%  "
        f"OSM land above 0 {result['land_above_0_pct']}%  spawns over sea {len(wet)}"
    )
    return result


def _vertex_lonlat(warp, landscape):
    xs = landscape["min_x"] + np.arange(landscape["verts_x"]) * landscape["spacing_x"]
    ys = landscape["min_y"] + np.arange(landscape["verts_y"]) * landscape["spacing_y"]
    x_real, y_real = _invert_columns(warp, xs, ys, lambda *_: None)
    lon = np.broadcast_to(warp.origin_lon + x_real[None, :] / warp.m_per_deg_lon, y_real.shape)
    return lon, warp.origin_lat + y_real / warp.m_per_deg_lat


def _open_sea_grid(is_land: np.ndarray, landscape, fringe_cells: float = 2.0) -> np.ndarray:
    """Sea vertices more than `fringe_cells` grid steps from OSM land."""
    from scipy.ndimage import distance_transform_edt

    return distance_transform_edt(~is_land) > fringe_cells


def _land_at_game(is_land: np.ndarray, landscape, x: float, y: float) -> bool:
    i = int(round((x - landscape["min_x"]) / landscape["spacing_x"]))
    j = int(round((y - landscape["min_y"]) / landscape["spacing_y"]))
    i = min(max(i, 0), is_land.shape[1] - 1)
    j = min(max(j, 0), is_land.shape[0] - 1)
    return bool(is_land[j, i])


def _draw_minimap(path: Path, height: np.ndarray, landscape, roads, places, is_land=None, waters=()) -> dict:
    from PIL import Image, ImageDraw

    ny, nx = height.shape
    aspect = (landscape["max_x"] - landscape["min_x"]) / max(landscape["max_y"] - landscape["min_y"], 1.0)
    if aspect >= 1.0:
        width, img_h = 2048, max(64, int(round(2048 / aspect)))
    else:
        img_h, width = 2048, max(64, int(round(2048 * aspect)))
    # North is the last row of the south-up height grid.
    sample_y = np.linspace(ny - 1, 0, img_h)
    sample_x = np.linspace(0, nx - 1, width)
    sy = np.clip(np.rint(sample_y).astype(np.int32), 0, ny - 1)
    sx = np.clip(np.rint(sample_x).astype(np.int32), 0, nx - 1)
    sampled = height[sy][:, sx]
    rgb = np.empty((img_h, width, 3), dtype=np.uint8)
    # The coastline mask, not the height, decides what is sea.
    sea = ~is_land[sy][:, sx] if is_land is not None else sampled < 0.25
    low = ~sea & (sampled < 40.0)
    mid = ~sea & (sampled >= 40.0) & (sampled < 220.0)
    high = ~sea & (sampled >= 220.0)
    rgb[sea] = (28, 78, 102)
    rgb[low] = (92, 110, 84)
    rgb[mid] = (70, 108, 72)
    rgb[high] = (150, 146, 138)
    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)

    def to_px(x, y):
        u = (x - landscape["min_x"]) / (landscape["max_x"] - landscape["min_x"])
        v = (landscape["max_y"] - y) / (landscape["max_y"] - landscape["min_y"])
        return u * (width - 1), v * (img_h - 1)

    for water in waters:
        ring = [to_px(float(x), float(y)) for x, y in water["ring"]]
        if len(ring) >= 3:
            draw.polygon(ring, fill=(40, 96, 124))
    for road in roads:
        color = ROAD_DRAW.get(road["highway"], (140, 140, 140))
        center = road["center"]
        stride = 1 if len(center) < 80 else 2
        points = [to_px(center[i, 0], center[i, 1]) for i in range(0, len(center), stride)]
        if len(points) >= 2:
            draw.line(points, fill=color, width=1)
    for place in places:
        if place.get("kind") == "helipad":
            continue
        px, py = to_px(place["x_m"], place["y_m"])
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=(220, 70, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    return {
        "file": path.name,
        "min_x_m": landscape["min_x"],
        "max_x_m": landscape["max_x"],
        "min_y_m": landscape["min_y"],
        "max_y_m": landscape["max_y"],
        "width_px": width,
        "height_px": img_h,
    }


def _write_previews(preview_dir: Path, warp, height, landscape, roads, coasts, places, harbour_rows, log: Log) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    preview_dir.mkdir(parents=True, exist_ok=True)
    written = []
    bounds = warp.config["bounds"]
    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], 180)
    lats = np.linspace(bounds["min_lat"], bounds["max_lat"], 140)
    lon_g, lat_g = np.meshgrid(lons, lats)
    rx, ry = warp.lonlat_to_real_m(lon_g, lat_g)
    scale = warp.horizontal_scale(rx, ry)
    fig, ax = plt.subplots(figsize=(9, 7))
    mesh = ax.pcolormesh(lons, lats, scale, shading="auto", cmap="viridis")
    fig.colorbar(mesh, ax=ax, label="horizontal scale")
    ax.set_title("Horizontal scale (game metres / real metres)")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    fig.tight_layout()
    path = preview_dir / "scale_field.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    written.append(path.name)

    fig, ax = plt.subplots(figsize=(9, 4))
    if harbour_rows:
        ax.plot([row["lon"] for row in harbour_rows], [row["game_width_m"] for row in harbour_rows], color="#1f4e79")
        ax.axhline(1000.0, color="#aa3333", linestyle="--", label="1 km")
        ax.legend()
    ax.set_title("Victoria Harbour game width")
    ax.set_xlabel("lon")
    ax.set_ylabel("metres")
    fig.tight_layout()
    path = preview_dir / "harbour_width.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    written.append(path.name)

    shade = height[::3, ::3]
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.imshow(
        shade,
        origin="lower",
        cmap="terrain",
        extent=[landscape["min_x"], landscape["max_x"], landscape["min_y"], landscape["max_y"]],
    )
    ax.set_title("Warped terrain (game metres, +X east, +Y north)")
    ax.set_aspect("equal")
    fig.tight_layout()
    path = preview_dir / "relief.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    written.append(path.name)

    fig, ax = plt.subplots(figsize=(9, 8))
    for line in coasts[::2]:
        if len(line) < 2:
            continue
        gx, gy = warp.lonlat_to_game_m(line[:, 0], line[:, 1])
        ax.plot(gx, gy, color="#8eb4c8", linewidth=0.4)
    for road in roads[::2]:
        center = road["center"]
        ax.plot(center[::2, 0], center[::2, 1], color="#444444", linewidth=0.3)
    for place in places:
        if place.get("kind") == "helipad":
            continue
        ax.scatter([place["x_m"]], [place["y_m"]], s=8, c="#cc3333")
        ax.text(place["x_m"] + 80, place["y_m"] + 80, place["id"], fontsize=6)
    ax.set_aspect("equal")
    ax.set_title("Roads, coastline, districts")
    fig.tight_layout()
    path = preview_dir / "network.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    written.append(path.name)
    log("previews " + ", ".join(written))
    return written


def _run_native_check(root: Path, log: Log) -> dict:
    binary = Path("/tmp/test_hk_warp")
    source = root / "tools" / "tests" / "test_hk_warp.cpp"
    compile_cmd = [
        "g++",
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-I",
        str(root / "shared"),
        "-o",
        str(binary),
        str(source),
    ]
    try:
        compiled = subprocess.run(compile_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        log("native warp check skipped: g++ is not installed")
        return {"compiled": False, "ok": False, "stderr": "g++ not found"}
    if compiled.returncode != 0:
        log("native warp compile failed\n" + compiled.stderr)
        return {"compiled": False, "ok": False, "stderr": compiled.stderr[-2000:]}
    ran = subprocess.run(
        [str(binary), str(root / "data" / "processed" / "warp_lut.bin"), str(root / "data" / "processed" / "golden_warp.csv")],
        capture_output=True,
        text=True,
    )
    log(ran.stdout.strip())
    if ran.returncode != 0:
        log(ran.stderr.strip())
    return {"compiled": True, "ok": ran.returncode == 0, "stdout": ran.stdout.strip(), "stderr": ran.stderr.strip()}


def _place_scales(warp, config) -> list[dict]:
    rows = []
    for place in config["places"]:
        if place.get("kind") == "helipad":
            continue
        rx, ry = warp.lonlat_to_real_m(place["lon"], place["lat"])
        dx, dy = warp.axis_scales(rx, ry)
        rows.append(
            {
                "id": place["id"],
                "scale_x": float(dx),
                "scale_y": float(dy),
                "horizontal": float(math.sqrt(max(float(dx), 1e-6) * max(float(dy), 1e-6))),
            }
        )
    return rows


def build_real(root: Path, config, warp, out: Path, log: Log) -> dict:
    raw = root / "data" / "raw" / "hong-kong-latest.osm.pbf"
    extracted = extract_osm(raw, log)
    extent = warp.geographic_extent_m()
    landscape = _landscape_shape(extent, config)
    bounds = (landscape["min_x"], landscape["min_y"], landscape["max_x"], landscape["max_y"])
    buildings = prepare_buildings(warp, extracted, bounds, log)
    grids = load_srtm(root / "data" / "raw")
    land, extract, coast_stats = build_land_mask(root, raw, extracted, grids, log)
    height, is_land = build_terrain(warp, grids, landscape, log, land, extract)
    roads = prepare_roads(warp, extracted, height, landscape, log)
    roads = roadnet.merge_parallel(roads, log)
    roadnet.set_design_profiles(roads)
    roads = roadnet.bridge_over_trenches(roads, log)
    open_sea = _open_sea_grid(is_land, landscape)

    def open_sea_at(xs, ys):
        i = np.clip(np.rint((np.asarray(xs) - landscape["min_x"]) / landscape["spacing_x"]).astype(np.int64), 0, open_sea.shape[1] - 1)
        j = np.clip(np.rint((np.asarray(ys) - landscape["min_y"]) / landscape["spacing_y"]).astype(np.int64), 0, open_sea.shape[0] - 1)
        return open_sea[j, i]

    roads = roadnet.deck_over_sea(roads, open_sea_at, log)
    natural = height
    height = roadnet.carve_terrain(height, roads, landscape, log)
    # Road shoulders may build up a seawall fringe, but never raise open sea.
    height = np.where(open_sea, np.minimum(height, natural), height).astype(np.float32)
    # Everything placed on the ground samples what terrain.r16 will store,
    # with Unreal's landscape triangulation.
    stored = quantize_r16(height.astype(np.float64))

    def surface_at(xs, ys):
        return sample_ue(stored, landscape["min_x"], landscape["min_y"], landscape["spacing_x"], landscape["spacing_y"], xs, ys)

    roadnet.set_bridge_decks(roads, surface_at)
    ribbons = []
    for road in roads:
        rib = roadnet.build_ribbon(road, surface_at)
        if rib is None:
            continue
        ribbons.append(rib)
        m = len(rib["verts"]) // len(road["xy"])
        centre = rib["verts"].reshape(len(road["xy"]), m, 3)
        mid = centre[:, m // 2, 2] if m % 2 else 0.5 * (centre[:, m // 2 - 1, 2] + centre[:, m // 2, 2])
        road["center"] = np.column_stack([road["xy"], mid])
        road["width"] = float(np.max(road["hl"] + road["hr"]))
    roads = [road for road in roads if "center" in road]
    log(f"road ribbons {len(ribbons)}  triangles {sum(len(r['tris']) for r in ribbons)}")
    buffers, tree = _road_buffers(roads, log)
    buildings = cut_buildings(buildings, buffers, tree, log)
    buildings = repair_rings(buildings, log)
    buildings = assign_building_z(buildings, surface_at, log)
    waters = prepare_water(warp, extracted, height, landscape, log)
    del buffers, tree
    tile = float(config["tile_size_m"])
    grouped = defaultdict(list)
    for building in buildings:
        grouped[_tile_index(building["cx"], building["cy"], landscape, tile)].append(building)
    tile_dir = out / "tiles"
    if tile_dir.exists():
        shutil.rmtree(tile_dir)
    tile_dir.mkdir(parents=True, exist_ok=True)
    mesh_info = _write_tile_meshes(tile_dir, grouped, ribbons, waters, landscape, tile, log)
    index = spawn_rules.SurfaceIndex(ribbons, buildings, surface_at)
    spawns, landmarks, notes = spawn_rules.build_spawns(
        config, warp, roads, index, lambda x, y: _find_pad(x, y, stored, landscape), log
    )
    minimap = _draw_minimap(out / "minimap.png", height, landscape, roads, landmarks["places"], is_land, waters)
    mask = write_land_mask(out, config, land, extract, grids, log)
    dem = load_dem()
    harbour_rows = measure_harbour(warp, dem, is_land=mask.is_land) if dem is not None else []
    coast_stats["harbour_clearance"] = harbour_clearance(warp, mask.is_land)
    log(f"harbour clearance Kowloon-HK Island {coast_stats['harbour_clearance'].get('min_m')} m")
    coast_stats.update(coast_agreement(stored, is_land, landscape, warp, extract, spawns, log))
    coasts = extracted["coasts"]
    previews = _write_previews(out / "previews", warp, height, landscape, roads, coasts, landmarks["places"], harbour_rows, log)
    r16_path = out / "terrain.r16"
    encoded = encode_height(height)
    # Sanity: mid-grey is sea level, one unit is 4 cm.
    assert int(encode_height(np.array([0.0]))[0]) == 32768
    assert abs(float(encode_height(np.array([1.0]))[0]) - (32768 + 25)) < 1.0
    encoded.tofile(r16_path)
    log(f"heightmap {encoded.shape[1]} x {encoded.shape[0]}  {r16_path.stat().st_size} bytes")
    return {
        "landscape": landscape,
        "extent": extent,
        "tiles": mesh_info["tiles"],
        "triangles": mesh_info["triangles"],
        "spawns": spawns,
        "landmarks": landmarks,
        "minimap": minimap,
        "previews": previews,
        "harbour": harbour_rows,
        "coast": coast_stats,
        "notes": notes,
        "counts": {
            "osm_buildings": len(extracted["buildings_ll"]),
            "osm_roads": len(extracted["roads"]),
            "buildings": len(buildings),
            "roads": len(roads),
            "bridges": sum(1 for road in roads if road["mode"] == "bridge"),
            "tunnels_open_cut": sum(1 for road in roads if road["mode"] == "tunnel"),
            "water": len(waters),
            "tiles": len(mesh_info["tiles"]),
            "triangles": mesh_info["triangles"],
        },
    }


def write_outputs(out: Path, config, warp, built: dict, native: dict, started: float, log: Log) -> dict:
    (out / "spawns.json").write_text(json.dumps(built["spawns"], indent=2), encoding="utf-8")
    (out / "landmarks.json").write_text(json.dumps(built["landmarks"], ensure_ascii=False, indent=2), encoding="utf-8")
    landscape = built["landscape"]
    harbour = built.get("harbour") or []
    widths = [row["game_width_m"] for row in harbour]
    extent = built["extent"]
    long_axis = float(extent["long_axis_m"])
    min_harbour = float(min(widths)) if widths else None
    limitations = [
        "The warp is separable: scale_x depends only on easting and scale_y only on northing, plus a smooth harbour widening. Islands that share a meridian with the core cannot be 1:10 on both axes without folding the core or pinching it.",
        "Tunnels, including cross-harbour tubes, are open cuts. The deck is the chord between the portals, clamped so it stays above the water plane. There is no bored tunnel and no tunnel roof.",
        "Building courtyards (OSM inner rings) are filled. building:part footprints may still overlap the parent footprint when the part is taller.",
        "Residential, service, footway, path and steps are omitted. Cheung Chau and Lamma only keep unclassified streets, so driving there is local. There is no ferry; walk or fly between islands.",
        "Terrain heights are SRTM 1 arc-second, not the Lands Department DTM. Land and sea come from OSM natural=coastline inside the Geofabrik extract polygon (SRTM > 1.5 m outside it, i.e. Shenzhen); sea is a synthetic shelf from -2 m at the shore to about -10 m, not surveyed bathymetry. Low land is clamped to +0.6 m.",
        "Minimum road widths (3.2 m / 8 m) are cut out of building footprints, so dense blocks lose a strip along the carriageway.",
        "HLOD meshes are not built by this script. The Unreal baker assigns an HLOD layer; generating proxies is a separate editor command.",
        "This environment did not launch Unreal Editor, so the bake, character, cars, helicopter and frame rate were not played.",
    ]
    manifest = {
        "version": 1,
        "units": "game metres; +X east, +Y north, +Z up; Unreal cm = (x, -y, z) * 100 because Unreal is left-handed",
        "axis_note": "glTF tiles are Y-up metres relative to the tile origin: ue_cm = (gltf.x, -gltf.z, gltf.y) * 100",
        "landscape": {
            "min_x_m": landscape["min_x"],
            "min_y_m": landscape["min_y"],
            "max_x_m": landscape["max_x"],
            "max_y_m": landscape["max_y"],
            "spacing_x_m": landscape["spacing_x"],
            "spacing_y_m": landscape["spacing_y"],
            "verts_x": landscape["verts_x"],
            "verts_y": landscape["verts_y"],
            "components_x": landscape["components_x"],
            "components_y": landscape["components_y"],
            "sections_per_component": landscape["sections_per_component"],
            "quads_per_section": landscape["quads_per_section"],
            "z_scale_cm": landscape["z_scale_cm"],
            "height_mid": 32768,
            "cm_per_height_unit": 4.0,
            "heightmap": "terrain.r16",
            "sea_level_m": 0.0,
        },
        "tile_size_m": float(config["tile_size_m"]),
        "minimap": built["minimap"],
        "tiles": built["tiles"],
        "spawns_file": "spawns.json",
        "landmarks_file": "landmarks.json",
        "warp_lut": "warp_lut.bin",
    }
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = {
        "ok": True,
        "seconds": round(time.perf_counter() - started, 1),
        "extent": extent,
        "long_axis_m": long_axis,
        "coast": built.get("coast"),
        "harbour_game_width_m": {
            "sections": len(widths),
            "min": min_harbour,
            "median": float(np.median(widths)) if widths else None,
            "max": float(max(widths)) if widths else None,
        },
        "place_scales": _place_scales(warp, config),
        "counts": built["counts"],
        "landscape": {
            "verts_x": landscape["verts_x"],
            "verts_y": landscape["verts_y"],
            "spacing_x_m": landscape["spacing_x"],
            "spacing_y_m": landscape["spacing_y"],
        },
        "native_warp": native,
        "spawn_notes": built["notes"],
        "previews": built["previews"],
        "data": {
            "osm": "data/raw/hong-kong-latest.osm.pbf from https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf",
            "coastline": "OSM natural=coastline from the same extract; extract polygon data/config/hong-kong.poly from https://download.geofabrik.de/asia/china/hong-kong.poly",
            "dem": "SRTM N22E113 and N22E114 from https://elevation-tiles-prod.s3.amazonaws.com/skadi/N22/",
            "lands_dtm": "not downloaded; https://data.gov.hk/en-data/dataset/hk-landsd-openmap-5-digital-terrain-model",
        },
        "limitations": limitations,
    }
    axis_ok = config["target_long_axis_min_m"] <= long_axis <= config["target_long_axis_max_m"]
    clearance = ((built.get("coast") or {}).get("harbour_clearance") or {}).get("min_m")
    harbour_ok = (
        min_harbour is not None
        and min_harbour >= float(config["min_harbour_width_m"])
        and clearance is not None
        and clearance >= float(config["min_harbour_width_m"])
    )
    native_ok = bool(native.get("ok"))
    content_ok = built["counts"]["roads"] > 0 and built["counts"]["buildings"] > 0 and built["counts"]["tiles"] > 0
    coast = built.get("coast") or {}
    coast_ok = (
        coast.get("sea_below_seabed_pct", 0.0) >= 99.0
        and coast.get("land_above_0_pct", 0.0) >= 99.0
        and not coast.get("spawns_over_sea")
    )
    report["ok"] = bool(axis_ok and harbour_ok and native_ok and content_ok and coast_ok)
    report["checks"] = {
        "long_axis": axis_ok,
        "harbour": harbour_ok,
        "native_warp": native_ok,
        "content": content_ok,
        "coast": coast_ok,
    }
    (out / "logs" / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(
        f"report ok={report['ok']} long_axis={long_axis:.0f} harbour_min={min_harbour} "
        f"tiles={built['counts']['tiles']} tris={built['counts']['triangles']}"
    )
    return report


def main(argv: list[str]) -> int:
    started = time.perf_counter()
    root = repo_root()
    out = root / "data" / "processed"
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    log = Log(out / "logs" / "pipeline.log")
    try:
        if "--synthetic" in argv:
            log("synthetic mode is not the deliverable; real OSM is required for this run")
            return 2
        config_path = root / "data" / "config" / "world.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        warp = build_warp(config)
        warp.save_bin(out / "warp_lut.bin")
        warp.write_golden(out / "golden_warp.csv")
        log("wrote warp lut and golden samples")
        # Queries after build() already read the same tables the file stores.
        built = build_real(root, config, warp, out, log)
        native = _run_native_check(root, log)
        report = write_outputs(out, config, warp, built, native, started, log)
        return 0 if report["ok"] else 1
    except Exception:
        log(traceback.format_exc())
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main([]))
