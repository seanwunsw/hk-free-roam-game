import numpy as np

from tools.pipeline import ground, labels, rail


class _Warp:
    """lon/lat are game metres already."""

    def lonlat_to_game_m(self, lon, lat):
        return np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)


class _Box:
    def __init__(self, x0, y0, x1, y1):
        self.box = (x0, y0, x1, y1)

    def inside(self, xy):
        x0, y0, x1, y1 = self.box
        return (xy[:, 0] >= x0) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)


def test_classify_prefers_natural_and_leisure_over_landuse():
    assert ground.classify({"landuse": "residential"}) == "landuse=residential"
    assert ground.classify({"landuse": "residential", "leisure": "park"}) == "leisure=park"
    assert ground.classify({"building": "yes"}) is None


def test_rasterise_draws_small_areas_over_large_and_keeps_the_sea(tmp_path, monkeypatch):
    monkeypatch.setattr(ground, "GROUND_PX", 256)
    ls = {"min_x": 0.0, "min_y": 0.0, "max_x": 1024.0, "max_y": 1024.0, "spacing_x": 16.0, "spacing_y": 16.0}
    is_land = np.ones((65, 65), dtype=bool)
    is_land[:, 48:] = False  # east quarter is sea
    height = np.zeros(is_land.shape, dtype=np.float32)
    big = np.array([[0.0, 0.0], [1024.0, 0.0], [1024.0, 1024.0], [0.0, 1024.0]])
    park = np.array([[100.0, 100.0], [300.0, 100.0], [300.0, 300.0], [100.0, 300.0]])
    grid, rgb = ground.rasterise(tmp_path / "g.png", ls, is_land, height,
                                 [("leisure=park", park), ("landuse=residential", big)], log=lambda m: None)
    at = ground.sampler(grid, rgb)
    assert tuple(at(200.0, 200.0)) == ground.CLASSES["leisure=park"]
    assert tuple(at(600.0, 600.0)) == ground.CLASSES["landuse=residential"]
    assert tuple(at(1000.0, 600.0)) == ground.SEA_RGB
    assert grid["areas"] == 2 and (tmp_path / "g.png").exists()


def test_rail_strip_breaks_where_it_crosses_a_road():
    line = {"ll": np.array([[0.0, 0.0], [200.0, 0.0]])}
    mesh, stats = rail.strips(_Warp(), [line], _Box(95.0, -10.0, 105.0, 10.0), lambda x, y: np.zeros(len(x)), (-1e4, -1e4, 1e4, 1e4))
    assert stats["level_crossing_gaps"] == 1
    xs = mesh["verts"][:, 0]
    assert not np.any((xs > 96.0) & (xs < 104.0))
    assert np.allclose(mesh["verts"][:, 2], rail.LIFT_M)
    # Clockwise seen from above (the ribbon convention): cross product z < 0.
    v = mesh["verts"]
    t = mesh["tris"][0]
    e1, e2 = v[t[1]] - v[t[0]], v[t[2]] - v[t[0]]
    assert e1[0] * e2[1] - e1[1] * e2[0] < 0


def test_landmark_points_merge_station_node_and_area():
    items = [
        {"zh": "屯門站", "en": "Tuen Mun", "kind": "station", "lon": 0.0, "lat": 0.0},
        {"zh": "屯門站", "en": "Tuen Mun", "kind": "station", "lon": 120.0, "lat": 40.0},
        {"zh": "屯門站", "en": "Tuen Mun", "kind": "lrt", "lon": 50.0, "lat": 0.0},
    ]
    river = {"zh": "屯門河", "en": "Tuen Mun River", "ll": np.array([[0.0, 1000.0], [2000.0, 1000.0]])}
    points = labels.landmark_points(_Warp(), items, [river], (-1e4, -1e4, 1e4, 1e4))
    kinds = [p["kind"] for p in points]
    assert kinds.count("station") == 1 and kinds.count("lrt") == 1
    assert kinds.count("river") == 5
