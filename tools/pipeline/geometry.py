"""Polygon and ribbon helpers used by the world builder. Game axes are metres, X east, Y north."""

from __future__ import annotations

import numpy as np

ROAD_CLASSES = (
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
)

_DEFAULT_LANES = {
    "motorway": 3,
    "motorway_link": 2,
    "trunk": 3,
    "trunk_link": 2,
    "primary": 2,
    "primary_link": 1,
    "secondary": 2,
    "secondary_link": 1,
    "tertiary": 2,
    "tertiary_link": 1,
    "unclassified": 1,
}


def road_game_width(highway: str, lanes: int | None, horizontal_scale: float) -> tuple[float, int]:
    """Playable width in game metres. One lane is at least 3.2 m; two lanes at least 8 m."""
    if lanes is None or lanes < 1:
        lanes = _DEFAULT_LANES.get(highway, 2)
    lanes = int(lanes)
    scaled = lanes * 3.4 * max(horizontal_scale, 0.05)
    if lanes <= 1:
        minimum = 3.2
    elif lanes == 2:
        minimum = 8.0
    else:
        minimum = max(8.0, lanes * 3.2)
    return max(scaled, minimum), lanes


def signed_area(poly: np.ndarray) -> float:
    x = poly[:, 0]
    y = poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def clean_ring(poly: np.ndarray, min_edge: float = 0.08) -> np.ndarray:
    if len(poly) == 0:
        return poly.reshape(0, 2)
    pts = [poly[0]]
    for point in poly[1:]:
        if np.hypot(point[0] - pts[-1][0], point[1] - pts[-1][1]) >= min_edge:
            pts.append(point)
    if len(pts) >= 2 and np.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < min_edge:
        pts.pop()
    return np.asarray(pts, dtype=np.float64)


def ensure_ccw(poly: np.ndarray) -> np.ndarray:
    if len(poly) >= 3 and signed_area(poly) < 0:
        return poly[::-1].copy()
    return poly


def douglas_peucker(points: np.ndarray, tolerance: float) -> np.ndarray:
    if len(points) <= 4 or tolerance <= 0:
        return points

    keep = {0, len(points) - 1}

    def recurse(start: int, end: int) -> None:
        if end <= start + 1:
            return
        segment = points[end] - points[start]
        length = float(np.hypot(segment[0], segment[1]))
        rel = points[start + 1 : end] - points[start]
        if length < 1e-8:
            dist = np.hypot(rel[:, 0], rel[:, 1])
        else:
            dist = np.abs(rel[:, 0] * segment[1] - rel[:, 1] * segment[0]) / length
        if dist.size == 0:
            return
        local = int(np.argmax(dist))
        if dist[local] > tolerance:
            index = start + 1 + local
            keep.add(index)
            recurse(start, index)
            recurse(index, end)

    recurse(0, len(points) - 1)
    return points[np.array(sorted(keep), dtype=np.int64)]


def _cross(poly: np.ndarray, i: int, j: int, k: int) -> float:
    return float(
        (poly[j, 0] - poly[i, 0]) * (poly[k, 1] - poly[i, 1])
        - (poly[j, 1] - poly[i, 1]) * (poly[k, 0] - poly[i, 0])
    )


def _point_in_tri(point: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    c1 = side(a, b, point)
    c2 = side(b, c, point)
    c3 = side(c, a, point)
    return c1 >= -1e-8 and c2 >= -1e-8 and c3 >= -1e-8


def ear_clip(poly: np.ndarray) -> list[tuple[int, int, int]] | None:
    count = len(poly)
    if count < 3:
        return None
    if count == 3:
        return [(0, 1, 2)] if _cross(poly, 0, 1, 2) > 1e-10 else None
    index = list(range(count))
    triangles: list[tuple[int, int, int]] = []
    guard = 0
    limit = count * count
    while len(index) > 3 and guard < limit:
        guard += 1
        found = False
        ring = len(index)
        for tip in range(ring):
            i0 = index[(tip - 1) % ring]
            i1 = index[tip]
            i2 = index[(tip + 1) % ring]
            if _cross(poly, i0, i1, i2) <= 1e-10:
                continue
            a, b, c = poly[i0], poly[i1], poly[i2]
            blocked = False
            for other in index:
                if other in (i0, i1, i2):
                    continue
                if _point_in_tri(poly[other], a, b, c):
                    blocked = True
                    break
            if blocked:
                continue
            triangles.append((i0, i1, i2))
            del index[tip]
            found = True
            break
        if not found:
            return None
    if len(index) == 3 and _cross(poly, index[0], index[1], index[2]) > 1e-10:
        triangles.append((index[0], index[1], index[2]))
        return triangles
    return None


def axis_aligned_ring(poly: np.ndarray) -> np.ndarray:
    min_x, min_y = poly.min(axis=0)
    max_x, max_y = poly.max(axis=0)
    if max_x - min_x < 1.0:
        max_x = min_x + 1.0
    if max_y - min_y < 1.0:
        max_y = min_y + 1.0
    return np.array(
        [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]],
        dtype=np.float64,
    )


class MeshAccum:
    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.normals: list[tuple[float, float, float]] = []
        self.uvs: list[tuple[float, float]] = []
        self.colors: list[tuple[float, float, float, float]] = []
        self.indices: list[int] = []

    def __len__(self) -> int:
        return len(self.indices) // 3

    def add_triangle(self, corners, normal, uvs, color) -> None:
        base = len(self.positions)
        for corner, uv in zip(corners, uvs):
            self.positions.append((float(corner[0]), float(corner[1]), float(corner[2])))
            self.normals.append((float(normal[0]), float(normal[1]), float(normal[2])))
            self.uvs.append((float(uv[0]), float(uv[1])))
            self.colors.append(color)
        self.indices.extend((base, base + 1, base + 2))

    def primitive(self, material: int) -> dict | None:
        if not self.indices:
            return None
        return {
            "positions": np.asarray(self.positions, dtype=np.float32),
            "normals": np.asarray(self.normals, dtype=np.float32),
            "uvs": np.asarray(self.uvs, dtype=np.float32),
            "colors": np.asarray(self.colors, dtype=np.float32),
            "indices": np.asarray(self.indices, dtype=np.uint32),
            "material": material,
        }


def _gltf(east: float, north: float, up: float, origin_east: float, origin_north: float):
    return (east - origin_east, up, north - origin_north)


def _convex_fan(poly: np.ndarray) -> list[tuple[int, int, int]] | None:
    count = len(poly)
    if count < 3:
        return None
    for index in range(count):
        if _cross(poly, index, (index + 1) % count, (index + 2) % count) <= 1e-8:
            return None
    return [(0, index, index + 1) for index in range(1, count - 1)]


def append_extrusion(
    accum: MeshAccum,
    ring: np.ndarray,
    z0: float,
    z1: float,
    color_rgb: tuple[float, float, float],
    origin_xy: tuple[float, float],
    min_height: float = 3.0,
) -> bool:
    ring = ensure_ccw(clean_ring(ring))
    if len(ring) > 16:
        ring = ensure_ccw(douglas_peucker(np.vstack([ring, ring[:1]]), 0.8)[:-1])
        ring = clean_ring(ring)
    triangles = _convex_fan(ring)
    if triangles is None:
        triangles = ear_clip(ring)
    if triangles is None:
        ring = axis_aligned_ring(ring)
        triangles = _convex_fan(ring)
        if triangles is None:
            return False
    if z1 < z0 + min_height:
        z1 = z0 + min_height
    ox, oy = origin_xy
    roof = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
    wall = (color_rgb[0], color_rgb[1], color_rgb[2], 0.0)
    up = (0.0, 1.0, 0.0)
    for i0, i1, i2 in triangles:
        corners = [
            _gltf(ring[i0, 0], ring[i0, 1], z1, ox, oy),
            _gltf(ring[i1, 0], ring[i1, 1], z1, ox, oy),
            _gltf(ring[i2, 0], ring[i2, 1], z1, ox, oy),
        ]
        uvs = [(ring[i0, 0], ring[i0, 1]), (ring[i1, 0], ring[i1, 1]), (ring[i2, 0], ring[i2, 1])]
        accum.add_triangle(corners, up, uvs, roof)
    perimeter = 0.0
    count = len(ring)
    height = z1 - z0
    for index in range(count):
        a = ring[index]
        b = ring[(index + 1) % count]
        dx = float(b[0] - a[0])
        dy = float(b[1] - a[1])
        length = float(np.hypot(dx, dy))
        if length < 1e-4:
            continue
        # Outward normal of a CCW ring, in glTF (east, up, north).
        normal = (dy / length, 0.0, -dx / length)
        p00 = _gltf(a[0], a[1], z0, ox, oy)
        p10 = _gltf(b[0], b[1], z0, ox, oy)
        p11 = _gltf(b[0], b[1], z1, ox, oy)
        p01 = _gltf(a[0], a[1], z1, ox, oy)
        uv00 = (perimeter, 0.0)
        uv10 = (perimeter + length, 0.0)
        uv11 = (perimeter + length, height)
        uv01 = (perimeter, height)
        accum.add_triangle((p00, p11, p10), normal, (uv00, uv11, uv10), wall)
        accum.add_triangle((p00, p01, p11), normal, (uv00, uv01, uv11), wall)
        perimeter += length
    return True


def _left_normals(points: np.ndarray) -> np.ndarray:
    count = len(points)
    normals = np.zeros((count, 2), dtype=np.float64)
    tangents = []
    for index in range(count - 1):
        delta = points[index + 1] - points[index]
        length = float(np.hypot(delta[0], delta[1]))
        if length < 1e-6:
            tangents.append(np.array([1.0, 0.0]))
        else:
            direction = delta / length
            tangents.append(np.array([-direction[1], direction[0]]))
    for index in range(count):
        if index == 0:
            normal = tangents[0]
        elif index == count - 1:
            normal = tangents[-1]
        else:
            normal = tangents[index - 1] + tangents[index]
            length = float(np.hypot(normal[0], normal[1]))
            if length < 1e-4:
                normal = tangents[index - 1]
            else:
                normal = normal / length
                align = float(np.dot(normal, tangents[index - 1]))
                align = max(align, 0.45)
                normal = normal / align
                scale = float(np.hypot(normal[0], normal[1]))
                if scale > 2.2:
                    normal = normal / scale * 2.2
        normals[index] = normal
    return normals


def append_ribbon(
    accum: MeshAccum,
    center: np.ndarray,
    width: float,
    origin_xy: tuple[float, float],
) -> None:
    if len(center) < 2 or width <= 0:
        return
    half = width * 0.5
    normals = _left_normals(center[:, :2])
    left = center[:, :2] + normals * half
    right = center[:, :2] - normals * half
    distance = np.zeros(len(center), dtype=np.float64)
    distance[1:] = np.cumsum(np.hypot(np.diff(center[:, 0]), np.diff(center[:, 1])))
    ox, oy = origin_xy
    white = (0.85, 0.85, 0.82, 1.0)
    for index in range(len(center) - 1):
        z0 = float(center[index, 2])
        z1 = float(center[index + 1, 2])
        corners = [
            _gltf(left[index, 0], left[index, 1], z0, ox, oy),
            _gltf(right[index, 0], right[index, 1], z0, ox, oy),
            _gltf(right[index + 1, 0], right[index + 1, 1], z1, ox, oy),
            _gltf(left[index + 1, 0], left[index + 1, 1], z1, ox, oy),
        ]
        uvs = [
            (distance[index], 0.0),
            (distance[index], 1.0),
            (distance[index + 1], 1.0),
            (distance[index + 1], 0.0),
        ]
        # Upward glTF normal. Winding p0,p3,p2 / p0,p2,p1 is checked against +Y.
        normal = (0.0, 1.0, 0.0)
        accum.add_triangle((corners[0], corners[3], corners[2]), normal, (uvs[0], uvs[3], uvs[2]), white)
        accum.add_triangle((corners[0], corners[2], corners[1]), normal, (uvs[0], uvs[2], uvs[1]), white)


def clip_polyline_rect(points: np.ndarray, xmin: float, ymin: float, xmax: float, ymax: float) -> list[np.ndarray]:
    """Split a polyline into the portions inside an inclusive rectangle. Z is interpolated."""
    if len(points) < 2:
        return []
    runs: list[list[np.ndarray]] = []
    current: list[np.ndarray] = []
    for index in range(len(points) - 1):
        piece = _clip_segment_rect(points[index], points[index + 1], xmin, ymin, xmax, ymax)
        if piece is None:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        start, end = piece
        if not current:
            current = [start, end]
        elif np.linalg.norm(current[-1] - start) > 0.05:
            runs.append(current)
            current = [start, end]
        else:
            current.append(end)
    if len(current) >= 2:
        runs.append(current)
    return [np.vstack(run) for run in runs]


def _clip_segment_rect(a: np.ndarray, b: np.ndarray, xmin, ymin, xmax, ymax):
    """Liang–Barsky clip of one segment. Returns the two endpoints inside the rect, or None."""
    dx = float(b[0] - a[0])
    dy = float(b[1] - a[1])
    dz = float(b[2] - a[2])
    p = [-dx, dx, -dy, dy]
    q = [float(a[0] - xmin), float(xmax - a[0]), float(a[1] - ymin), float(ymax - a[1])]
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    start = np.array([a[0] + t0 * dx, a[1] + t0 * dy, a[2] + t0 * dz], dtype=np.float64)
    end = np.array([a[0] + t1 * dx, a[1] + t1 * dy, a[2] + t1 * dz], dtype=np.float64)
    if np.hypot(end[0] - start[0], end[1] - start[1]) < 1e-3:
        return None
    return start, end


def point_in_ring(point: np.ndarray, ring: np.ndarray) -> bool:
    x, y = float(point[0]), float(point[1])
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside
