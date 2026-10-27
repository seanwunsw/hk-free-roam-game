#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "HKRideable.h"
#include "HKHelicopter.generated.h"

class UBoxComponent;
class UStaticMeshComponent;
class USpringArmComponent;
class UCameraComponent;

UCLASS()
class HKFREEROAM_API AHKHelicopter : public APawn, public IHKRideable
{
	GENERATED_BODY()

public:
	AHKHelicopter();

	virtual float GetInteractRadiusCm() const override { return 700.f; }
	virtual bool IsOccupied() const override { return bOccupied; }

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void PossessedBy(AController* NewController) override;
	virtual void UnPossessed() override;

	void SetMouseCyclic(float Roll, float Pitch);
	void SetKeyCyclic(float Roll, float Pitch);
	void SetYawInput(float Yaw);
	void SetCollectiveUp(bool bHeld);
	void SetCollectiveDown(bool bHeld);
	void ToggleHoverAssist();
	void StopPhysics();
	void ApplyPaint(UMaterialInterface* BodyMaterial);

	bool HoverAssistEnabled() const { return bHoverAssist; }
	float GetCollective() const { return Collective; }

private:
	void HoldParked(float DeltaSeconds);
	void Fly(float DeltaSeconds);
	void SpinRotors(float DeltaSeconds);

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UBoxComponent> Body;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> BodyVisual;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> TailVisual;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> MainRotor;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> TailRotor;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	bool bOccupied = false;
	bool bHoverAssist = true;
	bool bCollectiveUp = false;
	bool bCollectiveDown = false;
	float Collective = 0.f;
	float YawInput = 0.f;
	float MousePitch = 0.f;
	float MouseRoll = 0.f;
	float KeyPitch = 0.f;
	float KeyRoll = 0.f;
	float CyclicPitch = 0.f;
	float CyclicRoll = 0.f;
	float Spool = 1.f;
	float RotorAngle = 0.f;
	float TailRotorAngle = 0.f;

	static constexpr float MassKg = 1100.f;
};
