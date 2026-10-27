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

	void SetSprinting(bool bInSprinting);

private:
	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> BodyVisual;

	bool bSprinting = false;
};
