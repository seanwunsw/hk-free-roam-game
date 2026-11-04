"""Street dressing around the drivable ribbons: junctions (marking fade and
surface fills), raised pavement bands with kerbs, and walkways.

All meshes here use the road tile file and M_Road. Material ids in the glb:
1 drivable ribbon, 3 junction fill, 4 pavement / kerb / walkway. check_roads
only measures material 1, so its stacking and landing numbers stay comparable.

Vertex colour channels read by M_Road: R = lane markings on, G = paving
(concrete, not asphalt), B = steps (tread stripes), A = road mode alpha.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from tools.pipeline.roads import arc_length, ground_lift, left_normals, resample

JUNCTION_PAD_M = 1.0
FILL_BELOW_M = 0.05
KERB_M = 0.15
PAVEMENT_M = 1.5
WALK_LIFT_M = 0.06
WALK_STEP_M = 10.0
PAVE_CLASSES = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link", "residential", "living_street"}


# ---------------------------------------------------------------------------
# Junctions
# ---------------------------------------------------------------------------
def junction_nodes(roads: list[dict]) -> list[dict]:
    """Shared OSM nodes where three or more road arms meet.

    Each piece through the node adds an arm on each side that continues; a node
    where two pieces just join end to end has two arms and is not a junction.
    Returns per junction: xy, radius (largest half-width there plus a pad), the
    incident (piece, index) pairs, and whether every incident piece is ground."""
    by_key: dict[int, list[tuple[int, int]]] = {}
    for r, road in enumerate(roads):
        keys = road.get("keys")
        if keys is None or len(road["xy"]) < 2:
            continue
        for i in np.flatnonzero(keys >= 0):
            by_key.setdefault(int(keys[i]), []).append((r, int(i)))
    out = []
    for key, hits in by_key.items():
        arms = 0
        for r, i in hits:
            n = len(roads[r]["xy"])
            arms += int(i > 0) + int(i < n - 1)
        if arms < 3 or len({r for r, _ in hits}) < 2:
            continue
        r0, i0 = hits[0]
        xy = roads[r0]["xy"][i0]
        half = max(max(float(roads[r]["hl"][i]), float(roads[r]["hr"][i])) for r, i in hits)
        out.append(
            {
                "key": key,
                "xy": np.asarray(xy, dtype=np.float64),
                "radius": half + JUNCTION_PAD_M,
                "hits": hits,
                "ground": all(roads[r]["mode"] == "ground" for r, _ in hits),
                "layer": {roads[r]["layer"] if roads[r]["mode"] == "bridge" else 0 for r, _ in hits},
            }
        )
    return out


def apply_marking_fade(roads: list[dict], junctions: list[dict]) -> dict:
    """fade = 0 at centreline points inside any junction disc of a junction the
    piece passes through, so lane lines stop at the junction box."""
    incident: dict[int, list[int]] = {}
    for j, junc in enumerate(junctions):
        for r, _ in junc["hits"]:
            incident.setdefault(r, []).append(j)
    off = 0
    total = 0
    for r, road in enumerate(roads):
        fade = np.ones(len(road["xy"]))
        for j in incident.get(r, []):
            junc = junctions[j]
            d = np.hypot(road["xy"][:, 0] - junc["xy"][0], road["xy"][:, 1] - junc["xy"][1])
            fade[d < junc["radius"]] = 0.0
        road["fade"] = fade
        off += int((fade < 0.5).sum())
        total += len(fade)
    return {"junctions": len(junctions), "centreline_points_unmarked": off, "centreline_points": total}


def _hull(points: np.ndarray) -> np.ndarray | None:
    from scipy.spatial import ConvexHull, QhullError

    if len(points) < 3:
        return None
    try:
        hull = ConvexHull(points)
    except (QhullError, ValueError):
        return None
    ring = points[hull.vertices]
    return ring  # counter-clockwise


def junction_fill_rings(roads: list[dict], junctions: list[dict]) -> list[dict]:
    """Convex fill of the ribbon edge points of every arm within the junction
    radius (plus one sample), ground junctions only."""
    fills = []
    for junc in junctions:
        if not junc["ground"]:
            continue
        pts = []
        reach = junc["radius"] + 2.0
        for r, _ in junc["hits"]:
            road = roads[r]
            xy = road["xy"]
            d = np.hypot(xy[:, 0] - junc["xy"][0], xy[:, 1] - junc["xy"][1])
            near = np.flatnonzero(d <= reach)
            if len(near) == 0:
                continue
            nrm = left_normals(xy)
            pts.append(xy[near] + nrm[near] * road["hl"][near, None])
            pts.append(xy[near] - nrm[near] * road["hr"][near, None])
        if not pts:
            continue
        ring = _hull(np.concatenate(pts))
        if ring is None:
            continue
        lift = min(ground_lift(roads[r]["highway"]) for r, _ in junc["hits"]) - FILL_BELOW_M
        fills.append({"ring": ring, "centre": junc["xy"], "lift": lift})
    return fills


def junction_fill_mesh(fills: list[dict], surface_at) -> dict | None:
    """Fan from the centroid; vertices sit on the final surface plus the lift.
    Junction terrain is carved flat to the shared design height, so a fan follows it."""
    import shapely

    verts, tris, uvs = [], [], []
    base = 0
    for fill in fills:
        ring = np.asarray(shapely.simplify(shapely.polygons(fill["ring"]), 0.15).exterior.coords)[:-1]
        if len(ring) < 3:
            continue
        if shapely.polygons(ring).exterior.is_ccw is False:
            ring = ring[::-1]
        k = len(ring)
        c = ring.mean(axis=0)
        xy = np.vstack([c[None, :], ring])
        z = surface_at(xy[:, 0], xy[:, 1]) + fill["lift"]
        verts.append(np.column_stack([xy, z]))
        uvs.append(xy - c)
        a = np.arange(k)
        # Clockwise seen from above, like the ribbons, so the glTF normal is +Y.
        tris.append(np.column_stack([np.full(k, base), base + 1 + (a + 1) % k, base + 1 + a]))
        base += len(xy)
    if not verts:
        return None
    verts = np.concatenate(verts)
    color = np.zeros((len(verts), 4))
    color[:, 3] = 1.0
    return {"verts": verts, "uv": np.concatenate(uvs), "uv1": np.zeros((len(verts), 2)), "color": color,
            "tris": np.concatenate(tris).astype(np.int64), "alpha": 1.0, "material": 3}


# ---------------------------------------------------------------------------
# Blocking polygons and band meshes
# ---------------------------------------------------------------------------
def ribbon_outlines(roads: list[dict], pad: float = 0.0, modes=("ground", "tunnel")) -> list[np.ndarray]:
    rings = []
    for road in roads:
        if road["mode"] not in modes or len(road["xy"]) < 2:
            continue
        nrm = left_normals(road["xy"])
        left = road["xy"] + nrm * (road["hl"] + pad)[:, None]
        right = road["xy"] - nrm * (road["hr"] + pad)[:, None]
        rings.append(np.vstack([left, right[::-1]]))
    return rings


class Blockers:
    """Point-in-any-polygon test over many rings, plus junction discs."""

    def __init__(self, rings: list[np.ndarray], discs: list[tuple[np.ndarray, float]] = ()) -> None:
        import shapely

        polys = [shapely.make_valid(shapely.polygons(np.asarray(r, dtype=np.float64))) for r in rings if len(r) >= 3]
        self.polys = [p for p in polys if p is not None and not p.is_empty]
        self.tree = shapely.STRtree(self.polys) if self.polys else None
        self.disc_xy = np.array([d[0] for d in discs]) if len(discs) else np.zeros((0, 2))
        self.disc_r = np.array([d[1] for d in discs]) if len(discs) else np.zeros(0)
        self.disc_tree = cKDTree(self.disc_xy) if len(self.disc_xy) else None
        self.disc_max = float(self.disc_r.max()) if len(self.disc_r) else 0.0

    def inside(self, pts: np.ndarray) -> np.ndarray:
        import shapely

        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        out = np.zeros(len(pts), dtype=bool)
        if self.tree is not None and len(pts):
            hits = self.tree.query(shapely.points(pts), predicate="within")
            if hits.size:
                out[np.unique(hits[0])] = True
        if self.disc_tree is not None and len(pts):
            k = min(8, len(self.disc_xy))
            dist, idx = self.disc_tree.query(pts, k=k, distance_upper_bound=self.disc_max)
            dist = dist.reshape(len(pts), -1)
            idx = idx.reshape(len(pts), -1)
            valid = idx < len(self.disc_r)
            radius = np.where(valid, self.disc_r[np.minimum(idx, len(self.disc_r) - 1)], -1.0)
            out |= np.any(valid & (dist < radius), axis=1)
        return out


DECIMATE_XY_M = 0.15
DECIMATE_Z_M = 0.06
DECIMATE_MAX_M = 40.0


def _decimate_run(rows: np.ndarray, z: np.ndarray, along: np.ndarray) -> list[int]:
    """Greedy row subset of one run: a row may be skipped while every skipped row
    stays within DECIMATE_XY_M / DECIMATE_Z_M of the straight quad between the
    kept rows and the span is at most DECIMATE_MAX_M."""
    n = len(rows)
    keep = [0]
    a = 0
    while a < n - 1:
        b = a + 1
        while b + 1 < n and along[b + 1] - along[a] <= DECIMATE_MAX_M:
            c = b + 1
            t = (along[a + 1:c] - along[a]) / max(along[c] - along[a], 1e-9)
            lerp_xy = rows[a][None] + (rows[c] - rows[a])[None] * t[:, None, None]
            lerp_z = z[a][None] + (z[c] - z[a])[None] * t[:, None]
            if np.max(np.hypot(*(rows[a + 1:c] - lerp_xy).transpose(2, 0, 1))) > DECIMATE_XY_M:
                break
            if np.max(np.abs(z[a + 1:c] - lerp_z)) > DECIMATE_Z_M:
                break
            b = c
        keep.append(b)
        a = b
    return keep


def _strip_mesh(rows: np.ndarray, z: np.ndarray, keep: np.ndarray, along: np.ndarray, across: np.ndarray, color: tuple, material: int):
    """Quads between rows for kept segments, straight flat runs decimated.

    rows (N, M, 2) and z (N, M) are left-to-right across; keep (N-1,) per segment."""
    if not keep.any():
        return None
    m = rows.shape[1]
    verts, uvs, tris = [], [], []
    base = 0
    padded = np.r_[False, keep, False]
    starts = np.flatnonzero(padded[1:] & ~padded[:-1])
    ends = np.flatnonzero(~padded[1:] & padded[:-1])
    for s0, e0 in zip(starts, ends):
        idx = np.arange(s0, e0 + 1)
        sel = idx[_decimate_run(rows[idx], z[idx], along[idx])]
        k = len(sel)
        verts.append(np.column_stack([rows[sel].reshape(-1, 2), z[sel].reshape(-1)]))
        uvs.append(np.column_stack([np.repeat(along[sel], m), np.tile(across, k)]))
        r = (base + np.arange(k - 1) * m)[:, None]
        j = np.arange(m - 1)[None, :]
        p0 = (r + j).reshape(-1)
        p1 = p0 + 1
        p3 = p0 + m
        p2 = p3 + 1
        tris.append(np.column_stack([p0, p3, p2]))
        tris.append(np.column_stack([p0, p2, p1]))
        base += k * m
    verts = np.concatenate(verts)
    col = np.tile(np.asarray(color, dtype=np.float64), (len(verts), 1))
    return {"verts": verts, "uv": np.concatenate(uvs), "uv1": np.zeros((len(verts), 2)), "color": col,
            "tris": np.concatenate(tris), "alpha": 1.0, "material": material}


def merge_meshes(meshes: list[dict | None]) -> dict | None:
    meshes = [m for m in meshes if m is not None and len(m["tris"])]
    if not meshes:
        return None
    base = np.cumsum([0] + [len(m["verts"]) for m in meshes])[:-1]
    return {
        "verts": np.concatenate([m["verts"] for m in meshes]),
        "uv": np.concatenate([m["uv"] for m in meshes]),
        "uv1": np.concatenate([m["uv1"] for m in meshes]),
        "color": np.concatenate([m["color"] for m in meshes]),
        "tris": np.concatenate([m["tris"] + b for m, b in zip(meshes, base)]),
        "alpha": 1.0,
        "material": meshes[0]["material"],
    }


def pavement_bands(roads: list[dict], blockers: Blockers, surface_at, land_min: float = 0.3) -> tuple[dict | None, dict]:
    """Raised pavement on both sides of ground roads in PAVE_CLASSES.

    Columns across one side: kerb foot (ribbon edge height), kerb top (+KERB_M),
    pavement outer top, outer foot on the landscape. A segment is dropped where
    the pavement would lie on another road, a junction fill or open water."""
    meshes = []
    kept = total = 0
    for road in roads:
        if road["mode"] != "ground" or road["highway"] not in PAVE_CLASSES or len(road["xy"]) < 2:
            continue
        xy = road["xy"]
        nrm = left_normals(xy)
        lift = ground_lift(road["highway"])
        along = arc_length(xy)
        for sign, half in ((1.0, road["hl"]), (-1.0, road["hr"])):
            out_dir = nrm * sign
            edge = xy + out_dir * half[:, None]
            outer = edge + out_dir * PAVEMENT_M
            probe_in = edge + out_dir * 0.25
            probe_out = edge + out_dir * (PAVEMENT_M - 0.1)
            mids = np.concatenate([
                0.5 * (probe_in[1:] + probe_in[:-1]),
                0.5 * (probe_out[1:] + probe_out[:-1]),
                probe_in[1:], probe_in[:-1], probe_out[1:], probe_out[:-1],
            ])
            blocked = blockers.inside(mids).reshape(6, -1).any(axis=0)
            ez = surface_at(edge[:, 0], edge[:, 1]) + lift
            oz = surface_at(outer[:, 0], outer[:, 1])
            low = (oz < land_min)
            blocked |= low[1:] | low[:-1]
            keep = ~blocked
            total += len(keep)
            kept += int(keep.sum())
            # Left side: columns from the road edge outward; right side mirrored so
            # every strip runs left to right relative to the point order.
            # The outer side has no face: the pavement top meets rising ground or
            # overhangs falling ground by at most KERB_M + lift (buildings stand
            # 1.5 m from the ribbon, right at the outer edge).
            cols_xy = [edge, edge, outer]
            cols_z = [ez, ez + KERB_M, np.maximum(oz + lift, ez) + KERB_M]
            across = np.array([0.0, KERB_M, KERB_M + PAVEMENT_M])
            if sign > 0:
                cols_xy, cols_z, across = cols_xy[::-1], cols_z[::-1], across[::-1].copy()
            rows = np.stack(cols_xy, axis=1)
            z = np.stack(cols_z, axis=1)
            meshes.append(_strip_mesh(rows, z, keep, along, across, (0.0, 1.0, 0.0, 1.0), 4))
    mesh = merge_meshes(meshes)
    return mesh, {"segments": total, "kept": kept, "length_m": float(kept * 4.0)}


def walkway_mesh(warp, walks: list[dict], blockers: Blockers, surface_at, land_min: float = 0.3, bounds=None) -> tuple[dict | None, dict]:
    """Ground walkways (footway, pedestrian, steps) draped on the final surface,
    with segments on roads, pavements, junctions, buildings or water dropped."""
    from tools.pipeline.geometry import walk_game_width

    meshes = []
    counts: dict[str, int] = {}
    kept = total = 0
    if not walks:
        return None, {"ways": 0}
    lon = np.concatenate([w["ll"][:, 0] for w in walks])
    lat = np.concatenate([w["ll"][:, 1] for w in walks])
    gx, gy = warp.lonlat_to_game_m(lon, lat)
    sizes = np.cumsum([len(w["ll"]) for w in walks])[:-1]
    lines = [np.column_stack(p) for p in zip(np.split(gx, sizes), np.split(gy, sizes))]
    mids = np.array([line[len(line) // 2] for line in lines])
    rx, ry = warp.game_to_real_m(mids[:, 0], mids[:, 1])
    sx, sy = warp.axis_scales(rx, ry)
    for walk, line, ax, ay in zip(walks, lines, np.atleast_1d(sx), np.atleast_1d(sy)):
        if bounds is not None:
            lo, hi = line.min(axis=0), line.max(axis=0)
            if hi[0] < bounds[0] or lo[0] > bounds[2] or hi[1] < bounds[1] or lo[1] > bounds[3]:
                continue
        xy = resample(line, WALK_STEP_M)
        if len(xy) < 2:
            continue
        seg = np.diff(xy, axis=0)
        length = np.hypot(seg[:, 0], seg[:, 1])
        nx = -seg[:, 1] / np.maximum(length, 1e-9)
        ny = seg[:, 0] / np.maximum(length, 1e-9)
        perp = math.sqrt(float(np.mean((ax * nx) ** 2 + (ay * ny) ** 2)))
        half = 0.5 * walk_game_width(walk["highway"], perp)
        nrm = left_normals(xy)
        left = xy + nrm * half
        right = xy - nrm * half
        probes = np.concatenate([0.5 * (xy[1:] + xy[:-1]), 0.5 * (left[1:] + left[:-1]), 0.5 * (right[1:] + right[:-1]), xy[1:], xy[:-1]])
        blocked = blockers.inside(probes).reshape(5, -1).any(axis=0)
        zl = surface_at(left[:, 0], left[:, 1])
        zr = surface_at(right[:, 0], right[:, 1])
        low = np.minimum(zl, zr) < land_min
        blocked |= low[1:] | low[:-1]
        keep = ~blocked
        total += len(keep)
        kept += int(keep.sum())
        if not keep.any():
            continue
        counts[walk["highway"]] = counts.get(walk["highway"], 0) + 1
        rows = np.stack([left, right], axis=1)
        z = np.stack([zl, zr], axis=1) + WALK_LIFT_M
        steps = 1.0 if walk["highway"] == "steps" else 0.0
        meshes.append(_strip_mesh(rows, z, keep, arc_length(xy), np.array([0.0, 2 * half]), (0.0, 1.0, steps, 1.0), 4))
    mesh = merge_meshes(meshes)
    return mesh, {"ways": counts, "segments": total, "kept": kept}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def overlap_report(roads: list[dict], junctions: list[dict]) -> dict:
    """Planar overlap between ground ribbons of different pieces, outside every
    junction disc (where overlap is expected), as a share of ground road area.

    Also the grey-slab share: ribbon area where the width exceeds the lanes it
    carries times its lane width by more than 1 m."""
    import shapely

    ground = [r for r in roads if r["mode"] == "ground" and len(r["xy"]) >= 2]
    rings = ribbon_outlines(ground)
    polys = [shapely.make_valid(shapely.polygons(r)) for r in rings]
    area = float(sum(p.area for p in polys))
    tree = shapely.STRtree(polys)
    left, right = tree.query(polys, predicate="intersects")
    pairs = left < right
    left, right = left[pairs], right[pairs]
    inter = shapely.intersection(np.asarray(polys, dtype=object)[left], np.asarray(polys, dtype=object)[right])
    discs = [shapely.Point(j["xy"]).buffer(j["radius"] + 2.0, 8) for j in junctions if j["ground"]]
    over = shapely.union_all([g for g in inter if g is not None and not g.is_empty]) if len(inter) else shapely.Polygon()
    if discs and not over.is_empty:
        over = shapely.difference(over, shapely.union_all(discs))
    over_area = float(over.area) if not over.is_empty else 0.0
    slab = 0.0
    for road in ground:
        from tools.pipeline.roads import lane_layout

        width, _, ll, lr = lane_layout(road)
        carried = (ll + lr) * float(road.get("lane_m", road["width"] / max(road["lanes"], 1)))
        seg = np.hypot(*np.diff(road["xy"], axis=0).T)
        excess = width - carried > 1.0
        w_mid = 0.5 * (width[1:] + width[:-1])
        slab += float(np.sum(seg * w_mid * (excess[1:] | excess[:-1])))
    widths = np.concatenate([r["hl"] + r["hr"] for r in ground])
    return {
        "ground_ribbon_area_m2": round(area, 1),
        "unconnected_overlap_m2": round(over_area, 1),
        "unconnected_overlap_pct": round(100.0 * over_area / max(area, 1e-6), 3),
        "grey_slab_pct": round(100.0 * slab / max(area, 1e-6), 3),
        "width_p50_m": round(float(np.percentile(widths, 50)), 2),
        "width_p95_m": round(float(np.percentile(widths, 95)), 2),
        "width_max_m": round(float(widths.max()), 2),
    }


def junction_gap_report(roads: list[dict], fills: list[dict]) -> dict:
    """Area inside the junction fill outlines that no ground ribbon covers: the
    corner gaps a fill closes."""
    import shapely

    if not fills:
        return {"fills": 0}
    ground = [r for r in roads if r["mode"] == "ground" and len(r["xy"]) >= 2]
    ribbon = shapely.STRtree([shapely.make_valid(shapely.polygons(r)) for r in ribbon_outlines(ground)])
    gap = 0.0
    hull_area = 0.0
    for fill in fills:
        hull = shapely.polygons(fill["ring"])
        near = ribbon.geometries[ribbon.query(hull, predicate="intersects")]
        covered = shapely.union_all(near) if len(near) else shapely.Polygon()
        hull_area += hull.area
        gap += float(shapely.difference(hull, covered).area)
    return {"fills": len(fills), "fill_area_m2": round(hull_area, 1), "gap_closed_m2": round(gap, 1)}


def marking_report(roads: list[dict]) -> dict:
    """Centre lines on one-way ribbons, and marked points inside junctions."""
    from tools.pipeline.roads import lane_layout

    oneway_pts = oneway_centre = 0
    two_way_pts = 0
    for road in roads:
        width, split, ll, lr = lane_layout(road)
        centre = (ll > 0) & (lr > 0)
        if road.get("oneway") and not (road.get("opp_l", np.zeros(1)).any() or road.get("opp_r", np.zeros(1)).any()):
            oneway_pts += len(width)
            oneway_centre += int(centre.sum())
        two_way_pts += int(centre.sum())
    return {"oneway_points": oneway_pts, "oneway_points_with_centre_line": oneway_centre, "points_with_centre_line": two_way_pts}
