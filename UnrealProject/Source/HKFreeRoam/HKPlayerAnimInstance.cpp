#include "HKPlayerAnimInstance.h"

#include "HKFreeRoamCharacter.h"
#include "HKPlayerAvatar.h"

#include "Animation/AnimNodeBase.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "AnimationRuntime.h"
#include "GameFramework/CharacterMovementComponent.h"

namespace
{
	float SeqLength(const UAnimSequence* Seq)
	{
		return Seq ? FMath::Max(Seq->GetPlayLength(), UE_KINDA_SMALL_NUMBER) : 1.f;
	}

	/** Frame-rate independent ease toward Target with time constant Tau seconds. */
	float Approach(float Current, float Target, float DeltaSeconds, float Tau)
	{
		const float Alpha = 1.f - FMath::Exp(-DeltaSeconds / FMath::Max(Tau, 1e-3f));
		return FMath::Lerp(Current, Target, Alpha);
	}

	void AddLayer(FHKAnimLayer* Out, int32& Num, int32 Max, const UAnimSequence* Seq, float Time, float Weight)
	{
		if (!Seq || Weight < 0.01f || Num >= Max)
		{
			return;
		}
		Out[Num].Sequence = Seq;
		Out[Num].Time = Time;
		Out[Num].Weight = Weight;
		++Num;
	}

	void SampleLayer(const FHKAnimLayer& Layer, FPoseContext& Into)
	{
		FAnimationPoseData PoseData(Into);
		const FAnimExtractContext Context(static_cast<double>(Layer.Time), false, FDeltaTimeRecord(), true);
		Layer.Sequence->GetAnimationPose(PoseData, Context);
	}
}

void FHKPlayerAnimInstanceProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
	NumLayers = 0;
	if (UHKPlayerAnimInstance* Instance = Cast<UHKPlayerAnimInstance>(InAnimInstance))
	{
		NumLayers = Instance->BuildLayers(DeltaSeconds, Layers, HKMaxAnimLayers);
	}
}

bool FHKPlayerAnimInstanceProxy::Evaluate(FPoseContext& Output)
{
	if (NumLayers == 0)
	{
		Output.ResetToRefPose();
		return true;
	}

	FPoseContext Accum(Output, false);
	SampleLayer(Layers[0], Accum);
	float AccumWeight = Layers[0].Weight;

	for (int32 Index = 1; Index < NumLayers; ++Index)
	{
		const FHKAnimLayer& Layer = Layers[Index];
		FPoseContext Next(Output, false);
		SampleLayer(Layer, Next);

		FPoseContext Mixed(Output, false);
		FAnimationPoseData MixedData(Mixed);
		const float WeightOfAccum = AccumWeight / (AccumWeight + Layer.Weight);
		FAnimationRuntime::BlendTwoPosesTogether(FAnimationPoseData(Accum), FAnimationPoseData(Next), WeightOfAccum, MixedData);
		Accum = Mixed;
		AccumWeight += Layer.Weight;
	}

	Output = Accum;
	return true;
}

void UHKPlayerAnimInstance::NativeInitializeAnimation()
{
	Super::NativeInitializeAnimation();
	if (!Avatar)
	{
		if (const AHKFreeRoamCharacter* Character = Cast<AHKFreeRoamCharacter>(GetOwningActor()))
		{
			Avatar = Character->GetAvatar();
		}
	}
}

FAnimInstanceProxy* UHKPlayerAnimInstance::CreateAnimInstanceProxy()
{
	return new FHKPlayerAnimInstanceProxy(this);
}

void UHKPlayerAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
	delete static_cast<FHKPlayerAnimInstanceProxy*>(InProxy);
}

int32 UHKPlayerAnimInstance::BuildLayers(float DeltaSeconds, FHKAnimLayer* OutLayers, int32 MaxLayers)
{
	const ACharacter* Character = Cast<ACharacter>(GetOwningActor());
	if (!Avatar || !Character || !Character->GetCharacterMovement())
	{
		return 0;
	}
	const UCharacterMovementComponent* Move = Character->GetCharacterMovement();
	const UHKPlayerAvatar& A = *Avatar;
	const float Dt = FMath::Clamp(DeltaSeconds, 0.f, 0.1f);

	const FVector Velocity = Character->GetVelocity();
	SmoothedSpeed = Approach(SmoothedSpeed, Velocity.Size2D(), Dt, 0.08f);
	const float Speed = SmoothedSpeed;

	const bool bSwim = Move->IsSwimming();
	const bool bAir = !bSwim && Move->IsFalling();
	GroundWeight = Approach(GroundWeight, (!bSwim && !bAir) ? 1.f : 0.f, Dt, bAir ? 0.06f : 0.1f);
	AirWeight = Approach(AirWeight, bAir ? 1.f : 0.f, Dt, 0.06f);
	SwimWeight = Approach(SwimWeight, bSwim ? 1.f : 0.f, Dt, 0.15f);
	const float Total = FMath::Max(GroundWeight + AirWeight + SwimWeight, UE_KINDA_SMALL_NUMBER);

	int32 Num = 0;

	// Ground: idle -> walk -> jog -> sprint, piecewise linear in speed.
	{
		const UAnimSequence* Clips[4] = { A.Idle, A.Walk, A.Jog, A.Sprint };
		const float Ref[4] = { 0.f, FMath::Max(A.WalkRefSpeed, 1.f), FMath::Max(A.JogRefSpeed, 2.f), FMath::Max(A.SprintRefSpeed, 3.f) };
		int32 Lo = 0;
		float Alpha = 0.f;
		if (Speed >= Ref[3])
		{
			Lo = 2;
			Alpha = 1.f;
		}
		else
		{
			for (int32 i = 0; i < 3; ++i)
			{
				if (Speed < Ref[i + 1])
				{
					Lo = i;
					Alpha = (Speed - Ref[i]) / FMath::Max(Ref[i + 1] - Ref[i], 1.f);
					break;
				}
			}
		}
		const int32 Hi = Lo + 1;
		// The moving clip that sets the cadence (the faster of the pair).
		const UAnimSequence* Lead = Clips[Hi] ? Clips[Hi] : Clips[Lo];
		const float PlayRate = FMath::Clamp(Speed / Ref[Hi], 0.6f, 1.6f);
		if (Speed > 5.f)
		{
			LocoPhase = FMath::Fmod(LocoPhase + Dt * PlayRate / SeqLength(Lead), 1.f);
		}
		IdleTime = FMath::Fmod(IdleTime + Dt, SeqLength(A.Idle));

		const float W = GroundWeight / Total;
		auto TimeFor = [&](int32 i) { return i == 0 ? IdleTime : LocoPhase * SeqLength(Clips[i]); };
		AddLayer(OutLayers, Num, MaxLayers, Clips[Lo], TimeFor(Lo), W * (1.f - Alpha));
		AddLayer(OutLayers, Num, MaxLayers, Clips[Hi], TimeFor(Hi), W * Alpha);
	}

	// Air: jump start while rising, then the fall loop.
	{
		if (bAir && !bWasInAir)
		{
			AirTime = 0.f;
			FallTime = 0.f;
		}
		const bool bRising = bAir && Velocity.Z > 50.f && A.JumpStart && AirTime < SeqLength(A.JumpStart);
		if (bAir)
		{
			AirTime += Dt;
			if (!bRising)
			{
				FallTime += Dt;
			}
		}
		const float W = AirWeight / Total;
		if (bRising)
		{
			AddLayer(OutLayers, Num, MaxLayers, A.JumpStart, AirTime, W);
		}
		else
		{
			const UAnimSequence* Fall = A.JumpLoop ? A.JumpLoop.Get() : A.Idle.Get();
			AddLayer(OutLayers, Num, MaxLayers, Fall, FMath::Fmod(FallTime, SeqLength(Fall)), W);
		}
		bWasInAir = bAir;
	}

	// Swim: idle tread vs forward stroke by speed.
	{
		const float SwimRef = FMath::Max(A.SwimRefSpeed, 1.f);
		const float Alpha = FMath::Clamp(Speed / SwimRef, 0.f, 1.f);
		const float Rate = FMath::Lerp(1.f, FMath::Clamp(Speed / SwimRef, 0.6f, 1.5f), Alpha);
		SwimTime += Dt * Rate;
		const float W = SwimWeight / Total;
		const UAnimSequence* Tread = A.SwimIdle ? A.SwimIdle.Get() : A.Idle.Get();
		AddLayer(OutLayers, Num, MaxLayers, Tread, FMath::Fmod(SwimTime, SeqLength(Tread)), W * (1.f - Alpha));
		AddLayer(OutLayers, Num, MaxLayers, A.SwimFwd, FMath::Fmod(SwimTime, SeqLength(A.SwimFwd)), W * Alpha);
	}

	return Num;
}
