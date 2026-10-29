"""Road network shaping: merge stacked parallel ways, carve one ground surface,
lift bridges, and build ribbon meshes that sit on the carved landscape.

Order used by build_world:
    roads = prepare_roads(...)             # 4 m centrelines, mode, width
    roads = merge_parallel(roads)          # one ribbon per carriageway pair
    set_design_profiles(roads)             # smooth target heights
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
GROUND_MIN_Z = 0.25
DESIGN_SIGMA_M = 12.0
DESIGN_GRADE = 0.30
DESIGN_MAX_DEVIATION_M = 3.0
TRENCH_CLEARANCE_M = 4.0
BRIDGE_LIFT_M = 0.16
BRIDGE_FADE_M = 40.0


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


def limit_grade(z: np.ndarray, xy: np.ndarray, grade: float) -> np.ndarray:
    if len(z) < 2:
        return z
    step = np.maximum(np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1])), 0.5)
    out = np.array(z, dtype=np.float64, copy=True)
    for i in range(1, len(out)):
        cap = grade * step[i - 1]
        out[i] = min(max(out[i], out[i - 1] - cap), out[i - 1] + cap)
    for i in range(len(out) - 2, -1, -1):
        cap = grade * step[i]
        out[i] = min(max(out[i], out[i + 1] - cap), out[i + 1] + cap)
    return out


def ground_lift(highway: str) -> float:
    """Higher classes sit a few centimetres higher so overlapping junction ribbons do not z-fight."""
    rank = CLASS_RANK.get(highway, len(ROAD_CLASSES))
    return 0.10 + 0.012 * max(0, len(ROAD_CLASSES) - rank)


def make_road(xy, terrain_z, highway, lanes, mode, layer, horizontal) -> dict:
    width, lanes = road_game_width(highway, lanes, horizontal)
    half = np.full(len(xy), width * 0.5)
    return {
        "xy": np.asarray(xy, dtype=np.float64),
        "terrain": np.asarray(terrain_z, dtype=np.float64),
        "width": width,
        "base_half": width * 0.5,
        "hl": half.copy(),
        "hr": half.copy(),
        "lanes": lanes,
        "highway": highway,
        "mode": mode,
        "layer": int(layer),
        "horizontal": horizontal,
        "height_scale": float(np.clip(math.sqrt(max(horizontal, 1e-4)), 0.20, 1.25)),
    }


def slice_road(road: dict, start: int, end: int) -> dict:
    out = dict(road)
    for key in ("xy", "terrain", "hl", "hr", "design"):
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
                for shift in (-1, 0, 1):
                    k = np.clip(cc + shift, first[cc], last[cc])
                    np.maximum.at(g_hl, k[left], need[left])
                    np.maximum.at(g_hr, k[~left], need[~left])
        free = ~absorbed
        runs = []
        keep_mask = np.zeros(n, dtype=bool)
        for s, e in _runs(free):
            if s > 0 and e < n and e - s < 3:
                continue
            keep_mask[s:e] = True
            s2, e2 = max(0, s - 1), min(n, e + 1)
            if e2 - s2 >= 2 and arc_length(xy_b[s2:e2])[-1] >= 6.0:
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
        for s, e in kept_runs.get(i, []):
            out.append(slice_road(road, s, e))
    widened = sum(1 for r in out if np.any(r["hl"] > r["base_half"] + 0.01) or np.any(r["hr"] > r["base_half"] + 0.01))
    log(f"merge_parallel: {len(roads)} ways -> {len(out)} pieces  absorbed points {absorbed_points}/{len(pts)}  widened pieces {widened}")
    return out


def set_design_profiles(roads: list[dict]) -> None:
    """Target heights for ground roads and open-cut tunnels.

    Ground: the terrain profile smoothed along the road, grade-limited, but
    never more than DESIGN_MAX_DEVIATION_M from the smoothed terrain, so the
    carve cannot build tall embankments or deep cuts on steep streets.
    """
    sigma = DESIGN_SIGMA_M / STEP_M
    for road in roads:
        t = road["terrain"]
        xy = road["xy"]
        if road["mode"] == "tunnel":
            s = arc_length(xy)
            total = float(s[-1]) or 1.0
            z = t[0] + (t[-1] - t[0]) * (s / total)
            road["design"] = np.maximum(z, 0.40)
        elif road["mode"] == "ground":
            smooth = gaussian_filter1d(np.maximum(t, GROUND_MIN_Z), sigma, mode="nearest") if len(t) > 2 else np.maximum(t, GROUND_MIN_Z)
            z = limit_grade(smooth, xy, DESIGN_GRADE)
            z = np.clip(z, smooth - DESIGN_MAX_DEVIATION_M, smooth + DESIGN_MAX_DEVIATION_M)
            road["design"] = np.maximum(z, GROUND_MIN_Z)


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
    ground = [r for r in roads if r["mode"] == "ground" and len(r["xy"]) > 1]
    log(f"carving tunnels {len(tunnels)} then ground roads {len(ground)}")
    if tunnels:
        total, count = rasterise_profiles(height.shape, landscape, tunnels)
        carved = _blend_corridor(carved, total, count, spacing, 28.0)
    if ground:
        total, count = rasterise_profiles(height.shape, landscape, ground)
        carved = _blend_corridor(carved, total, count, spacing, 16.0)
        log(f"ground corridor nodes {int((count > 0).sum())}")
    return carved.astype(np.float32)


def _bridge_graph_distances(bridges: list[dict]) -> list[tuple[float, float]]:
    """Distance along connected bridge ways from each bridge end to the nearest
    end that comes down to the ground, so a viaduct split into several OSM ways
    does not dip to the ground at every split."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    if not bridges:
        return []
    ends = np.array([[r["xy"][0], r["xy"][-1]] for r in bridges]).reshape(-1, 2)
    layer = np.repeat([r["layer"] for r in bridges], 2)
    tree = cKDTree(ends)
    parent = np.arange(len(ends))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in tree.query_pairs(2.0):
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
    return [(float(dist[a[i]]), float(dist[b[i]])) for i in range(len(bridges))]


def set_bridge_decks(roads: list[dict], surface_at) -> None:
    """Deck height per centreline point: carved ground (sea clamped to 0) kept
    over short dips, plus clearance that fades to zero toward ground ends."""
    for road in roads:
        if "deck_fixed" in road:
            road["deck"] = road["deck_fixed"]
            road["deck_fade"] = np.zeros(len(road["xy"]))
    bridges = [r for r in roads if r["mode"] == "bridge" and len(r["xy"]) > 1 and "deck_fixed" not in r]
    dists = _bridge_graph_distances(bridges)
    for road, (d0, d1) in zip(bridges, dists):
        xy = road["xy"]
        s = arc_length(xy)
        total = float(s[-1])
        base = np.maximum(surface_at(xy[:, 0], xy[:, 1]), 0.0)
        if len(base) > 2:
            base = maximum_filter1d(base, size=max(1, int(round(60.0 / STEP_M))) | 1, mode="nearest")
            base = gaussian_filter1d(base, DESIGN_SIGMA_M / STEP_M, mode="nearest")
        clearance = max(6.0, 9.0 * road["height_scale"])
        end_dist = np.minimum(d0 + s, d1 + (total - s))
        fade = np.clip(end_dist / BRIDGE_FADE_M, 0.0, 1.0)
        fade = fade * fade * (3.0 - 2.0 * fade)
        road["deck"] = base + BRIDGE_LIFT_M + clearance * fade
        road["deck_fade"] = fade


def ribbon_grid(road: dict):
    """(N, M, 2) vertex positions across the ribbon, left edge first, and v coordinates."""
    xy = road["xy"]
    normals = left_normals(xy)
    width = road["hl"] + road["hr"]
    m = max(2, int(math.ceil(float(width.max()) / ACROSS_M)) + 1)
    v = np.linspace(0.0, 1.0, m)
    offset = road["hl"][:, None] - v[None, :] * width[:, None]
    pos = xy[:, None, :] + normals[:, None, :] * offset[:, :, None]
    return pos, v


def build_ribbon(road: dict, surface_at) -> dict | None:
    """World-space ribbon mesh (x east, y north, z up) for one road piece."""
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
    uv = np.column_stack([np.repeat(s, m), np.tile(v, n)])
    ii, jj = np.meshgrid(np.arange(n - 1), np.arange(m - 1), indexing="ij")
    p0 = (ii * m + jj).reshape(-1)
    p1 = p0 + 1
    p2 = p0 + m + 1
    p3 = p0 + m
    # Same winding as geometry.append_ribbon: (p0, p3, p2) and (p0, p2, p1) face +Y in glTF.
    tris = np.concatenate([np.column_stack([p0, p3, p2]), np.column_stack([p0, p2, p1])])
    return {"verts": verts, "uv": uv, "tris": tris, "alpha": MODE_ALPHA[road["mode"]]}


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
