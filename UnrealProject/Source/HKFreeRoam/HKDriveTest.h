#pragma once

// HK.DriveTest: unattended driving measurements per class on a flat pad spawned 2 km above Tuen
// Mun. Same schedule and metric names as tools/drive_model/tests.py; pass ranges come from
// "Targets" in data/config/vehicles.json. Writes Saved/HKDriveTest/summary_<stamp>.csv, one
// trace_<class>_<stamp>.csv per class, and HKDriveTest PASS/FAIL lines in the log.

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HKHandling.h"
#include "HKDriveTest.generated.h"

class AHKCar;
class AStaticMeshActor;

UCLASS(NotPlaceable, Transient)
class HKFREEROAM_API AHKDriveTestRunner : public AActor
{
	GENERATED_BODY()

public:
	AHKDriveTestRunner();

	static void Start(UWorld* World, const TArray<EHKCarClass>& Classes, bool bQuitWhenDone);
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	enum class EPhase : uint8
	{
		Wait,
		Accel,
		Brake,
		TopSpeed,
		Lat60,
		Lat120,
		Slalom,
		Drift,
		HandsOff,
		Rough,
		Done,
	};

	void BuildPad();
	void NextClass();
	void Begin(EPhase Phase);
	void Finish();
	void StepPhase(float Dt);
	void Record(float Dt);
	void WriteClass();

	// Lane centre (cm) for heading hold, and helpers matching tests.py.
	float HoldHeading(float LaneY) const;
	void SpeedHold(float TargetKmh, float& OutThrottle, float& OutBrake) const;
	FVector PadPoint(float XM, float YM) const;
	float LocalX() const;
	float LocalY() const;

	TArray<EHKCarClass> Queue;
	bool bQuit = false;
	int32 ClassIndex = -1;
	EHKCarClass Current = EHKCarClass::FR;

	UPROPERTY()
	TObjectPtr<AHKCar> Car;

	UPROPERTY()
	TArray<TObjectPtr<AActor>> PadActors;

	UPROPERTY()
	TObjectPtr<AActor> PreviousView;

	FVector Origin = FVector::ZeroVector;
	EPhase Phase = EPhase::Wait;
	float PhaseTime = 0.f;
	float SettleTime = 0.f;
	bool bSpunUp = false;
	float Clock = 0.f;

	// Per-phase scratch.
	float Peak = 0.f;
	float Peak2 = 0.f;
	float Entry = -1.f;
	float Recover = -1.f;
	float Hold = 0.f;
	float LastSlip = 0.f;
	float HeadingTravel = 0.f;
	float PrevYaw = 0.f;
	bool bSpun = false;
	int32 Frames = 0;
	int32 LockedFrames = 0;
	FVector BrakeStart = FVector::ZeroVector;
	bool bBrakeStarted = false;
	TArray<float> Window;
	TArray<float> SteerHist;
	TArray<float> YawHist;
	TArray<float> SpeedHist;
	float StartHeading = 0.f;

	TMap<FString, float> Metrics;
	double JitterYawSq = 0.0;
	double JitterPosSq = 0.0;
	int32 JitterFrames = 0;
	FString Trace;
	FString Summary;
	FString Stamp;
	int32 Failures = 0;
	float CurrentSteer = 0.f;
};
