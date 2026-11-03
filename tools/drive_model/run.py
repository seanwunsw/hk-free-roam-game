"""python -m tools.drive_model.run [class ...] [--csv DIR]

Runs the offline HK.DriveTest schedule for each class and prints metrics against Targets."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from . import config
from .tests import Run, evaluate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("classes", nargs="*")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    data = config.load()
    specs = config.classes(data)
    names = args.classes or list(specs)
    failures = 0
    rows = []
    for name in names:
        run = Run(specs[name])
        metrics = run.all()
        targets = data["classes"][name].get("Targets", {})
        verdict = evaluate(metrics, targets)
        print(f"== {name}")
        for key in sorted(metrics):
            mark = "" if key not in verdict else ("PASS" if verdict[key] else "FAIL")
            rng = targets.get(key, "")
            print(f"  {key:18s} {metrics[key]:8.2f}  {str(rng):16s} {mark}")
        failures += sum(not ok for ok in verdict.values())
        rows.append({"class": name, **{k: round(v, 3) for k, v in metrics.items()},
                     "fails": ",".join(k for k, ok in verdict.items() if not ok)})
        if args.csv:
            args.csv.mkdir(parents=True, exist_ok=True)
            with open(args.csv / f"model_trace_{name}.csv", "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["t", "phase", "x", "y", "kmh", "slip_deg", "yaw_dps", "lat_g", "long_g", "roll_deg",
                                 "pitch_deg", "steer", "throttle", "brake", "handbrake", "rear_grip", "gear"])
                writer.writerows(run.trace)
    if args.csv:
        keys = sorted({k for row in rows for k in row})
        with open(args.csv / "model_summary.csv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
    print(f"model failures: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
