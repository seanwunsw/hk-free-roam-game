"""python -m tools.drive_model.calibrate SUMMARY.csv [--vehicles VEHICLES.json]

Compares the offline model, run on the current vehicles.json (or the one the UE run used), with a UE HK.DriveTest summary CSV
(class,metric,value,min,max,result). Use it after each UE run: if a metric drifts, refit the tyre
constants at the top of model.py on that run's traces and record the fit in docs/DRIVING_PLAN.md."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from . import config
from .tests import Run

METRICS = ["Accel0To100S", "Brake100To0M", "LatG60", "LatG120", "SlalomYawGain", "SlalomLagS",
           "DriftPeakSlipDeg", "DriftRecoverS", "HandsOffRecoverS", "MaxRollDeg", "TopSpeedKmh"]


def read_ue(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            out.setdefault(row["class"], {})[row["metric"]] = float(row["value"])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--vehicles", type=Path, default=config.VEHICLES,
                        help="vehicles.json the UE run used (default: the current one)")
    args = parser.parse_args(argv)
    ue = read_ue(args.summary)
    specs = config.classes(config.load(args.vehicles))
    print(f"{'metric':18s}" + "".join(f"{c + ' UE':>10s}{c + ' model':>11s}" for c in ue))
    model = {c: Run(specs[c]).all() for c in ue if c in specs}
    for key in METRICS:
        line = f"{key:18s}"
        for c in ue:
            line += f"{ue[c].get(key, float('nan')):10.2f}{model.get(c, {}).get(key, float('nan')):11.2f}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
