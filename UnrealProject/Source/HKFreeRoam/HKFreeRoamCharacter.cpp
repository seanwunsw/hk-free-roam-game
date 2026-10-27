#include "HKFreeRoamCharacter.h"

#include "HKFreeRoam.h"
#include "HKPlayerAnimInstance.h"
#include "HKPlayerAvatar.h"

#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Materials/MaterialInterface.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
	// Camera framing for a 180 cm body; scaled by height / 180.
	constexpr float RefHeightCm = 180.f;
	constexpr float RefArmLength = 380.f;
	constexpr float RefSocketY = 40.f;
	constexpr float RefSocketZ = 70.f;

	void FrameCamera(USpringArmComponent* Boom, float HeightCm)
	{
		const float Ratio = FMath::Clamp(HeightCm / RefHeightCm, 0.4f, 1.2f);
		Boom->TargetArmLength = FMath::Clamp(RefArmLength * Ratio, 240.f, RefArmLength);
		Boom->SocketOffset = FVector(0.f, RefSocketY * Ratio, RefSocketZ * Ratio);
	}
}

AHKFreeRoamCharacter::AHKFreeRoamCharacter()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = false;
	bUseControllerRotationRoll = false;

	GetCapsuleComponent()->InitCapsuleSize(DefaultCapsuleRadius, DefaultCapsuleHalfHeight);

	UCharacterMovementComponent* Move = GetCharacterMovement();
	Move->bOrientRotationToMovement = true;
	Move->RotationRate = FRotator(0.f, 540.f, 0.f);
	Move->MaxWalkSpeed = 500.f;
	Move->MaxAcceleration = 2400.f;
	Move->BrakingDecelerationWalking = 1600.f;
	Move->JumpZVelocity = 520.f;
	Move->AirControl = 0.35f;
	// Must stay below the capsule half-height.
	Move->MaxStepHeight = 45.f;
	Move->SetWalkableFloorAngle(50.f);
	Move->MaxSwimSpeed = 450.f;
	Move->Buoyancy = 1.15f;
	JumpMaxCount = 1;

	// The skeletal mesh is only shown once a baked avatar is applied in BeginPlay.
	GetMesh()->SetVisibility(false);
	GetMesh()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	GetMesh()->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::OnlyTickPoseWhenRendered;

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(GetCapsuleComponent());
	FrameCamera(CameraBoom, DefaultCapsuleHalfHeight * 2.f);
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 12.f;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	// Engine cube: 100 cm, pivot at its centre. Fill the capsule from its bottom
	// (-HalfHeight) to 10 cm below its top.
	BodyVisual = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("BodyVisual"));
	BodyVisual->SetupAttachment(GetCapsuleComponent());
	BodyVisual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	const float CubeHeight = DefaultCapsuleHalfHeight * 2.f - 10.f;
	BodyVisual->SetRelativeLocation(FVector(0.f, 0.f, -DefaultCapsuleHalfHeight + CubeHeight * 0.5f));
	BodyVisual->SetRelativeScale3D(FVector(0.45f, 0.3f, CubeHeight / 100.f));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (Cube.Succeeded())
	{
		BodyVisual->SetStaticMesh(Cube.Object);
	}
}

void AHKFreeRoamCharacter::BeginPlay()
{
	Super::BeginPlay();
	ApplyAvatar();
}

bool AHKFreeRoamCharacter::ApplyAvatar()
{
	Avatar = LoadObject<UHKPlayerAvatar>(nullptr, UHKPlayerAvatar::ObjectPath(), nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!Avatar || !Avatar->Mesh)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: no baked avatar at %s; using the cube. Add a model (data/characters/README.md) and re-run the bake."),
			UHKPlayerAvatar::ObjectPath());
		Avatar = nullptr;
		return false;
	}

	const float Height = FMath::Max(Avatar->HeightCm, 40.f);
	const float HalfHeight = FMath::Max(Height * 0.5f, 30.f);
	const float Radius = FMath::Clamp(Height * 0.23f, 18.f, 42.f);
	// Grow upward from the current feet position so a bigger capsule does not start inside the floor.
	const float OldHalfHeight = GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
	GetCapsuleComponent()->SetCapsuleSize(Radius, HalfHeight, true);
	AddActorWorldOffset(FVector(0.f, 0.f, HalfHeight - OldHalfHeight));
	GetCharacterMovement()->MaxStepHeight = FMath::Min(45.f, HalfHeight * 0.66f);

	USkeletalMeshComponent* MeshComp = GetMesh();
	MeshComp->SetSkeletalMeshAsset(Avatar->Mesh);
	MeshComp->SetRelativeScale3D(FVector(Avatar->MeshScale));
	MeshComp->SetRelativeLocationAndRotation(
		FVector(0.f, 0.f, -HalfHeight - Avatar->FootZCm),
		FRotator(0.f, Avatar->MeshYawDeg, 0.f));
	MeshComp->SetAnimInstanceClass(UHKPlayerAnimInstance::StaticClass());
	if (UHKPlayerAnimInstance* Anim = Cast<UHKPlayerAnimInstance>(MeshComp->GetAnimInstance()))
	{
		Anim->SetAvatar(Avatar);
	}
	MeshComp->SetOverlayMaterial(Avatar->OutlineMaterial);
	MeshComp->SetVisibility(true);

	BodyVisual->SetVisibility(false);
	BodyVisual->SetHiddenInGame(true);

	FrameCamera(CameraBoom, Height);

	UE_LOG(LogHK, Log, TEXT("Player: avatar %s (%.0f cm, scale %.3f, outline %s)"),
		*Avatar->SourceFile, Height, Avatar->MeshScale, Avatar->OutlineMaterial ? TEXT("on") : TEXT("off"));
	return true;
}

UHKPlayerAvatar* AHKFreeRoamCharacter::GetAvatar() const
{
	return Avatar;
}

float AHKFreeRoamCharacter::GetGroundLift() const
{
	return GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + GroundClearance;
}

void AHKFreeRoamCharacter::SetSprinting(bool bInSprinting)
{
	bSprinting = bInSprinting;
	GetCharacterMovement()->MaxWalkSpeed = bSprinting ? 900.f : 500.f;
}
