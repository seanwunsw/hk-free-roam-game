"""HK.DriveTest schedule for the offline model. Keep in step with HKDriveTest.cpp: same phases,
same autopilot, same metric names (they are the keys of Targets in vehicles.json)."""

from __future__ import annotations

import math

from .assist import Input
from .model import GAME_DT, G, Car

DT = GAME_DT


def _hold_heading(car: Car, lane_y: float = 0.0) -> float:
    desired = -math.atan((car.y - lane_y) / 20.0)
    return max(-0.3, min(0.3, 1.5 * (desired - car.yaw)))


def _speed_hold(car: Car, target_kmh: float) -> tuple[float, float]:
    err = target_kmh - car.kmh
    throttle = max(0.0, min(1.0, 0.35 + 0.12 * err))
    brake = max(0.0, min(1.0, -0.08 * err - 0.4))
    return throttle, brake


def _inp(throttle=0.0, brake=0.0, steer=0.0, handbrake=False) -> Input:
    i = Input()
    i.Throttle, i.Brake, i.Steer, i.bHandbrake = throttle, brake, steer, handbrake
    return i


class Run:
    def __init__(self, spec: dict):
        self.spec = spec
        self.metrics: dict[str, float] = {"Spins": 0.0, "MaxYawRateDegS": 0.0}
        self.trace: list[tuple] = []
        self.t = 0.0
        self.phase = ""

    def fresh(self) -> Car:
        return Car(self.spec)

    def tick(self, car: Car, inp: Input):
        out = car.tick(inp)
        self.t += DT
        self.metrics["MaxYawRateDegS"] = max(self.metrics["MaxYawRateDegS"], abs(math.degrees(car.r)))
        self.trace.append((round(self.t, 4), self.phase, car.x, car.y, car.kmh, out.SlipDeg, math.degrees(car.r),
                           car.ay / G, car.ax / G, math.degrees(car.roll), math.degrees(car.pitch),
                           out.Steer, out.Throttle, out.Brake, out.Handbrake, out.RearGrip, car.gear))
        return out

    # 0-100 then 100-0.
    def accel_brake(self):
        self.phase = "accel"
        car = self.fresh()
        t = 0.0
        squat = 0.0
        while car.kmh < 100.0 and t < 30.0:
            self.tick(car, _inp(1.0, steer=_hold_heading(car)))
            squat = max(squat, math.degrees(car.pitch))
            t += DT
        self.metrics["Accel0To100S"] = t
        self.metrics["AccelSquatDeg"] = squat
        self.phase = "brake"
        x0, y0 = car.x, car.y
        locked = frames = 0
        dive = 0.0
        while car.kmh > 0.5 and frames < 1200:
            out = self.tick(car, _inp(0.0, 1.0, steer=_hold_heading(car)))
            frames += 1
            locked += sum(car.locked) > 0
            dive = min(dive, math.degrees(car.pitch))
            if out.Brake < 0.99:
                x0, y0 = car.x, car.y  # distance from full brake pressure
        self.metrics["Brake100To0M"] = math.hypot(car.x - x0, car.y - y0)
        self.metrics["BrakeLockPct"] = 100.0 * locked / max(frames, 1)
        self.metrics["BrakeDiveDeg"] = -dive

    def top_speed(self):
        self.phase = "top"
        car = self.fresh()
        history = []
        t = 0.0
        while t < 120.0:
            self.tick(car, _inp(1.0, steer=_hold_heading(car)))
            history.append(car.kmh)
            t += DT
            if len(history) > 180 and history[-1] - history[-180] < 1.0 and car.kmh > 60:
                break
        self.metrics["TopSpeedKmh"] = max(history)

    def lateral(self, target_kmh: float, key: str):
        self.phase = key
        car = self.fresh()
        while car.kmh < target_kmh - 1:
            self.tick(car, _inp(1.0, steer=_hold_heading(car)))
        window: list[float] = []
        best = 0.0
        roll = 0.0
        t = 0.0
        while t < 9.0:
            throttle, brake = _speed_hold(car, target_kmh)
            out = self.tick(car, _inp(throttle, brake, steer=min(1.0, t / 8.0)))
            t += DT
            window.append(abs(car.ay) / G)
            window = window[-60:]
            roll = max(roll, abs(math.degrees(car.roll)))
            if len(window) == 60 and abs(out.SlipDeg) < 12 and abs(car.kmh - target_kmh) < 0.08 * target_kmh:
                best = max(best, sum(window) / 60)
        self.metrics[key] = best
        self.metrics["MaxRollDeg"] = max(self.metrics.get("MaxRollDeg", 0.0), roll)

    def slalom(self):
        self.phase = "slalom"
        car = self.fresh()
        while car.kmh < 79:
            self.tick(car, _inp(1.0, steer=_hold_heading(car)))
        steer_hist, yaw_hist = [], []
        t = 0.0
        while t < 6.0:
            steer = 0.5 * math.sin(2 * math.pi * 0.5 * t)
            throttle, brake = _speed_hold(car, 80.0)
            self.tick(car, _inp(throttle, brake, steer=steer))
            t += DT
            if t > 2.0:
                steer_hist.append(steer)
                yaw_hist.append(math.degrees(car.r))
        self.metrics["SlalomYawGain"] = max(abs(v) for v in yaw_hist) / 0.5
        best_lag, best = 0, -1e9
        for lag in range(0, 60):
            c = sum(steer_hist[i] * yaw_hist[i + lag] for i in range(len(steer_hist) - lag))
            if c > best:
                best, best_lag = c, lag
        self.metrics["SlalomLagS"] = best_lag * DT

    def drift(self, countersteer: bool = True):
        self.phase = "drift" if countersteer else "handsoff"
        car = self.fresh()
        while car.kmh < 70:
            self.tick(car, _inp(1.0, steer=_hold_heading(car)))
        entry = None
        recover = None
        peak = 0.0
        hold = 0.0
        heading0 = car.yaw
        spun = False
        t = 0.0
        last_slip = 0.0
        while t < 8.0:
            if t < 0.7:
                inp = _inp(0.6, steer=0.8, handbrake=True)
            elif countersteer:
                inp = _inp(0.3, steer=max(-1.0, min(1.0, last_slip / 15.0)))
            else:
                inp = _inp()
            out = self.tick(car, inp)
            t += DT
            last_slip = out.SlipDeg
            slip = abs(out.SlipDeg)
            peak = max(peak, slip)
            if entry is None and slip > 15.0:
                entry = t
            if slip > 80.0 or abs(car.yaw - heading0) > math.radians(200):
                spun = True
            if t > 0.7 and recover is None:
                if slip < 5.0 and abs(math.degrees(car.r)) < 15.0:
                    hold += DT
                    if hold >= 0.3:
                        recover = t - 0.7 - 0.3
                else:
                    hold = 0.0
            if car.kmh < 5:
                break
        if countersteer:
            self.metrics["DriftEntryS"] = entry if entry is not None else 99.0
            self.metrics["DriftRecoverS"] = recover if recover is not None else 99.0
            self.metrics["DriftPeakSlipDeg"] = peak
        else:
            self.metrics["HandsOffRecoverS"] = recover if recover is not None else 99.0
        self.metrics["Spins"] += 1.0 if spun else 0.0

    def all(self):
        self.accel_brake()
        self.top_speed()
        self.lateral(60.0, "LatG60")
        self.lateral(120.0, "LatG120")
        self.slalom()
        self.drift(True)
        self.drift(False)
        return self.metrics



def evaluate(metrics: dict[str, float], targets: dict[str, list]) -> dict[str, bool]:
    result = {}
    for key, (lo, hi) in targets.items():
        if key not in metrics:
            continue
        value = metrics[key]
        result[key] = (lo is None or value >= lo) and (hi is None or value <= hi)
    return result
