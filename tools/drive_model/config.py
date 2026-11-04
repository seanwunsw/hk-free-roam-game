"""Load data/config/vehicles.json the same way HKHandling.cpp does (Defaults deep-merged per class)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VEHICLES = ROOT / "data" / "config" / "vehicles.json"
SECTIONS = ("Chassis", "Engine", "Wheels", "Assist", "Camera", "Body")


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(path: Path = VEHICLES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classes(data: dict | None = None) -> dict[str, dict]:
    data = data or load()
    return {name: merge(data["Defaults"], block) for name, block in data["classes"].items()}


def assist_params(spec: dict) -> dict[str, float]:
    """Assist block plus the geometry fields AHKCar fills in (VelLat is taken at the actor origin)."""
    params = dict(spec["Assist"])
    params["RearAxleM"] = params.get("WheelbaseM", 2.7) / 2.0
    return params
