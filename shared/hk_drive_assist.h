#pragma once

// Arcade driving assist on top of Chaos Vehicle. Plain C++17, no Unreal headers, so the same code
// runs in AHKCar and in the offline model (tools/drive_model). Data comes from
// data/config/vehicles.json through FHKHandling (UE) or json (Python).
//
// Sign convention (matches Unreal vectors, see docs/DRIVING_PLAN.md):
//   SpeedFwd  m/s along the car's forward axis, negative when reversing.
//   VelLat    m/s along the car's right axis (+ = sliding to the right).
//   YawRate   rad/s about the car's up axis, + = nose turning right.
//   Steer     -1..1, + = right.
//   SlipDeg   rear-axle slip angle, atan2(VelLat - YawRate * RearAxleM, SpeedFwd). It stays near
//             zero in a normal turn at any speed (the centre slip angle does not: ~20 deg at full
//             lock when slow). A right-hand drift (rear out to the left) has SlipDeg < 0 and
//             dSlip/dt ~ -YawRate. VelLat is measured at the point RearAxleM ahead of the rear axle.
//   RollDeg   + = right side down.  Outputs are accelerations (mass-independent); the caller turns
//             them into AddTorque/AddForce with bAccelChange.

#include <algorithm>
#include <cmath>

namespace hkdrive
{

struct Params
{
	float MaxSteerDeg = 36.f;
	float WheelbaseM = 2.7f;
	float RearAxleM = 1.35f;          // from the VelLat reference point back to the rear axle
	float GripG = 1.0f;               // expected lateral grip, used for the target yaw rate limit
	float SteerSpeedRefKmh = 140.f;   // speed where steering reaches HighSpeedSteer
	float HighSpeedSteer = 0.35f;     // steering fraction left at SteerSpeedRefKmh and above
	float SteerRise = 3.5f;           // 1/s, toward a larger angle
	float SteerReturn = 6.f;          // 1/s, toward centre or the other side
	float ThrottleRise = 3.f;
	float ThrottleFall = 6.f;
	float BrakeRise = 7.f;
	float BrakeFall = 10.f;
	float TopSpeedKmh = 260.f;
	float YawDamping = 4.f;           // 1/s, removes yaw rate above the target (ESC-like)
	float MaxSlipDeg = 40.f;          // anti-spin starts pushing beyond this
	float AntiSpin = 9.f;             // rad/s^2 per rad beyond MaxSlipDeg
	float SpinDamping = 2.5f;         // 1/s, damps yaw that grows the slip once near MaxSlipDeg
	float DriftSlipDeg = 25.f;        // slip at which a slide counts as a full drift
	float HandbrakeRearGrip = 0.45f;  // rear friction scale while the handbrake is held
	float HandbrakeYawKick = 1.6f;    // rad/s^2 per unit steer while the handbrake starts a slide
	float PowerOversteer = 0.25f;     // rear grip lost per unit throttle while drifting
	float GripRecoverSeconds = 0.6f;  // rear grip back to 1 after the slide ends
	float CountersteerAssist = 3.f;   // rad/s^2 per rad of slip while countersteering
	float AutoCountersteer = 0.25f;   // steer added toward the slide at MaxSlipDeg
	float DriftSteerOpen = 0.8f;      // steering limit allowed while sliding (fraction of lock)
	float LateralGrip = 1.5f;         // 1/s, damps sideways velocity outside a drift (no ice)
	float LateralGripMaxG = 0.3f;
	float HighSpeedGripKmh = 200.f;
	float HighSpeedGripLoss = 0.f;    // grip fraction lost 100 km/h above HighSpeedGripKmh
	float DownforceG = 0.15f;         // extra down acceleration at 200 km/h, in g
	float AllowedRollDeg = 4.f;       // free body roll before the anti-roll assist pushes back
	float AntiRoll = 12.f;            // rad/s^2 per rad beyond AllowedRollDeg
	float RollDamping = 2.f;          // 1/s
	float AirControl = 1.5f;          // 1/s damping of roll/pitch rates in the air
	float OffroadGrip = 0.75f;        // grip scale off the road surface
};

// Name table for loading Params from vehicles.json "Assist". Keep it in Params order;
// tools/tests/test_drive_model.py checks it lists every field.
struct ParamField
{
	const char* Name;
	float Params::*Member;
};

inline const ParamField* ParamFields(int& Count)
{
	static const ParamField Fields[] = {
		{"MaxSteerDeg", &Params::MaxSteerDeg},
		{"WheelbaseM", &Params::WheelbaseM},
		{"RearAxleM", &Params::RearAxleM},
		{"GripG", &Params::GripG},
		{"SteerSpeedRefKmh", &Params::SteerSpeedRefKmh},
		{"HighSpeedSteer", &Params::HighSpeedSteer},
		{"SteerRise", &Params::SteerRise},
		{"SteerReturn", &Params::SteerReturn},
		{"ThrottleRise", &Params::ThrottleRise},
		{"ThrottleFall", &Params::ThrottleFall},
		{"BrakeRise", &Params::BrakeRise},
		{"BrakeFall", &Params::BrakeFall},
		{"TopSpeedKmh", &Params::TopSpeedKmh},
		{"YawDamping", &Params::YawDamping},
		{"MaxSlipDeg", &Params::MaxSlipDeg},
		{"AntiSpin", &Params::AntiSpin},
		{"SpinDamping", &Params::SpinDamping},
		{"DriftSlipDeg", &Params::DriftSlipDeg},
		{"HandbrakeRearGrip", &Params::HandbrakeRearGrip},
		{"HandbrakeYawKick", &Params::HandbrakeYawKick},
		{"PowerOversteer", &Params::PowerOversteer},
		{"GripRecoverSeconds", &Params::GripRecoverSeconds},
		{"CountersteerAssist", &Params::CountersteerAssist},
		{"AutoCountersteer", &Params::AutoCountersteer},
		{"DriftSteerOpen", &Params::DriftSteerOpen},
		{"LateralGrip", &Params::LateralGrip},
		{"LateralGripMaxG", &Params::LateralGripMaxG},
		{"HighSpeedGripKmh", &Params::HighSpeedGripKmh},
		{"HighSpeedGripLoss", &Params::HighSpeedGripLoss},
		{"DownforceG", &Params::DownforceG},
		{"AllowedRollDeg", &Params::AllowedRollDeg},
		{"AntiRoll", &Params::AntiRoll},
		{"RollDamping", &Params::RollDamping},
		{"AirControl", &Params::AirControl},
		{"OffroadGrip", &Params::OffroadGrip},
	};
	Count = static_cast<int>(sizeof(Fields) / sizeof(Fields[0]));
	return Fields;
}

struct State
{
	float SpeedFwd = 0.f;
	float VelLat = 0.f;
	float YawRate = 0.f;
	float RollDeg = 0.f;
	float RollRate = 0.f;  // rad/s, + = rolling right side down
	float PitchRate = 0.f; // rad/s, sign only used for damping
	bool bGrounded = true;
	bool bOffroad = false;
};

struct Input
{
	float Throttle = 0.f; // 0..1
	float Brake = 0.f;    // 0..1 (Chaos turns brake into reverse when stopped)
	float Steer = 0.f;    // -1..1
	bool bHandbrake = false;
};

struct Output
{
	float Steer = 0.f;
	float Throttle = 0.f;
	float Brake = 0.f;
	float Handbrake = 0.f;
	float FrontGrip = 1.f; // multiplies the class FrictionFront
	float RearGrip = 1.f;  // multiplies the class FrictionRear
	float YawAccel = 0.f;  // rad/s^2 about up, + = right
	float RollAccel = 0.f; // rad/s^2, + = right side down
	float PitchAccel = 0.f;
	float LatAccel = 0.f;  // m/s^2 along right
	float DownAccel = 0.f; // m/s^2 along -up
	float SlipDeg = 0.f;
	float DriftAmount = 0.f; // 0..1
	float TargetYawRate = 0.f;
	bool bCountersteer = false;
	bool bSpinRisk = false;
};

// Persistent per-car state between steps.
struct Memory
{
	float Steer = 0.f;
	float Throttle = 0.f;
	float Brake = 0.f;
	float RearGrip = 1.f;
};

constexpr float Pi = 3.14159265358979f;
constexpr float G = 9.81f;

inline float Clamp(float V, float Lo, float Hi) { return std::min(std::max(V, Lo), Hi); }
inline float Sign(float V) { return V > 0.f ? 1.f : (V < 0.f ? -1.f : 0.f); }
inline float Deg(float Radians) { return Radians * 180.f / Pi; }
inline float Rad(float Degrees) { return Degrees * Pi / 180.f; }
inline float SmoothStep(float X)
{
	X = Clamp(X, 0.f, 1.f);
	return X * X * (3.f - 2.f * X);
}
inline float Approach(float Current, float Target, float RatePerSecond, float Dt)
{
	const float Step = RatePerSecond * Dt;
	return Current < Target ? std::min(Current + Step, Target) : std::max(Current - Step, Target);
}

// Steering limit from speed: full lock when slow, HighSpeedSteer at SteerSpeedRefKmh.
inline float SteerLimit(const Params& P, float Kmh)
{
	return 1.f + (P.HighSpeedSteer - 1.f) * SmoothStep(Kmh / std::max(P.SteerSpeedRefKmh, 1.f));
}

// Yaw rate the driver asks for going forward: kinematic bicycle rate, capped by what the tyres
// can hold (GripG * g / v, plus 10%).
inline float TargetYawRate(const Params& P, float SpeedFwd, float SteerOut)
{
	const float V = std::fabs(SpeedFwd);
	const float Delta = Rad(SteerOut * P.MaxSteerDeg);
	const float Kinematic = V * std::tan(Delta) / std::max(P.WheelbaseM, 0.5f);
	const float Limit = P.GripG * G / std::max(V, 3.f) * 1.1f;
	return Clamp(Kinematic, -Limit, Limit);
}

inline Output Step(const Params& P, const State& S, const Input& In, Memory& M, float Dt)
{
	Output O;
	Dt = Clamp(Dt, 0.f, 0.1f);
	const float V = std::fabs(S.SpeedFwd);
	const float Kmh = V * 3.6f;
	const bool bForward = S.SpeedFwd > 1.f;

	// Slip angle only means something going forward at speed.
	const float Slip = bForward ? std::atan2(S.VelLat - S.YawRate * P.RearAxleM, S.SpeedFwd) : 0.f;
	const float SlipAbs = std::fabs(Slip);
	O.SlipDeg = Deg(Slip);
	const float DriftStart = Rad(4.f);
	O.DriftAmount = (bForward && Kmh > 15.f)
		? Clamp((SlipAbs - DriftStart) / std::max(Rad(P.DriftSlipDeg) - DriftStart, 0.01f), 0.f, 1.f)
		: 0.f;
	const float InSteer = Clamp(In.Steer, -1.f, 1.f);
	// Countersteer: steering toward the travel direction (same sign as the slip).
	O.bCountersteer = bForward && SlipAbs > Rad(3.f) && std::fabs(InSteer) > 0.15f && Sign(InSteer) == Sign(Slip);

	// 1. Steering: speed-sensitive limit, opened up while sliding so countersteer has room,
	//    a little automatic countersteer, and rate limits (quick back to centre).
	float Limit = SteerLimit(P, Kmh);
	const bool bSlideIntent = In.bHandbrake || O.DriftAmount > 0.2f;
	if (bSlideIntent)
	{
		Limit = std::max(Limit, P.DriftSteerOpen * std::max(O.DriftAmount, In.bHandbrake ? 0.5f : 0.f));
	}
	float SteerTarget = InSteer * Limit;
	if (bForward && Kmh > 20.f)
	{
		SteerTarget += P.AutoCountersteer * Clamp(Slip / Rad(P.MaxSlipDeg), -1.f, 1.f);
	}
	SteerTarget = Clamp(SteerTarget, -1.f, 1.f);
	const bool bGrowing = std::fabs(SteerTarget) > std::fabs(M.Steer) && (M.Steer == 0.f || Sign(SteerTarget) == Sign(M.Steer));
	M.Steer = Approach(M.Steer, SteerTarget, bGrowing ? P.SteerRise : P.SteerReturn, Dt);
	O.Steer = M.Steer;

	// 2. Throttle and brake ramps; soft governor at the class top speed.
	float ThrottleTarget = Clamp(In.Throttle, 0.f, 1.f);
	if (bForward)
	{
		const float Band = std::max(P.TopSpeedKmh * 0.04f, 3.f);
		ThrottleTarget *= Clamp((P.TopSpeedKmh - Kmh) / Band, 0.f, 1.f);
	}
	M.Throttle = Approach(M.Throttle, ThrottleTarget, ThrottleTarget > M.Throttle ? P.ThrottleRise : P.ThrottleFall, Dt);
	const float BrakeTarget = Clamp(In.Brake, 0.f, 1.f);
	M.Brake = Approach(M.Brake, BrakeTarget, BrakeTarget > M.Brake ? P.BrakeRise : P.BrakeFall, Dt);
	O.Throttle = M.Throttle;
	O.Brake = M.Brake;
	O.Handbrake = In.bHandbrake ? 1.f : 0.f;

	// 3. Rear grip: handbrake drops it fast, throttle keeps a slide alive, countersteer or
	//    releasing everything brings it back over GripRecoverSeconds.
	float RearTarget = 1.f;
	if (In.bHandbrake && bForward && Kmh > 8.f)
	{
		RearTarget = P.HandbrakeRearGrip;
	}
	else if (O.DriftAmount > 0.f && !O.bCountersteer)
	{
		RearTarget = 1.f - P.PowerOversteer * M.Throttle * O.DriftAmount;
	}
	float RecoverRate = 1.f / std::max(P.GripRecoverSeconds, 0.05f);
	if (O.bCountersteer)
	{
		RecoverRate *= 2.f;
	}
	M.RearGrip = Approach(M.RearGrip, RearTarget, RearTarget < M.RearGrip ? 1.f / 0.12f : RecoverRate, Dt);

	float SurfaceGrip = S.bOffroad ? P.OffroadGrip : 1.f;
	if (P.HighSpeedGripLoss > 0.f)
	{
		SurfaceGrip *= 1.f - P.HighSpeedGripLoss * Clamp((Kmh - P.HighSpeedGripKmh) / 100.f, 0.f, 1.f);
	}
	O.FrontGrip = SurfaceGrip;
	O.RearGrip = SurfaceGrip * M.RearGrip;

	if (!S.bGrounded)
	{
		// Air: damp tumbling so the car lands on its wheels; no grip assists.
		O.RollAccel = -P.AirControl * S.RollRate;
		O.PitchAccel = -P.AirControl * S.PitchRate;
		O.YawAccel = -0.5f * P.AirControl * S.YawRate;
		return O;
	}

	// 4. Yaw. Outside a slide: remove yaw rate beyond what the steering asks for (no random spins,
	//    stable at speed). In a slide: handbrake kick to start it, anti-spin beyond MaxSlipDeg,
	//    extra help while countersteering.
	O.TargetYawRate = TargetYawRate(P, S.SpeedFwd, O.Steer);
	const float SpeedScale = Clamp((Kmh - 10.f) / 40.f, 0.f, 1.f);
	if (bForward)
	{
		const float Excess = S.YawRate - O.TargetYawRate;
		const bool bOver = std::fabs(S.YawRate) > std::fabs(O.TargetYawRate) || Sign(S.YawRate) != Sign(O.TargetYawRate);
		if (bOver)
		{
			O.YawAccel -= P.YawDamping * Excess * SpeedScale * (1.f - 0.85f * (bSlideIntent ? 1.f : O.DriftAmount));
		}
		if (In.bHandbrake && Kmh > 25.f && SlipAbs < Rad(P.DriftSlipDeg))
		{
			O.YawAccel += P.HandbrakeYawKick * InSteer;
		}
		const float Max = Rad(P.MaxSlipDeg);
		if (SlipAbs > Max)
		{
			O.YawAccel += P.AntiSpin * (SlipAbs - Max) * Sign(Slip);
		}
		// Yaw that grows the slip has the opposite sign to the slip.
		if (SlipAbs > 0.6f * Max && Sign(S.YawRate) == -Sign(Slip))
		{
			O.YawAccel -= P.SpinDamping * S.YawRate * Clamp((SlipAbs - 0.6f * Max) / (0.4f * Max), 0.f, 1.f);
		}
		if (O.bCountersteer)
		{
			O.YawAccel += P.CountersteerAssist * Slip * std::fabs(InSteer);
		}
		O.bSpinRisk = SlipAbs > Rad(75.f) || std::fabs(S.YawRate) > 2.6f;

		// 5. Lateral grip outside a slide: damp the rear axle's sideways slip (not the kinematic
		//    sideways motion of a turn), so the car does not ice-skate wide.
		const float RearLat = S.VelLat - S.YawRate * P.RearAxleM;
		const float LatScale = (1.f - O.DriftAmount) * (In.bHandbrake ? 0.f : 1.f) * Clamp(Kmh / 10.f, 0.f, 1.f);
		O.LatAccel = Clamp(-RearLat * P.LateralGrip, -P.LateralGripMaxG * G, P.LateralGripMaxG * G) * LatScale * SurfaceGrip;
	}

	// 6. Body: free roll up to AllowedRollDeg, then push back; damp roll rate.
	const float RollAbs = std::fabs(S.RollDeg);
	if (RollAbs > P.AllowedRollDeg)
	{
		O.RollAccel -= P.AntiRoll * Rad(RollAbs - P.AllowedRollDeg) * Sign(S.RollDeg);
	}
	O.RollAccel -= P.RollDamping * S.RollRate;

	// 7. Downforce grows with speed squared.
	O.DownAccel = Clamp(P.DownforceG * G * (Kmh / 200.f) * (Kmh / 200.f), 0.f, G);
	return O;
}

} // namespace hkdrive
