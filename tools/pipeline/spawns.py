"""Spawn placement on the final road surfaces.

Spawns are chosen after the ribbons and buildings are final, so a spawn is
accepted only where it stands on the top walkable surface and nothing (bridge
deck, other ribbon, building) is overhead within HEADROOM_M.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from tools.pipeline.roads import tangents

HEADROOM_M = 4.0
STEP_TOLERANCE_M = 0.3
BUCKET_M = 32.0


class SurfaceIndex:
    """Point queries against road ribbon triangles and building footprints."""

    def __init__(self, ribbons: list[dict], buildings: list[dict], surface_at) -> None:
        self.surface_at = surface_at
        verts, tris = [], []
        base = 0
        for rib in ribbons:
            verts.append(rib["verts"])
            tris.append(rib["tris"] + base)
            base += len(rib["verts"])
        self.v = np.concatenate(verts) if verts else np.zeros((0, 3))
        self.t = np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)
        self.buckets = self._bucket(self.v[self.t][:, :, :2] if len(self.t) else np.zeros((0, 3, 2)))
        import shapely

        self.buildings = buildings
        polys = [shapely.polygons(np.asarray(b["ring"], dtype=np.float64)) for b in buildings]
        self.bpolys = polys
        self.btree = shapely.STRtree(polys) if polys else None

    @staticmethod
    def _bucket(tri_xy: np.ndarray) -> dict:
        out: dict = {}
        if len(tri_xy) == 0:
            return out
        lo = np.floor(tri_xy.min(axis=1) / BUCKET_M).astype(np.int64)
        hi = np.floor(tri_xy.max(axis=1) / BUCKET_M).astype(np.int64)
        keys, ids = [], []
        for dx in (0, 1):
            for dy in (0, 1):
                kx = lo[:, 0] + dx
                ky = lo[:, 1] + dy
                use = (kx <= hi[:, 0]) & (ky <= hi[:, 1])
                keys.append(kx[use] * 1_000_003 + ky[use])
                ids.append(np.flatnonzero(use))
        keys = np.concatenate(keys)
        ids = np.concatenate(ids)
        order = np.argsort(keys, kind="stable")
        keys, ids = keys[order], ids[order]
        starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
        ends = np.r_[starts[1:], len(keys)]
        for s, e in zip(starts, ends):
            out[int(keys[s])] = ids[s:e]
        return out

    def road_hits(self, x: float, y: float) -> np.ndarray:
        key = int(math.floor(x / BUCKET_M)) * 1_000_003 + int(math.floor(y / BUCKET_M))
        ids = self.buckets.get(key)
        if ids is None or len(ids) == 0:
            return np.zeros(0)
        tri = self.v[self.t[ids]]
        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        v0 = b[:, :2] - a[:, :2]
        v1 = c[:, :2] - a[:, :2]
        v2 = np.array([x, y]) - a[:, :2]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-9
        den = np.where(ok, den, 1.0)
        l1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
        l2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
        l0 = 1.0 - l1 - l2
        inside = ok & (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        return (l0 * a[:, 2] + l1 * b[:, 2] + l2 * c[:, 2])[inside]

    def building_spans(self, x: float, y: float) -> list[tuple[float, float]]:
        if self.btree is None:
            return []
        import shapely

        point = shapely.Point(x, y)
        out = []
        for i in self.btree.query(point, predicate="intersects"):
            b = self.buildings[int(i)]
            out.append((float(b["z"]), float(b["z"] + b["height"])))
        return out

    def top_surface(self, x: float, y: float, near_z: float | None = None) -> tuple[float, bool]:
        """Highest walkable surface at (x, y) (at or below near_z + tolerance when given) and whether it is a road."""
        ground = float(self.surface_at(np.array([x]), np.array([y]))[0])
        hits = self.road_hits(x, y)
        if near_z is not None:
            hits = hits[hits <= near_z + STEP_TOLERANCE_M]
        if len(hits) and hits.max() >= ground:
            return float(hits.max()), True
        return ground, False

    def clear(self, points: np.ndarray, z: float) -> bool:
        for x, y in points:
            hits = self.road_hits(float(x), float(y))
            if np.any((hits > z + STEP_TOLERANCE_M) & (hits <= z + HEADROOM_M)):
                return False
            for base, top in self.building_spans(float(x), float(y)):
                if top > z + STEP_TOLERANCE_M and base < z + HEADROOM_M:
                    return False
        return True


def _footprint(x: float, y: float, yaw_deg: float, half_len: float, half_wid: float) -> np.ndarray:
    t = np.array([math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))])
    n = np.array([-t[1], t[0]])
    pts = [np.array([x, y])]
    for a in (-half_len, half_len):
        for b in (-half_wid, half_wid):
            pts.append(np.array([x, y]) + t * a + n * b)
    return np.array(pts)


def build_spawns(config, warp, roads: list[dict], index: SurfaceIndex, find_pad, log=print):
    ground = [r for r in roads if r["mode"] == "ground" and len(r["xy"]) > 1]
    pts = np.concatenate([r["xy"] for r in ground])
    owner = np.concatenate([np.full(len(r["xy"]), i) for i, r in enumerate(ground)])
    local = np.concatenate([np.arange(len(r["xy"])) for r in ground])
    tree = cKDTree(pts)
    tans = [tangents(r["xy"]) for r in ground]

    def yaw_at(r: int, i: int) -> float:
        t = tans[r][i]
        return math.degrees(math.atan2(t[1], t[0]))

    def car_spot(r: int, i: int):
        road = ground[r]
        x, y = road["xy"][i]
        yaw = yaw_at(r, i)
        z, on_road = index.top_surface(x, y, near_z=float(road["center"][i, 2]))
        if not on_road:
            return None
        if not index.clear(_footprint(x, y, yaw, 2.3, 1.0), z):
            return None
        return float(x), float(y), z, yaw

    def player_spot(r: int, i: int):
        road = ground[r]
        x, y = road["xy"][i]
        yaw = yaw_at(r, i)
        t = tans[r][i]
        right = np.array([t[1], -t[0]])
        options = []
        if road["hr"][i] >= 2.2:
            options.append(np.array([x, y]) + right * min(3.0, road["hr"][i] - 0.8))
        if road["hl"][i] >= 2.2:
            options.append(np.array([x, y]) - right * min(3.0, road["hl"][i] - 0.8))
        options.append(np.array([x, y]) - t * 6.0)
        for px, py in options:
            z, on_road = index.top_surface(px, py, near_z=float(road["center"][i, 2]) + 0.5)
            if not on_road:
                continue
            if index.clear(_footprint(px, py, yaw, 0.35, 0.35), z):
                return float(px), float(py), z, yaw
        return None

    def candidates(x: float, y: float):
        k = min(len(pts), 4000)
        dist, idx = tree.query([x, y], k=k, distance_upper_bound=450.0)
        for d, j in zip(np.atleast_1d(dist), np.atleast_1d(idx)):
            if not np.isfinite(d):
                break
            yield int(owner[j]), int(local[j])

    places, cars, helicopters, helipads, notes = [], [], [], [], []
    player = None
    for place in config["places"]:
        gx, gy = (float(v) for v in warp.lonlat_to_game_m(place["lon"], place["lat"]))
        kind = place.get("kind")
        yaw = 0.0
        if place.get("helicopter") or kind == "helipad":
            px, py, pz = find_pad(gx, gy)
            if abs(px - gx) + abs(py - gy) > 1.0:
                notes.append(f"{place['id']} helipad snapped from water/slope to flat land")
            item = {"id": place["id"], "x_m": px, "y_m": py, "z_m": pz, "yaw_deg": 0.0}
            helipads.append(item)
            helicopters.append(dict(item))
            gx, gy, gz = px, py, pz
            anchor = None
        else:
            gz = float(index.surface_at(np.array([gx]), np.array([gy]))[0])
            anchor = None
            for r, i in candidates(gx, gy):
                car = car_spot(r, i)
                if car is None:
                    continue
                person = player_spot(r, i)
                if person is None:
                    continue
                anchor = (r, i, car, person)
                break
            if anchor is None:
                notes.append(f"{place['id']} has no clear ground road within 450 m")
                gz = max(gz, 0.4)
            else:
                gx, gy, gz, yaw = anchor[3]
                person = anchor[3]
        record = {
            "id": place["id"],
            "name_zh": place.get("name_zh", place["id"]),
            "kind": kind,
            "hotkey": place.get("hotkey"),
            "lon": place["lon"],
            "lat": place["lat"],
            "x_m": gx,
            "y_m": gy,
            "z_m": gz,
            "yaw_deg": yaw,
        }
        places.append(record)
        if place.get("player_start"):
            player = {"id": place["id"], "x_m": gx, "y_m": gy, "z_m": gz, "yaw_deg": yaw}
        count = int(place.get("cars") or 0)
        if count > 0 and kind != "helipad":
            if anchor is None:
                notes.append(f"{place['id']} car skipped, no road")
                continue
            r, i, first_car, _ = anchor
            placed = [first_car]
            # Further slots: along the same road first, then the next nearest
            # clear road points, keeping cars at least 8 m apart.
            options = [(r, j) for j in range(i + 6, len(ground[r]["xy"]), 6)]
            options += list(candidates(first_car[0], first_car[1]))
            for rr, jj in options:
                if len(placed) >= count:
                    break
                spot = car_spot(rr, jj)
                if spot is None:
                    continue
                if min(math.hypot(spot[0] - p[0], spot[1] - p[1]) for p in placed) < 8.0:
                    continue
                if math.hypot(spot[0] - person[0], spot[1] - person[1]) < 3.0:
                    continue
                placed.append(spot)
            for slot, (x, y, z, cyaw) in enumerate(placed):
                cars.append({"id": f"{place['id']}_{slot}", "place": place["id"], "x_m": x, "y_m": y, "z_m": z, "yaw_deg": cyaw})
            if len(placed) < count:
                notes.append(f"{place['id']} placed {len(placed)}/{count} cars")
    if player is None and places:
        player = {key: places[0][key] for key in ("id", "x_m", "y_m", "z_m", "yaw_deg")}
        notes.append("player start fell back to the first place")
    log(f"spawns player {player['id'] if player else None}  cars {len(cars)}  helipads {len(helipads)}")
    for note in notes:
        log("spawn note: " + note)
    spawns = {"player": player, "cars": cars, "helicopters": helicopters, "helipads": helipads}
    return spawns, {"places": places}, notes
