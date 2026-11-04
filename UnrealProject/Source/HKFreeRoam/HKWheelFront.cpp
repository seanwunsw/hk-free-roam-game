#include "HKWheelFront.h"

UHKWheelFront::UHKWheelFront()
{
	AxleType = EAxleType::Front;
	bAffectedBySteering = true;
	bAffectedByHandbrake = false;
	bAffectedByEngine = true;
	bAffectedByBrake = true;
	MaxSteerAngle = 36.f;
	WheelRadius = 34.f;
	WheelWidth = 20.f;
	// Chaos labels SpringRate "N/m" but scales it by 100 internally (the 250 default could not hold
	// any car in N/m). 45000 gave ~1 mm sag and a ~18 Hz bounce, faster than the physics step can
	// integrate, so cars exploded off the road at spawn. 600 is ~6 cm sag at 1450 kg, ~2 Hz.
	SpringRate = 600.f;
	SpringPreload = 50.f;
	SuspensionDampingRatio = 0.5f;
	SuspensionMaxRaise = 10.f;
	SuspensionMaxDrop = 12.f;
	FrictionForceMultiplier = 3.5f;
	CorneringStiffness = 1000.f;
	WheelLoadRatio = 0.5f;
	MaxBrakeTorque = 2800.f;
	MaxHandBrakeTorque = 0.f;
}
