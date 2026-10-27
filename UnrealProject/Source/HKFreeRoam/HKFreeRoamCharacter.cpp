#include "HKFreeRoamCharacter.h"

#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "UObject/ConstructorHelpers.h"

AHKFreeRoamCharacter::AHKFreeRoamCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = false;
	bUseControllerRotationRoll = false;

	GetCapsuleComponent()->InitCapsuleSize(42.f, 90.f);

	UCharacterMovementComponent* Move = GetCharacterMovement();
	Move->bOrientRotationToMovement = true;
	Move->RotationRate = FRotator(0.f, 540.f, 0.f);
	Move->MaxWalkSpeed = 500.f;
	Move->MaxAcceleration = 2400.f;
	Move->BrakingDecelerationWalking = 1600.f;
	Move->JumpZVelocity = 520.f;
	Move->AirControl = 0.35f;
	Move->MaxStepHeight = 45.f;
	Move->SetWalkableFloorAngle(50.f);
	Move->MaxSwimSpeed = 450.f;
	Move->Buoyancy = 1.15f;
	JumpMaxCount = 1;

	GetMesh()->SetVisibility(false);
	GetMesh()->SetCollisionEnabled(ECollisionEnabled::NoCollision);

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(GetCapsuleComponent());
	CameraBoom->TargetArmLength = 380.f;
	CameraBoom->SocketOffset = FVector(0.f, 40.f, 70.f);
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 12.f;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	BodyVisual = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyVisual"));
	BodyVisual->SetupAttachment(GetCapsuleComponent());
	BodyVisual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	BodyVisual->SetRelativeLocation(FVector(0.f, 0.f, -70.f));
	BodyVisual->SetRelativeScale3D(FVector(0.55f, 0.35f, 1.35f));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (Cube.Succeeded())
	{
		BodyVisual->SetStaticMesh(Cube.Object);
	}
}

void AHKFreeRoamCharacter::SetSprinting(bool bInSprinting)
{
	bSprinting = bInSprinting;
	GetCharacterMovement()->MaxWalkSpeed = bSprinting ? 900.f : 500.f;
}

void AHKFreeRoamCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (GetAttachParentActor())
	{
		return;
	}
	UpdateSwim(GetActorLocation().Z);
}

void AHKFreeRoamCharacter::UpdateSwim(float Z)
{
	// There is no physics volume. Below the water plane (Z = 0 cm) the pawn is forced to swim
	// and given a small upward speed so it does not walk the bathymetry.
	UCharacterMovementComponent* Move = GetCharacterMovement();
	const bool bSwimming = Move->MovementMode == MOVE_Swimming;
	if (Z < 20.f && (!Move->IsMovingOnGround() || Z < 5.f))
	{
		if (!bSwimming)
		{
			Move->SetMovementMode(MOVE_Swimming);
		}
		if (Z < 0.f && Move->Velocity.Z < 80.f)
		{
			Move->Velocity.Z = 80.f;
		}
	}
	else if (bSwimming && (Z > 150.f || (Move->IsMovingOnGround() && Z > 80.f)))
	{
		Move->SetMovementMode(MOVE_Walking);
	}
}
