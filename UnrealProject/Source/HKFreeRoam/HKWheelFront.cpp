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
	// SpringRate is N/m. 45000 holds a 1450 kg car with a few centimetres of sag.
	SpringRate = 45000.f;
	SpringPreload = 0.f;
	SuspensionDampingRatio = 0.5f;
	SuspensionMaxRaise = 8.f;
	SuspensionMaxDrop = 12.f;
	FrictionForceMultiplier = 3.5f;
	CorneringStiffness = 1000.f;
	WheelLoadRatio = 0.5f;
	MaxBrakeTorque = 2800.f;
	MaxHandBrakeTorque = 0.f;
}
