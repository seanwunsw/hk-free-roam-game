#pragma once

#include "CoreMinimal.h"
#include "HKHandling.h"
#include "HKRideable.h"
#include "WheeledVehiclePawn.h"
#include "hk_drive_assist.h"
#include "HKCar.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class USkeletalMesh;
class UStaticMesh;
class UPhysicsAsset;
class UChaosWheeledVehicleMovementComponent;
class UHKChaseCamera;

// What the car did last tick, for the HUD and HK.DriveTest. Accelerations come from the change in
// body velocity (no gravity), in g; angles in degrees.
struct FHKCarTelemetry
{
	float Kmh = 0.f;
	float SpeedFwd = 0.f; // m/s
	float SlipDeg = 0.f;  // rear-axle slip, see hk_drive_assist.h
	float YawRateDeg = 0.f;
	float LatG = 0.f;
	float LongG = 0.f;
	float VertG = 0.f;
	float RollDeg = 0.f;  // + = right side down
	float PitchDeg = 0.f; // + = nose up
	int32 Gear = 0;
	float Rpm = 0.f;
	int32 LockedWheels = 0;
	bool bGrounded = true;
	bool bOffroad = false;
	hkdrive::Output Assist;
};

UCLASS()
class HKFREEROAM_API AHKCar : public AWheeledVehiclePawn, public IHKRideable
{
	GENERATED_BODY()

public:
	AHKCar();

	virtual float GetInteractRadiusCm() const override { return 450.f; }
	virtual bool IsOccupied() const override { return bOccupied; }

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void PossessedBy(AController* NewController) override;
	virtual void UnPossessed() override;

	void ApplyDrive(float ForwardAxis, float SteerAxis, bool bHandbrake);
	void StopPhysics();
	void SetVehicleMesh(USkeletalMesh* NewMesh, UPhysicsAsset* PhysicsAsset);
	void ApplyPaint(UMaterialInterface* BodyMaterial, UMaterialInterface* WheelMaterial);

	// Driving class (data/config/vehicles.json). SetCarClass reapplies the handling at once.
	EHKCarClass GetCarClass() const { return CarClass; }
	void SetCarClass(EHKCarClass NewClass);
	void ApplyHandling();
	FName CarId() const { return Tags.Num() > 0 ? Tags[0] : NAME_None; }

	void AddCameraLook(float YawDeg, float PitchDeg);
	UHKChaseCamera* GetChaseCamera() const { return ChaseCamera; }
	const FHKCarTelemetry& Telemetry() const { return Telem; }

	// HK.DriveTest: drive without a controller, inputs from SetAutopilot.
	void BeginTestDrive();
	void EndTestDrive();
	void SetAutopilot(const hkdrive::Input& Input) { Autopilot = Input; }
	// Teleport, zero all motion and assist memory, snap the camera.
	void ResetMotion(const FVector& Location, float YawDeg);

	static AHKCar* SpawnCar(UWorld* World, EHKCarClass Class, const FTransform& Where, FName Id, int32 PaintIndex);

	// Skeleton bones the wheels attach to, in WheelSetups order (FL, FR, RL, RR).
	static const TArray<FName>& WheelBoneNames();

protected:
	// Class from the config by car id unless set before BeginPlay (SpawnCar, the editor).
	UPROPERTY(EditAnywhere, Category = "HK")
	EHKCarClass CarClass = EHKCarClass::FR;

	UPROPERTY(EditAnywhere, Category = "HK")
	bool bClassOverride = false;

private:
	UChaosWheeledVehicleMovementComponent* Movement() const;
	void ConfigureMechanical();
	void SetupWheel(UStaticMeshComponent* Wheel, const FVector& Offset, UStaticMesh* WheelMesh);
	void Park();
	void HoldIfGroundUnloaded();
	void PatchWheelBones();
	void EnableChassisPhysics();
	void UpdateWheelVisuals(float DeltaSeconds);
	void SelfRightIfFlipped(float DeltaSeconds);
	void DriveTick(float DeltaSeconds);
	void UpdateTelemetry(float DeltaSeconds);
	void TrySpawnLot();

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UHKChaseCamera> ChaseCamera;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelFL;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelFR;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelRL;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelRR;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> Cabin;

	bool bOccupied = false;
	bool bTestDrive = false;
	bool bHandlingApplied = false;
	float VisualSteerDegrees = 0.f;
	float WheelSpinDegrees = 0.f;
	float FlippedSeconds = 0.f;
	static constexpr float FlipHoldSeconds = 2.f;

	hkdrive::Input DriverInput;
	TOptional<hkdrive::Input> Autopilot;
	hkdrive::Memory AssistMemory;
	float BaseFriction[4] = {3.4f, 3.4f, 3.4f, 3.4f};
	float AppliedFriction[4] = {0.f, 0.f, 0.f, 0.f};
	float WheelRadiusCm = 34.f;

	FHKCarTelemetry Telem;
	FVector PrevVelocity = FVector::ZeroVector;
	bool bHasPrevVelocity = false;
	float PrevWheelAngle[4] = {0.f, 0.f, 0.f, 0.f};
	bool bHasPrevWheelAngle = false;

	FTimerHandle LotTimer;
	int32 LotTries = 0;
};
