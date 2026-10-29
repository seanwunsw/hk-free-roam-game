"""Measure how well the road meshes sit on one consistent ground surface.

Usage: python -m pipeline.check_roads [processed_dir] [--spawns FILE] [--json OUT]

Reports
  * stacked roads: share of road area (0.5 m cells) covered by two or more
    separate ribbon surfaces, overall and where their heights differ by more
    than the character step (0.45 m) or 1 m;
  * road-vs-terrain vertical offset, sampling terrain.r16 with Unreal's
    landscape triangulation;
  * spawns with road or building geometry overhead (within 4 m) or inside a
    building footprint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline.glbutil import read_hkgm_primitives  # type: ignore
    from pipeline.surface import decode_r16, sample_ue  # type: ignore
else:
    from .glbutil import read_hkgm_primitives
    from .surface import decode_r16, sample_ue

CELL = 0.5
STEP = 0.45
MODE_NAMES = {1.0: "ground", 0.75: "tunnel", 0.5: "bridge"}
OFFSET_BINS = [-np.inf, -1.0, -0.3, -0.05, 0.05, 0.3, 0.45, 1.0, 2.0, 4.0, np.inf]


def raster_triangles(xy: np.ndarray, z: np.ndarray, cell: float = CELL):
    """Cell centres covered by triangles: returns (ix, iy, z, tri)."""
    if len(xy) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0), empty
    lo = xy.min(axis=1)
    hi = xy.max(axis=1)
    k0 = np.floor(lo / cell - 0.5).astype(np.int64) + 1
    k1 = np.floor(hi / cell - 0.5).astype(np.int64)
    nk = np.maximum(k1 - k0 + 1, 0)
    counts = nk[:, 0] * nk[:, 1]
    total = int(counts.sum())
    if total == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0), empty
    tri = np.repeat(np.arange(len(xy)), counts)
    start = np.repeat(np.cumsum(counts) - counts, counts)
    local = np.arange(total) - start
    w = nk[tri, 0]
    ix = k0[tri, 0] + local % w
    iy = k0[tri, 1] + local // w
    px = (ix + 0.5) * cell
    py = (iy + 0.5) * cell
    a = xy[tri, 0]
    b = xy[tri, 1]
    c = xy[tri, 2]
    v0x, v0y = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
    v1x, v1y = c[:, 0] - a[:, 0], c[:, 1] - a[:, 1]
    v2x, v2y = px - a[:, 0], py - a[:, 1]
    den = v0x * v1y - v1x * v0y
    ok = np.abs(den) > 1e-12
    den = np.where(ok, den, 1.0)
    l1 = (v2x * v1y - v1x * v2y) / den
    l2 = (v0x * v2y - v2x * v0y) / den
    l0 = 1.0 - l1 - l2
    eps = -1e-6
    inside = ok & (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
    zz = l0 * z[tri, 0] + l1 * z[tri, 1] + l2 * z[tri, 2]
    return ix[inside], iy[inside], zz[inside], tri[inside]


def tile_world_triangles(prim: dict, origin_x: float, origin_y: float):
    pos = prim["positions"].astype(np.float64)
    idx = prim["indices"].reshape(-1, 3)
    world = np.column_stack([pos[:, 0] + origin_x, pos[:, 2] + origin_y, pos[:, 1]])
    return world, idx


def surface_components(pos_local: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Connected surface id per triangle, welding coincident vertices."""
    key = np.round(pos_local * 100.0).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    t = weld[tris]
    n = int(weld.max()) + 1 if len(weld) else 0
    rows = np.concatenate([t[:, 0], t[:, 1]])
    cols = np.concatenate([t[:, 1], t[:, 2]])
    graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return labels[t[:, 0]]


def mode_of(alpha: np.ndarray) -> np.ndarray:
    out = np.full(len(alpha), "ground", dtype=object)
    out[np.abs(alpha - 0.75) < 0.05] = "tunnel"
    out[np.abs(alpha - 0.5) < 0.05] = "bridge"
    return out


class Terrain:
    def __init__(self, processed: Path, manifest: dict) -> None:
        land = manifest["landscape"]
        ny, nx = land["verts_y"], land["verts_x"]
        raw = np.fromfile(processed / "terrain.r16", dtype="<u2").reshape(ny, nx)
        self.h = decode_r16(raw)
        self.min_x = land["min_x_m"]
        self.min_y = land["min_y_m"]
        self.sx = land["spacing_x_m"]
        self.sy = land["spacing_y_m"]

    def __call__(self, x, y):
        return sample_ue(self.h, self.min_x, self.min_y, self.sx, self.sy, x, y)


def analyse_roads(processed: Path, manifest: dict, terrain: Terrain) -> dict:
    tile = manifest["tile_size_m"]
    area_cells = 0
    multi = 0
    gap_step = 0
    gap_1m = 0
    gap_low = 0
    ground_cells = 0
    ground_multi_step = 0
    offsets = []
    modes = []
    for entry in manifest["tiles"]:
        rel = entry.get("roads")
        if not rel:
            continue
        ox, oy = entry["origin_x_m"], entry["origin_y_m"]
        prims = [p for p in read_hkgm_primitives(processed / rel) if p["material"] == 1]
        all_ix, all_iy, all_z, all_comp, all_mode = [], [], [], [], []
        comp_base = 0
        for prim in prims:
            world, tris = tile_world_triangles(prim, ox, oy)
            if len(tris) == 0:
                continue
            comp = surface_components(prim["positions"], tris) + comp_base
            comp_base = int(comp.max()) + 1
            tri_alpha = prim["colors"][tris[:, 0], 3]
            ix, iy, zz, ti = raster_triangles(world[tris][:, :, :2], world[tris][:, :, 2])
            all_ix.append(ix)
            all_iy.append(iy)
            all_z.append(zz)
            all_comp.append(comp[ti])
            all_mode.append(mode_of(tri_alpha[ti]))
        if not all_ix:
            continue
        ix = np.concatenate(all_ix)
        iy = np.concatenate(all_iy)
        zz = np.concatenate(all_z)
        comp = np.concatenate(all_comp)
        mode = np.concatenate(all_mode)
        cx = (ix + 0.5) * CELL
        cy = (iy + 0.5) * CELL
        own = (cx >= ox) & (cx < ox + tile) & (cy >= oy) & (cy < oy + tile)
        ix, iy, zz, comp, mode, cx, cy = ix[own], iy[own], zz[own], comp[own], mode[own], cx[own], cy[own]
        if len(ix) == 0:
            continue
        cell_id = (ix - ix.min()) * 1_000_003 + (iy - iy.min())
        order = np.lexsort((comp, cell_id))
        cell_id, comp, zz, mode, cx, cy = cell_id[order], comp[order], zz[order], mode[order], cx[order], cy[order]
        first = np.ones(len(cell_id), dtype=bool)
        first[1:] = (cell_id[1:] != cell_id[:-1]) | (comp[1:] != comp[:-1])
        cell_id, comp, zz, mode, cx, cy = cell_id[first], comp[first], zz[first], mode[first], cx[first], cy[first]
        starts = np.flatnonzero(np.r_[True, cell_id[1:] != cell_id[:-1]])
        n_surf = np.diff(np.r_[starts, len(cell_id)])
        zmin = np.minimum.reduceat(zz, starts)
        zmax = np.maximum.reduceat(zz, starts)
        gap = zmax - zmin
        area_cells += len(starts)
        multi += int((n_surf >= 2).sum())
        gap_step += int(((n_surf >= 2) & (gap > STEP)).sum())
        gap_1m += int(((n_surf >= 2) & (gap > 1.0)).sum())
        gap_low += int(((n_surf >= 2) & (gap > STEP) & (gap <= 4.0)).sum())
        ground = mode == "ground"
        is_ground_cell = np.maximum.reduceat(ground.astype(np.int8), starts) > 0
        ground_cells += int(is_ground_cell.sum())
        g_only = np.where(ground, zz, np.nan)
        g_starts_count = np.add.reduceat(ground.astype(np.int64), starts)
        with np.errstate(invalid="ignore"):
            g_min = np.fmin.reduceat(g_only, starts)
            g_max = np.fmax.reduceat(g_only, starts)
        ground_multi_step += int(((g_starts_count >= 2) & ((g_max - g_min) > STEP)).sum())
        off = zz - terrain(cx, cy)
        offsets.append(off.astype(np.float32))
        modes.append(mode)
    offsets = np.concatenate(offsets) if offsets else np.zeros(0)
    modes = np.concatenate(modes) if modes else np.zeros(0, dtype=object)
    cell_area = CELL * CELL

    def dist(sel: np.ndarray) -> dict:
        o = offsets[sel]
        if len(o) == 0:
            return {"area_m2": 0.0}
        hist, _ = np.histogram(o, bins=OFFSET_BINS)
        labels = ["<-1", "-1..-0.3", "-0.3..-0.05", "-0.05..0.05", "0.05..0.3", "0.3..0.45", "0.45..1", "1..2", "2..4", ">4"]
        return {
            "area_m2": round(float(len(o) * cell_area)),
            "pct": {k: round(100.0 * v / len(o), 2) for k, v in zip(labels, hist)},
            "p01_p50_p99": [round(float(v), 3) for v in np.percentile(o, [1, 50, 99])],
            "within_step_pct": round(100.0 * float(np.mean(np.abs(o) <= STEP)), 2),
        }

    result = {
        "road_area_m2": round(area_cells * cell_area),
        "stacked_pct": round(100.0 * multi / max(area_cells, 1), 3),
        "stacked_gap_gt_0.45m_pct": round(100.0 * gap_step / max(area_cells, 1), 3),
        "stacked_gap_gt_1m_pct": round(100.0 * gap_1m / max(area_cells, 1), 3),
        "stacked_gap_0.45_to_4m_pct": round(100.0 * gap_low / max(area_cells, 1), 3),
        "ground_stacked_gap_gt_0.45m_pct_of_ground": round(100.0 * ground_multi_step / max(ground_cells, 1), 3),
        "offset_all": dist(np.ones(len(offsets), dtype=bool)),
        "offset_excluding_gt4m": dist(offsets <= 4.0),
    }
    for name in ("ground", "bridge", "tunnel"):
        sel = modes == name
        if sel.any() and not sel.all():
            result[f"offset_{name}"] = dist(sel)
    return result


def _load_tile_tris(processed: Path, entry: dict, key: str, material: int | None):
    rel = entry.get(key)
    if not rel:
        return np.zeros((0, 3, 3))
    out = []
    for prim in read_hkgm_primitives(processed / rel):
        if material is not None and prim["material"] != material:
            continue
        world, tris = tile_world_triangles(prim, entry["origin_x_m"], entry["origin_y_m"])
        out.append(world[tris])
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def _point_hits(tris: np.ndarray, px: float, py: float):
    """z of every triangle containing (px, py)."""
    if len(tris) == 0:
        return np.zeros(0)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    v0 = b[:, :2] - a[:, :2]
    v1 = c[:, :2] - a[:, :2]
    v2 = np.array([px, py]) - a[:, :2]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-9
    den = np.where(ok, den, 1.0)
    l1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
    l2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    l0 = 1 - l1 - l2
    inside = ok & (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
    z = l0 * a[:, 2] + l1 * b[:, 2] + l2 * c[:, 2]
    return z[inside]


def analyse_spawns(processed: Path, manifest: dict, spawns: dict, terrain: Terrain) -> dict:
    tile = manifest["tile_size_m"]
    by_ix = {(e["ix"], e["iy"]): e for e in manifest["tiles"]}
    lx = manifest["landscape"]["min_x_m"]
    ly = manifest["landscape"]["min_y_m"]
    cache: dict = {}

    def tris_near(x: float, y: float):
        ix = int(np.floor((x - lx) / tile))
        iy = int(np.floor((y - ly) / tile))
        roads, builds = [], []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                e = by_ix.get((ix + dx, iy + dy))
                if e is None:
                    continue
                k = (ix + dx, iy + dy)
                if k not in cache:
                    cache[k] = (_load_tile_tris(processed, e, "roads", 1), _load_tile_tris(processed, e, "buildings", 0))
                roads.append(cache[k][0])
                builds.append(cache[k][1])
        return np.concatenate(roads) if roads else np.zeros((0, 3, 3)), np.concatenate(builds) if builds else np.zeros((0, 3, 3))

    entries = [("player", spawns["player"])] + [(c["id"], c) for c in spawns.get("cars", [])]
    report = []
    for name, s in entries:
        x, y, z = s["x_m"], s["y_m"], s["z_m"]
        roads, builds = tris_near(x, y)
        overhead = False
        inside_building = False
        top_gap = None
        under = []
        for ddx in (-0.5, 0.0, 0.5):
            for ddy in (-0.5, 0.0, 0.5):
                rz = _point_hits(roads, x + ddx, y + ddy)
                bz = _point_hits(builds, x + ddx, y + ddy)
                if np.any((rz > z + 0.3) & (rz <= z + 4.0)) or np.any((bz > z + 0.3) & (bz <= z + 4.0)):
                    overhead = True
                if np.any(bz > z + 0.3):
                    inside_building = True
                if ddx == 0.0 and ddy == 0.0:
                    under = list(rz[rz <= z + 0.3]) + [float(terrain(x, y))]
        if under:
            top_gap = round(float(z - max(under)), 3)
        report.append({"id": name, "overhead_within_4m": overhead, "inside_building": inside_building, "z_minus_surface_below_m": top_gap})
    return {
        "spawns": len(report),
        "with_geometry_overhead": sum(r["overhead_within_4m"] for r in report),
        "inside_building": sum(r["inside_building"] for r in report),
        "floating_gt_0.3m": sum(1 for r in report if r["z_minus_surface_below_m"] is not None and r["z_minus_surface_below_m"] > 0.3),
        "player": report[0],
        "bad": [r for r in report if r["overhead_within_4m"] or r["inside_building"] or (r["z_minus_surface_below_m"] or 0) > 0.3],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("processed", nargs="?", default=str(Path(__file__).resolve().parents[2] / "data" / "processed"))
    ap.add_argument("--spawns", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--skip-roads", action="store_true")
    args = ap.parse_args(argv)
    processed = Path(args.processed)
    manifest = json.loads((processed / "manifest.json").read_text())
    terrain = Terrain(processed, manifest)
    out: dict = {"processed": str(processed)}
    if not args.skip_roads:
        out["roads"] = analyse_roads(processed, manifest, terrain)
    spawn_path = Path(args.spawns) if args.spawns else processed / "spawns.json"
    if spawn_path.exists():
        out["spawns"] = analyse_spawns(processed, manifest, json.loads(spawn_path.read_text()), terrain)
    text = json.dumps(out, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
