"""Land/sea mask from OSM natural=coastline, clipped to the extract polygon.

OSM draws coastline ways with land on the left. A Geofabrik extract keeps whole
ways that cross its .poly boundary, so the coastline is open only outside that
polygon. We node every coastline way together with the extract boundary,
polygonize, keep the faces inside the extract and label each face by the
direction of the coastline edges on its boundary. Nothing is guessed about how
to close the open ends. Outside the extract there is no OSM data, so the caller
falls back to the DEM there.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

LAND_PNG = "land_mask.png"
LAND_JSON = "land_mask.json"


def read_poly(path: Path):
    """Osmosis .poly file -> shapely (Multi)Polygon. Holes ('!' sections) are subtracted."""
    import shapely

    outers, holes = [], []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    index = 1
    while index < len(lines):
        name = lines[index].strip()
        index += 1
        if not name or name == "END":
            continue
        ring = []
        while index < len(lines) and lines[index].strip() != "END":
            parts = lines[index].split()
            if len(parts) >= 2:
                ring.append((float(parts[0]), float(parts[1])))
            index += 1
        index += 1
        if len(ring) >= 3:
            (holes if name.startswith("!") else outers).append(shapely.Polygon(ring))
    geom = shapely.union_all(outers)
    if holes:
        geom = shapely.difference(geom, shapely.union_all(holes))
    return geom


def load_coastlines(pbf: Path) -> list[np.ndarray]:
    """Every natural=coastline way at full resolution, as (n, 2) lon/lat arrays."""
    import osmium

    out: list[np.ndarray] = []

    class Handler(osmium.SimpleHandler):
        def way(self, way):
            if way.tags.get("natural") != "coastline":
                return
            try:
                coords = np.array([(node.lon, node.lat) for node in way.nodes], dtype=np.float64)
            except osmium.InvalidLocationError:
                return
            if len(coords) >= 2:
                out.append(coords)

    Handler().apply_file(str(pbf), locations=True)
    return out


def build_land(coastlines: list[np.ndarray], extract) -> tuple[object, dict]:
    """Land (Multi)Polygon in lon/lat inside `extract`, plus face statistics."""
    import shapely
    from shapely.geometry.polygon import orient

    lines = [line for line in coastlines if len(line) >= 2]
    if not lines:
        return shapely.Polygon(), {"faces": 0, "land_faces": 0, "sea_faces": 0, "unlabelled_faces": 0}
    boundary = shapely.boundary(extract)
    noded = shapely.union_all([shapely.MultiLineString(lines), boundary])
    faces = [face for face in shapely.get_parts(shapely.polygonize(shapely.get_parts(noded))) if extract.contains(face.representative_point())]
    segs = np.concatenate([np.stack([line[:-1], line[1:]], axis=1) for line in lines])
    direction = segs[:, 1] - segs[:, 0]
    tree = shapely.STRtree(shapely.linestrings(segs))
    land, labels = [], {"land": 0, "sea": 0, "unlabelled": 0}
    for face in faces:
        face = orient(face, 1.0)  # exterior CCW, holes CW: the face lies left of every edge
        rings = [np.asarray(face.exterior.coords)] + [np.asarray(ring.coords) for ring in face.interiors]
        a = np.concatenate([ring[:-1] for ring in rings])
        b = np.concatenate([ring[1:] for ring in rings])
        hit_edge, hit_seg = tree.query_nearest(shapely.points(0.5 * (a + b)), max_distance=1e-9, all_matches=False)
        if len(hit_edge) == 0:
            labels["unlabelled"] += 1
            continue
        same = np.einsum("ij,ij->i", b[hit_edge] - a[hit_edge], direction[hit_seg])
        if (same > 0).sum() > (same < 0).sum():
            land.append(face)
            labels["land"] += 1
        else:
            labels["sea"] += 1
    geom = shapely.union_all(land) if land else shapely.Polygon()
    stats = {
        "coastline_ways": len(lines),
        "faces": len(faces),
        "land_faces": labels["land"],
        "sea_faces": labels["sea"],
        "unlabelled_faces": labels["unlabelled"],
    }
    return geom, stats


def land_at(land, extract, lon, lat, dem_elev=None, dem_land_m: float = 1.5) -> np.ndarray:
    """Boolean land mask for lon/lat arrays. Inside the extract the OSM land polygon
    decides; outside it (no OSM data) the DEM does, if given."""
    import shapely

    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    shapely.prepare(land)
    shapely.prepare(extract)
    flat_lon = lon.ravel()
    flat_lat = lat.ravel()
    out = np.zeros(flat_lon.shape, dtype=bool)
    inside = np.zeros(flat_lon.shape, dtype=bool)
    chunk = 1_000_000
    for start in range(0, len(flat_lon), chunk):
        sl = slice(start, start + chunk)
        inside[sl] = shapely.contains_xy(extract, flat_lon[sl], flat_lat[sl])
        idx = np.flatnonzero(inside[sl]) + start
        if len(idx):
            out[idx] = shapely.contains_xy(land, flat_lon[idx], flat_lat[idx])
    if dem_elev is not None:
        elev = np.asarray(dem_elev).ravel()
        out[~inside] = elev[~inside] > dem_land_m
    return out.reshape(lon.shape)


def write_mask(out_dir: Path, mask: np.ndarray, bounds: dict, step_deg: float) -> None:
    """North-up 1-bit PNG of a lon/lat land mask, plus its georeference."""
    import json

    from PIL import Image

    Image.fromarray(np.flipud(mask).astype(np.uint8) * 255, mode="L").convert("1").save(out_dir / LAND_PNG, optimize=True)
    meta = dict(bounds)
    meta.update({"step_deg": step_deg, "width": int(mask.shape[1]), "height": int(mask.shape[0]), "row0": "north"})
    (out_dir / LAND_JSON).write_text(json.dumps(meta, indent=2), encoding="utf-8")


class LandMask:
    """Reads land_mask.png/json back for point queries (check_map, tests)."""

    def __init__(self, out_dir: Path) -> None:
        import json

        from PIL import Image

        meta = json.loads((Path(out_dir) / LAND_JSON).read_text(encoding="utf-8"))
        self.meta = meta
        self.grid = np.flipud(np.asarray(Image.open(Path(out_dir) / LAND_PNG).convert("L")) > 127)
        self.step = float(meta["step_deg"])

    def is_land(self, lon, lat) -> np.ndarray:
        col = np.rint((np.asarray(lon) - self.meta["min_lon"]) / self.step).astype(np.int64)
        row = np.rint((np.asarray(lat) - self.meta["min_lat"]) / self.step).astype(np.int64)
        ok = (col >= 0) & (row >= 0) & (col < self.grid.shape[1]) & (row < self.grid.shape[0])
        out = np.zeros(np.broadcast(col, row).shape, dtype=bool)
        out[ok] = self.grid[row[ok], col[ok]]
        return out
