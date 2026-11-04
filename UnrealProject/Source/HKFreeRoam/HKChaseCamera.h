#pragma once

// GTA-style chase camera for AHKCar. Drives the car's spring arm and camera after physics:
// yaw follows a critically damped spring toward the car heading blended with the velocity
// heading, the arm pulls back on throttle and speed and pushes in under braking, FOV widens
// with speed, small shake at high speed and on bumps. The mouse orbits 360 degrees around the
// car and recentres behind it after RecenterDelay; the scroll wheel zooms.

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "HKHandling.h"
#include "HKChaseCamera.generated.h"

class USpringArmComponent;
class UCameraComponent;

struct FHKCameraJitter
{
	int32 Frames = 0;
	double YawSq = 0.0; // sum of squared second differences of the rig yaw, deg^2
	double PosSq = 0.0; // same for the camera position relative to the car, cm^2
	float RmsYawDeg() const { return Frames > 0 ? static_cast<float>(FMath::Sqrt(YawSq / Frames)) : 0.f; }
	float RmsPosCm() const { return Frames > 0 ? static_cast<float>(FMath::Sqrt(PosSq / Frames)) : 0.f; }
};

UCLASS(ClassGroup = (HK))
class HKFREEROAM_API UHKChaseCamera : public UActorComponent
{
	GENERATED_BODY()

public:
	UHKChaseCamera();

	void Init(USpringArmComponent* InBoom, UCameraComponent* InCamera);
	void SetConfig(const FHKCameraConfig& InConfig) { Config = InConfig; }
	// Jump straight behind the car (possess, teleport, reset).
	void Snap();
	// Mouse orbit in degrees (+X right, +Y up).
	void AddLook(float YawDeg, float PitchDeg);
	// Scroll-wheel zoom, in wheel notches (+ = in).
	void AddZoom(float Notches);

	// Arm pivot above the car origin (the mesh root is on the road). The spring arm's collision
	// probe starts here, so it must sit above the body, clear of the road and the car.
	static constexpr float PivotCm = 110.f;
	static constexpr float MinZoom = 0.5f;
	static constexpr float MaxZoom = 2.2f;

	const FHKCameraJitter& Jitter() const { return JitterStats; }
	void ResetJitter() { JitterStats = FHKCameraJitter(); JitterHistory = 0; }

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	void Step(float Dt);

	UPROPERTY()
	TObjectPtr<USpringArmComponent> Boom;

	UPROPERTY()
	TObjectPtr<UCameraComponent> Camera;

	FHKCameraConfig Config;
	float Yaw = 0.f;
	float YawVel = 0.f;
	float LookYaw = 0.f;
	float LookPitch = 0.f;
	float LookIdle = 100.f;
	float Arm = 600.f;
	float Zoom = 1.f;
	float ZoomTarget = 1.f;
	float LatShift = 0.f;
	float Roll = 0.f;
	float Fov = 80.f;
	float LongG = 0.f;
	float LatG = 0.f;
	float Bump = 0.f;
	float Time = 0.f;
	float LastRigYaw = 0.f;
	FVector PrevVelocity = FVector::ZeroVector;
	bool bHasPrev = false;

	FHKCameraJitter JitterStats;
	int32 JitterHistory = 0;
	float PrevYaw[2] = {0.f, 0.f};
	FVector PrevPos[2] = {FVector::ZeroVector, FVector::ZeroVector};
};
