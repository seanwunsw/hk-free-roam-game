"""Planar vehicle model (yaw, lateral, longitudinal, plus roll and pitch as spring-dampers) driven by
the real hk_drive_assist.h. Tyres saturate with load; engine, gears and drivetrain follow
vehicles.json. Frame: x forward, y right, yaw + = nose right (same as the assist).

MU_PER_FRICTION maps Chaos FrictionForceMultiplier to a friction coefficient. It is an assumption,
not a measured Chaos value: HK.DriveTest in Unreal is the real check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .assist import Assist, Input, State

G = 9.81
MU_PER_FRICTION = 0.30
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
        self.mu = [w["FrictionFront"] * MU_PER_FRICTION] * 2 + [w["FrictionRear"] * MU_PER_FRICTION] * 2
        drive = c["Drive"]
        split = c.get("FrontRearSplit", 0.5)
        rear = {"RWD": 1.0, "FWD": 0.0}.get(drive, split)
        self.drive_share = [(1 - rear) / 2] * 2 + [rear / 2] * 2
        front_mass = self.m * self.b / (2 * HALF_WHEELBASE)
        k_front = (2 * math.pi * w["RideHzFront"]) ** 2 * front_mass / 2
        k_rear = (2 * math.pi * w["RideHzRear"]) ** 2 * (self.m - front_mass) / 2
        rollbar = 1.0 + w.get("RollbarScaling", 0.0)
        self.k_roll = (k_front + k_rear) * 2 * HALF_TRACK ** 2 / 2 * 2 * rollbar
        self.c_roll = 2 * w["DampingRatio"] * math.sqrt(self.k_roll * self.ix)
        self.k_pitch = (k_front + k_rear) * 2 * HALF_WHEELBASE ** 2
        self.c_pitch = 2 * w["DampingRatio"] * math.sqrt(self.k_pitch * self.iy)
        self.engine = e
        self.brake_torque = [w["BrakeTorqueFront"]] * 2 + [w["BrakeTorqueRear"]] * 2
        self.handbrake_torque = w["HandbrakeTorque"]
        self.abs = w.get("bABS", True)
        self.tc = [w.get("bTractionControlFront", True)] * 2 + [w.get("bTractionControlRear", True)] * 2
        self.drag = c["DragCoefficient"]
        self.max_steer = math.radians(self.spec["Assist"]["MaxSteerDeg"])
        self.assist = Assist(_assist(self.spec))

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
            fy = -mu_n * math.tanh(alpha / 0.09) * (1 - 0.12 * min(max((abs(alpha) - 0.15) / 0.3, 0), 1))
            # Wheel spin: drive, brake, handbrake, tyre reaction.
            tq = drive_torque * self.drive_share[i]
            bt = brake * self.brake_torque[i] + (handbrake * self.handbrake_torque if i >= 2 else 0.0)
            slip_ratio = (self.omega[i] * self.radius - v_long) / max(abs(v_long), 2.0)
            if self.abs and brake > 0 and slip_ratio < -0.12:
                bt *= 0.3
            if self.tc[i] and tq > 0 and slip_ratio > 0.15:
                tq *= 0.4
            fx = mu_n * math.tanh(slip_ratio / 0.06)
            # Combined slip: friction ellipse.
            total = math.hypot(fx, fy)
            if total > mu_n:
                fx *= mu_n / total
                fy *= mu_n / total
            w = self.omega[i]
            if abs(w) < 1e-3 and bt >= abs(tq - fx * self.radius):
                # Static brake lock: wheel stays stopped, tyre force is whatever keeps it there.
                self.omega[i] = 0.0
                self.locked[i] = abs(v_long) > 1.0
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
        for _ in range(round(GAME_DT / PHYS_DT)):
            self.physics(out, PHYS_DT)
        return out


def _assist(spec):
    from .config import assist_params
    return assist_params(spec)
