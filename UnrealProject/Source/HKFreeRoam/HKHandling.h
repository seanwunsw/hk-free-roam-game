#pragma once

// Driving classes from data/config/vehicles.json (single source of truth, also read by
// tools/drive_model). HK.ReloadHandling reloads the file and reapplies it to every car.

#include "CoreMinimal.h"
#include "hk_drive_assist.h"
#include "HKHandling.generated.h"

class UClass;

UENUM()
enum class EHKCarClass : uint8
{
	FR,  // front engine, rear-wheel drive
	FF,  // front-wheel drive
	AWD, // all-wheel drive ("4WD")
};

constexpr int32 HKCarClassCount = 3;

enum class EHKDrive : uint8
{
	RWD,
	FWD,
	AWD,
};

struct FHKChassisConfig
{
	float MassKg = 1450.f;
	float ComX = 0.f; // cm ahead of the wheelbase centre
	float ComZ = 45.f;
	FVector InertiaScale = FVector::OneVector;
	float DragCoefficient = 0.32f;
	EHKDrive Drive = EHKDrive::RWD;
	float FrontRearSplit = 0.5f; // Chaos: 0 = all front, 1 = all rear; AWD only
	float IdleBrake = 0.f;
};

struct FHKEngineConfig
{
	float MaxTorqueNm = 480.f;
	float MaxRPM = 7000.f;
	float IdleRPM = 900.f;
	TArray<float> TorqueRpm;
	TArray<float> TorqueScale;
	float RevUpMOI = 5.f;
	float RevDownRate = 600.f;
	float EngineBrake = 0.05f;
	float FinalRatio = 3.7f;
	TArray<float> Gears;
	float ReverseGear = 3.4f;
	float ChangeUpRPM = 6600.f;
	float ChangeDownRPM = 3000.f;
	float ShiftTime = 0.18f;
};

struct FHKWheelsConfig
{
	float RadiusCm = 34.f;
	float WidthCm = 22.f;
	float RideHzFront = 2.f;
	float RideHzRear = 2.1f;
	float DampingRatio = 0.55f;
	float Preload = 50.f;
	float MaxRaiseCm = 10.f;
	float MaxDropCm = 12.f;
	float FrictionFront = 3.4f;
	float FrictionRear = 3.4f;
	float CorneringStiffness = 1000.f;
	float WheelLoadRatio = 0.5f;
	float BrakeTorqueFront = 2200.f;
	float BrakeTorqueRear = 1300.f;
	float HandbrakeTorque = 4000.f;
	bool bABS = true;
	bool bTractionControlFront = true;
	bool bTractionControlRear = true;
	float RollbarScaling = 0.6f;
};

struct FHKCameraConfig
{
	float ArmCm = 600.f;
	float HeightCm = 150.f;
	float PitchDeg = -10.f;
	float BaseFov = 80.f;
	float FovAdd = 12.f;
	float FovSpeedKmh = 220.f;
	float AccelPullCm = 60.f;
	float BrakePushCm = 45.f;
	float SpeedPullCm = 80.f;
	float LatShiftCm = 35.f;
	float LatRollDeg = 0.8f;
	float YawStiffness = 4.f;
	float YawStiffnessFast = 8.f;
	float VelocityBlend = 0.45f;
	float ShakeStartKmh = 150.f;
	float ShakeDeg = 0.35f;
	float BumpShakeDeg = 0.6f;
	float RecenterDelay = 1.2f;
	float LagSpeed = 12.f;
};

struct FHKBodyConfig
{
	float CabinX = -15.f;
	float CabinLength = 200.f;
	float CabinWidth = 160.f;
	float CabinHeight = 45.f;
};

struct FHKHandling
{
	EHKCarClass Class = EHKCarClass::FR;
	FHKChassisConfig Chassis;
	FHKEngineConfig Engine;
	FHKWheelsConfig Wheels;
	hkdrive::Params Assist;
	FHKCameraConfig Camera;
	FHKBodyConfig Body;
	// HK.DriveTest pass ranges; NaN means no bound.
	TMap<FString, FVector2f> Targets;
};

struct FHKCarLotConfig
{
	bool bEnabled = false;
	FName Anchor;
	TArray<EHKCarClass> Classes;
	float SpacingM = 7.5f;
};

namespace HKHandling
{
	// Loads on first use. Missing or broken file: built-in defaults and one warning.
	const FHKHandling& Get(EHKCarClass Class);
	EHKCarClass ClassForCar(FName CarId);
	const FHKCarLotConfig& Lot();
	bool Reload();
	FString ConfigPath();

	const TCHAR* ClassName(EHKCarClass Class);
	bool ParseClass(const FString& Text, EHKCarClass& Out);

	// Per-class wheel UCLASSes (CDOs written from the config); index 0 front, 1 rear.
	UClass* WheelClass(EHKCarClass Class, bool bFront);
	// Writes Get(Class) into the wheel CDOs. Call before the vehicle (re)creates its wheels.
	void WriteWheelDefaults(EHKCarClass Class);
}
