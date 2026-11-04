"""At-grade railway strips (Light Rail, plus ground-level heavy rail) built like road
ribbons: one quad strip per track, UV.x metres along, UV.y metres from the left edge.

Samples inside a road ribbon or junction fill are dropped, so at a level crossing the
road surface is the only surface and the two never z-fight."""

from __future__ import annotations

import numpy as np

from tools.pipeline import roads as roadnet

TRACK_HALF_M = 1.5
LIFT_M = 0.09
RAIL_MATERIAL = 5


def strips(warp, rails: list[dict], blockers, surface_at, bounds) -> tuple[dict | None, dict]:
    verts, uvs, tris = [], [], []
    base = 0
    kept_m = 0.0
    crossings = 0
    for rail in rails:
        gx, gy = warp.lonlat_to_game_m(rail["ll"][:, 0], rail["ll"][:, 1])
        xy = np.column_stack([gx, gy])
        if xy[:, 0].max() < bounds[0] or xy[:, 0].min() > bounds[2] or xy[:, 1].max() < bounds[1] or xy[:, 1].min() > bounds[3]:
            continue
        xy = roadnet.resample(xy)
        if len(xy) < 2:
            continue
        blocked = blockers.inside(xy)
        # Runs of free samples become separate strips.
        run_starts = np.flatnonzero(np.diff(np.r_[1, blocked.astype(np.int8)]) == -1)
        run_ends = np.flatnonzero(np.diff(np.r_[blocked.astype(np.int8), 1]) == 1) + 1
        crossings += max(0, len(run_starts) - 1)
        for start, end in zip(run_starts, run_ends):
            piece = xy[start:end]
            if len(piece) < 2:
                continue
            nrm = roadnet.left_normals(piece)
            left = piece + nrm * TRACK_HALF_M
            right = piece - nrm * TRACK_HALF_M
            zl = surface_at(left[:, 0], left[:, 1])
            zr = surface_at(right[:, 0], right[:, 1])
            zc = surface_at(piece[:, 0], piece[:, 1])
            z = np.maximum(np.maximum(zl, zr), zc) + LIFT_M
            along = np.r_[0.0, np.cumsum(np.hypot(*np.diff(piece, axis=0).T))]
            n = len(piece)
            v = np.empty((2 * n, 3))
            v[0::2, :2] = left
            v[1::2, :2] = right
            v[0::2, 2] = z
            v[1::2, 2] = z
            uv = np.empty((2 * n, 2))
            uv[0::2, 0] = along
            uv[1::2, 0] = along
            uv[0::2, 1] = 0.0
            uv[1::2, 1] = 2 * TRACK_HALF_M
            k = np.arange(n - 1)
            a, b, c, d = 2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 3
            # Clockwise seen from above, like the road ribbons, so the glTF normal is +Y.
            t = np.column_stack([np.column_stack([a, c, b]), np.column_stack([c, d, b])]).reshape(-1, 3)
            verts.append(v)
            uvs.append(uv)
            tris.append(t + base)
            base += 2 * n
            kept_m += float(along[-1])
    stats = {"rail_ways": len(rails), "strip_km": round(kept_m / 1000.0, 1), "level_crossing_gaps": crossings}
    if not verts:
        return None, stats
    v = np.concatenate(verts)
    n = len(v)
    mesh = {
        "verts": v,
        "uv": np.concatenate(uvs),
        "uv1": np.zeros((n, 2)),
        "color": np.tile((0.0, 0.0, 0.0, 1.0), (n, 1)),
        "alpha": 1.0,
        "tris": np.concatenate(tris).astype(np.int64),
        "material": RAIL_MATERIAL,
    }
    return mesh, stats
