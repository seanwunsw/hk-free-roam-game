#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "HKFreeRoamCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class UHKPlayerAvatar;

UCLASS()
class HKFREEROAM_API AHKFreeRoamCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	/** Default (chibi, about 120 cm) capsule. The baked avatar may resize it in BeginPlay. */
	static constexpr float DefaultCapsuleRadius = 30.f;
	static constexpr float DefaultCapsuleHalfHeight = 60.f;
	/** Extra height above the capsule bottom when the player is placed on the ground (exit, teleport, spawn). */
	static constexpr float GroundClearance = 20.f;

	AHKFreeRoamCharacter();

	void SetSprinting(bool bInSprinting);

	/** Capsule half-height plus GroundClearance: how far above a ground hit to put the actor origin. */
	float GetGroundLift() const;

	/** Baked avatar applied in BeginPlay, or null when the cube body is in use. */
	UHKPlayerAvatar* GetAvatar() const;

protected:
	virtual void BeginPlay() override;

private:
	/** Loads the baked UHKPlayerAvatar and switches from the cube to the skeletal mesh. */
	bool ApplyAvatar();

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<USpringArmComponent> CameraBoom;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UCameraComponent> FollowCamera;

	/** Fallback body when no avatar is baked. */
	UPROPERTY(VisibleAnywhere, Category = "HK")
	TObjectPtr<UStaticMeshComponent> BodyVisual;

	UPROPERTY(Transient)
	TObjectPtr<UHKPlayerAvatar> Avatar;

	bool bSprinting = false;
};
