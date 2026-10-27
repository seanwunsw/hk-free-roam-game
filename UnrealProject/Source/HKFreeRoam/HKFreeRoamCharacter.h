#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "HKFreeRoamCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;

UCLASS()
class HKFREEROAM_API AHKFreeRoamCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AHKFreeRoamCharacter();
	virtual void Tick(float DeltaSeconds) override;

	void SetSprinting(bool bInSprinting);

private:
	void UpdateSwim(float Z);

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> BodyVisual;

	bool bSprinting = false;
};
