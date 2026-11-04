import numpy as np

from tools.pipeline import minimap_tiles


def _landscape():
    return {"min_x": 0.0, "min_y": 0.0, "max_x": 2048.0, "max_y": 1024.0, "spacing_x": 16.0, "spacing_y": 16.0}


def test_tiles_skip_open_sea_and_draw_roads_north_up(tmp_path):
    ls = _landscape()
    is_land = np.zeros((65, 129), dtype=bool)
    is_land[:, :64] = True  # west tile is land, east tile is sea
    height = np.zeros(is_land.shape, dtype=np.float32)
    road = {"xy": np.array([[100.0, 900.0], [900.0, 900.0]]), "hl": np.array([4.0, 4.0]), "hr": np.array([4.0, 4.0]),
            "highway": "primary", "mode": "ground"}
    grid = minimap_tiles.draw_tiles(tmp_path / "mm", ls, is_land, height, [road], [], [], log=lambda m: None)
    assert grid["nx"] == 2 and grid["ny"] == 1 and grid["tiles"] == 1
    from PIL import Image

    image = np.asarray(Image.open(tmp_path / "mm" / "x00_y00.png"))
    assert image.shape == (512, 512, 3)
    # y = 900 m is near the top (north) of the tile: row (1024 - 900) / 2 = 62.
    assert tuple(image[62, 250]) == minimap_tiles.ROAD_RGB["primary"]
    assert tuple(image[400, 250]) != minimap_tiles.ROAD_RGB["primary"]
