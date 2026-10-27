#include "HKCar.h"

#include "HKFreeRoam.h"
#include "HKWheelFront.h"
#include "HKWheelRear.h"

#include "Camera/CameraComponent.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "Materials/MaterialInterface.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "UObject/ConstructorHelpers.h"

AHKCar::AHKCar()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;

	ConfigureMechanical();

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(GetMesh());
	CameraBoom->TargetArmLength = 560.f;
	CameraBoom->SocketOffset = FVector(0.f, 0.f, 90.f);
	CameraBoom->bUsePawnControlRotation = true;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 8.f;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	WheelFL = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("WheelFL"));
	WheelFR = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("WheelFR"));
	WheelRL = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("WheelRL"));
	WheelRR = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("WheelRR"));
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
	UStaticMesh* WheelMesh = Cylinder.Succeeded() ? Cylinder.Object : nullptr;
	// UE +Y is right, so the left wheels sit on negative Y. Z is the wheel centre.
	SetupWheel(WheelFL, FVector(135.f, -80.f, 34.f), WheelMesh);
	SetupWheel(WheelFR, FVector(135.f, 80.f, 34.f), WheelMesh);
	SetupWheel(WheelRL, FVector(-135.f, -80.f, 34.f), WheelMesh);
	SetupWheel(WheelRR, FVector(-135.f, 80.f, 34.f), WheelMesh);
}

void AHKCar::ConfigureMechanical()
{
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Move)
	{
		return;
	}

	Move->WheelSetups.SetNum(4);
	const FVector Offsets[4] = {
		FVector(135.f, -80.f, 34.f),
		FVector(135.f, 80.f, 34.f),
		FVector(-135.f, -80.f, 34.f),
		FVector(-135.f, 80.f, 34.f)};
	UClass* Classes[4] = {
		UHKWheelFront::StaticClass(),
		UHKWheelFront::StaticClass(),
		UHKWheelRear::StaticClass(),
		UHKWheelRear::StaticClass()};
	for (int32 Index = 0; Index < 4; ++Index)
	{
		Move->WheelSetups[Index].WheelClass = Classes[Index];
		Move->WheelSetups[Index].BoneName = TEXT("Root");
		Move->WheelSetups[Index].AdditionalOffset = Offsets[Index];
	}

	Move->Mass = 1450.f;
	Move->EngineSetup.MaxTorque = 520.f;
	Move->EngineSetup.MaxRPM = 6500.f;
	Move->EngineSetup.EngineIdleRPM = 900.f;
	if (FRichCurve* Torque = Move->EngineSetup.TorqueCurve.GetRichCurve())
	{
		Torque->Reset();
		Torque->AddKey(0.f, 0.45f);
		Torque->AddKey(1500.f, 0.75f);
		Torque->AddKey(3500.f, 1.0f);
		Torque->AddKey(6500.f, 0.7f);
	}

	Move->TransmissionSetup.bUseAutomaticGears = true;
	Move->TransmissionSetup.bUseAutoReverse = true;
	Move->TransmissionSetup.FinalRatio = 4.8f;
	Move->TransmissionSetup.ForwardGearRatios = {3.6f, 2.15f, 1.45f, 1.05f, 0.82f};
	Move->TransmissionSetup.ReverseGearRatios = {3.82f};
	Move->TransmissionSetup.ChangeUpRPM = 5500.f;
	Move->TransmissionSetup.ChangeDownRPM = 2200.f;
	Move->TransmissionSetup.GearChangeTime = 0.25f;

	Move->DifferentialSetup.DifferentialType = EVehicleDifferential::AllWheelDrive;
	Move->DifferentialSetup.FrontRearSplit = 0.5f;

	if (FRichCurve* Steering = Move->SteeringSetup.SteeringCurve.GetRichCurve())
	{
		Steering->Reset();
		Steering->AddKey(0.f, 1.f);
		Steering->AddKey(2000.f, 0.65f);
	}
}

UChaosWheeledVehicleMovementComponent* AHKCar::Movement() const
{
	return Cast<UChaosWheeledVehicleMovementComponent>(GetVehicleMovementComponent());
}

void AHKCar::SetupWheel(UStaticMeshComponent* Wheel, const FVector& Offset, UStaticMesh* WheelMesh)
{
	Wheel->SetupAttachment(GetMesh());
	Wheel->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Wheel->SetRelativeLocation(Offset);
	Wheel->SetRelativeRotation(FRotator(0.f, 0.f, 90.f));
	// Engine cylinder is 100 cm across and 100 cm tall. Radius 34 cm, width 20 cm.
	Wheel->SetRelativeScale3D(FVector(0.68f, 0.68f, 0.20f));
	if (WheelMesh)
	{
		Wheel->SetStaticMesh(WheelMesh);
	}
}

void AHKCar::BeginPlay()
{
	Super::BeginPlay();
	if (!GetMesh()->GetSkeletalMeshAsset())
	{
		if (USkeletalMesh* Skel = LoadObject<USkeletalMesh>(nullptr, TEXT("/Game/HK/Vehicles/SK_HKCar.SK_HKCar")))
		{
			UPhysicsAsset* Physics = LoadObject<UPhysicsAsset>(nullptr, TEXT("/Game/HK/Vehicles/SK_HKCar.PA_HKCar"));
			SetVehicleMesh(Skel, Physics);
		}
		else
		{
			UE_LOG(LogHK, Warning, TEXT("Car %s has no skeletal mesh. Bake the world before driving."), *GetName());
		}
	}
	else
	{
		PatchWheelBones();
	}

	GetMesh()->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	GetMesh()->SetCollisionObjectType(ECC_Vehicle);
	GetMesh()->SetCollisionResponseToAllChannels(ECR_Block);
	GetMesh()->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
	if (!bOccupied)
	{
		Park();
	}
}

void AHKCar::PatchWheelBones()
{
	USkeletalMesh* Skel = GetMesh()->GetSkeletalMeshAsset();
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Skel || !Move || Skel->GetRefSkeleton().GetNum() <= 0)
	{
		return;
	}
	const FName Bone = Skel->GetRefSkeleton().GetBoneName(0);
	bool bChanged = false;
	for (FChaosWheelSetup& Setup : Move->WheelSetups)
	{
		if (Setup.BoneName != Bone)
		{
			Setup.BoneName = Bone;
			bChanged = true;
		}
	}
	if (bChanged && GetWorld() && GetWorld()->IsGameWorld())
	{
		GetMesh()->RecreatePhysicsState();
	}
}

void AHKCar::SetVehicleMesh(USkeletalMesh* Mesh, UPhysicsAsset* PhysicsAsset)
{
	if (!Mesh)
	{
		return;
	}
	GetMesh()->SetSkeletalMeshAsset(Mesh);
	if (PhysicsAsset)
	{
		GetMesh()->SetPhysicsAsset(PhysicsAsset);
	}
	PatchWheelBones();
}

void AHKCar::ApplyPaint(UMaterialInterface* BodyMaterial, UMaterialInterface* WheelMaterial)
{
	if (BodyMaterial)
	{
		GetMesh()->SetMaterial(0, BodyMaterial);
	}
	if (WheelMaterial)
	{
		WheelFL->SetMaterial(0, WheelMaterial);
		WheelFR->SetMaterial(0, WheelMaterial);
		WheelRL->SetMaterial(0, WheelMaterial);
		WheelRR->SetMaterial(0, WheelMaterial);
	}
}

void AHKCar::PossessedBy(AController* NewController)
{
	Super::PossessedBy(NewController);
	bOccupied = true;
	GetMesh()->SetEnableGravity(true);
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->SetHandbrakeInput(0.f);
		Move->SetBrakeInput(0.f);
	}
}

void AHKCar::UnPossessed()
{
	bOccupied = false;
	Park();
	Super::UnPossessed();
}

void AHKCar::Park()
{
	VisualSteerDegrees = 0.f;
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->SetThrottleInput(0.f);
		Move->SetSteeringInput(0.f);
		Move->SetBrakeInput(1.f);
		Move->SetHandbrakeInput(1.f);
	}
}

void AHKCar::ApplyDrive(float ForwardAxis, float SteerAxis, bool bHandbrake)
{
	if (!bOccupied)
	{
		return;
	}
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Move)
	{
		return;
	}
	const float Axis = FMath::Clamp(ForwardAxis, -1.f, 1.f);
	Move->SetThrottleInput(FMath::Max(Axis, 0.f));
	Move->SetBrakeInput(FMath::Max(-Axis, 0.f));
	Move->SetSteeringInput(FMath::Clamp(SteerAxis, -1.f, 1.f));
	Move->SetHandbrakeInput(bHandbrake ? 1.f : 0.f);
	VisualSteerDegrees = FMath::Clamp(SteerAxis, -1.f, 1.f) * 36.f;
}

void AHKCar::StopPhysics()
{
	GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
	GetMesh()->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->SetThrottleInput(0.f);
		Move->SetSteeringInput(0.f);
		Move->SetBrakeInput(1.f);
		Move->StopMovementImmediately();
	}
}

void AHKCar::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bOccupied)
	{
		Park();
		HoldIfGroundUnloaded();
	}
	UpdateWheelVisuals(DeltaSeconds);
}

void AHKCar::HoldIfGroundUnloaded()
{
	// Cars are always loaded, but the streamed landscape and roads under a far car are not.
	// Without ground a parked car would fall to KillZ and be destroyed, so hold it in place.
	FHitResult Ground;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKCarGround), false, this);
	const FVector Start = GetActorLocation();
	const bool bGround = GetWorld()->LineTraceSingleByChannel(Ground, Start, Start - FVector(0.f, 0.f, 500.f), ECC_Visibility, Params);
	UPrimitiveComponent* Body = GetMesh();
	Body->SetEnableGravity(bGround);
	if (!bGround)
	{
		Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	}
}

void AHKCar::UpdateWheelVisuals(float DeltaSeconds)
{
	const float Speed = Movement() ? Movement()->GetForwardSpeed() : 0.f;
	WheelSpinDegrees = FMath::UnwindDegrees(WheelSpinDegrees + FMath::RadiansToDegrees(Speed / 34.f) * DeltaSeconds);
	const FRotator Front(WheelSpinDegrees, VisualSteerDegrees, 90.f);
	const FRotator Rear(WheelSpinDegrees, 0.f, 90.f);
	WheelFL->SetRelativeRotation(Front);
	WheelFR->SetRelativeRotation(Front);
	WheelRL->SetRelativeRotation(Rear);
	WheelRR->SetRelativeRotation(Rear);
}
