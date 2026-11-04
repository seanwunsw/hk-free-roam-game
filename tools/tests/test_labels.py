"""Road and place names for the HUD."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline import labels  # noqa: E402


def test_split_names_prefers_language_tags_then_bilingual_name():
    assert labels.split_names({"name": "青山公路 Castle Peak Road", "name:zh": "青山公路", "name:en": "Castle Peak Road"}) == ("青山公路", "Castle Peak Road")
    assert labels.split_names({"name": "青山公路 Castle Peak Road"}) == ("青山公路", "Castle Peak Road")
    assert labels.split_names({"name": "Tuen Mun Road"}) == ("", "Tuen Mun Road")
    assert labels.split_names({"name": "屯門公路"}) == ("屯門公路", "")


def test_grid_lists_every_cell_a_road_crosses():
    road = {"name_zh": "青山公路", "name_en": "Castle Peak Road", "highway": "primary", "xy": np.array([[0.0, 0.0], [1000.0, 0.0]])}
    unnamed = {"name_zh": "", "name_en": "", "highway": "service", "xy": np.array([[0.0, 0.0], [10.0, 0.0]])}
    doc = labels.build([road, unnamed], [], [])
    assert len(doc["roads"]) == 1 and doc["names"] == [["青山公路", "Castle Peak Road"]]
    assert doc["roads"][0]["p"] == "0 0 10000 0"
    grid = doc["grid"]
    assert grid["nx"] == 4 and all(str(i) in grid["cells"] for i in range(4))
