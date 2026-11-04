#include "HKWheelRear.h"

UHKWheelRear::UHKWheelRear()
{
	AxleType = EAxleType::Rear;
	bAffectedBySteering = false;
	bAffectedByHandbrake = true;
	bAffectedByEngine = true;
	bAffectedByBrake = true;
	MaxSteerAngle = 0.f;
	WheelRadius = 34.f;
	WheelWidth = 20.f;
	// See UHKWheelFront: ~6 cm sag, ~2 Hz.
	SpringRate = 600.f;
	SpringPreload = 50.f;
	SuspensionDampingRatio = 0.5f;
	SuspensionMaxRaise = 10.f;
	SuspensionMaxDrop = 12.f;
	FrictionForceMultiplier = 3.5f;
	CorneringStiffness = 1000.f;
	WheelLoadRatio = 0.5f;
	MaxBrakeTorque = 2200.f;
	MaxHandBrakeTorque = 4500.f;
}
