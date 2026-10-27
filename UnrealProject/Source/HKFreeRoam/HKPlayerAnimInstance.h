#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "HKPlayerAnimInstance.generated.h"

class UAnimSequence;
class UHKPlayerAvatar;

/** One weighted sample of a sequence. */
struct FHKAnimLayer
{
	const UAnimSequence* Sequence = nullptr;
	float Time = 0.f;
	float Weight = 0.f;
};

/** Up to this many sequences are sampled and blended per frame. */
static constexpr int32 HKMaxAnimLayers = 6;

/**
 * Proxy for UHKPlayerAnimInstance. PreUpdate (game thread) asks the instance
 * for this frame's weighted layers; Evaluate (any thread) samples and blends
 * them. No anim graph, so no AnimBP asset.
 */
USTRUCT()
struct FHKPlayerAnimInstanceProxy : public FAnimInstanceProxy
{
	GENERATED_BODY()

	FHKPlayerAnimInstanceProxy() = default;
	explicit FHKPlayerAnimInstanceProxy(UAnimInstance* InAnimInstance)
		: FAnimInstanceProxy(InAnimInstance)
	{
	}

protected:
	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate(FPoseContext& Output) override;

private:
	FHKAnimLayer Layers[HKMaxAnimLayers];
	int32 NumLayers = 0;
};

/**
 * Code-only locomotion for the player: idle / walk / jog / sprint blended by
 * ground speed with a shared phase, jump start / fall in the air, swim idle /
 * swim forward in water. Clips come from UHKPlayerAvatar.
 */
UCLASS(Transient, NotBlueprintable)
class HKFREEROAM_API UHKPlayerAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:
	void SetAvatar(UHKPlayerAvatar* InAvatar) { Avatar = InAvatar; }

	/** Fills OutLayers for this frame. Game thread only (called from the proxy's PreUpdate). */
	int32 BuildLayers(float DeltaSeconds, FHKAnimLayer* OutLayers, int32 MaxLayers);

protected:
	virtual void NativeInitializeAnimation() override;
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;

private:
	UPROPERTY(Transient)
	TObjectPtr<UHKPlayerAvatar> Avatar;

	float GroundWeight = 1.f;
	float AirWeight = 0.f;
	float SwimWeight = 0.f;
	/** Normalised 0..1 phase shared by walk, jog and sprint so blends stay in step. */
	float LocoPhase = 0.f;
	float IdleTime = 0.f;
	float AirTime = 0.f;
	float FallTime = 0.f;
	float SwimTime = 0.f;
	float SmoothedSpeed = 0.f;
	bool bWasInAir = false;
};
