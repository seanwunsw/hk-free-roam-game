#include "HKChaseCamera.h"

#include "Camera/CameraComponent.h"
#include "GameFramework/Actor.h"
#include "GameFramework/SpringArmComponent.h"

UHKChaseCamera::UHKChaseCamera()
{
	PrimaryComponentTick.bCanEverTick = true;
	// After Chaos has moved the body this frame, so the rig never trails one frame behind.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UHKChaseCamera::Init(USpringArmComponent* InBoom, UCameraComponent* InCamera)
{
	Boom = InBoom;
	Camera = InCamera;
	if (Boom)
	{
		Boom->bUsePawnControlRotation = false;
		Boom->bInheritPitch = false;
		Boom->bInheritRoll = false;
		Boom->bInheritYaw = false;
		Boom->SetUsingAbsoluteRotation(true);
		Boom->bEnableCameraLag = true;
		Boom->bEnableCameraRotationLag = false;
		Boom->bDoCollisionTest = true;
		// The arm applies the rotation set here in the same frame.
		Boom->SetTickGroup(TG_PostPhysics);
		Boom->AddTickPrerequisiteComponent(this);
	}
}

void UHKChaseCamera::Snap()
{
	const AActor* Car = GetOwner();
	if (!Car)
	{
		return;
	}
	Yaw = Car->GetActorRotation().Yaw;
	YawVel = 0.f;
	LookYaw = LookPitch = 0.f;
	LookIdle = 100.f;
	Arm = Config.ArmCm;
	LatShift = Roll = LongG = LatG = Bump = 0.f;
	Fov = Config.BaseFov;
	bHasPrev = false;
	ResetJitter();
	Step(0.f);
}

void UHKChaseCamera::AddLook(float YawDeg, float PitchDeg)
{
	LookYaw = FMath::UnwindDegrees(LookYaw + YawDeg);
	LookPitch = FMath::Clamp(LookPitch + PitchDeg, -50.f, 25.f);
	if (FMath::Abs(YawDeg) + FMath::Abs(PitchDeg) > 0.01f)
	{
		LookIdle = 0.f;
	}
}

void UHKChaseCamera::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	// Fixed small steps: the springs stay stable and identical at any frame rate.
	float Left = FMath::Min(DeltaTime, 0.1f);
	while (Left > 1e-5f)
	{
		const float Dt = FMath::Min(Left, 1.f / 120.f);
		Step(Dt);
		Left -= Dt;
	}
	const AActor* Car = GetOwner();
	if (Camera && Car && DeltaTime > 0.f)
	{
		// Jitter: frame-to-frame second difference of the smooth rig (shake excluded) and of the
		// camera position relative to the car. A steady follow scores ~0; stutter shows up here.
		const FVector Rel = Camera->GetComponentLocation() - Car->GetActorLocation();
		if (JitterHistory >= 2)
		{
			const float D2 = FMath::FindDeltaAngleDegrees(PrevYaw[0], LastRigYaw) - FMath::FindDeltaAngleDegrees(PrevYaw[1], PrevYaw[0]);
			const FVector P2 = Rel - 2.f * PrevPos[0] + PrevPos[1];
			JitterStats.YawSq += D2 * D2;
			JitterStats.PosSq += P2.SizeSquared();
			++JitterStats.Frames;
		}
		PrevYaw[1] = PrevYaw[0];
		PrevYaw[0] = LastRigYaw;
		PrevPos[1] = PrevPos[0];
		PrevPos[0] = Rel;
		JitterHistory = FMath::Min(JitterHistory + 1, 2);
	}
}

void UHKChaseCamera::Step(float Dt)
{
	const AActor* Car = GetOwner();
	if (!Car || !Boom)
	{
		return;
	}
	const FVector Velocity = Car->GetVelocity();
	const FVector Fwd = Car->GetActorForwardVector();
	const FVector Right = Car->GetActorRightVector();
	const FVector Up = Car->GetActorUpVector();
	const float SpeedFwd = FVector::DotProduct(Velocity, Fwd);
	const float Kmh = Velocity.Size() * 0.036f;
	const float CarYaw = Car->GetActorRotation().Yaw;

	if (Dt > 0.f)
	{
		// Smoothed accelerations in g (EMA ~0.15 s) for arm, shift and roll; raw vertical jolt for shake.
		const FVector Accel = bHasPrev ? (Velocity - PrevVelocity) / Dt : FVector::ZeroVector;
		PrevVelocity = Velocity;
		bHasPrev = true;
		const float Alpha = 1.f - FMath::Exp(-Dt / 0.15f);
		LongG += (FVector::DotProduct(Accel, Fwd) / 981.f - LongG) * Alpha;
		LatG += (FVector::DotProduct(Accel, Right) / 981.f - LatG) * Alpha;
		const float Jolt = FMath::Abs(FVector::DotProduct(Accel, Up)) / 981.f;
		Bump = FMath::Max(Bump * FMath::Exp(-Dt / 0.12f), FMath::Clamp((Jolt - 0.6f) / 2.f, 0.f, 1.f));
		Time += Dt;
	}

	// Heading: car yaw, blended toward the direction of travel when moving forward.
	float Desired = CarYaw;
	if (SpeedFwd > 400.f)
	{
		const float VelYaw = FMath::RadiansToDegrees(FMath::Atan2(Velocity.Y, Velocity.X));
		const float Blend = Config.VelocityBlend * FMath::Clamp((Kmh - 15.f) / 30.f, 0.f, 1.f);
		Desired = CarYaw + Blend * FMath::FindDeltaAngleDegrees(CarYaw, VelYaw);
	}
	const float K = FMath::Lerp(Config.YawStiffness, Config.YawStiffnessFast, FMath::Clamp(Kmh / 150.f, 0.f, 1.f));
	if (Dt > 0.f)
	{
		const float Err = FMath::FindDeltaAngleDegrees(Yaw, Desired);
		YawVel += (K * K * Err - 2.f * K * YawVel) * Dt;
		Yaw = FMath::UnwindDegrees(Yaw + YawVel * Dt);
		// Never let the car leave the frame on a hard spin.
		const float Lag = FMath::FindDeltaAngleDegrees(Yaw, Desired);
		if (FMath::Abs(Lag) > 70.f)
		{
			Yaw = FMath::UnwindDegrees(Desired - FMath::Sign(Lag) * 70.f);
		}

		LookIdle += Dt;
		if (LookIdle > Config.RecenterDelay && Kmh > 10.f)
		{
			const float Decay = FMath::Exp(-2.5f * Dt);
			LookYaw *= Decay;
			LookPitch *= Decay;
		}

		const float Pull = Config.SpeedPullCm * FMath::Clamp(Kmh / 200.f, 0.f, 1.f)
			+ Config.AccelPullCm * FMath::Clamp(LongG / 0.5f, 0.f, 1.f)
			- Config.BrakePushCm * FMath::Clamp(-LongG / 0.8f, 0.f, 1.f);
		const float Follow = 1.f - FMath::Exp(-3.f * Dt);
		Arm += (Config.ArmCm + Pull - Arm) * Follow;
		LatShift += (-Config.LatShiftCm * FMath::Clamp(LatG, -1.2f, 1.2f) - LatShift) * Follow;
		Roll += (Config.LatRollDeg * FMath::Clamp(LatG, -1.2f, 1.2f) - Roll) * Follow;
		const float FovTarget = Config.BaseFov + Config.FovAdd * FMath::SmoothStep(0.f, 1.f, Kmh / FMath::Max(Config.FovSpeedKmh, 1.f));
		Fov += (FovTarget - Fov) * (1.f - FMath::Exp(-2.f * Dt));
	}

	const float Shake = Config.ShakeDeg * FMath::Clamp((Kmh - Config.ShakeStartKmh) / 100.f, 0.f, 1.f) + Config.BumpShakeDeg * Bump;
	const float ShakePitch = Shake * FMath::PerlinNoise1D(Time * 7.3f);
	const float ShakeYaw = Shake * 0.6f * FMath::PerlinNoise1D(Time * 5.1f + 31.7f);

	const float RigYaw = Yaw + LookYaw;
	Boom->SetWorldRotation(FRotator(Config.PitchDeg + LookPitch + ShakePitch, RigYaw + ShakeYaw, 0.f));
	Boom->TargetArmLength = Arm;
	Boom->SocketOffset = FVector(0.f, LatShift, Config.HeightCm);
	Boom->CameraLagSpeed = Config.LagSpeed;
	if (Camera)
	{
		Camera->SetFieldOfView(Fov);
		Camera->SetRelativeRotation(FRotator(0.f, 0.f, Roll));
	}
	LastRigYaw = RigYaw;
}
