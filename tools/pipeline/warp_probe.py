"""Read-only measurements of a finished road network.

Nothing here changes decks, grades or ribbons. build_world calls it so the same
numbers are in logs/report.json before and after a warp change. Bridge heights
are someone else's fix; these figures are only the warp's effect on the roads
that solver already produced.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from tools.pipeline.geometry import MIN_LANE_M, ROAD_CLASSES
from tools.pipeline.roads import lane_layout

# Character step used by check_roads. A bridge foot at least this far from the
# ground road it meets is a step a car or the player can catch on.
STEP_M = 0.45
# A bridge end whose graph distance to a ground terminal is within one sample.
TERMINAL_M = 1.0
# The connected ground road shares a node, so it is within a couple of metres.
# A wider match starts picking up the road passing underneath.
GROUND_MATCH_M = 3.0

# Tuen Mun Road against Castle Peak Road. The two names meet just north-west of
# this point; 60 m catches only the at-grade motorway, so the search is wider
# and the pair is the bridge sample closest to a Castle Peak Road sample.
PROBE_LON = 113.98084
PROBE_LAT = 22.38273
PROBE_RADIUS_M = 250.0
PAIR_MATCH_M = 25.0

DRIVABLE = set(ROAD_CLASSES)


def _is_tuen_mun_road(road: dict) -> bool:
    en = (road.get("name_en") or "").casefold()
    zh = road.get("name_zh") or ""
    return en == "tuen mun road" or zh == "屯門公路"


def _is_castle_peak_road(road: dict) -> bool:
    en = (road.get("name_en") or "").casefold()
    zh = road.get("name_zh") or ""
    return en.startswith("castle peak road") or zh.startswith("青山公路")


def _collect(roads: list[dict], predicate, gx: float, gy: float, radius: float) -> list[dict]:
    found = []
    for road in roads:
        if "center" not in road or not predicate(road):
            continue
        centre = road["center"]
        dist = np.hypot(centre[:, 0] - gx, centre[:, 1] - gy)
        for j in np.flatnonzero(dist <= radius):
            found.append(
                {
                    "x": float(centre[j, 0]),
                    "y": float(centre[j, 1]),
                    "distance_m": float(dist[j]),
                    "z_m": float(centre[j, 2]),
                    "mode": road.get("mode"),
                    "highway": road.get("highway"),
                    "name_en": road.get("name_en") or "",
                    "name_zh": road.get("name_zh") or "",
                }
            )
    return found


def _public(sample: dict, extra: dict | None = None) -> dict:
    out = {
        "distance_m": round(sample["distance_m"], 2),
        "z_m": round(sample["z_m"], 3),
        "mode": sample["mode"],
        "highway": sample["highway"],
        "name_en": sample["name_en"],
        "name_zh": sample["name_zh"],
    }
    if extra:
        out.update(extra)
    return out


def lane_widths(roads: list[dict]) -> dict:
    """Length-weighted lane width of drivable ribbons, after parallel merges."""
    narrow = None
    narrow_ribbon = None
    length = 0.0
    at_floor = 0.0
    samples = []
    ribbons = []
    for road in roads:
        if road.get("highway") not in DRIVABLE or "center" not in road or len(road["xy"]) < 2:
            continue
        width, _, lanes_l, lanes_r = lane_layout(road)
        lanes = np.maximum(np.asarray(lanes_l) + np.asarray(lanes_r), 1)
        wide = np.asarray(width, dtype=np.float64)
        per = wide / lanes
        run = np.hypot(*np.diff(road["xy"], axis=0).T)
        # Each segment is owned by its start sample.
        length += float(run.sum())
        at_floor += float(run[per[:-1] <= MIN_LANE_M + 0.02].sum())
        j = int(np.argmin(per))
        k = int(np.argmin(wide))
        local = float(per[j])
        ribbon_min = float(wide[k])
        samples.append(local)
        ribbons.append(ribbon_min)
        meta = (road.get("highway"), road.get("name_en") or road.get("name_zh") or "", road.get("mode"))
        if narrow is None or local < narrow[0]:
            narrow = (local, float(wide[j]), int(lanes[j]), *meta)
        if narrow_ribbon is None or ribbon_min < narrow_ribbon[0]:
            narrow_ribbon = (ribbon_min, int(lanes[k]), *meta)
    if not samples:
        return {"samples": 0}
    arr = np.asarray(samples, dtype=np.float64)
    return {
        "pieces": int(len(arr)),
        "narrowest_lane_m": round(float(arr.min()), 3),
        "narrowest_lane_ribbon_m": round(narrow[1], 3),
        "narrowest_lane_count": narrow[2],
        "p01_lane_m": round(float(np.percentile(arr, 1)), 3),
        "median_piece_lane_m": round(float(np.median(arr)), 3),
        "narrowest_ribbon_m": round(float(min(ribbons)), 3),
        "length_at_floor_pct": round(100.0 * at_floor / max(length, 1e-9), 2),
        "floor_m": MIN_LANE_M,
        "narrowest_highway": narrow[3],
        "narrowest_name": narrow[4],
        "narrowest_mode": narrow[5],
        "narrowest_ribbon_highway": narrow_ribbon[2],
        "narrowest_ribbon_name": narrow_ribbon[3],
    }


def bridge_end_steps(roads: list[dict]) -> dict:
    """Vertical step at each bridge foot where the deck meets a ground road.

    A foot is a bridge sample whose distance along the bridge graph to a ground
    terminal is <= TERMINAL_M. deck_fixed pieces (sea crossings and trenches)
    are not bridge ends. The step is the centreline height difference to the
    nearest ground or tunnel sample within GROUND_MATCH_M.
    """
    ground = [r for r in roads if r.get("mode") in ("ground", "tunnel") and "center" in r and len(r["xy"]) > 1]
    if not ground:
        return {"terminals": 0, "matched": 0, "steps_ge_0_45m": 0}
    pts = np.concatenate([r["center"][:, :2] for r in ground])
    zs = np.concatenate([r["center"][:, 2] for r in ground])
    tree = cKDTree(pts)
    steps = []
    unmatched = 0
    for road in roads:
        if road.get("mode") != "bridge" or "deck_fixed" in road or "end_dist" not in road or "center" not in road:
            continue
        end_dist = np.asarray(road["end_dist"], dtype=np.float64)
        centre = road["center"]
        for index in (0, len(centre) - 1):
            if not np.isfinite(end_dist[index]) or float(end_dist[index]) > TERMINAL_M:
                continue
            dist, j = tree.query(centre[index, :2], distance_upper_bound=GROUND_MATCH_M)
            if not np.isfinite(dist):
                unmatched += 1
                continue
            steps.append(abs(float(centre[index, 2]) - float(zs[j])))
    arr = np.asarray(steps, dtype=np.float64) if steps else np.zeros(0)
    over = int(np.sum(arr >= STEP_M)) if len(arr) else 0
    return {
        "terminals_matched": int(len(arr)),
        "unmatched": int(unmatched),
        "steps_ge_0_45m": over,
        "steps_ge_0_45m_pct": round(100.0 * over / max(len(arr), 1), 2),
        "median_m": round(float(np.median(arr)), 3) if len(arr) else None,
        "max_m": round(float(arr.max()), 3) if len(arr) else None,
    }


def height_gap(roads: list[dict], warp, surface_at=None) -> dict:
    """Tuen Mun Road versus Castle Peak Road near the probe.

    Samples of both names inside PROBE_RADIUS_M are paired. A bridge sample of
    Tuen Mun Road within PAIR_MATCH_M of a Castle Peak Road sample is the stack;
    the pair closest to the probe wins. The ratio is that Tuen Mun Road ribbon
    height divided by the Castle Peak Road ribbon height.
    """
    gx, gy = (float(v) for v in warp.lonlat_to_game_m(PROBE_LON, PROBE_LAT))
    tuen = _collect(roads, _is_tuen_mun_road, gx, gy, PROBE_RADIUS_M)
    castle = _collect(roads, _is_castle_peak_road, gx, gy, PROBE_RADIUS_M)
    terrain = None
    if surface_at is not None:
        terrain = round(float(surface_at(np.array([gx]), np.array([gy]))[0]), 3)
    out = {
        "probe_lon": PROBE_LON,
        "probe_lat": PROBE_LAT,
        "radius_m": PROBE_RADIUS_M,
        "game_x_m": round(gx, 2),
        "game_y_m": round(gy, 2),
        "terrain_z_m": terrain,
        "tuen_mun_samples": len(tuen),
        "castle_peak_samples": len(castle),
        "tuen_mun_road": None,
        "castle_peak_road": None,
        "horizontal_m": None,
        "vertical_gap_m": None,
        "height_ratio": None,
        "pair": None,
    }
    if not tuen or not castle:
        return out
    tree = cKDTree(np.array([[s["x"], s["y"]] for s in castle]))
    best = None
    for sample in tuen:
        dist, j = tree.query([sample["x"], sample["y"]])
        dist = float(dist)
        if sample.get("mode") != "bridge" or dist > PAIR_MATCH_M:
            continue
        rank = (sample["distance_m"], dist)
        if best is None or rank < best[0]:
            best = (rank, sample, castle[int(j)], dist)
    if best is None:
        return out
    _, left, right, apart = best
    gap = left["z_m"] - right["z_m"]
    ratio = left["z_m"] / right["z_m"] if right["z_m"] != 0.0 else None
    out.update(
        {
            "tuen_mun_road": _public(left, {"to_other_m": round(apart, 2)}),
            "castle_peak_road": _public(right),
            "horizontal_m": round(apart, 2),
            "vertical_gap_m": round(gap, 3),
            "height_ratio": round(ratio, 3) if ratio is not None else None,
            "pair": "bridge_over_castle_peak",
        }
    )
    return out


def summarise(roads: list[dict], warp, surface_at=None) -> dict:
    return {
        "lanes": lane_widths(roads),
        "bridge_end_steps": bridge_end_steps(roads),
        "tuen_mun_road_gap": height_gap(roads, warp, surface_at),
    }
