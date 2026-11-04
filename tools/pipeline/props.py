"""Street props: traffic signals and safe islands from OSM, and the Sketchfab models.

Placement (per tile, tiles/p_<ix>_<iy>.json):
  {"version": 1, "units": "game metres, yaw degrees counter-clockwise from east",
   "props": [{"asset": slug, "x": .., "y": .., "z": .., "yaw": ..}, ...]}
x, y, z are world game metres (+X east, +Y north); yaw is where the model's front faces.

Models: data/props/<slug>/*.glb (downloaded by hand, see data/props/README.md) are
flattened here into props/<slug>.glb in the tile GLB layout (metres, X east, Y up,
Z north, vertex colours from the base colour texture), scaled to a real height, with
the front turned to +X. The bake imports those as one HISM per asset per tile."""

from __future__ import annotations

import json
import math
import struct
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import numpy as np

from tools.pipeline.glbutil import write_glb

ASSETS = {
    # height_m: model height after scaling (the Sketchfab GLBs are in centimetres after their
    # node matrices, the light is 2.86 m and the island 0.38 m, so both are rescaled).
    # front_yaw_deg: where the lit or signed face points after import, degrees CCW from east.
    # Measured from Sean's files: the vehicle head's red/amber/green lenses sit on the glTF
    # +X face (0); the safe island's blue keep-left sign is on its -X face (180).
    # The pivot is the middle of the lowest 3% of the model (the pole or bollard foot), not
    # the bounding box, because the signal arm sticks out to one side. Tune in props.json.
    "hk_traffic_light": {"height_m": 3.6, "front_yaw_deg": 0.0},
    "hk_safe_island": {"height_m": 1.1, "front_yaw_deg": 180.0},
}
SIGNAL_ASSET = "hk_traffic_light"
ISLAND_ASSET = "hk_safe_island"
KERB_OUT_M = 0.6
STOP_BACK_M = 2.5
SNAP_M = 18.0
MERGE_DEG = 30.0

_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---------------------------------------------------------------------------
# Model flattening
# ---------------------------------------------------------------------------
def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, _, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path} is not a GLB")
    offset = 12
    doc, blob = None, b""
    while offset < min(length, len(data)):
        size, kind = struct.unpack_from("<I4s", data, offset)
        chunk = data[offset + 8 : offset + 8 + size]
        if kind == b"JSON":
            doc = json.loads(chunk.decode("utf-8"))
        elif kind == b"BIN\x00":
            blob = chunk
        offset += 8 + size
    if doc is None:
        raise ValueError(f"{path} has no JSON chunk")
    return doc, blob


def _accessor(doc: dict, blob: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    dtype = _COMP[acc["componentType"]]
    ncomp = _NCOMP[acc["type"]]
    count = acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, ncomp), dtype=np.float32)
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    item = np.dtype(dtype).itemsize * ncomp
    stride = view.get("byteStride", item) or item
    raw = np.frombuffer(blob, dtype=np.uint8, count=stride * (count - 1) + item, offset=start)
    rows = np.lib.stride_tricks.as_strided(raw, shape=(count, item), strides=(stride, 1))
    out = np.frombuffer(np.ascontiguousarray(rows).tobytes(), dtype=dtype).reshape(count, ncomp).astype(np.float64)
    if acc.get("normalized") and dtype != np.float32:
        out /= float(np.iinfo(dtype).max)
    return out


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]), dtype=np.float64)
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    m = np.eye(4)
    m[:3, :3] = r * s[None, :]
    m[:3, 3] = t
    return m


def _image(doc: dict, blob: bytes, texture_index: int, cache: dict):
    if texture_index in cache:
        return cache[texture_index]
    image = None
    try:
        from PIL import Image

        source = doc["textures"][texture_index].get("source")
        img = doc["images"][source]
        if "bufferView" in img:
            view = doc["bufferViews"][img["bufferView"]]
            start = view.get("byteOffset", 0)
            image = np.asarray(Image.open(BytesIO(blob[start : start + view["byteLength"]])).convert("RGBA"), dtype=np.float64) / 255.0
            # Base colour textures are sRGB; vertex colours (and VertColor in M_Prop) are linear.
            image[..., :3] = image[..., :3] ** 2.2
    except Exception:
        image = None
    cache[texture_index] = image
    return image


def flatten_glb(path: Path) -> dict:
    """All mesh primitives of the default scene in one list of triangles, node transforms
    applied, glTF space (Y up). Colour = baseColorFactor x texture at the UV x COLOR_0."""
    doc, blob = _read_glb(path)
    scenes = doc.get("scenes") or [{"nodes": list(range(len(doc.get("nodes", []))))}]
    roots = scenes[doc.get("scene", 0)].get("nodes", [])
    positions, normals, colors, indices = [], [], [], []
    base = 0
    images: dict = {}

    def visit(index: int, parent: np.ndarray) -> None:
        nonlocal base
        node = doc["nodes"][index]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4 or "POSITION" not in prim["attributes"]:
                    continue
                attrs = prim["attributes"]
                pos = _accessor(doc, blob, attrs["POSITION"])[:, :3]
                n = len(pos)
                idx = _accessor(doc, blob, prim["indices"]).astype(np.int64).reshape(-1) if "indices" in prim else np.arange(n)
                if "NORMAL" in attrs:
                    nrm = _accessor(doc, blob, attrs["NORMAL"])[:, :3]
                else:
                    # The bake orders triangle corners by the stored normals, so make some.
                    tri = idx.reshape(-1, 3)
                    face = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
                    nrm = np.zeros((n, 3))
                    for corner in range(3):
                        np.add.at(nrm, tri[:, corner], face)
                col = np.ones((n, 4))
                material = doc.get("materials", [{}])[prim["material"]] if "material" in prim else {}
                pbr = material.get("pbrMetallicRoughness", {})
                col *= np.array(pbr.get("baseColorFactor", [1, 1, 1, 1]), dtype=np.float64)[None, :]
                tex = pbr.get("baseColorTexture")
                uv_key = f"TEXCOORD_{tex.get('texCoord', 0)}" if tex else None
                if tex and uv_key in attrs:
                    image = _image(doc, blob, tex["index"], images)
                    if image is not None:
                        uv = _accessor(doc, blob, attrs[uv_key])
                        h, w = image.shape[:2]
                        u = np.mod(uv[:, 0], 1.0)
                        v = np.mod(uv[:, 1], 1.0)
                        col *= image[np.clip((v * h).astype(np.int64), 0, h - 1), np.clip((u * w).astype(np.int64), 0, w - 1)]
                if "COLOR_0" in attrs:
                    vc = _accessor(doc, blob, attrs["COLOR_0"])
                    col[:, : vc.shape[1]] *= vc
                p = (world @ np.column_stack([pos, np.ones(n)]).T).T[:, :3]
                normal_m = np.linalg.inv(world[:3, :3]).T
                q = nrm @ normal_m.T
                q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
                if np.linalg.det(world[:3, :3]) < 0:
                    idx = idx.reshape(-1, 3)[:, ::-1].reshape(-1)
                positions.append(p)
                normals.append(q)
                colors.append(col)
                indices.append(idx + base)
                base += n
        for child in node.get("children", []):
            visit(child, world)

    for root in roots:
        visit(root, np.eye(4))
    if not positions:
        raise ValueError(f"{path} has no triangle meshes")
    return {
        "positions": np.concatenate(positions),
        "normals": np.concatenate(normals),
        "colors": np.concatenate(colors),
        "indices": np.concatenate(indices),
    }


def _settings(root: Path) -> dict:
    settings = {slug: dict(value) for slug, value in ASSETS.items()}
    path = root / "data" / "props" / "props.json"
    if path.exists():
        for slug, value in json.loads(path.read_text(encoding="utf-8")).get("assets", {}).items():
            settings.setdefault(slug, {}).update(value)
    return settings


def prepare_assets(root: Path, out: Path, log=print) -> dict:
    """Flatten data/props/<slug>/*.glb into out/props/<slug>.glb. A missing model is
    skipped with a log line; its placements are still written."""
    settings = _settings(root)
    target = out / "props"
    target.mkdir(parents=True, exist_ok=True)
    assets = {}
    for slug, conf in sorted(settings.items()):
        folder = root / "data" / "props" / slug
        sources = sorted(folder.glob("*.glb")) if folder.is_dir() else []
        if not sources:
            log(f"props: no GLB in data/props/{slug}, skipped (placements still written)")
            continue
        try:
            mesh = flatten_glb(sources[0])
        except Exception as exc:  # a broken download should not stop the world build
            log(f"props: {sources[0].name} unreadable, skipped: {exc}")
            continue
        p = mesh["positions"]
        # glTF is right-handed with +Z front; the tile GLBs use Z north. Mirror Z so the
        # model is not mirrored in game, then sit it on y = 0, centred, at its real height.
        p = p * np.array([1.0, 1.0, -1.0])
        nrm = mesh["normals"] * np.array([1.0, 1.0, -1.0])
        idx = mesh["indices"].reshape(-1, 3)[:, ::-1].reshape(-1)
        lo, hi = p.min(axis=0), p.max(axis=0)
        tall = max(hi[1] - lo[1], 1e-6)
        scale = float(conf.get("height_m", 2.0)) / tall
        foot = p[p[:, 1] <= lo[1] + 0.03 * tall]
        centre = np.array([(foot[:, 0].min() + foot[:, 0].max()) * 0.5, lo[1], (foot[:, 2].min() + foot[:, 2].max()) * 0.5])
        p = (p - centre) * scale
        # Turn the front to +X (east): yaw 0 in the placements means "faces east".
        turn = -math.radians(float(conf.get("front_yaw_deg", 0.0)))
        c, s = math.cos(turn), math.sin(turn)
        # Rotation about +Y (up) in X east / Z north space, counter-clockwise seen from above.
        rot = np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
        p = p @ rot.T
        nrm = nrm @ rot.T
        path = target / f"{slug}.glb"
        write_glb(
            path,
            [
                {
                    "positions": p.astype(np.float32),
                    "normals": nrm.astype(np.float32),
                    "uvs": np.zeros((len(p), 2), np.float32),
                    "colors": np.clip(mesh["colors"], 0.0, 1.0).astype(np.float32),
                    "indices": idx.astype(np.uint32),
                    "material": 6,
                }
            ],
        )
        try:
            extras = _read_glb(sources[0])[0].get("asset", {}).get("extras", {})
        except Exception:
            extras = {}
        assets[slug] = {
            "file": f"props/{path.name}",
            "credit": {k: extras[k] for k in ("title", "author", "license", "source") if k in extras},
            "source": f"data/props/{slug}/{sources[0].name}",
            "triangles": int(len(idx) // 3),
            "height_m": round(float(p[:, 1].max()), 2),
            "footprint_m": [round(float(np.ptp(p[:, 0])), 2), round(float(np.ptp(p[:, 2])), 2)],
        }
        log(f"props: {slug} from {sources[0].name}  {assets[slug]['triangles']} triangles  scale {scale:.4f}")
    return assets


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
class _RoadIndex:
    """Nearest drivable centreline sample with its heading, half widths and height."""

    def __init__(self, roads: list[dict]) -> None:
        from scipy.spatial import cKDTree

        from tools.pipeline import roads as roadnet

        xy, head, hl, hr, z, ids = [], [], [], [], [], []
        for k, road in enumerate(roads):
            if "center" not in road or len(road["xy"]) < 2:
                continue
            pts = road["xy"]
            d = np.gradient(pts, axis=0)
            xy.append(pts)
            head.append(d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9))
            hl.append(road["hl"])
            hr.append(road["hr"])
            z.append(road["center"][:, 2])
            ids.append(np.full(len(pts), k))
        self.xy = np.concatenate(xy)
        self.head = np.concatenate(head)
        self.hl = np.concatenate(hl)
        self.hr = np.concatenate(hr)
        self.z = np.concatenate(z)
        self.ids = np.concatenate(ids)
        self.tree = cKDTree(self.xy)
        self.roadnet = roadnet

    def near(self, x: float, y: float, k: int = 12):
        dist, idx = self.tree.query([x, y], k=min(k, len(self.xy)), distance_upper_bound=SNAP_M)
        dist = np.atleast_1d(dist)
        idx = np.atleast_1d(idx)
        ok = idx < len(self.xy)
        return dist[ok], idx[ok]


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / max(float(np.hypot(*v)), 1e-9)


def _yaw(v) -> float:
    return round(math.degrees(math.atan2(v[1], v[0])), 1)


def place(warp, extracted: dict, roads: list[dict], bounds, log=print) -> tuple[list[dict], dict]:
    """Signals at the left kerb before the stop line, facing the traffic that arrives
    (HK drives on the left); islands on the centreline along the road."""
    index = _RoadIndex(roads)
    props: list[dict] = []
    stats = defaultdict(int)

    # Approaches: (node id) -> list of travel directions arriving at the node, in game XY.
    approaches = defaultdict(list)
    nodes = {}
    for item in extracted.get("signal_approaches", []):
        gx, gy = warp.lonlat_to_game_m(np.array([item["lon"], item["from_lon"]]), np.array([item["lat"], item["from_lat"]]))
        x, y = float(gx[0]), float(gy[0])
        if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
            continue
        d = np.array([gx[0] - gx[1], gy[0] - gy[1]])
        if np.hypot(*d) < 1e-6:
            continue
        nodes[item["id"]] = (x, y)
        approaches[item["id"]].append(_unit(d))
    for node_id, dirs in approaches.items():
        x, y = nodes[node_id]
        kept: list[np.ndarray] = []
        for d in dirs:
            if all(float(np.dot(d, k)) < math.cos(math.radians(MERGE_DEG)) for k in kept):
                kept.append(d)
        stats["signal_nodes"] += 1
        for d in kept[:4]:
            dist, idx = index.near(x - d[0] * STOP_BACK_M, y - d[1] * STOP_BACK_M)
            if not len(dist):
                stats["signal_unsnapped"] += 1
                continue
            # The sample whose heading best matches this approach (either orientation).
            align = np.abs(np.einsum("ij,j->i", index.head[idx], d))
            best = idx[int(np.argmax(align - dist / (4.0 * SNAP_M)))]
            same = float(np.dot(index.head[best], d)) >= 0.0
            half = float(index.hl[best] if same else index.hr[best])
            centre = index.xy[best]
            left = np.array([-d[1], d[0]])
            # Offset from the snapped centreline, along the approach, to the left kerb.
            along = float(np.dot(np.array([x, y]) - centre, d)) - STOP_BACK_M
            pos = centre + d * along + left * (half + KERB_OUT_M)
            props.append({"asset": SIGNAL_ASSET, "x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2),
                          "z": round(float(index.z[best]), 2), "yaw": _yaw(-d)})
            stats["signals"] += 1

    def island_at(x: float, y: float, axis=None) -> None:
        if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
            return
        dist, idx = index.near(x, y, k=4)
        if not len(dist):
            stats["island_unsnapped"] += 1
            return
        best = idx[0]
        # The sign faces the traffic travelling along the road's digitised direction.
        head = -(index.head[best] if axis is None else axis)
        if axis is None:
            # Crossing islands sit on the dividing line (the ribbon split, else the centre).
            c = index.xy[best]
            pos = c
        else:
            pos = np.array([x, y])
        props.append({"asset": ISLAND_ASSET, "x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2),
                      "z": round(float(index.z[best]), 2), "yaw": _yaw(head)})
        stats["islands"] += 1

    for item in extracted.get("island_nodes", []):
        gx, gy = warp.lonlat_to_game_m(np.array([item["lon"]]), np.array([item["lat"]]))
        island_at(float(gx[0]), float(gy[0]))
    for ring_ll in extracted.get("island_ways", []):
        gx, gy = warp.lonlat_to_game_m(ring_ll[:, 0], ring_ll[:, 1])
        ring = np.column_stack([gx, gy])
        c = ring.mean(axis=0)
        cov = np.cov((ring - c).T) if len(ring) > 2 else np.eye(2)
        axis = np.linalg.eigh(cov)[1][:, -1]
        dist, _ = index.near(float(c[0]), float(c[1]), k=1)
        if not len(dist) or float(dist[0]) > 6.0:
            stats["island_ways_off_road"] += 1
            continue
        island_at(float(c[0]), float(c[1]), _unit(axis))
    stats = dict(stats)
    log(f"props placed {json.dumps(stats)}")
    return props, stats


def write_tiles(tile_dir: Path, props: list[dict], landscape, tile: float) -> dict:
    """tiles/p_<ix>_<iy>.json per tile; returns {(ix, iy): relative path}."""
    grouped = defaultdict(list)
    max_ix = max(0, int(math.floor((landscape["max_x"] - landscape["min_x"] - 1e-3) / tile)))
    max_iy = max(0, int(math.floor((landscape["max_y"] - landscape["min_y"] - 1e-3) / tile)))
    for prop in props:
        ix = min(max_ix, max(0, int(math.floor((prop["x"] - landscape["min_x"]) / tile))))
        iy = min(max_iy, max(0, int(math.floor((prop["y"] - landscape["min_y"]) / tile))))
        grouped[(ix, iy)].append(prop)
    out = {}
    for (ix, iy), items in grouped.items():
        path = tile_dir / f"p_{ix}_{iy}.json"
        doc = {"version": 1, "units": "game metres, yaw degrees counter-clockwise from east", "props": items}
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        out[(ix, iy)] = f"tiles/{path.name}"
    return out


def count_in_box(props: list[dict], box) -> dict:
    counts = defaultdict(int)
    for prop in props:
        if box[0] <= prop["x"] <= box[2] and box[1] <= prop["y"] <= box[3]:
            counts[prop["asset"]] += 1
    return dict(counts)
