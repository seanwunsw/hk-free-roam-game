"""Whole-network road heights: shared junction vertices and an exact grade limit.

Every road piece used to get its design height on its own (forward/backward
clamp along the way). The backward pass never changes anything after the
forward one, so a long climb drifted off the terrain in the digitising
direction, and two ways meeting at a junction disagreed.

Here every ground and open-cut tunnel piece is one graph:

* A junction is an OSM node used twice or more (bit-identical lon/lat in the
  extract). It is kept as an exact sample through simplification and
  resampling and becomes ONE graph vertex shared by every piece through it.
* Pieces that merge_parallel cut out of an absorbed carriageway end inside the
  kept ribbon; their free ends get a contact edge to the nearest sample of the
  ribbon they stop on.
* The target is the terrain smoothed along the graph. With c(u, v) the
  cheapest grade-limited rise between two vertices,
  A(v) = min_u(t_u + c(u, v)) and B(v) = max_u(t_u - c(u, v)) both satisfy
  every edge limit, so their midpoint does too. Two multi-source Dijkstra runs
  give both. The result is the same whichever way a road was digitised.

Bridges keep their own deck rule (roads.set_bridge_decks); this module also
holds the crossing finder that lifts decks over roads they pass above.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from tools.pipeline.geometry import douglas_peucker

GRADE = 0.30
GROUND_MIN_Z = 0.25
MAX_DEVIATION_M = 3.0
SMOOTH_PASSES = 18  # lazy averaging; ~ a 12 m gaussian along 4 m samples
TUNNEL_MIN_Z = 0.40
CONTACT_MAX_M = 17.0


# ---------------------------------------------------------------------------
# Junctions and pinned resampling
# ---------------------------------------------------------------------------
def node_keys(ll: np.ndarray) -> np.ndarray:
    """OSM stores 1e-7 degree integers, so a shared node has identical lon/lat."""
    ll = np.asarray(ll, dtype=np.float64)
    lon = np.rint(ll[:, 0] * 1e7).astype(np.int64)
    lat = np.rint(ll[:, 1] * 1e7).astype(np.int64)
    return (lon << 31) + lat


def junction_keys(lines: list[np.ndarray]) -> list[np.ndarray]:
    """Per line, the node key where that node is used two or more times
    (by different ways, or twice by one way such as a closed roundabout), else -1."""
    if not lines:
        return []
    keys = [node_keys(ll) for ll in lines]
    allk = np.concatenate(keys)
    uniq, inv, counts = np.unique(allk, return_inverse=True, return_counts=True)
    shared = counts[np.asarray(inv).reshape(-1)] >= 2
    out = np.where(shared, allk, -1)
    sizes = np.cumsum([len(k) for k in keys])[:-1]
    return np.split(out, sizes)


def _resample_span(xy: np.ndarray, step: float) -> np.ndarray:
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(s[-1])
    if total < 1e-6:
        return xy[[0, -1]]
    count = max(1, int(math.ceil(total / step)))
    t = np.linspace(0.0, total, count + 1)
    return np.column_stack([np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])])


def pinned_resample(xy: np.ndarray, keys: np.ndarray, step: float, dp_tolerance: float = 2.5):
    """Simplify and resample a polyline every <= step metres, keeping every
    junction vertex (keys >= 0) and both ends as exact samples.

    Returns (xy, keys) with keys -1 on ordinary samples, or None when the
    line has no length.
    """
    xy = np.asarray(xy, dtype=np.float64)
    keys = np.asarray(keys, dtype=np.int64)
    if len(xy) < 2:
        return None
    pins = np.unique(np.concatenate([[0, len(xy) - 1], np.flatnonzero(keys >= 0)]))
    out_xy = [xy[:1]]
    out_k = [keys[:1]]
    for a, b in zip(pins[:-1], pins[1:]):
        span = xy[a : b + 1]
        if len(span) > 4:
            span = douglas_peucker(span, dp_tolerance)
        if float(np.hypot(*(span[-1] - span[0]))) < 1e-6 and len(span) <= 2:
            # Repeated node: keep the pin once.
            if keys[b] >= 0 and out_k[-1][-1] != keys[b]:
                out_k[-1] = out_k[-1].copy()
                if out_k[-1][-1] < 0:
                    out_k[-1][-1] = keys[b]
            continue
        pts = _resample_span(span, step)[1:]
        k = np.full(len(pts), -1, dtype=np.int64)
        k[-1] = keys[b]
        out_xy.append(pts)
        out_k.append(k)
    rxy = np.concatenate(out_xy)
    rk = np.concatenate(out_k)
    if len(rxy) < 2 or float(np.hypot(*(rxy[-1] - rxy[0]))) + float(np.sum(np.hypot(*np.diff(rxy, axis=0).T))) < 1e-6:
        return None
    return rxy, rk


# ---------------------------------------------------------------------------
# Graph solver
# ---------------------------------------------------------------------------
def _sym(a, b, w, n) -> sparse.csr_matrix:
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    key = lo * np.int64(n) + hi
    order = np.lexsort((w, key))
    ks = key[order]
    first = np.concatenate([[True], ks[1:] != ks[:-1]]) if len(ks) else np.zeros(0, dtype=bool)
    pick = order[first]
    lo, hi, w = lo[pick], hi[pick], w[pick]
    return sparse.csr_matrix((np.concatenate([w, w]), (np.concatenate([lo, hi]), np.concatenate([hi, lo]))), shape=(n, n))


def envelope(graph: sparse.csr_matrix, src_idx, src_val) -> np.ndarray:
    """min over sources u of (src_val[u] + path cost u -> v); +inf if unreachable.
    One Dijkstra from a virtual super-source."""
    n = graph.shape[0]
    src_idx = np.asarray(src_idx, dtype=np.int64)
    src_val = np.asarray(src_val, dtype=np.float64)
    if len(src_idx) == 0:
        return np.full(n, np.inf)
    base = float(src_val.min())
    weights = (src_val - base) + 1e-9
    top = sparse.hstack([graph, sparse.csr_matrix((n, 1))], format="csr")
    bottom = sparse.csr_matrix((weights, (np.zeros(len(src_idx), dtype=np.int64), src_idx)), shape=(1, n + 1))
    full = sparse.vstack([top, bottom], format="csr")
    dist = dijkstra(full, directed=True, indices=n)
    return base + dist[:n]


def lipschitz_midpoint(cost_graph: sparse.csr_matrix, target: np.ndarray) -> np.ndarray:
    every = np.arange(cost_graph.shape[0])
    lower = envelope(cost_graph, every, target)
    upper = -envelope(cost_graph, every, -target)
    return 0.5 * (lower + upper)


def build_graph(pieces: list[dict], contact: bool = True):
    """Vertex id per sample (junction keys shared), plus edge arrays.

    Returns dict with gid (per piece), n, edges (u, v, length)."""
    sizes = np.array([len(p["xy"]) for p in pieces], dtype=np.int64)
    off = np.concatenate([[0], np.cumsum(sizes)])
    total = int(off[-1])
    xy = np.concatenate([p["xy"] for p in pieces]) if total else np.zeros((0, 2))
    keys = np.concatenate([p.get("keys", np.full(len(p["xy"]), -1, dtype=np.int64)) for p in pieces]) if total else np.zeros(0, dtype=np.int64)
    owner = np.repeat(np.arange(len(pieces)), sizes)
    keyed = keys >= 0
    ukeys, kinv = np.unique(keys[keyed], return_inverse=True)
    gid = np.empty(total, dtype=np.int64)
    gid[keyed] = np.asarray(kinv).reshape(-1)
    gid[~keyed] = len(ukeys) + np.arange(int((~keyed).sum()))
    n = len(ukeys) + int((~keyed).sum())
    seg = np.flatnonzero(owner[:-1] == owner[1:]) if total > 1 else np.zeros(0, dtype=np.int64)
    eu, ev = gid[seg], gid[seg + 1]
    el = np.maximum(np.hypot(*(xy[seg + 1] - xy[seg]).T), 0.05) if len(seg) else np.zeros(0)
    keep = eu != ev
    eu, ev, el = eu[keep], ev[keep], el[keep]
    contacts = 0
    if contact and total:
        # Pieces using each key.
        key_pieces = {}
        for k, o in zip(keys[keyed], owner[keyed]):
            key_pieces.setdefault(int(k), set()).add(int(o))
        half = np.concatenate([np.maximum(p["hl"], p["hr"]) if "hl" in p else np.full(len(p["xy"]), 4.0) for p in pieces])
        tree = cKDTree(xy)
        cu, cv, cl = [], [], []
        for i, p in enumerate(pieces):
            for end in (off[i], off[i + 1] - 1):
                k = int(keys[end])
                if k >= 0 and len(key_pieces.get(k, ())) >= 2:
                    continue
                d, j = tree.query(xy[end], k=16, distance_upper_bound=CONTACT_MAX_M)
                for dd, jj in zip(np.atleast_1d(d), np.atleast_1d(j)):
                    if not np.isfinite(dd):
                        break
                    if owner[jj] == i or gid[jj] == gid[end]:
                        continue
                    if dd <= half[jj] + 1.0:
                        cu.append(gid[end])
                        cv.append(gid[jj])
                        cl.append(max(float(dd), 0.05))
                        contacts += 1
                    break
        if cu:
            eu = np.concatenate([eu, cu])
            ev = np.concatenate([ev, cv])
            el = np.concatenate([el, cl])
    return {"gid": [gid[off[i] : off[i + 1]] for i in range(len(pieces))], "n": n, "eu": eu, "ev": ev, "el": el,
            "junctions": len(ukeys), "contacts": contacts}


def _smooth(adj: sparse.csr_matrix, x: np.ndarray, passes: int) -> np.ndarray:
    deg = np.asarray(adj.sum(axis=1)).ravel()
    inv = np.where(deg > 0, 1.0 / np.maximum(deg, 1.0), 0.0)
    for _ in range(passes):
        x = np.where(deg > 0, 0.5 * x + 0.5 * (adj @ x) * inv, x)
    return x


def solve_design_profiles(roads: list[dict], log=print, grade: float = GRADE) -> dict:
    """Set road["design"] on ground and open-cut tunnel pieces from one network solve."""
    pieces = [r for r in roads if r["mode"] in {"ground", "tunnel"} and len(r["xy"]) >= 2]
    if not pieces:
        return {}
    g = build_graph(pieces)
    n = g["n"]
    eu, ev, el = g["eu"], g["ev"], g["el"]
    cost = _sym(eu, ev, grade * el, n)
    adj = _sym(eu, ev, np.ones(len(eu)), n)
    deg = np.asarray(adj.sum(axis=1)).ravel()

    raw = np.zeros(n)
    hits = np.zeros(n)
    is_ground = np.zeros(n, dtype=bool)
    is_tunnel = np.zeros(n, dtype=bool)
    for p, ids in zip(pieces, g["gid"]):
        np.add.at(raw, ids, np.maximum(p["terrain"], GROUND_MIN_Z))
        np.add.at(hits, ids, 1.0)
        (is_ground if p["mode"] == "ground" else is_tunnel)[ids] = True
    raw /= np.maximum(hits, 1.0)
    base = _smooth(adj, raw, SMOOTH_PASSES)
    target = base.copy()
    tunnel_inner = is_tunnel & ~is_ground & (deg > 1)
    for p, ids in zip(pieces, g["gid"]):
        if p["mode"] != "tunnel":
            continue
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p["xy"], axis=0).T))])
        chord = base[ids[0]] + (base[ids[-1]] - base[ids[0]]) * (s / max(float(s[-1]), 1e-6))
        inner = tunnel_inner[ids]
        target[ids[inner]] = chord[inner]

    z = lipschitz_midpoint(cost, target)
    z[~np.isfinite(z)] = target[~np.isfinite(z)]
    # Keep the corridor carve modest on steep warped slopes (as before).
    z = np.where(tunnel_inner, z, np.clip(z, base - MAX_DEVIATION_M, base + MAX_DEVIATION_M))
    lower = np.where(tunnel_inner, TUNNEL_MIN_Z, GROUND_MIN_Z)
    floor = -envelope(cost, np.arange(n), -lower)
    z = np.maximum(z, floor)
    for p, ids in zip(pieces, g["gid"]):
        p["design"] = z[ids].copy()
        p["gid"] = ids
    viol = np.abs(z[eu] - z[ev]) - grade * el if len(eu) else np.zeros(1)
    stats = {
        "vertices": int(n),
        "junction_vertices": int(g["junctions"]),
        "contact_edges": int(g["contacts"]),
        "max_grade_violation_m": float(max(0.0, viol.max())),
        "edges_over_grade_pct": float(np.mean(viol > 1e-3) * 100.0),
        "clamped_pct": float(np.mean(np.abs(z - base) >= MAX_DEVIATION_M - 1e-6) * 100.0),
    }
    log(
        f"road graph: {n} vertices  {g['junctions']} junction vertices  {g['contacts']} contact edges  "
        f"max grade violation {stats['max_grade_violation_m']:.3f} m  edges over grade {stats['edges_over_grade_pct']:.3f}%  "
        f"clamped to +-{MAX_DEVIATION_M:.0f} m {stats['clamped_pct']:.2f}%"
    )
    return stats


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def junction_spread(roads: list[dict], field: str = "design", modes=("ground", "tunnel")) -> dict:
    """Max height difference at OSM nodes shared by two or more pieces."""
    ks, zs = [], []
    for r in roads:
        if r["mode"] not in modes or field not in r or "keys" not in r:
            continue
        z = r[field][:, 2] if field == "center" else r[field]
        m = r["keys"] >= 0
        ks.append(r["keys"][m])
        zs.append(np.asarray(z)[m])
    if not ks:
        return {"junctions": 0}
    k = np.concatenate(ks)
    z = np.concatenate(zs)
    order = np.argsort(k, kind="stable")
    k, z = k[order], z[order]
    uk, start, counts = np.unique(k, return_index=True, return_counts=True)
    multi = counts >= 2
    zmax = np.maximum.reduceat(z, start)
    zmin = np.minimum.reduceat(z, start)
    spread = (zmax - zmin)[multi]
    if not len(spread):
        return {"junctions": 0}
    return {
        "junctions": int(len(spread)),
        "max_m": float(spread.max()),
        "p99_m": float(np.percentile(spread, 99)),
        "over_5cm_pct": float(np.mean(spread > 0.05) * 100.0),
        "over_50cm_pct": float(np.mean(spread > 0.5) * 100.0),
    }


def grade_stats(roads: list[dict], field: str = "design", modes=("ground",), limit: float = GRADE) -> dict:
    over = 0.0
    total = 0.0
    worst = 0.0
    for r in roads:
        if r["mode"] not in modes or field not in r or len(r["xy"]) < 2:
            continue
        z = r[field][:, 2] if field == "center" else r[field]
        run = np.hypot(*np.diff(r["xy"], axis=0).T)
        ok = run >= 0.5
        g = np.abs(np.diff(z))[ok] / run[ok]
        total += float(run[ok].sum())
        over += float(run[ok][g > limit + 0.005].sum())
        if len(g):
            worst = max(worst, float(g.max()))
    return {"length_km": total / 1000.0, "over_limit_pct": over / max(total, 1e-9) * 100.0, "max_grade": worst}


def deck_crossings(bridges: list[dict], lowers: list[dict], deck_key: str, lower_z, near_end_m: float = 10.0):
    """Places where a bridge centreline crosses a lower road it is not connected to.

    Returns arrays (bridge_index, sample_i, t, lower_z, deck_z). lower_z(road, j, u)
    gives the lower road height at segment j, fraction u.
    """
    import shapely

    empty = (np.zeros(0, dtype=np.int64),) * 2 + (np.zeros(0),) * 3
    if not bridges or not lowers:
        return empty
    lp0, lp1, lown, lseg = [], [], [], []
    for li, r in enumerate(lowers):
        if len(r["xy"]) < 2:
            continue
        lp0.append(r["xy"][:-1])
        lp1.append(r["xy"][1:])
        lown.append(np.full(len(r["xy"]) - 1, li))
        lseg.append(np.arange(len(r["xy"]) - 1))
    if not lp0:
        return empty
    lp0, lp1, lown, lseg = map(np.concatenate, (lp0, lp1, lown, lseg))
    tree = shapely.STRtree(shapely.linestrings(np.stack([lp0, lp1], axis=1)))
    out = []
    for bi, b in enumerate(bridges):
        xy = b["xy"]
        if len(xy) < 2:
            continue
        geoms = shapely.linestrings(np.stack([xy[:-1], xy[1:]], axis=1))
        pairs = tree.query(geoms, predicate="intersects")
        if pairs.size == 0:
            continue
        si, lj = pairs[0], pairs[1]
        p = xy[si]
        r = xy[si + 1] - p
        q = lp0[lj]
        sv = lp1[lj] - q
        qp = q - p
        den = r[:, 0] * sv[:, 1] - r[:, 1] * sv[:, 0]
        ok = np.abs(den) > 1e-9
        den = np.where(ok, den, 1.0)
        t = np.clip((qp[:, 0] * sv[:, 1] - qp[:, 1] * sv[:, 0]) / den, 0, 1)
        u = np.clip((qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / den, 0, 1)
        bk = b.get("keys", np.full(len(xy), -1))
        for a in range(len(si)):
            if not ok[a]:
                continue
            i, li, j = int(si[a]), int(lown[lj[a]]), int(lseg[lj[a]])
            low = lowers[li]
            lk = low.get("keys", np.full(len(low["xy"]), -1))
            ends = {int(bk[i]), int(bk[i + 1])} - {-1}
            if ends & ({int(lk[j]), int(lk[j + 1])} - {-1}):
                continue
            ed = b.get("end_dist")
            if ed is not None and (ed[i] * (1 - t[a]) + ed[i + 1] * t[a]) < near_end_m:
                continue
            dz = b[deck_key]
            out.append((bi, i, float(t[a]), float(lower_z(low, j, float(u[a]))), float(dz[i] * (1 - t[a]) + dz[i + 1] * t[a])))
    if not out:
        return empty
    arr = list(zip(*out))
    return (np.array(arr[0]), np.array(arr[1]), np.array(arr[2]), np.array(arr[3]), np.array(arr[4]))
