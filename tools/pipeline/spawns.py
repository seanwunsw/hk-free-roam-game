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


CAR_HALF_WIDTH_M = 1.0
PLAYER_GAP_M = 3.0
# Car half-length 2.3 m plus margin and the 4 m sample spacing.
JUNCTION_CLEAR_M = 4.5


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
    all_tan = np.concatenate(tans)
    all_half = np.concatenate([np.maximum(r["hl"], r["hr"]) for r in ground])

    def in_junction(r: int, x: float, y: float, yaw: float) -> bool:
        """True when another road crossing at an angle passes within its half-width
        plus JUNCTION_CLEAR_M of (x, y): the spot is inside a junction box."""
        heading = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        for j in tree.query_ball_point([x, y], float(all_half.max()) + JUNCTION_CLEAR_M):
            if owner[j] == r or abs(float(all_tan[j] @ heading)) > math.cos(math.radians(20.0)):
                continue
            if math.hypot(pts[j, 0] - x, pts[j, 1] - y) < all_half[j] + JUNCTION_CLEAR_M:
                return True
        return False

    def yaw_at(r: int, i: int) -> float:
        t = tans[r][i]
        return math.degrees(math.atan2(t[1], t[0]))

    def lane_offset(r: int, i: int) -> float:
        """Left-of-heading offset of the car from the centreline.

        Hong Kong drives on the left, so a parked car sits in the left lane: half the
        left half-width, kept at least CAR_HALF_WIDTH_M + 0.2 m inside the ribbon edge.
        Narrow roads (one lane) keep the car on the centreline.
        """
        hl = float(ground[r]["hl"][i])
        return max(0.0, min(0.5 * hl, hl - CAR_HALF_WIDTH_M - 0.2))

    def car_spot(r: int, i: int):
        road = ground[r]
        yaw = yaw_at(r, i)
        t = tans[r][i]
        left = np.array([-t[1], t[0]])
        x, y = road["xy"][i] + left * lane_offset(r, i)
        if in_junction(r, float(x), float(y), yaw):
            return None
        z, on_road = index.top_surface(x, y, near_z=float(road["center"][i, 2]))
        if not on_road:
            return None
        if not index.clear(_footprint(x, y, yaw, 2.3, CAR_HALF_WIDTH_M), z):
            return None
        return float(x), float(y), z, yaw

    def player_spot(r: int, i: int):
        """A spot PLAYER_GAP_M beside the car, kerb side (left) first, on the road edge
        or the level ground just past it, never inside the car footprint."""
        road = ground[r]
        yaw = yaw_at(r, i)
        t = tans[r][i]
        left = np.array([-t[1], t[0]])
        base = road["xy"][i]
        road_z = float(road["center"][i, 2])
        off = lane_offset(r, i)
        options = [left * (off + PLAYER_GAP_M), -left * (PLAYER_GAP_M - off)]
        for delta in options:
            px, py = base + delta
            z, on_road = index.top_surface(px, py, near_z=road_z + 0.5)
            if not on_road and abs(z - road_z) > 0.6:
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


def nearby_centerlines(roads: list[dict], spawns: dict, radius_m: float = 60.0) -> list[dict]:
    """Final (warped, merged) ground road centrelines within radius_m of any car or the
    player, so check_roads can measure spawn placement without the whole road set."""
    points = [spawns["player"]] if spawns.get("player") else []
    points += spawns.get("cars", [])
    if not points:
        return []
    tree = cKDTree(np.array([[p["x_m"], p["y_m"]] for p in points]))
    out = []
    for road in roads:
        if road["mode"] != "ground" or len(road["xy"]) < 2:
            continue
        near = tree.query_ball_point(road["xy"], radius_m)
        if not any(len(n) for n in near):
            continue
        out.append({
            "xy": np.round(road["xy"], 3).tolist(),
            "hl": np.round(road["hl"], 3).tolist(),
            "hr": np.round(road["hr"], 3).tolist(),
        })
    return out


def spawn_lane_report(spawns: dict, centerlines: list[dict]) -> dict:
    """Per car: distance to the nearest ground centreline segment, heading error to that
    segment (folded to 0-90 degrees, since either travel direction is a valid lane), the
    signed lateral offset (+ left), and whether the 2.0 m wide car body fits on the ribbon.
    Also the player's distance to the first car."""
    segs = []
    for line in centerlines:
        xy = np.asarray(line["xy"], dtype=float)
        hl = np.asarray(line["hl"], dtype=float)
        hr = np.asarray(line["hr"], dtype=float)
        for k in range(len(xy) - 1):
            segs.append((xy[k], xy[k + 1], 0.5 * (hl[k] + hl[k + 1]), 0.5 * (hr[k] + hr[k + 1])))
    cars = []
    for car in spawns.get("cars", []):
        p = np.array([car["x_m"], car["y_m"]])
        best = None
        for a, b, hl, hr in segs:
            d = b - a
            length = float(np.hypot(*d))
            if length < 1e-6:
                continue
            u = float(np.clip(np.dot(p - a, d) / (length * length), 0.0, 1.0))
            q = a + u * d
            dist = float(np.hypot(*(p - q)))
            if best is None or dist < best[0]:
                side = float(d[0] * (p - a)[1] - d[1] * (p - a)[0]) / length
                best = (dist, d / length, side, hl, hr)
        if best is None:
            cars.append({"id": car["id"], "centerline_m": None})
            continue
        dist, tan, side, hl, hr = best
        yaw = math.radians(car["yaw_deg"])
        err = math.degrees(math.acos(min(1.0, abs(math.cos(yaw) * tan[0] + math.sin(yaw) * tan[1]))))
        fits = (side + CAR_HALF_WIDTH_M <= hl + 0.05) and (-side + CAR_HALF_WIDTH_M <= hr + 0.05)
        cars.append({"id": car["id"], "centerline_m": round(dist, 3), "lateral_left_m": round(side, 3),
                     "heading_err_deg": round(err, 2), "body_on_ribbon": bool(fits)})
    measured = [c for c in cars if c.get("centerline_m") is not None]
    player = spawns.get("player")
    first = next((c for c in spawns.get("cars", []) if c["id"].endswith("_0") and player and c["place"] == player["id"]), None)
    gap = None
    if player and first:
        gap = round(math.hypot(player["x_m"] - first["x_m"], player["y_m"] - first["y_m"]), 3)
    return {
        "cars": len(cars),
        "unmeasured": len(cars) - len(measured),
        "max_centerline_m": max((c["centerline_m"] for c in measured), default=None),
        "max_heading_err_deg": max((c["heading_err_deg"] for c in measured), default=None),
        "body_off_ribbon": sum(1 for c in measured if not c["body_on_ribbon"]),
        "player_to_first_car_m": gap,
        "detail": cars,
    }
