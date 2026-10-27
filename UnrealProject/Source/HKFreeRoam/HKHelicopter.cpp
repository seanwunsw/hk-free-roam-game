#include "HKHelicopter.h"

#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"

AHKHelicopter::AHKHelicopter()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = false;
	bUseControllerRotationRoll = false;

	Body = CreateDefaultSubobject<UBoxComponent>(TEXT("Body"));
	SetRootComponent(Body);
	Body->SetBoxExtent(FVector(280.f, 70.f, 55.f));
	Body->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	Body->SetCollisionObjectType(ECC_Vehicle);
	Body->SetCollisionResponseToAllChannels(ECR_Block);
	Body->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
	Body->SetSimulatePhysics(false);
	Body->SetEnableGravity(false);
	Body->SetMassOverrideInKg(NAME_None, MassKg, true);
	Body->SetLinearDamping(0.05f);
	Body->SetAngularDamping(0.2f);

	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));

	BodyVisual = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyVisual"));
	BodyVisual->SetupAttachment(Body);
	BodyVisual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	BodyVisual->SetRelativeScale3D(FVector(5.6f, 1.4f, 1.1f));

	TailVisual = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("TailVisual"));
	TailVisual->SetupAttachment(Body);
	TailVisual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	TailVisual->SetRelativeLocation(FVector(-390.f, 0.f, 10.f));
	TailVisual->SetRelativeScale3D(FVector(3.4f, 0.22f, 0.22f));

	MainRotor = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MainRotor"));
	MainRotor->SetupAttachment(Body);
	MainRotor->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	MainRotor->SetRelativeLocation(FVector(0.f, 0.f, 70.f));
	MainRotor->SetRelativeScale3D(FVector(7.f, 7.f, 0.04f));

	TailRotor = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("TailRotor"));
	TailRotor->SetupAttachment(Body);
	TailRotor->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	TailRotor->SetRelativeLocation(FVector(-540.f, 0.f, 20.f));
	TailRotor->SetRelativeRotation(FRotator(0.f, 0.f, 90.f));
	TailRotor->SetRelativeScale3D(FVector(1.3f, 1.3f, 0.04f));

	if (Cube.Succeeded())
	{
		BodyVisual->SetStaticMesh(Cube.Object);
		TailVisual->SetStaticMesh(Cube.Object);
	}
	if (Cylinder.Succeeded())
	{
		MainRotor->SetStaticMesh(Cylinder.Object);
		TailRotor->SetStaticMesh(Cylinder.Object);
	}

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(Body);
	CameraBoom->TargetArmLength = 950.f;
	CameraBoom->SocketOffset = FVector(0.f, 0.f, 160.f);
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->bInheritPitch = true;
	CameraBoom->bInheritYaw = true;
	CameraBoom->bInheritRoll = false;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 4.f;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;
}

void AHKHelicopter::BeginPlay()
{
	Super::BeginPlay();
	Body->SetSimulatePhysics(true);
	Body->SetEnableGravity(false);
	Body->SetMassOverrideInKg(NAME_None, MassKg, true);
	Spool = 1.f;
}

void AHKHelicopter::PossessedBy(AController* NewController)
{
	Super::PossessedBy(NewController);
	bOccupied = true;
	Body->SetEnableGravity(true);
	Body->SetSimulatePhysics(true);
}

void AHKHelicopter::UnPossessed()
{
	bOccupied = false;
	MousePitch = 0.f;
	MouseRoll = 0.f;
	KeyPitch = 0.f;
	KeyRoll = 0.f;
	YawInput = 0.f;
	bCollectiveUp = false;
	bCollectiveDown = false;
	Body->SetEnableGravity(false);
	Super::UnPossessed();
}

void AHKHelicopter::SetMouseCyclic(float Roll, float Pitch)
{
	MouseRoll = Roll;
	MousePitch = Pitch;
}

void AHKHelicopter::SetKeyCyclic(float Roll, float Pitch)
{
	KeyRoll = Roll;
	KeyPitch = Pitch;
}

void AHKHelicopter::SetYawInput(float Yaw)
{
	YawInput = FMath::Clamp(Yaw, -1.f, 1.f);
}

void AHKHelicopter::SetCollectiveUp(bool bHeld)
{
	bCollectiveUp = bHeld;
}

void AHKHelicopter::SetCollectiveDown(bool bHeld)
{
	bCollectiveDown = bHeld;
}

void AHKHelicopter::ToggleHoverAssist()
{
	bHoverAssist = !bHoverAssist;
}

void AHKHelicopter::StopPhysics()
{
	if (Body->IsSimulatingPhysics())
	{
		Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	}
}

void AHKHelicopter::ApplyPaint(UMaterialInterface* BodyMaterial)
{
	if (!BodyMaterial)
	{
		return;
	}
	BodyVisual->SetMaterial(0, BodyMaterial);
	TailVisual->SetMaterial(0, BodyMaterial);
}

void AHKHelicopter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!Body->IsSimulatingPhysics())
	{
		Body->SetSimulatePhysics(true);
	}
	SpinRotors(DeltaSeconds);
	if (!bOccupied)
	{
		HoldParked(DeltaSeconds);
		return;
	}
	Fly(DeltaSeconds);
	MousePitch = 0.f;
	MouseRoll = 0.f;
}

void AHKHelicopter::HoldParked(float DeltaSeconds)
{
	// Gravity stays off while nobody is flying, so a parked helicopter cannot fall into the harbour.
	Body->SetEnableGravity(false);
	Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	const FRotator Upright(0.f, GetActorRotation().Yaw, 0.f);
	SetActorRotation(FMath::RInterpTo(GetActorRotation(), Upright, DeltaSeconds, 3.f), ETeleportType::TeleportPhysics);
}

void AHKHelicopter::Fly(float DeltaSeconds)
{
	Body->SetEnableGravity(true);
	if (bCollectiveUp)
	{
		Collective += DeltaSeconds * 0.45f;
	}
	if (bCollectiveDown)
	{
		Collective -= DeltaSeconds * 0.45f;
	}
	Collective = FMath::Clamp(Collective, -0.15f, 1.f);
	Spool = FMath::FInterpTo(Spool, 1.f, DeltaSeconds, 0.67f);

	const float Mass = FMath::Max(Body->GetMass(), 1.f);
	const float Weight = Mass * 980.f;
	// Assist off: full collective gives 1.5x weight (hover near 0.63), so the pilot can climb.
	const float Base = bHoverAssist ? Weight : 0.15f * Weight;
	const float Span = bHoverAssist ? 0.85f : 1.35f;
	float Thrust = FMath::Max(Base + Collective * Weight * Span, 0.f) * Spool;
	if (Collective > 0.05f)
	{
		FHitResult Ground;
		FCollisionQueryParams Params(SCENE_QUERY_STAT(HKHeliGround), false, this);
		const FVector Start = GetActorLocation() - FVector(0.f, 0.f, 50.f);
		if (GetWorld()->LineTraceSingleByChannel(Ground, Start, Start - FVector(0.f, 0.f, 600.f), ECC_Visibility, Params) && Ground.Distance < 500.f)
		{
			Thrust *= 1.f + 0.2f * (1.f - Ground.Distance / 500.f);
		}
	}
	Body->AddForce(GetActorUpVector() * Thrust);

	const float PitchTarget = FMath::Clamp(MousePitch + KeyPitch, -1.f, 1.f);
	const float RollTarget = FMath::Clamp(MouseRoll + KeyRoll, -1.f, 1.f);
	CyclicPitch = FMath::FInterpTo(CyclicPitch, PitchTarget, DeltaSeconds, 2.0f);
	CyclicRoll = FMath::FInterpTo(CyclicRoll, RollTarget, DeltaSeconds, 2.0f);

	// bAccelChange treats the vector as rad/s^2, so mass is not applied twice.
	// A positive torque about local +X lifts the right side, so roll is negated: +roll banks right.
	FVector Angular(-CyclicRoll * 2.0f, CyclicPitch * 2.0f, YawInput * 1.2f);
	Angular = GetActorTransform().TransformVectorNoScale(Angular);
	if (bHoverAssist)
	{
		Angular += FVector::CrossProduct(GetActorUpVector(), FVector::UpVector) * 3.5f;
		Angular -= Body->GetPhysicsAngularVelocityInRadians() * 1.2f;
	}
	Body->AddTorqueInRadians(Angular, NAME_None, true);
}

void AHKHelicopter::SpinRotors(float DeltaSeconds)
{
	const float Rate = bOccupied ? 1400.f : 500.f;
	RotorAngle = FMath::UnwindDegrees(RotorAngle + Rate * Spool * DeltaSeconds);
	TailRotorAngle = FMath::UnwindDegrees(TailRotorAngle + Rate * 1.8f * Spool * DeltaSeconds);
	MainRotor->SetRelativeRotation(FRotator(0.f, RotorAngle, 0.f));
	TailRotor->SetRelativeRotation(FRotator(TailRotorAngle, 0.f, 90.f));
}
