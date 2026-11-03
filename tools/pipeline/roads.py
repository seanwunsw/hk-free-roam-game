"""Road network shaping: merge stacked parallel ways, carve one ground surface,
lift bridges, and build ribbon meshes that sit on the carved landscape.

Order used by build_world:
    roads = prepare_roads(...)             # 4 m centrelines, mode, width
    roads = merge_parallel(roads)          # one ribbon per carriageway pair
    road_graph.solve_design_profiles(roads)  # one network height solve
    carved = carve_terrain(height, roads)  # one surface, no nearest-seed steps
    surface = quantized carved terrain     # what terrain.r16 stores
    set_bridge_decks(roads, surface)
    ribbons = build_ribbons(roads, surface)

Every ground and tunnel ribbon vertex takes its height from the carved surface,
sampled with Unreal's landscape triangulation, plus a small lift. So the road
cannot float above or sink under the landscape it was carved into, and two
ground ribbons that overlap share the same height (up to the lift).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, gaussian_filter1d, maximum_filter1d
from scipy.spatial import cKDTree

from tools.pipeline.geometry import ROAD_CLASSES, road_game_width

STEP_M = 4.0
ACROSS_M = 4.0
MODE_ALPHA = {"ground": 1.0, "tunnel": 0.75, "bridge": 0.5}
CLASS_RANK = {name: index for index, name in enumerate(ROAD_CLASSES)}
PARALLEL_COS = math.cos(math.radians(30.0))
MAX_SIDE_HALF_M = 16.0
DESIGN_SIGMA_M = 12.0
TRENCH_CLEARANCE_M = 4.0
BRIDGE_LIFT_M = 0.16
BRIDGE_FADE_M = 40.0
OVERPASS_CLEARANCE_M = 5.5
OVERPASS_NEAR_END_M = 10.0
OVERPASS_RAMP_GRADE = 0.20


def arc_length(xy: np.ndarray) -> np.ndarray:
    out = np.zeros(len(xy))
    if len(xy) > 1:
        out[1:] = np.cumsum(np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1])))
    return out


def resample(xy: np.ndarray, step: float = STEP_M) -> np.ndarray:
    s = arc_length(xy)
    total = float(s[-1]) if len(s) else 0.0
    if total < 1e-6:
        return xy[:1]
    count = max(1, int(math.ceil(total / step)))
    targets = np.linspace(0.0, total, count + 1)
    return np.column_stack([np.interp(targets, s, xy[:, 0]), np.interp(targets, s, xy[:, 1])])


def tangents(xy: np.ndarray) -> np.ndarray:
    d = np.gradient(xy, axis=0) if len(xy) > 1 else np.array([[1.0, 0.0]])
    n = np.hypot(d[:, 0], d[:, 1])[:, None]
    return np.where(n > 1e-9, d / np.maximum(n, 1e-9), np.array([1.0, 0.0]))


def left_normals(xy: np.ndarray, cap: float = 2.2) -> np.ndarray:
    """Mitred left normals (same rule as geometry._left_normals, vectorised)."""
    seg = np.diff(xy, axis=0)
    length = np.hypot(seg[:, 0], seg[:, 1])[:, None]
    seg_n = np.where(length > 1e-6, np.column_stack([-seg[:, 1], seg[:, 0]]) / np.maximum(length, 1e-6), np.array([0.0, 1.0]))
    out = np.empty((len(xy), 2))
    out[0] = seg_n[0]
    out[-1] = seg_n[-1]
    if len(xy) > 2:
        mid = seg_n[:-1] + seg_n[1:]
        mlen = np.hypot(mid[:, 0], mid[:, 1])[:, None]
        unit = np.where(mlen > 1e-4, mid / np.maximum(mlen, 1e-4), seg_n[:-1])
        align = np.maximum(np.sum(unit * seg_n[:-1], axis=1), 0.45)[:, None]
        miter = unit / align
        scale = np.hypot(miter[:, 0], miter[:, 1])[:, None]
        miter = np.where(scale > cap, miter / scale * cap, miter)
        out[1:-1] = miter
    return out


def ground_lift(highway: str) -> float:
    """Higher classes sit a few centimetres higher so overlapping junction ribbons do not z-fight."""
    rank = CLASS_RANK.get(highway, len(ROAD_CLASSES))
    return 0.10 + 0.012 * max(0, len(ROAD_CLASSES) - rank)


def make_road(xy, terrain_z, highway, lanes, mode, layer, horizontal, keys=None, perp=None, oneway=False) -> dict:
    """One road way. perp is the warp scale across the road (defaults to horizontal).
    A one-way road's points run in its legal direction."""
    width, lanes = road_game_width(highway, lanes, horizontal if perp is None else perp)
    n = len(xy)
    half = np.full(n, width * 0.5)
    # Lanes on each side of the direction split. Hong Kong drives on the left, so for
    # a two-way road the left half (of the point order) carries the forward lanes.
    if oneway or lanes < 2:
        lanes_l, lanes_r = lanes, 0
    else:
        lanes_l, lanes_r = lanes - lanes // 2, lanes // 2
    return {
        "xy": np.asarray(xy, dtype=np.float64),
        "keys": np.full(n, -1, dtype=np.int64) if keys is None else np.asarray(keys, dtype=np.int64),
        "terrain": np.asarray(terrain_z, dtype=np.float64),
        "width": width,
        "base_half": width * 0.5,
        "hl": half.copy(),
        "hr": half.copy(),
        "lanes": lanes,
        "lane_m": width / lanes,
        "oneway": bool(oneway),
        # Lanes absorbed by merge_parallel on each side, and whether any of them
        # carries traffic against this way (so the merged ribbon is two-way).
        "add_l": np.zeros(n, dtype=np.int64),
        "add_r": np.zeros(n, dtype=np.int64),
        "opp_l": np.zeros(n, dtype=bool),
        "opp_r": np.zeros(n, dtype=bool),
        "own_l": lanes_l,
        "own_r": lanes_r,
        "highway": highway,
        "mode": mode,
        "layer": int(layer),
        "horizontal": horizontal,
        "height_scale": float(np.clip(math.sqrt(max(horizontal, 1e-4)), 0.20, 1.25)),
    }


def slice_road(road: dict, start: int, end: int) -> dict:
    out = dict(road)
    for key in ("xy", "terrain", "hl", "hr", "design", "keys", "add_l", "add_r", "opp_l", "opp_r", "fade"):
        if key in road:
            out[key] = road[key][start:end].copy()
    return out


def _group_key(road: dict) -> tuple:
    return (road["mode"], road["layer"] if road["mode"] == "bridge" else 0)


def _priority_order(roads: list[dict]) -> list[int]:
    lengths = [float(arc_length(r["xy"])[-1]) for r in roads]
    return sorted(
        range(len(roads)),
        key=lambda i: (CLASS_RANK.get(roads[i]["highway"], 99), -roads[i]["width"], -lengths[i], i),
    )


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) runs where mask is True."""
    if not mask.any():
        return []
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def merge_parallel(roads: list[dict], log=print) -> list[dict]:
    """Fold lower-priority ways that run on top of a higher-priority way into it.

    A point of way B is absorbed when it lies inside the ribbon of an
    already-kept way A of the same mode (and bridge layer) that runs parallel
    (within 30 degrees). A grows its half-width on that side to cover B, so a
    dual carriageway becomes one wide ribbon instead of two stacked ones. B
    keeps only its unabsorbed runs, each extended one point into A so it still
    connects. Ways are visited from the highest priority down, so A is final
    before anything is folded into it.
    """
    if not roads:
        return roads
    order = _priority_order(roads)
    prio = np.empty(len(roads), dtype=np.int64)
    prio[np.asarray(order)] = np.arange(len(roads))
    sizes = np.array([len(r["xy"]) for r in roads])
    offsets = np.concatenate([[0], np.cumsum(sizes)])
    owner = np.repeat(np.arange(len(roads)), sizes)
    first = offsets[:-1][owner]
    last = offsets[1:][owner] - 1
    pts = np.concatenate([r["xy"] for r in roads])
    tan = np.concatenate([tangents(r["xy"]) for r in roads])
    keys: dict = {}
    group = np.repeat([keys.setdefault(_group_key(r), len(keys)) for r in roads], sizes)
    g_hl = np.concatenate([r["hl"] for r in roads])
    g_hr = np.concatenate([r["hr"] for r in roads])
    total = len(pts)
    g_add_l = np.zeros(total, dtype=np.int64)
    g_add_r = np.zeros(total, dtype=np.int64)
    g_opp_l = np.zeros(total, dtype=bool)
    g_opp_r = np.zeros(total, dtype=bool)
    alive = np.ones(len(pts), dtype=bool)
    tree = cKDTree(pts)
    kept_runs: dict[int, list[tuple[int, int]]] = {}
    absorbed_points = 0
    for b in order:
        road = roads[b]
        n = len(road["xy"])
        sl = slice(offsets[b], offsets[b + 1])
        hb = road["base_half"]
        xy_b = road["xy"]
        cands = tree.query_ball_point(xy_b, r=hb + MAX_SIDE_HALF_M)
        counts = np.fromiter((len(x) for x in cands), dtype=np.int64, count=n)
        absorbed = np.zeros(n, dtype=bool)
        if counts.sum():
            bp = np.repeat(np.arange(n), counts)
            c = np.concatenate([np.asarray(x, dtype=np.int64) for x in cands if len(x)])
            ok = alive[c] & (group[c] == group[offsets[b]]) & (prio[owner[c]] < prio[b])
            bp, c = bp[ok], c[ok]
            if len(c):
                d = xy_b[bp] - pts[c]
                ta = tan[c]
                along = ta[:, 0] * d[:, 0] + ta[:, 1] * d[:, 1]
                lat = ta[:, 0] * d[:, 1] - ta[:, 1] * d[:, 0]
                par = np.abs(np.sum(ta * tan[sl][bp], axis=1)) >= PARALLEL_COS
                side = np.where(lat >= 0, g_hl[c], g_hr[c])
                new_side = np.abs(lat) + hb
                valid = par & (np.abs(along) <= STEP_M * 0.6) & (np.abs(lat) < side + hb - 0.25) & (new_side <= MAX_SIDE_HALF_M)
                bp, c, lat, new_side = bp[valid], c[valid], lat[valid], new_side[valid]
            if len(c):
                rank = np.argsort(np.abs(lat), kind="stable")
                _, pick = np.unique(bp[rank], return_index=True)
                pick = rank[pick]
                absorbed[bp[pick]] = True
                # A lone absorbed point is a crossing or a touch, not a shared carriageway.
                for s, e in _runs(absorbed):
                    if e - s < 2:
                        absorbed[s:e] = False
                pick = pick[absorbed[bp[pick]]]
                cc, need, left = c[pick], new_side[pick], lat[pick] >= 0
                opposite = np.sum(tan[cc] * tan[sl][bp[pick]], axis=1) < 0
                if not road.get("oneway", False):
                    opposite[:] = True
                lanes_b = np.full(len(cc), int(road.get("lanes", 1)))
                for shift in (-1, 0, 1):
                    k = np.clip(cc + shift, first[cc], last[cc])
                    np.maximum.at(g_hl, k[left], need[left])
                    np.maximum.at(g_hr, k[~left], need[~left])
                    np.maximum.at(g_add_l, k[left], lanes_b[left])
                    np.maximum.at(g_add_r, k[~left], lanes_b[~left])
                    g_opp_l[k[left & opposite]] = True
                    g_opp_r[k[~left & opposite]] = True
        free = ~absorbed
        runs = []
        keep_mask = np.zeros(n, dtype=bool)
        for s, e in _runs(free):
            if s > 0 and e < n and e - s < 3:
                continue
            s2, e2 = max(0, s - 1), min(n, e + 1)
            if e2 - s2 >= 2 and arc_length(xy_b[s2:e2])[-1] >= 6.0:
                # Only points of an emitted piece may absorb later ways; a run
                # dropped for being short must not swallow a way into nothing.
                keep_mask[s:e] = True
                runs.append((s2, e2))
        kept_runs[b] = runs
        alive[sl] &= keep_mask
        absorbed_points += int((~keep_mask).sum())
    out = []
    for i, road in enumerate(roads):
        base = road["base_half"]
        for key, arr_all in (("hl", g_hl), ("hr", g_hr)):
            arr = maximum_filter1d(arr_all[offsets[i] : offsets[i + 1]], size=3, mode="nearest")
            arr = np.convolve(np.pad(arr, 1, mode="edge"), np.ones(3) / 3.0, mode="valid")
            road[key] = np.maximum(arr, base)
        part = slice(offsets[i], offsets[i + 1])
        for key, arr_all in (("add_l", g_add_l), ("add_r", g_add_r), ("opp_l", g_opp_l), ("opp_r", g_opp_r)):
            road[key] = maximum_filter1d(arr_all[part], size=3, mode="nearest")
        for s, e in kept_runs.get(i, []):
            out.append(slice_road(road, s, e))
    widened = sum(1 for r in out if np.any(r["hl"] > r["base_half"] + 0.01) or np.any(r["hr"] > r["base_half"] + 0.01))
    log(f"merge_parallel: {len(roads)} ways -> {len(out)} pieces  absorbed points {absorbed_points}/{len(pts)}  widened pieces {widened}")
    return out


def bridge_over_trenches(roads: list[dict], log=print) -> list[dict]:
    """Ground stretches that cross an open-cut tunnel trench become short decks.

    Long tunnels are open-cut trenches in the landscape. Where a ground road
    crosses one (its design height is more than TRENCH_CLEARANCE_M above the
    tunnel's), carving the ground road would wall off the trench and the
    tunnel ribbon would climb over the wall. Instead that stretch becomes a
    flat deck at the road's own design height and the trench stays open.
    """
    tunnels = [r for r in roads if r["mode"] == "tunnel" and "design" in r and len(r["xy"]) > 1]
    if not tunnels:
        return roads
    tp = np.concatenate([r["xy"] for r in tunnels])
    tz = np.concatenate([r["design"] for r in tunnels])
    trad = np.concatenate([np.maximum(np.maximum(r["hl"], r["hr"]) + 6.0, 10.0) for r in tunnels])
    tree = cKDTree(tp)
    reach = float(trad.max())
    out = []
    decks = 0
    for road in roads:
        if road["mode"] != "ground" or len(road["xy"]) < 2:
            out.append(road)
            continue
        xy = road["xy"]
        side = np.maximum(road["hl"], road["hr"])
        hits = tree.query_ball_point(xy, r=reach + float(side.max()))
        over = np.zeros(len(xy), dtype=bool)
        for i, h in enumerate(hits):
            if not h:
                continue
            h = np.asarray(h)
            dist = np.hypot(tp[h, 0] - xy[i, 0], tp[h, 1] - xy[i, 1])
            over[i] = bool(np.any((dist <= trad[h] + side[i]) & (tz[h] < road["design"][i] - TRENCH_CLEARANCE_M)))
        if not over.any():
            out.append(road)
            continue
        over = maximum_filter1d(over.astype(np.int8), size=5, mode="nearest") > 0
        n = len(xy)
        for s, e in _runs(~over):
            if e - s >= 2:
                out.append(slice_road(road, s, e))
        for s, e in _runs(over):
            piece = slice_road(road, max(0, s - 1), min(n, e + 1))
            if len(piece["xy"]) < 2:
                continue
            piece["mode"] = "bridge"
            piece["layer"] = 0
            piece["deck_fixed"] = piece["design"] + ground_lift(road["highway"])
            out.append(piece)
            decks += 1
    log(f"ground stretches decked over tunnel trenches {decks}")
    return out


def deck_over_sea(roads: list[dict], open_sea_at, log=print) -> list[dict]:
    """Ground and open-cut tunnel stretches over open sea become low decks.

    Both drape on the landscape, and carving the landscape up to them would
    build a causeway across the water (the cross-harbour tubes used to make a
    land bridge from Hung Hom to Causeway Bay). Instead the stretch keeps its
    design height as a fixed deck and the seabed under it stays open.
    """
    out = []
    decks = 0
    for road in roads:
        if road["mode"] not in {"ground", "tunnel"} or len(road["xy"]) < 2 or "design" not in road:
            out.append(road)
            continue
        wet = np.asarray(open_sea_at(road["xy"][:, 0], road["xy"][:, 1]), dtype=bool)
        if not wet.any():
            out.append(road)
            continue
        wet = maximum_filter1d(wet.astype(np.int8), size=5, mode="nearest") > 0
        n = len(road["xy"])
        for s, e in _runs(~wet):
            if e - s >= 2:
                out.append(slice_road(road, s, e))
        for s, e in _runs(wet):
            piece = slice_road(road, max(0, s - 1), min(n, e + 1))
            if len(piece["xy"]) < 2:
                continue
            piece["mode"] = "bridge"
            piece["layer"] = 0
            piece["deck_fixed"] = np.maximum(piece["design"], 0.40) + ground_lift(road["highway"])
            out.append(piece)
            decks += 1
    log(f"ground/tunnel stretches decked over open sea {decks}")
    return out


def _segment_arrays(roads: list[dict]):
    """Per segment: ends, design heights, and the half-widths each side that the
    carve treats as the road core (full weight) and the outer corridor."""
    p0, p1, z0, z1, cl, cr = [], [], [], [], [], []
    for road in roads:
        xy = road["xy"]
        if len(xy) < 2:
            continue
        z = road["design"]
        extra = 6.0 if road["mode"] == "tunnel" else 1.0
        left = road["hl"] + extra
        right = road["hr"] + extra
        p0.append(xy[:-1])
        p1.append(xy[1:])
        z0.append(z[:-1])
        z1.append(z[1:])
        cl.append(np.maximum(left[:-1], left[1:]))
        cr.append(np.maximum(right[:-1], right[1:]))
    if not p0:
        return None
    return tuple(np.concatenate(a) for a in (p0, p1, z0, z1, cl, cr))


def rasterise_profiles(shape, landscape, roads: list[dict], chunk: int = 60000):
    """Weighted sum and weight of design heights at grid nodes near each road.

    Nodes inside the road core (half-width + 1 m) get weight 1; weight falls
    linearly to 0.05 over one grid spacing beyond it, so every landscape
    triangle that touches a ribbon has all three corners carved.
    """
    ny, nx = shape
    total = np.zeros(ny * nx)
    count = np.zeros(ny * nx)
    sx, sy = landscape["spacing_x"], landscape["spacing_y"]
    margin = float(np.hypot(sx, sy)) + 0.5
    arrays = _segment_arrays(roads)
    if arrays is None:
        return total.reshape(shape), count.reshape(shape)
    P0, P1, Z0, Z1, CL, CR = arrays
    mx, my = landscape["min_x"], landscape["min_y"]
    for start in range(0, len(P0), chunk):
        p0, p1 = P0[start : start + chunk], P1[start : start + chunk]
        z0, z1 = Z0[start : start + chunk], Z1[start : start + chunk]
        cl, cr = CL[start : start + chunk], CR[start : start + chunk]
        reach = np.maximum(cl, cr) + margin
        lo = np.minimum(p0, p1) - reach[:, None]
        hi = np.maximum(p0, p1) + reach[:, None]
        i0 = np.clip(np.ceil((lo[:, 0] - mx) / sx), 0, nx - 1).astype(np.int64)
        i1 = np.clip(np.floor((hi[:, 0] - mx) / sx), 0, nx - 1).astype(np.int64)
        j0 = np.clip(np.ceil((lo[:, 1] - my) / sy), 0, ny - 1).astype(np.int64)
        j1 = np.clip(np.floor((hi[:, 1] - my) / sy), 0, ny - 1).astype(np.int64)
        wi = np.maximum(i1 - i0 + 1, 0)
        wj = np.maximum(j1 - j0 + 1, 0)
        k = wi * wj
        seg = np.repeat(np.arange(len(p0)), k)
        loc = np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)
        gi = i0[seg] + loc % np.maximum(wi[seg], 1)
        gj = j0[seg] + loc // np.maximum(wi[seg], 1)
        qx = mx + gi * sx
        qy = my + gj * sy
        d = p1[seg] - p0[seg]
        dd = np.maximum(np.sum(d * d, axis=1), 1e-9)
        rx = qx - p0[seg, 0]
        ry = qy - p0[seg, 1]
        t = np.clip((rx * d[:, 0] + ry * d[:, 1]) / dd, 0.0, 1.0)
        dist = np.hypot(rx - t * d[:, 0], ry - t * d[:, 1])
        lat = d[:, 0] * ry - d[:, 1] * rx
        core = np.where(lat >= 0, cl[seg], cr[seg])
        weight = np.clip(1.0 - (dist - core) / margin, 0.0, 1.0)
        weight = np.where(dist <= core, 1.0, np.where(dist <= core + margin, np.maximum(weight, 0.05), 0.0))
        use = weight > 0
        z = z0[seg] + t * (z1[seg] - z0[seg])
        node = gj[use] * nx + gi[use]
        total += np.bincount(node, weights=(z * weight)[use], minlength=ny * nx)
        count += np.bincount(node, weights=weight[use], minlength=ny * nx)
    return total.reshape(shape), count.reshape(shape)


def _blend_corridor(base: np.ndarray, total: np.ndarray, count: np.ndarray, spacing: float, shoulder_m: float) -> np.ndarray:
    footprint = count > 0
    if not footprint.any():
        return base
    smooth_total = gaussian_filter(total, 1.0)
    smooth_count = gaussian_filter(count, 1.0)
    dist, idx = distance_transform_edt(~footprint, return_indices=True)
    inner = np.where(footprint, total / np.maximum(count, 1), 0.0)
    nearest = inner[idx[0], idx[1]]
    target = np.where(smooth_count > 1e-3, smooth_total / np.maximum(smooth_count, 1e-3), nearest)
    blend = np.clip(1.0 - dist * spacing / shoulder_m, 0.0, 1.0)
    alpha = blend * blend * (3.0 - 2.0 * blend)
    return base * (1.0 - alpha) + target * alpha


MINOR_CARVE_CLASSES = {"residential", "living_street", "service"}
MINOR_SHOULDER_M = 6.0


def carve_terrain(height: np.ndarray, roads: list[dict], landscape, log=print) -> np.ndarray:
    """Pull the landscape onto the road design profiles.

    Every node inside a corridor takes a smoothed average of the design
    heights of all roads covering it (normalised convolution), so junctions
    and parallel roads blend instead of flipping between nearest seeds. A
    smoothstep shoulder blends back to the natural terrain. Tunnels are
    carved first; ground roads override them.
    """
    spacing = 0.5 * (landscape["spacing_x"] + landscape["spacing_y"])
    carved = height.astype(np.float64)
    tunnels = [r for r in roads if r["mode"] == "tunnel" and len(r["xy"]) > 1]
    ground_all = [r for r in roads if r["mode"] == "ground" and len(r["xy"]) > 1]
    ground = [r for r in ground_all if r.get("highway") not in MINOR_CARVE_CLASSES]
    minor = [r for r in ground_all if r.get("highway") in MINOR_CARVE_CLASSES]
    log(f"carving tunnels {len(tunnels)} then ground roads {len(ground)} then minor roads {len(minor)}")
    taken = np.zeros(height.shape, dtype=bool)
    if tunnels:
        total, count = rasterise_profiles(height.shape, landscape, tunnels)
        carved = _blend_corridor(carved, total, count, spacing, 28.0)
        taken |= count > 0
    if ground:
        total, count = rasterise_profiles(height.shape, landscape, ground)
        carved = _blend_corridor(carved, total, count, spacing, 16.0)
        taken |= count > 0
        log(f"ground corridor nodes {int((count > 0).sum())}")
    if minor:
        # Minor roads (residential, service, living street) get a narrow shoulder
        # and never override a main-road or tunnel corridor, so the many coastal
        # service roads and piers do not pull the sea floor up or fill trenches.
        total, count = rasterise_profiles(height.shape, landscape, minor)
        total = np.where(taken, 0.0, total)
        count = np.where(taken, 0.0, count)
        carved = np.where(taken, carved, _blend_corridor(carved, total, count, spacing, MINOR_SHOULDER_M))
        log(f"minor corridor nodes {int((count > 0).sum())}")
    return carved.astype(np.float32)


def _bridge_graph_distances(bridges: list[dict]):
    """Distance along connected bridge ways from each bridge end to the nearest
    end that comes down to the ground, so a viaduct split into several OSM ways
    does not dip to the ground at every split.

    Returns (per-bridge (d0, d1), node id of each start, node id of each end)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    if not bridges:
        return [], np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    ends = np.array([[r["xy"][0], r["xy"][-1]] for r in bridges]).reshape(-1, 2)
    layer = np.repeat([r["layer"] for r in bridges], 2)
    tree = cKDTree(ends)
    parent = np.arange(len(ends))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in sorted(tree.query_pairs(2.0)):
        if layer[i] == layer[j]:
            parent[find(i)] = find(j)
    node = np.array([find(i) for i in range(len(ends))])
    _, node = np.unique(node, return_inverse=True)
    n_nodes = int(node.max()) + 1
    degree = np.bincount(node, minlength=n_nodes)
    # An end that stops on top of another bridge (a ramp joining a viaduct
    # mid-span, or a piece left by merge_parallel) is not a ground end.
    pts = np.concatenate([r["xy"] for r in bridges])
    owner = np.concatenate([np.full(len(r["xy"]), i) for i, r in enumerate(bridges)])
    half = np.concatenate([np.maximum(r["hl"], r["hr"]) for r in bridges])
    play = np.concatenate([np.full(len(r["xy"]), r["layer"]) for r in bridges])
    ptree = cKDTree(pts)
    terminal = np.zeros(n_nodes, dtype=bool)
    for e in range(len(ends)):
        if degree[node[e]] != 1:
            continue
        hits = ptree.query_ball_point(ends[e], r=MAX_SIDE_HALF_M + 1.0)
        on_other = any(owner[h] != e // 2 and play[h] == layer[e] and np.hypot(*(pts[h] - ends[e])) <= half[h] + 1.0 for h in hits)
        terminal[node[e]] = not on_other
    lengths = np.array([arc_length(r["xy"])[-1] for r in bridges])
    a = node[0::2]
    b = node[1::2]
    graph = coo_matrix((np.concatenate([lengths, lengths]) + 1e-3, (np.concatenate([a, b]), np.concatenate([b, a]))), shape=(n_nodes, n_nodes)).tocsr()
    sources = np.flatnonzero(terminal)
    if len(sources) == 0:
        dist = np.full(n_nodes, np.inf)
    else:
        dist = dijkstra(graph, directed=False, indices=sources, min_only=True)
    return [(float(dist[a[i]]), float(dist[b[i]])) for i in range(len(bridges))], a, b


def _lower_z(road: dict, j: int, u: float, surface_at) -> float:
    """Driving surface height of a road piece at segment j, fraction u."""
    p = road["xy"][j] * (1 - u) + road["xy"][j + 1] * u
    if road["mode"] == "bridge":
        return float(road["deck"][j] * (1 - u) + road["deck"][j + 1] * u)
    return float(surface_at(np.array([p[0]]), np.array([p[1]]))[0]) + ground_lift(road["highway"])


def _floor_decks(bridges: list[dict], a_nodes, b_nodes, sources: list[tuple[int, int, float]], grade: float) -> np.ndarray:
    """Per bridge sample, max over sources of (value - grade * distance) along the
    connected bridge graph (piece ends sharing a node are one vertex)."""
    from tools.pipeline.road_graph import _sym, envelope

    sizes = np.array([len(r["xy"]) for r in bridges])
    off = np.concatenate([[0], np.cumsum(sizes)])
    n_nodes = int(max(a_nodes.max(), b_nodes.max())) + 1
    vid = np.empty(int(off[-1]), dtype=np.int64)
    nxt = n_nodes
    for i, r in enumerate(bridges):
        k = sizes[i]
        ids = np.arange(nxt, nxt + k)
        nxt += k
        ids[0] = a_nodes[i]
        ids[-1] = b_nodes[i]
        vid[off[i] : off[i + 1]] = ids
    owner = np.repeat(np.arange(len(bridges)), sizes)
    pts = np.concatenate([r["xy"] for r in bridges])
    seg = np.flatnonzero(owner[:-1] == owner[1:])
    eu, ev = vid[seg], vid[seg + 1]
    el = np.maximum(np.hypot(*(pts[seg + 1] - pts[seg]).T), 0.05)
    keep = eu != ev
    graph = _sym(eu[keep], ev[keep], grade * el[keep], nxt)
    best = {}
    for bi, i, value in sources:
        for v in (vid[off[bi] + i], vid[off[bi] + i + 1]):
            best[int(v)] = max(best.get(int(v), -np.inf), value)
    src = np.array(list(best.keys()), dtype=np.int64)
    val = np.array([best[k] for k in src.tolist()])
    floor = -envelope(graph, src, -val)
    return floor[vid]


def set_bridge_decks(roads: list[dict], surface_at, log=print) -> dict:
    """Deck height per centreline point: carved ground (sea clamped to 0) kept
    over short dips, plus clearance that fades to zero toward ground ends.

    The fade length at a point is min(BRIDGE_FADE_M, way length / 3) of its
    bridge way; where bridge ways meet, the largest of theirs. So a short
    bridge still reaches full clearance in its middle.

    Then a hard floor: where a deck crosses a lower road it does not connect
    to (more than OVERPASS_NEAR_END_M from a ground end), it must clear that
    road by OVERPASS_CLEARANCE_M. The floor spreads along the connected
    bridge ways at OVERPASS_RAMP_GRADE, and decks are raised to it, lower
    bridge layers first.
    """
    from tools.pipeline.road_graph import deck_crossings

    for road in roads:
        if "deck_fixed" in road:
            road["deck"] = road["deck_fixed"]
            road["deck_fade"] = np.zeros(len(road["xy"]))
            road["end_dist"] = np.zeros(len(road["xy"]))
    bridges = [r for r in roads if r["mode"] == "bridge" and len(r["xy"]) > 1 and "deck_fixed" not in r]
    dists, a_nodes, b_nodes = _bridge_graph_distances(bridges)
    if not bridges:
        return {}
    lengths = np.array([arc_length(r["xy"])[-1] for r in bridges])
    own_fade = np.maximum(np.minimum(BRIDGE_FADE_M, lengths / 3.0), STEP_M)
    n_nodes = int(max(a_nodes.max(), b_nodes.max())) + 1
    node_fade = np.zeros(n_nodes)
    np.maximum.at(node_fade, a_nodes, own_fade)
    np.maximum.at(node_fade, b_nodes, own_fade)
    for i, (road, (d0, d1)) in enumerate(zip(bridges, dists)):
        xy = road["xy"]
        s = arc_length(xy)
        total = float(s[-1])
        base = np.maximum(surface_at(xy[:, 0], xy[:, 1]), 0.0)
        if len(base) > 2:
            base = maximum_filter1d(base, size=max(1, int(round(60.0 / STEP_M))) | 1, mode="nearest")
            base = gaussian_filter1d(base, DESIGN_SIGMA_M / STEP_M, mode="nearest")
        clearance = max(6.0, 9.0 * road["height_scale"])
        end_dist = np.minimum(d0 + s, d1 + (total - s))
        fade_len = np.full(len(xy), own_fade[i])
        fade_len[0] = node_fade[a_nodes[i]]
        fade_len[-1] = node_fade[b_nodes[i]]
        fade = np.clip(end_dist / fade_len, 0.0, 1.0)
        fade = fade * fade * (3.0 - 2.0 * fade)
        road["deck"] = base + BRIDGE_LIFT_M + clearance * fade
        road["deck_fade"] = fade
        road["end_dist"] = end_dist
    lifted = 0
    worst = 0.0
    ground = [r for r in roads if r["mode"] in {"ground", "tunnel"} and len(r["xy"]) > 1]
    for layer in sorted({r["layer"] for r in bridges}):
        upper = [i for i, r in enumerate(bridges) if r["layer"] == layer]
        lowers = ground + [r for r in roads if r["mode"] == "bridge" and len(r["xy"]) > 1 and (r["layer"] < layer or ("deck_fixed" in r and layer > 0))]
        bi, si, _, lz, dz = deck_crossings([bridges[i] for i in upper], lowers, "deck", lambda r, j, u: _lower_z(r, j, u, surface_at), OVERPASS_NEAR_END_M)
        need = lz + OVERPASS_CLEARANCE_M
        short = need > dz + 1e-6
        if not short.any():
            continue
        sources = [(upper[int(b)], int(i), float(v)) for b, i, v in zip(bi[short], si[short], need[short])]
        floor = _floor_decks(bridges, a_nodes, b_nodes, sources, OVERPASS_RAMP_GRADE)
        sizes = np.cumsum([0] + [len(r["xy"]) for r in bridges])
        for k in upper:
            f = floor[sizes[k] : sizes[k + 1]]
            raise_by = f - bridges[k]["deck"]
            if np.any(raise_by > 1e-6):
                worst = max(worst, float(raise_by.max()))
                bridges[k]["deck"] = np.maximum(bridges[k]["deck"], f)
                lifted += 1
    log(f"bridge decks {len(bridges)}  raised over crossed roads {lifted}  max raise {worst:.2f} m")
    return {"bridge_pieces": len(bridges), "raised_over_crossings": lifted, "max_raise_m": worst}


def bridge_clearance_report(roads: list[dict]) -> dict:
    """Final deck centreline height minus the driving surface of every lower road
    it crosses without a shared node (crossings near a ramp foot excluded)."""
    from tools.pipeline.road_graph import deck_crossings

    bridges = [r for r in roads if r["mode"] == "bridge" and "center" in r and "deck_fixed" not in r and len(r["xy"]) > 1]
    for r in bridges:
        r["_cz"] = r["center"][:, 2]
    gaps = []
    for layer in sorted({r["layer"] for r in bridges}):
        upper = [r for r in bridges if r["layer"] == layer]
        lowers = [r for r in roads if "center" in r and len(r["xy"]) > 1 and (r["mode"] != "bridge" or r["layer"] < layer or ("deck_fixed" in r and layer > 0))]

        def lz(r, j, u):
            return float(r["center"][j, 2] * (1 - u) + r["center"][j + 1, 2] * u)

        _, _, _, low, deck = deck_crossings(upper, lowers, "_cz", lz, OVERPASS_NEAR_END_M)
        gaps.append(deck - low)
    for r in bridges:
        r.pop("_cz", None)
    gap = np.concatenate(gaps) if gaps else np.zeros(0)
    if not len(gap):
        return {"crossings": 0}
    return {
        "crossings": int(len(gap)),
        "min_m": float(gap.min()),
        "p05_m": float(np.percentile(gap, 5)),
        "median_m": float(np.median(gap)),
        "under_4m_pct": float(np.mean(gap < 4.0) * 100.0),
        "under_5_5m_pct": float(np.mean(gap < OVERPASS_CLEARANCE_M - 0.01) * 100.0),
    }


ACROSS_MAX_M = 6.5


def ribbon_grid(road: dict):
    """(N, M, 2) vertex positions across the ribbon, left edge first, and v coordinates.

    The carve makes the ground flat across a road, so a ribbon up to ACROSS_MAX_M
    wide needs no inner column; wider ones get a column every ACROSS_M or so."""
    xy = road["xy"]
    normals = left_normals(xy)
    width = road["hl"] + road["hr"]
    wmax = float(width.max())
    m = 2 if wmax <= ACROSS_MAX_M else max(3, int(math.ceil(wmax / ACROSS_M)) + 1)
    v = np.linspace(0.0, 1.0, m)
    offset = road["hl"][:, None] - v[None, :] * width[:, None]
    pos = xy[:, None, :] + normals[:, None, :] * offset[:, :, None]
    return pos, v


def lane_layout(road: dict):
    """Per centreline point: ribbon width, direction split (metres from the left
    edge; equal to the width when the ribbon is one-way), lanes left and right of it."""
    hl, hr = road["hl"], road["hr"]
    width = hl + hr
    n = len(hl)
    own_l = int(road.get("own_l", road.get("lanes", 1)))
    own_r = int(road.get("own_r", 0))
    add_l = road.get("add_l", np.zeros(n, dtype=np.int64))
    add_r = road.get("add_r", np.zeros(n, dtype=np.int64))
    opp_l = road.get("opp_l", np.zeros(n, dtype=bool))
    opp_r = road.get("opp_r", np.zeros(n, dtype=bool))
    bh = float(road.get("base_half", float(width.min()) * 0.5))
    if own_r > 0:
        split = hl.copy()
        lanes_l = own_l + add_l
        lanes_r = own_r + add_r
    else:
        right = opp_r
        left = opp_l & ~opp_r
        split = np.where(right, hl + bh, np.where(left, hl - bh, width))
        lanes_l = np.where(right, own_l + add_l, np.where(left, add_l, own_l + add_l + add_r))
        lanes_r = np.where(right, add_r, np.where(left, own_l + add_r, 0))
    split = np.clip(split, 0.0, width)
    return width, split, np.asarray(lanes_l, dtype=np.int64), np.asarray(lanes_r, dtype=np.int64)


def marking_code(split: np.ndarray, lanes_l: np.ndarray, lanes_r: np.ndarray) -> np.ndarray:
    """UV1.y: split metres + 64 * lanes left + 1024 * lanes right (M_Road decodes it)."""
    return np.clip(split, 0.0, 63.9) + 64.0 * np.clip(lanes_l, 0, 15) + 1024.0 * np.clip(lanes_r, 0, 15)


def build_ribbon(road: dict, surface_at) -> dict | None:
    """World-space ribbon mesh (x east, y north, z up) for one road piece.

    uv: (metres along, metres from the left edge). uv1: (ribbon width, marking code).
    color: R = markings on (0 inside junctions), G = 0 (asphalt), A = mode alpha."""
    xy = road["xy"]
    if len(xy) < 2:
        return None
    pos, v = ribbon_grid(road)
    n, m = pos.shape[:2]
    flat = pos.reshape(-1, 2)
    if road["mode"] == "bridge":
        z = surface_at(flat[:, 0], flat[:, 1]).reshape(n, m) + BRIDGE_LIFT_M
        z = np.maximum(z, road["deck"][:, None])
    else:
        z = surface_at(flat[:, 0], flat[:, 1]).reshape(n, m) + ground_lift(road["highway"])
    verts = np.column_stack([flat, z.reshape(-1)])
    s = arc_length(xy)
    width, split, lanes_l, lanes_r = lane_layout(road)
    uv = np.column_stack([np.repeat(s, m), (v[None, :] * width[:, None]).reshape(-1)])
    uv1 = np.column_stack([np.repeat(width, m), np.repeat(marking_code(split, lanes_l, lanes_r), m)])
    fade = road.get("fade", np.ones(n))
    color = np.zeros((n * m, 4))
    color[:, 0] = np.repeat(fade, m)
    color[:, 3] = MODE_ALPHA[road["mode"]]
    ii, jj = np.meshgrid(np.arange(n - 1), np.arange(m - 1), indexing="ij")
    p0 = (ii * m + jj).reshape(-1)
    p1 = p0 + 1
    p2 = p0 + m + 1
    p3 = p0 + m
    # Same winding as geometry.append_ribbon: (p0, p3, p2) and (p0, p2, p1) face +Y in glTF.
    tris = np.concatenate([np.column_stack([p0, p3, p2]), np.column_stack([p0, p2, p1])])
    return {"verts": verts, "uv": uv, "uv1": uv1, "color": color, "tris": tris, "alpha": MODE_ALPHA[road["mode"]], "material": 1}


def vertex_normals_gltf(verts_gltf: np.ndarray, tris: np.ndarray) -> np.ndarray:
    a = verts_gltf[tris[:, 0]]
    b = verts_gltf[tris[:, 1]]
    c = verts_gltf[tris[:, 2]]
    face = np.cross(b - a, c - a)
    acc = np.zeros_like(verts_gltf)
    for k in range(3):
        np.add.at(acc, tris[:, k], face)
    length = np.linalg.norm(acc, axis=1, keepdims=True)
    out = np.where(length > 1e-9, acc / np.maximum(length, 1e-9), np.array([0.0, 1.0, 0.0]))
    out[out[:, 1] < 0] *= -1.0
    return out


def edge_polygons(roads: list[dict], pad: float) -> list[np.ndarray]:
    """Outline rings (ribbon edges plus pad) of drivable non-bridge pieces."""
    rings = []
    for road in roads:
        if road["mode"] == "bridge" or len(road["xy"]) < 2:
            continue
        normals = left_normals(road["xy"])
        left = road["xy"] + normals * (road["hl"] + pad)[:, None]
        right = road["xy"] - normals * (road["hr"] + pad)[:, None]
        rings.append(np.vstack([left, right[::-1]]))
    return rings
