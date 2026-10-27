#pragma once

#include "CoreMinimal.h"
#include "HKRideable.h"
#include "WheeledVehiclePawn.h"
#include "HKCar.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class USkeletalMesh;
class UStaticMesh;
class UPhysicsAsset;
class UChaosWheeledVehicleMovementComponent;

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
	void SetVehicleMesh(USkeletalMesh* Mesh, UPhysicsAsset* PhysicsAsset);
	void ApplyPaint(UMaterialInterface* BodyMaterial, UMaterialInterface* WheelMaterial);

private:
	UChaosWheeledVehicleMovementComponent* Movement() const;
	void ConfigureMechanical();
	void SetupWheel(UStaticMeshComponent* Wheel, const FVector& Offset, UStaticMesh* WheelMesh);
	void Park();
	void HoldIfGroundUnloaded();
	void PatchWheelBones();
	void UpdateWheelVisuals(float DeltaSeconds);

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelFL;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelFR;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelRL;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> WheelRR;

	bool bOccupied = false;
	float VisualSteerDegrees = 0.f;
	float WheelSpinDegrees = 0.f;
};
