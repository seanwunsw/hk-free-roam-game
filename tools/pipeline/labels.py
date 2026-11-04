"""Street, place and district names for the HUD and the minimap.

data/processed/road_names.json is small enough to load at startup: named drivable
centrelines as decimetre integer strings, a cell grid that lists which roads cross each
cell, OSM place points and the configured districts. Coordinates are game metres."""

from __future__ import annotations

import math
import re

import numpy as np

from tools.pipeline.geometry import douglas_peucker

CELL_M = 250.0
SIMPLIFY_M = 1.5
PLACE_KINDS = ("city", "town", "suburb", "quarter", "neighbourhood", "village")
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def split_names(tags) -> tuple[str, str]:
    """(Chinese, English) from name:zh / name:en, falling back on a bilingual name."""
    zh = (tags.get("name:zh") or tags.get("name:zh-Hant") or tags.get("name:zh-HK") or "").strip()
    en = (tags.get("name:en") or "").strip()
    name = (tags.get("name") or "").strip()
    if name and (not zh or not en):
        if _CJK.search(name):
            cjk = "".join(ch for ch in name if _CJK.match(ch) or ch in "·‧（）")
            latin = _CJK.sub("", name).strip(" ()（）·")
            zh = zh or cjk.strip()
            en = en or (latin if re.search(r"[A-Za-z]", latin) else "")
        else:
            en = en or name
    return zh, en


def _points_text(xy: np.ndarray) -> str:
    q = np.rint(np.asarray(xy, dtype=np.float64) * 10.0).astype(np.int64)
    return " ".join(f"{a} {b}" for a, b in q)


def build(roads: list[dict], places: list[dict], districts: list[dict], landmarks: list[dict] = (), cell_m: float = CELL_M) -> dict:
    names: list[list[str]] = []
    name_index: dict[tuple[str, str], int] = {}
    out_roads = []
    for road in roads:
        zh, en = road.get("name_zh") or "", road.get("name_en") or ""
        if not (zh or en) or len(road["xy"]) < 2:
            continue
        key = (zh, en)
        if key not in name_index:
            name_index[key] = len(names)
            names.append([zh, en])
        xy = np.asarray(road["xy"], dtype=np.float64)
        if len(xy) > 2:
            xy = douglas_peucker(xy, SIMPLIFY_M)
        out_roads.append({"n": name_index[key], "c": road["highway"], "p": _points_text(xy), "_xy": xy})
    if out_roads:
        allxy = np.vstack([r["_xy"] for r in out_roads])
        min_x, min_y = (float(math.floor(v)) for v in allxy.min(axis=0))
        max_x, max_y = (float(math.ceil(v)) for v in allxy.max(axis=0))
    else:
        min_x = min_y = 0.0
        max_x = max_y = cell_m
    nx = max(1, int(math.ceil((max_x - min_x) / cell_m)))
    ny = max(1, int(math.ceil((max_y - min_y) / cell_m)))
    cells: dict[int, set[int]] = {}
    for index, road in enumerate(out_roads):
        xy = road.pop("_xy")
        for a, b in zip(xy[:-1], xy[1:]):
            # Sample each segment at a quarter cell so every cell it crosses is listed.
            steps = max(1, int(math.ceil(float(np.hypot(*(b - a))) / (cell_m * 0.25))))
            for t in np.linspace(0.0, 1.0, steps + 1):
                p = a + (b - a) * t
                i = min(nx - 1, max(0, int((p[0] - min_x) // cell_m)))
                j = min(ny - 1, max(0, int((p[1] - min_y) // cell_m)))
                cells.setdefault(j * nx + i, set()).add(index)
    return {
        "version": 1,
        "units": "game metres; road points are decimetre integers 'x y x y ...'",
        "names": names,
        "roads": out_roads,
        "grid": {
            "cell_m": cell_m,
            "min_x_m": min_x,
            "min_y_m": min_y,
            "nx": nx,
            "ny": ny,
            "cells": {str(k): sorted(v) for k, v in sorted(cells.items())},
        },
        "places": list(places),
        "districts": list(districts),
        "landmarks": list(landmarks),
    }


def place_points(warp, nodes: list[dict], bounds) -> list[dict]:
    out = []
    for node in nodes:
        x, y = warp.lonlat_to_game_m(np.array([node["lon"]]), np.array([node["lat"]]))
        x, y = float(x[0]), float(y[0])
        if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
            continue
        out.append({"zh": node["zh"], "en": node["en"], "kind": node["kind"], "x_m": round(x, 1), "y_m": round(y, 1)})
    return out


def stats(doc: dict) -> dict:
    return {
        "named_roads": len(doc["roads"]),
        "names": len(doc["names"]),
        "grid_cells": len(doc["grid"]["cells"]),
        "places": len(doc["places"]),
        "districts": len(doc["districts"]),
        "landmarks": len(doc["landmarks"]),
    }


def district_areas(warp, districts_ll: list[dict], tolerance_m: float = 25.0, min_m2: float = 20000.0) -> list[dict]:
    """The 18 districts as simplified game-metre outer rings for point-in-polygon tests."""
    out = []
    for district in districts_ll:
        rings = []
        for ll in district["rings"]:
            x, y = warp.lonlat_to_game_m(ll[:, 0], ll[:, 1])
            xy = np.column_stack([x, y])
            closed = douglas_peucker(np.vstack([xy, xy[:1]]), tolerance_m)[:-1]
            if len(closed) < 3:
                continue
            area = 0.5 * abs(float(np.dot(closed[:, 0], np.roll(closed[:, 1], -1)) - np.dot(closed[:, 1], np.roll(closed[:, 0], -1))))
            if area >= min_m2:
                rings.append(_points_text(closed))
        if rings:
            cx, cy = (float(v) for v in np.vstack([np.column_stack(warp.lonlat_to_game_m(r[:, 0], r[:, 1])) for r in district["rings"]]).mean(axis=0))
            out.append({"zh": district["zh"], "en": district["en"], "kind": "district", "x_m": round(cx, 1), "y_m": round(cy, 1), "rings": rings})
    return out


# ---------------------------------------------------------------------------
# Landmarks: stations, hospitals, malls and rivers for the HUD (within 300 m) and minimap icons
# ---------------------------------------------------------------------------
LANDMARK_KINDS = ("station", "lrt", "tram", "hospital", "mall", "river")
RIVER_STEP_M = 400.0
LANDMARK_MERGE_M = 300.0


def landmark_kind(tags) -> str | None:
    railway = tags.get("railway")
    if railway in ("station", "halt") or (tags.get("public_transport") == "station" and (tags.get("train") == "yes" or tags.get("light_rail") == "yes" or tags.get("subway") == "yes")):
        if tags.get("station") == "light_rail" or tags.get("light_rail") == "yes":
            return "lrt"
        return "station"
    if railway == "tram_stop":
        return "lrt" if tags.get("light_rail") == "yes" or tags.get("tram") != "yes" else "tram"
    if tags.get("amenity") == "hospital" or tags.get("healthcare") == "hospital":
        return "hospital"
    if tags.get("shop") == "mall":
        return "mall"
    return None


def landmark_points(warp, items: list[dict], rivers: list[dict], bounds) -> list[dict]:
    """Game-metre landmark points; a station's node and area (or several entrances) merge
    into one point per name and kind within 300 m. Rivers get a point every 400 m."""
    out: list[dict] = []
    for item in items:
        x, y = warp.lonlat_to_game_m(np.array([item["lon"]]), np.array([item["lat"]]))
        out.append({"zh": item["zh"], "en": item["en"], "kind": item["kind"], "x_m": float(x[0]), "y_m": float(y[0])})
    for river in rivers:
        gx, gy = warp.lonlat_to_game_m(river["ll"][:, 0], river["ll"][:, 1])
        xy = np.column_stack([gx, gy])
        if len(xy) < 2:
            continue
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        for target in np.arange(RIVER_STEP_M * 0.5, max(s[-1], 1.0), RIVER_STEP_M):
            x = float(np.interp(target, s, xy[:, 0]))
            y = float(np.interp(target, s, xy[:, 1]))
            out.append({"zh": river["zh"], "en": river["en"], "kind": "river", "x_m": x, "y_m": y})
    kept: list[dict] = []
    by_key: dict[tuple, list[dict]] = {}
    for point in out:
        if not (bounds[0] <= point["x_m"] <= bounds[2] and bounds[1] <= point["y_m"] <= bounds[3]):
            continue
        key = (point["zh"] or point["en"], point["kind"])
        merge = LANDMARK_MERGE_M if point["kind"] != "river" else RIVER_STEP_M * 0.5
        if any(math.hypot(o["x_m"] - point["x_m"], o["y_m"] - point["y_m"]) < merge for o in by_key.get(key, ())):
            continue
        point["x_m"] = round(point["x_m"], 1)
        point["y_m"] = round(point["y_m"], 1)
        by_key.setdefault(key, []).append(point)
        kept.append(point)
    return kept
