"""Planar vehicle model (yaw, lateral, longitudinal, plus roll and pitch as spring-dampers) driven by
the real hk_drive_assist.h. Tyres saturate with load; engine, gears and drivetrain follow
vehicles.json. Frame: x forward, y right, yaw + = nose right (same as the assist).

Tyre constants are calibrated against the first UE 5.8 HK.DriveTest run (drivetest1, 2026-11-03,
see tools/drive_model/calibrate.py and docs/DRIVING_PLAN.md). They are an empirical fit of what Chaos
did, not tyre physics: HK.DriveTest in Unreal is still the real check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .assist import Assist, Input, State

G = 9.81
# Chaos FrictionForceMultiplier -> friction coefficient. UE braked at ~1.6 g on friction 3.3-3.6 and
# peaked at 1.55-1.8 g lateral; FF's traction-limited launch fits the same value.
MU_PER_FRICTION = 0.47
# drivetest2 (friction ~2.2, grip-limited braking) gave more grip per friction unit for FF and AWD
# than for FR, in braking and lateral alike (UE 1.11 / 1.20 / 1.29 g braking on near-equal friction).
# Cause not known (load sensitivity? driven-wheel engine braking?); fitted per drivetrain.
MU_SCALE_BY_DRIVE = {"RWD": 0.94, "FWD": 1.06, "AWD": 1.15}
# Under braking Chaos holds more grip than the lateral/traction fit gives (drivetest2: 1.11-1.29 g
# braking vs ~0.67 g FR launch on the same tyres). Empirical: braking wheels get LONG_MU_SCALE x the
# longitudinal limit; traction stays at 1. The model's ABS caps brake torque at that limit (a
# release/re-apply cycle chattered and locked wheels that UE never locked).
LONG_MU_SCALE = 1.12
# Lateral tyre curve, in g per unit of wheel load, before the friction limit clips it. Fitted to the
# UE LatG60/LatG120 ramps (steady state, each axle carries lat_g of its load):
# - rear: linear, ~0.5 g per degree of slip -> tanh(alpha / REAR_ALPHA0);
# - front: very soft and convex (the main reason UE's slalom yaw gain was half the old model's):
#   tanh((alpha / a0)^FRONT_POWER), a0 = FRONT_ALPHA0 at FRONT_ALPHA0_MS, shrinking with speed.
# Treated as independent of FrictionForceMultiplier (friction only clips the peak). If UE shows the
# curve scaling with friction instead, set LAT_CURVE_SCALES_WITH_FRICTION.
LAT_PEAK = 1.6
REAR_ALPHA0 = math.radians(3.2)
FRONT_ALPHA0 = math.radians(15.0)
FRONT_ALPHA0_MS = 16.9
FRONT_ALPHA0_SPEED_EXP = -0.58
FRONT_POWER = 2.5
LAT_CURVE_SCALES_WITH_FRICTION = False
LAT_CURVE_FRICTION_REF = 3.45
# drivetest1 (friction ~3.4) was torque-limited: UE stopped in 22-23 m (~1.7 g) where
# sum(torque)/(radius*mass) gives ~1.47 g, so Chaos brakes ~1.3x harder than the torque as written.
# drivetest2 (friction ~2.2) was grip-limited. Both runs fit within ~1 m (drivetest1 AWD ~3 m long).
BRAKE_TORQUE_SCALE = 1.3
# Chaos body roll was about half the spring-only estimate (springs + rollbar + suspension geometry).
ROLL_STIFFNESS_SCALE = 2.0
# Chaos applies the inputs set this frame on the next physics step: one game frame of lag.
INPUT_DELAY_FRAMES = 1
HALF_WHEELBASE = 1.35
HALF_TRACK = 0.80
RHO_AREA = 1.2 * 1.9 * 1.3  # air density * frontal area
PHYS_DT = 1.0 / 480.0
GAME_DT = 1.0 / 60.0


def interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


@dataclass
class Car:
    spec: dict
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    r: float = 0.0
    roll: float = 0.0
    roll_rate: float = 0.0
    pitch: float = 0.0
    pitch_rate: float = 0.0
    gear: int = 1
    shift_timer: float = 0.0
    omega: list = field(default_factory=lambda: [0.0] * 4)  # wheel spin rad/s FL FR RL RR
    ax: float = 0.0
    ay: float = 0.0
    locked: list = field(default_factory=lambda: [False] * 4)

    def __post_init__(self):
        c, e, w = self.spec["Chassis"], self.spec["Engine"], self.spec["Wheels"]
        self.m = c["MassKg"]
        self.cx = c["ComX"] / 100.0
        self.h = c["ComZ"] / 100.0
        self.a = HALF_WHEELBASE - self.cx  # CoM to front axle
        self.b = HALF_WHEELBASE + self.cx  # CoM to rear axle
        inertia = c.get("InertiaScale", {"X": 1, "Y": 1, "Z": 1})
        self.iz = self.m * (4.3 ** 2 + 1.9 ** 2) / 12.0 * inertia["Z"]
        self.ix = self.m * (1.9 ** 2 + 0.7 ** 2) / 12.0 * inertia["X"] + self.m * self.h ** 2
        self.iy = self.m * (4.3 ** 2 + 0.7 ** 2) / 12.0 * inertia["Y"] + self.m * self.h ** 2
        self.radius = w["RadiusCm"] / 100.0
        self.iw = 1.2 if self.m > 600 else 0.5
        mu = MU_PER_FRICTION * MU_SCALE_BY_DRIVE.get(c["Drive"], 1.0)
        self.mu = [w["FrictionFront"] * mu] * 2 + [w["FrictionRear"] * mu] * 2
        drive = c["Drive"]
        split = c.get("FrontRearSplit", 0.5)
        rear = {"RWD": 1.0, "FWD": 0.0}.get(drive, split)
        self.drive_share = [(1 - rear) / 2] * 2 + [rear / 2] * 2
        front_mass = self.m * self.b / (2 * HALF_WHEELBASE)
        k_front = (2 * math.pi * w["RideHzFront"]) ** 2 * front_mass / 2
        k_rear = (2 * math.pi * w["RideHzRear"]) ** 2 * (self.m - front_mass) / 2
        rollbar = 1.0 + w.get("RollbarScaling", 0.0)
        self.k_roll = (k_front + k_rear) * 2 * HALF_TRACK ** 2 / 2 * 2 * rollbar * ROLL_STIFFNESS_SCALE
        self.c_roll = 2 * w["DampingRatio"] * math.sqrt(self.k_roll * self.ix)
        self.k_pitch = (k_front + k_rear) * 2 * HALF_WHEELBASE ** 2
        self.c_pitch = 2 * w["DampingRatio"] * math.sqrt(self.k_pitch * self.iy)
        self.engine = e
        self.brake_torque = [w["BrakeTorqueFront"] * BRAKE_TORQUE_SCALE] * 2 + [w["BrakeTorqueRear"] * BRAKE_TORQUE_SCALE] * 2
        self.handbrake_torque = w["HandbrakeTorque"] * BRAKE_TORQUE_SCALE
        self.abs = w.get("bABS", True)
        self.tc = [w.get("bTractionControlFront", True)] * 2 + [w.get("bTractionControlRear", True)] * 2
        self.drag = c["DragCoefficient"]
        self.max_steer = math.radians(self.spec["Assist"]["MaxSteerDeg"])
        self.assist = Assist(_assist(self.spec))
        self.pending = []

    @property
    def kmh(self):
        return self.vx * 3.6

    def rpm(self):
        ratio = self.engine["Gears"][self.gear - 1] * self.engine["FinalRatio"]
        driven = [self.omega[i] for i in range(4) if self.drive_share[i] > 0]
        wheel = sum(driven) / max(len(driven), 1)
        return max(self.engine["IdleRPM"], abs(wheel) * ratio * 60 / (2 * math.pi))

    def engine_torque(self, throttle):
        e = self.engine
        # Clutch / converter slip at launch: the engine never bogs below this.
        rpm = max(self.rpm(), e["IdleRPM"] + throttle * 2500.0)
        if rpm >= e["MaxRPM"]:
            return 0.0
        scale = interp(e["TorqueRpm"], e["TorqueScale"], rpm)
        return throttle * e["MaxTorqueNm"] * scale

    def lat_curve(self, i, alpha):
        """Lateral force per unit load (g) at slip angle alpha >= 0, before the friction ellipse."""
        if i < 2:
            a0 = FRONT_ALPHA0 * (max(abs(self.vx), 3.0) / FRONT_ALPHA0_MS) ** FRONT_ALPHA0_SPEED_EXP
            shape = math.tanh((alpha / a0) ** FRONT_POWER)
        else:
            shape = math.tanh(alpha / REAR_ALPHA0) * (1 - 0.12 * min(max((alpha - 0.15) / 0.3, 0), 1))
        scale = self.mu[i] / (LAT_CURVE_FRICTION_REF * MU_PER_FRICTION) if LAT_CURVE_SCALES_WITH_FRICTION else 1.0
        return LAT_PEAK * scale * shape

    def shift(self, dt):
        e = self.engine
        if self.shift_timer > 0:
            self.shift_timer -= dt
            return
        # Shift on road speed so wheelspin does not make the box hunt.
        ratio = e["Gears"][self.gear - 1] * e["FinalRatio"]
        rpm = max(e["IdleRPM"], abs(self.vx) / self.radius * ratio * 60 / (2 * math.pi))
        if rpm > e["ChangeUpRPM"] and self.gear < len(e["Gears"]):
            self.gear += 1
            self.shift_timer = e["ShiftTime"]
        elif (rpm < e["ChangeDownRPM"] and self.gear > 1
              and rpm * e["Gears"][self.gear - 2] / e["Gears"][self.gear - 1] < 0.9 * e["ChangeUpRPM"]):
            self.gear -= 1
            self.shift_timer = e["ShiftTime"]

    def assist_state(self) -> State:
        s = State()
        s.SpeedFwd = self.vx
        # VelLat at the geometric centre (actor origin), like AHKCar.
        s.VelLat = self.vy - self.r * self.cx
        s.YawRate = self.r
        s.RollDeg = math.degrees(self.roll)
        s.RollRate = self.roll_rate
        s.PitchRate = self.pitch_rate
        s.bGrounded = True
        s.bOffroad = False
        return s

    def physics(self, out, dt):
        m = self.m
        steer = out.Steer * self.max_steer
        throttle, brake, handbrake = out.Throttle, out.Brake, out.Handbrake
        grip = [out.FrontGrip, out.FrontGrip, out.RearGrip, out.RearGrip]
        pos = [(self.a, -HALF_TRACK), (self.a, HALF_TRACK), (-self.b, -HALF_TRACK), (-self.b, HALF_TRACK)]
        down = m * (G + out.DownAccel)
        static = [down * self.b / (2 * HALF_WHEELBASE) / 2] * 2 + [down * self.a / (2 * HALF_WHEELBASE) / 2] * 2
        dlong = m * self.ax * self.h / (2 * HALF_WHEELBASE) / 2
        dlat = m * self.ay * self.h / (2 * HALF_TRACK) / 2
        loads = []
        for i, (px, py) in enumerate(pos):
            n = static[i] + (-dlong if px > 0 else dlong) + (dlat if py > 0 else -dlat)
            loads.append(max(n, 50.0))
        drive_torque = 0.0 if self.shift_timer > 0 else self.engine_torque(throttle) * self.engine["Gears"][self.gear - 1] * self.engine["FinalRatio"] * 0.9
        fx_sum = fy_sum = mz = 0.0
        for i, (px, py) in enumerate(pos):
            delta = steer if i < 2 else 0.0
            vwx = self.vx - self.r * py
            vwy = self.vy + self.r * px
            cd, sd = math.cos(delta), math.sin(delta)
            v_long = vwx * cd + vwy * sd
            v_lat = -vwx * sd + vwy * cd
            mu_n = self.mu[i] * grip[i] * loads[i]
            alpha = math.atan2(v_lat, max(abs(v_long), 0.5))
            fy = -math.copysign(self.lat_curve(i, abs(alpha)), alpha) * loads[i]
            # Wheel spin: drive, brake, handbrake, tyre reaction.
            tq = drive_torque * self.drive_share[i]
            bt = brake * self.brake_torque[i] + (handbrake * self.handbrake_torque if i >= 2 else 0.0)
            slip_ratio = (self.omega[i] * self.radius - v_long) / max(abs(v_long), 2.0)
            if self.abs and brake > 0 and slip_ratio < -0.12 and abs(v_long) > 3.0:  # ABS off below ~10 km/h
                bt = min(bt, mu_n * LONG_MU_SCALE * self.radius)  # ABS holds the tyre at its peak
            if self.tc[i] and tq > 0 and slip_ratio > 0.15:
                tq *= 0.4
            mu_x = mu_n * (LONG_MU_SCALE if bt > 0 else 1.0)
            fx = mu_x * math.tanh(slip_ratio / 0.06)
            # Combined slip: friction ellipse (radii mu_x along the wheel, mu_n across).
            total = math.hypot(fx / mu_x, fy / mu_n)
            if total > 1.0:
                fx /= total
                fy /= total
            w = self.omega[i]
            if abs(w) < 1e-3 and bt >= abs(tq - fx * self.radius):
                # Static brake lock: wheel stays stopped, tyre force is whatever keeps it there.
                self.omega[i] = 0.0
                self.locked[i] = abs(v_long) > 3.0  # same 3 m/s floor as AHKCar telemetry
            else:
                brake_dir = math.copysign(1.0, w) if abs(w) > 1e-3 else math.copysign(1.0, tq - fx * self.radius)
                dw = (tq - fx * self.radius - bt * brake_dir) / self.iw * dt
                new = w + dw
                if w != 0 and new * w < 0 and bt > 0:
                    new = 0.0
                self.omega[i] = new
                self.locked[i] = abs(new * self.radius) < 0.2 * abs(v_long) and abs(v_long) > 3.0
            bx = fx * cd - fy * sd
            by = fx * sd + fy * cd
            fx_sum += bx
            fy_sum += by
            mz += px * by - py * bx
        drag = 0.5 * RHO_AREA * self.drag * self.vx * abs(self.vx) + 0.015 * m * G * math.tanh(self.vx)
        ax = (fx_sum - drag) / m
        ay = fy_sum / m + out.LatAccel
        self.vx += (ax + self.r * self.vy) * dt
        self.vy += (ay - self.r * self.vx) * dt
        self.r += (mz / self.iz + out.YawAccel) * dt
        self.ax, self.ay = ax, ay
        # Roll: + = right side down, driven by lateral acceleration to the left (outside of a right turn).
        roll_acc = (-m * ay * self.h - self.k_roll * self.roll - self.c_roll * self.roll_rate) / self.ix + out.RollAccel
        self.roll_rate += roll_acc * dt
        self.roll += self.roll_rate * dt
        # Pitch: + = nose up; braking (ax < 0) dives.
        pitch_acc = (m * ax * self.h - self.k_pitch * self.pitch - self.c_pitch * self.pitch_rate) / self.iy
        self.pitch_rate += pitch_acc * dt
        self.pitch += self.pitch_rate * dt
        self.yaw += self.r * dt
        self.x += (self.vx * math.cos(self.yaw) - self.vy * math.sin(self.yaw)) * dt
        self.y += (self.vx * math.sin(self.yaw) + self.vy * math.cos(self.yaw)) * dt
        self.shift(dt)

    def tick(self, inp: Input):
        out = self.assist.step(self.assist_state(), inp, GAME_DT)
        self.pending.append(out)
        applied = self.pending.pop(0) if len(self.pending) > INPUT_DELAY_FRAMES else out
        for _ in range(round(GAME_DT / PHYS_DT)):
            self.physics(applied, PHYS_DT)
        return out


def _assist(spec):
    from .config import assist_params
    return assist_params(spec)
