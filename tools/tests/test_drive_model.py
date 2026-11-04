"""Driving: vehicles.json vs the C++ readers, car class assignment, the shared assist header, and the
offline model's targets. The model is a sanity check of the tuning, not a replacement for HK.DriveTest."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.drive_model import config  # noqa: E402
from tools.drive_model.assist import HEADER, parse_header  # noqa: E402

SRC = ROOT / "UnrealProject" / "Source" / "HKFreeRoam"
SPAWNS = ROOT / "data" / "processed" / "spawns.json"
CLASSES = {"FR", "FF", "AWD"}
HAS_GXX = shutil.which("g++") is not None


def _vehicles() -> dict:
    return config.load()


def _cpp_section_keys() -> dict[str, set[str]]:
    """Keys ReadClass reads per section, from Num/Bool/Floats/TryGetStringField calls."""
    text = (SRC / "HKHandling.cpp").read_text(encoding="utf-8")
    body = text[text.index("void ReadClass"):text.index("void Load(")]
    var_to_section = dict(re.findall(r"TSharedPtr<FJsonObject>\s+(\w+)\s*=\s*Section\(\w+,\s*TEXT\(\"(\w+)\"\)\)", body))
    keys: dict[str, set[str]] = {}
    for var, key in re.findall(r"(?:Num|Bool|Floats)\((\w+),\s*TEXT\(\"(\w+)\"\)", body):
        keys.setdefault(var_to_section[var], set()).add(key)
    for var, key in re.findall(r"(\w+)->TryGetStringField\(TEXT\(\"(\w+)\"\)", body):
        keys.setdefault(var_to_section[var], set()).add(key)
    keys["Chassis"].add("InertiaScale")  # read as its own X/Y/Z section
    return keys


def test_classes_are_the_three_drivetrains():
    data = _vehicles()
    assert set(data["classes"]) == CLASSES
    drives = {name: spec["Chassis"]["Drive"] for name, spec in config.classes(data).items()}
    assert drives == {"FR": "RWD", "FF": "FWD", "AWD": "AWD"}
    split = {name: spec["Chassis"]["FrontRearSplit"] for name, spec in config.classes(data).items()}
    # Chaos: FrontRearSplit is the rear share (0.6 = 40/60 front/rear).
    assert split["FR"] == 1.0 and split["FF"] == 0.0 and split["AWD"] == pytest.approx(0.6)


def test_classes_differ_in_mass_balance_grip_steer_and_suspension():
    specs = config.classes()
    groups = {
        "mass": [("Chassis", "MassKg")],
        "balance": [("Chassis", "ComX")],
        "grip": [("Wheels", "FrictionFront"), ("Wheels", "FrictionRear"), ("Assist", "GripG")],
        "steer": [("Assist", "HighSpeedSteer"), ("Assist", "SteerRise")],
        "suspension": [("Wheels", "RideHzFront"), ("Wheels", "RideHzRear"), ("Wheels", "RollbarScaling")],
    }
    for group, paths in groups.items():
        values = {name: tuple(spec[a][b] for a, b in paths) for name, spec in specs.items()}
        assert len(set(values.values())) == 3, (group, values)


def test_json_keys_match_cpp_readers():
    cpp = _cpp_section_keys()
    for name, spec in config.classes().items():
        for section in ("Chassis", "Engine", "Wheels", "Camera", "Body"):
            json_keys = {k for k in spec[section] if not k.startswith("_")}
            assert json_keys <= cpp[section], (name, section, json_keys - cpp[section])
            assert cpp[section] <= json_keys, (name, section, cpp[section] - json_keys)


def test_assist_keys_are_header_fields():
    fields = {f for _, f in parse_header()["Params"]}
    for name, spec in config.classes().items():
        unknown = {k for k in spec["Assist"] if not k.startswith("_")} - fields
        assert not unknown, (name, unknown)


def test_param_fields_table_matches_params_struct():
    text = HEADER.read_text(encoding="utf-8")
    table = re.findall(r"\{\"(\w+)\",\s*&Params::(\w+)\}", text)
    assert all(a == b for a, b in table)
    assert [a for a, _ in table] == [f for _, f in parse_header()["Params"]]


def test_targets_name_real_metrics():
    runner = (SRC / "HKDriveTest.cpp").read_text(encoding="utf-8")
    # Every metric name the UE runner can write (Metrics.Add / FindOrAdd, including the ternaries).
    ue = set()
    for call in re.findall(r"Metrics\.(?:Add|FindOrAdd)\(([^;]*)\);", runner):
        ue |= set(re.findall(r'TEXT\("(\w+)"\)', call))
    ue |= {"CamJitterDeg", "CamJitterPosCm"}
    for name, spec in config.classes().items():
        for key, bounds in spec["Targets"].items():
            if key.startswith("_"):
                continue
            assert key in ue, (name, key)
            assert isinstance(bounds, list) and len(bounds) == 2


def test_every_spawned_car_has_a_class_and_all_three_are_near_tuen_mun():
    data = _vehicles()
    ids = {car["id"] for car in json.loads(SPAWNS.read_text(encoding="utf-8"))["cars"]}
    assign = {k: v for k, v in data["assign"].items() if not k.startswith("_")}
    assert set(assign) == ids
    assert set(assign.values()) == CLASSES
    lot = data["lot"]
    near = {assign[lot["anchor"]]} | (set(lot["classes"]) if lot["enabled"] else set())
    assert near == CLASSES


def test_cpp_class_names_parse():
    text = (SRC / "HKHandling.h").read_text(encoding="utf-8")
    assert re.search(r"enum class EHKCarClass : uint8\s*\{\s*FR,[^\n]*\n\s*FF,[^\n]*\n\s*AWD,", text)
    cpp = (SRC / "HKHandling.cpp").read_text(encoding="utf-8")
    for alias in ("RWD", "FWD", "4WD"):
        assert f'TEXT("{alias}")' in cpp


@pytest.mark.skipif(not HAS_GXX, reason="g++ not installed")
def test_assist_signs():
    from tools.drive_model.assist import Assist, Input, State

    assist = Assist(config.assist_params(config.classes()["FR"]))
    state = State()
    state.SpeedFwd = 20.0
    state.bGrounded = True
    inp = Input()
    inp.Steer = 1.0
    out = None
    for _ in range(60):
        out = assist.step(state, inp, 1.0 / 60.0)
    assert out.Steer > 0.0
    # Yawing right with the wheel centred: the yaw help must oppose the yaw.
    state.YawRate = 2.0
    inp.Steer = 0.0
    for _ in range(30):
        out = assist.step(state, inp, 1.0 / 60.0)
    assert out.YawAccel < 0.0


@pytest.mark.skipif(not HAS_GXX, reason="g++ not installed")
@pytest.mark.parametrize("name", sorted(CLASSES))
def test_model_meets_targets(name):
    from tools.drive_model.tests import Run, evaluate

    spec = config.classes()[name]
    metrics = Run(spec).all()
    result = evaluate(metrics, {k: v for k, v in spec["Targets"].items() if not k.startswith("_")})
    failed = {k: metrics[k] for k, ok in result.items() if not ok}
    assert not failed, failed


def test_fr_is_the_fast_accelerating_class():
    # Sean's spec: FR is the "fast acceleration" car. The target windows must say so on their own,
    # before any model run: FR's slowest allowed 0-100 beats the quickest allowed for AWD and FF.
    targets = {name: spec["Targets"]["Accel0To100S"] for name, spec in config.classes().items()}
    assert targets["FR"][1] < targets["AWD"][0] and targets["FR"][1] < targets["FF"][0]
    # FF (the easy-to-turn car) is the slowest: its quickest allowed 0-100 is behind AWD's slowest.
    assert targets["AWD"][1] <= targets["FF"][0]
    specs = config.classes()
    assert specs["FR"]["Chassis"]["ComX"] < 0  # weight on the driven rear axle
    assert specs["FR"]["Assist"]["PowerOversteer"] > specs["AWD"]["Assist"]["PowerOversteer"] > specs["FF"]["Assist"]["PowerOversteer"]
    assert specs["AWD"]["Assist"]["OffroadGrip"] > specs["FR"]["Assist"]["OffroadGrip"]


@pytest.mark.skipif(not HAS_GXX, reason="g++ not installed")
def test_model_acceleration_order():
    from tools.drive_model.tests import Run

    times = {}
    for name, spec in config.classes().items():
        run = Run(spec)
        run.accel_brake()
        times[name] = run.metrics["Accel0To100S"]
    assert times["FR"] + 0.5 < times["AWD"] < times["FF"], times


# UE 5.8 HK.DriveTest runs (2026-11-03). fixtures/vehicles_<run>.json is the exact vehicles.json each
# run used. drivetest1: pre-retune JSON, brakes torque-limited. drivetest2: drivefix2, grip-limited.
# IN-SAMPLE: the model's constants (MU_PER_FRICTION, MU_SCALE_BY_DRIVE, LONG_MU_SCALE,
# BRAKE_TORQUE_SCALE) were fitted to these same runs, so passing says the fit has not drifted, not
# that the model predicts a new tune. Only a new HK.DriveTest validates a retune.
UE_RUNS = {
    "drivetest1": {
        "FR": {"Accel0To100S": 3.52, "SlalomYawGain": 40.8, "LatG120": 1.70, "TopSpeedKmh": 252, "Brake100To0M": 23.35},
        "FF": {"Accel0To100S": 4.85, "SlalomYawGain": 38.4, "LatG120": 1.77, "TopSpeedKmh": 213, "Brake100To0M": 22.73},
        "AWD": {"Accel0To100S": 5.38, "SlalomYawGain": 36.2, "LatG120": 1.72, "TopSpeedKmh": 236, "Brake100To0M": 21.92},
    },
    "drivetest2": {
        "FR": {"Accel0To100S": 4.58, "SlalomYawGain": 41.9, "LatG120": 1.18, "TopSpeedKmh": 252, "Brake100To0M": 33.83},
        "FF": {"Accel0To100S": 6.20, "SlalomYawGain": 45.9, "LatG120": 1.34, "TopSpeedKmh": 213, "Brake100To0M": 30.29},
        "AWD": {"Accel0To100S": 5.38, "SlalomYawGain": 36.2, "LatG120": 1.45, "TopSpeedKmh": 236, "Brake100To0M": 28.15},
    },
}
UE_TOLERANCE = {"Accel0To100S": 0.13, "SlalomYawGain": 0.10, "LatG120": 0.15, "TopSpeedKmh": 0.03,
                "Brake100To0M": 0.16}


@pytest.mark.skipif(not HAS_GXX, reason="g++ not installed")
@pytest.mark.parametrize("run,name", [(r, n) for r in sorted(UE_RUNS) for n in sorted(UE_RUNS[r])])
def test_model_reproduces_ue_runs(run, name):
    from tools.drive_model.tests import Run

    spec = config.classes(config.load(FIXTURES / f"vehicles_{run}.json"))[name]
    metrics = Run(spec).all()
    for key, ue in UE_RUNS[run][name].items():
        assert abs(metrics[key] - ue) <= UE_TOLERANCE[key] * ue, (key, metrics[key], ue)


SWEEPS = ROOT / "data" / "config" / "sweeps"


def _missing_keys(over, base, path=""):
    for key, value in over.items():
        if key.startswith("_"):
            continue
        if key not in base:
            yield path + key
        elif isinstance(value, dict):
            yield from _missing_keys(value, base[key], path + key + ".")


@pytest.mark.parametrize("sweep", sorted(SWEEPS.glob("*.json")), ids=lambda p: p.name)
def test_sweep_overlays_only_override_existing_keys(sweep):
    # HK.ReloadHandling <overlay> merges these over vehicles.json; a typo would silently do nothing.
    assert list(_missing_keys(json.loads(sweep.read_text(encoding="utf-8")), config.load())) == []
