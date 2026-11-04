#include "HKCar.h"

#include "HKChaseCamera.h"
#include "HKFreeRoam.h"
#include "HKWheelFront.h"
#include "HKWheelRear.h"

#include "Camera/CameraComponent.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "ChaosVehicleWheel.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "TimerManager.h"
#include "GameFramework/Controller.h"
#include "GameFramework/SpringArmComponent.h"
#include "Materials/MaterialInterface.h"
#include "PhysicsEngine/BodyInstance.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "UObject/ConstructorHelpers.h"

static TAutoConsoleVariable<int32> CVarDriveAssist(
	TEXT("HK.DriveAssist"), 1,
	TEXT("1: arcade assist on top of Chaos (default). 0: raw Chaos with the class setup, for A/B comparison."));

static TAutoConsoleVariable<int32> CVarCarLot(
	TEXT("HK.CarLot"), 0,
	TEXT("Default 0 (off) until Sean decides. 1: park one car of each missing class beside the lot anchor (vehicles.json \"lot\") at runtime. 0: off."));

static TAutoConsoleVariable<float> CVarWheelSuspensionSign(
	TEXT("HK.CarWheelSuspension"), 1.f,
	TEXT("Visual wheel travel: Z offset = sign * GetSuspensionOffset(). Set -1 if wheels move the wrong way, 0 to freeze."));

namespace
{
	const FVector WheelXY[4] = {FVector(135.f, -80.f, 0.f), FVector(135.f, 80.f, 0.f), FVector(-135.f, -80.f, 0.f), FVector(-135.f, 80.f, 0.f)};
	// Top of the chassis box baked by HKBakeLibrary (Z 20..90 cm).
	constexpr float BodyTopCm = 90.f;
	constexpr float BodyBoxCentreZ = 55.f;
}

AHKCar::AHKCar()
{
	PrimaryActorTick.bCanEverTick = true;
	AutoPossessPlayer = EAutoReceiveInput::Disabled;
	// Only the player drives this; never let an AIController auto-possess it.
	AutoPossessAI = EAutoPossessAI::Disabled;
	AIControllerClass = nullptr;
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;

	ConfigureMechanical();

	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(GetMesh());
	CameraBoom->TargetArmLength = 560.f;
	CameraBoom->SocketOffset = FVector(0.f, 0.f, 150.f);
	// UHKChaseCamera owns the rotation; the control rotation only matters on foot.
	CameraBoom->bUsePawnControlRotation = false;
	CameraBoom->bEnableCameraLag = true;
	CameraBoom->CameraLagSpeed = 12.f;

	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	ChaseCamera = CreateDefaultSubobject<UHKChaseCamera>(TEXT("ChaseCamera"));

	// Per-class cabin block on the baked chassis box, painted with the body. Visual only.
	Cabin = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Cabin"));
	Cabin->SetupAttachment(GetMesh());
	Cabin->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Cabin->SetCanEverAffectNavigation(false);
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (Cube.Succeeded())
	{
		Cabin->SetStaticMesh(Cube.Object);
	}

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
		// Bakes before the wheel bones only have Root; PatchWheelBones falls back to it.
		Move->WheelSetups[Index].BoneName = WheelBoneNames()[Index];
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

	// The curve's X axis is mph; the assist owns speed-sensitive steering, so keep it flat.
	if (FRichCurve* Steering = Move->SteeringSetup.SteeringCurve.GetRichCurve())
	{
		Steering->Reset();
		Steering->AddKey(0.f, 1.f);
		Steering->AddKey(300.f, 1.f);
	}
	// The assist ramps throttle, brake and steering itself; let Chaos follow almost at once.
	for (FVehicleInputRateConfig* Rate : {&Move->ThrottleInputRate, &Move->BrakeInputRate, &Move->SteeringInputRate, &Move->HandbrakeInputRate})
	{
		Rate->RiseRate = 60.f;
		Rate->FallRate = 60.f;
	}
}

void AHKCar::SetCarClass(EHKCarClass NewClass)
{
	CarClass = NewClass;
	bClassOverride = true;
	ApplyHandling();
}

void AHKCar::ApplyHandling()
{
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Move)
	{
		return;
	}
	const FHKHandling& H = HKHandling::Get(CarClass);
	HKHandling::WriteWheelDefaults(CarClass);

	Move->Mass = H.Chassis.MassKg;
	Move->InertiaTensorScale = H.Chassis.InertiaScale;
	Move->DragCoefficient = H.Chassis.DragCoefficient;
	Move->DownforceCoefficient = 0.f; // the assist adds downforce
	Move->ChassisWidth = 190.f;
	Move->ChassisHeight = 70.f;
	// IdleBrakeInput is protected on UChaosVehicleMovementComponent in 5.8; set it through its UPROPERTY.
	static FFloatProperty* const IdleBrake = FindFProperty<FFloatProperty>(UChaosVehicleMovementComponent::StaticClass(), TEXT("IdleBrakeInput"));
	if (IdleBrake)
	{
		IdleBrake->SetPropertyValue_InContainer(Move, H.Chassis.IdleBrake);
	}

	FVehicleEngineConfig& Engine = Move->EngineSetup;
	Engine.MaxTorque = H.Engine.MaxTorqueNm;
	Engine.MaxRPM = H.Engine.MaxRPM;
	Engine.EngineIdleRPM = H.Engine.IdleRPM;
	Engine.EngineBrakeEffect = H.Engine.EngineBrake;
	Engine.EngineRevUpMOI = H.Engine.RevUpMOI;
	Engine.EngineRevDownRate = H.Engine.RevDownRate;
	if (FRichCurve* Torque = Engine.TorqueCurve.GetRichCurve())
	{
		Torque->Reset();
		for (int32 Index = 0; Index < FMath::Min(H.Engine.TorqueRpm.Num(), H.Engine.TorqueScale.Num()); ++Index)
		{
			Torque->AddKey(H.Engine.TorqueRpm[Index], H.Engine.TorqueScale[Index]);
		}
	}
	FVehicleTransmissionConfig& Gearbox = Move->TransmissionSetup;
	Gearbox.bUseAutomaticGears = true;
	Gearbox.bUseAutoReverse = true;
	Gearbox.FinalRatio = H.Engine.FinalRatio;
	if (H.Engine.Gears.Num() > 0)
	{
		Gearbox.ForwardGearRatios = H.Engine.Gears;
	}
	Gearbox.ReverseGearRatios = {H.Engine.ReverseGear};
	Gearbox.ChangeUpRPM = H.Engine.ChangeUpRPM;
	Gearbox.ChangeDownRPM = H.Engine.ChangeDownRPM;
	Gearbox.GearChangeTime = H.Engine.ShiftTime;
	Gearbox.TransmissionEfficiency = 0.9f;

	// Drivetrain: which axle Chaos drives, and the AWD front/rear torque split.
	switch (H.Chassis.Drive)
	{
	case EHKDrive::FWD:
		Move->DifferentialSetup.DifferentialType = EVehicleDifferential::FrontWheelDrive;
		break;
	case EHKDrive::AWD:
		Move->DifferentialSetup.DifferentialType = EVehicleDifferential::AllWheelDrive;
		break;
	default:
		Move->DifferentialSetup.DifferentialType = EVehicleDifferential::RearWheelDrive;
		break;
	}
	Move->DifferentialSetup.FrontRearSplit = H.Chassis.FrontRearSplit;

	WheelRadiusCm = H.Wheels.RadiusCm;
	for (int32 Index = 0; Index < Move->WheelSetups.Num() && Index < 4; ++Index)
	{
		Move->WheelSetups[Index].WheelClass = HKHandling::WheelClass(CarClass, Index < 2);
		Move->WheelSetups[Index].AdditionalOffset = WheelXY[Index] + FVector(0.f, 0.f, WheelRadiusCm);
		BaseFriction[Index] = Index < 2 ? H.Wheels.FrictionFront : H.Wheels.FrictionRear;
		AppliedFriction[Index] = BaseFriction[Index];
	}

	// Weight distribution: nudge the chassis box's centre of mass (box centre is 55 cm up).
	if (FBodyInstance* Body = GetMesh()->GetBodyInstance())
	{
		Body->COMNudge = FVector(H.Chassis.ComX, 0.f, H.Chassis.ComZ - BodyBoxCentreZ);
		if (Body->IsValidBodyInstance())
		{
			Body->UpdateMassProperties();
		}
	}

	if (GetWorld() && GetWorld()->IsGameWorld() && Move->IsRegistered())
	{
		// Chaos builds its vehicle and wheels from these settings when the physics state is
		// created, so rebuild it. The setters below cover any field the rebuild keeps.
		Move->RecreatePhysicsState();
		for (int32 Index = 0; Index < Move->GetNumWheels() && Index < 4; ++Index)
		{
			const bool bFront = Index < 2;
			Move->SetWheelFrictionMultiplier(Index, BaseFriction[Index]);
			Move->SetWheelMaxBrakeTorque(Index, bFront ? H.Wheels.BrakeTorqueFront : H.Wheels.BrakeTorqueRear);
			Move->SetWheelHandbrakeTorque(Index, bFront ? 0.f : H.Wheels.HandbrakeTorque);
			Move->SetWheelMaxSteerAngle(Index, bFront ? H.Assist.MaxSteerDeg : 0.f);
			Move->SetWheelRadius(Index, WheelRadiusCm);
			Move->SetABSEnabled(Index, H.Wheels.bABS);
			Move->SetTractionControlEnabled(Index, bFront ? H.Wheels.bTractionControlFront : H.Wheels.bTractionControlRear);
			Move->SetAffectedByEngine(Index, H.Chassis.Drive == EHKDrive::AWD || (bFront ? H.Chassis.Drive == EHKDrive::FWD : H.Chassis.Drive == EHKDrive::RWD));
		}
		if (H.Chassis.Drive == EHKDrive::AWD)
		{
			Move->SetDifferentialFrontRearSplit(H.Chassis.FrontRearSplit);
		}
		Move->SetMaxEngineTorque(H.Engine.MaxTorqueNm);
		Move->SetDragCoefficient(H.Chassis.DragCoefficient);
	}

	// Visuals: wheel size and the class cabin.
	const float Diameter = WheelRadiusCm * 2.f / 100.f;
	for (UStaticMeshComponent* Wheel : {WheelFL.Get(), WheelFR.Get(), WheelRL.Get(), WheelRR.Get()})
	{
		Wheel->SetRelativeScale3D(FVector(Diameter, Diameter, H.Wheels.WidthCm / 100.f));
	}
	const FHKBodyConfig& B = H.Body;
	Cabin->SetVisibility(B.CabinHeight > 1.f);
	Cabin->SetRelativeLocation(FVector(B.CabinX, 0.f, BodyTopCm + B.CabinHeight * 0.5f));
	Cabin->SetRelativeScale3D(FVector(B.CabinLength, B.CabinWidth, FMath::Max(B.CabinHeight, 1.f)) / 100.f);

	ChaseCamera->SetConfig(H.Camera);
	AssistMemory = hkdrive::Memory();
	bHandlingApplied = true;
}

const TArray<FName>& AHKCar::WheelBoneNames()
{
	static const TArray<FName> Names = {FName(TEXT("Wheel_FL")), FName(TEXT("Wheel_FR")), FName(TEXT("Wheel_RL")), FName(TEXT("Wheel_RR"))};
	return Names;
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
	// A pawn placed in a level is auto-possessed by an AIController by default
	// (APawn::AutoPossessAI = PlacedInWorld). That AI possession marked the vehicle
	// occupied, so F never found it. Maps baked before this fix still carry the
	// default, so drop any AI controller here too.
	if (AController* Existing = GetController(); Existing && !Existing->IsPlayerController())
	{
		Existing->UnPossess();
		Existing->Destroy();
	}
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

	EnableChassisPhysics();
	ChaseCamera->Init(CameraBoom, FollowCamera);
	if (!bClassOverride)
	{
		CarClass = HKHandling::ClassForCar(CarId());
	}
	ApplyHandling();
	if (!bOccupied)
	{
		Park();
		HoldIfGroundUnloaded();
	}

	const FHKCarLotConfig& Lot = HKHandling::Lot();
	if (Lot.bEnabled && CVarCarLot.GetValueOnGameThread() != 0 && !Lot.Anchor.IsNone() && CarId() == Lot.Anchor)
	{
		// The streamed road under the anchor may not be loaded yet; retry once a second.
		GetWorldTimerManager().SetTimer(LotTimer, this, &AHKCar::TrySpawnLot, 1.f, true, 0.5f);
	}
}

void AHKCar::TrySpawnLot()
{
	const FHKCarLotConfig& Lot = HKHandling::Lot();
	UWorld* World = GetWorld();
	if (!World || ++LotTries > 60)
	{
		GetWorldTimerManager().ClearTimer(LotTimer);
		UE_LOG(LogHK, Warning, TEXT("Car lot beside %s: no ground found in 60 s, skipped"), *CarId().ToString());
		return;
	}
	const FVector Origin = GetActorLocation();
	const FVector Fwd = FVector(GetActorForwardVector().X, GetActorForwardVector().Y, 0.f).GetSafeNormal();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKCarLot), false, this);
	FHitResult Anchor;
	if (!World->LineTraceSingleByChannel(Anchor, Origin + FVector(0, 0, 100), Origin - FVector(0, 0, 500), ECC_Visibility, Params))
	{
		return; // ground not streamed in yet
	}
	GetWorldTimerManager().ClearTimer(LotTimer);
	// Slots in line with the anchor: ahead, behind, two ahead, two behind ...
	int32 Slot = 0;
	for (int32 Index = 0; Index < Lot.Classes.Num(); ++Index)
	{
		bool bPlaced = false;
		while (!bPlaced && Slot < 8)
		{
			const int32 Step = Slot / 2 + 1;
			const float Sign = Slot % 2 == 0 ? 1.f : -1.f;
			++Slot;
			const FVector Probe = Origin + Fwd * (Sign * Step * Lot.SpacingM * 100.f);
			FHitResult Ground;
			if (!World->LineTraceSingleByChannel(Ground, Probe + FVector(0, 0, 300), Probe - FVector(0, 0, 600), ECC_Visibility, Params)
				|| FMath::Abs(Ground.ImpactPoint.Z - Anchor.ImpactPoint.Z) > 150.f || Ground.ImpactNormal.Z < 0.9f)
			{
				continue;
			}
			const FVector Where = Ground.ImpactPoint + FVector(0, 0, 2);
			const FCollisionShape Box = FCollisionShape::MakeBox(FVector(230.f, 100.f, 60.f));
			if (World->OverlapAnyTestByChannel(Where + FVector(0, 0, 90), FQuat(GetActorRotation()), ECC_Vehicle, Box, Params))
			{
				continue;
			}
			const EHKCarClass Class = Lot.Classes[Index];
			const FName Id(*FString::Printf(TEXT("%s_lot_%s"), *CarId().ToString(), HKHandling::ClassName(Class)));
			if (SpawnCar(World, Class, FTransform(FRotator(0, GetActorRotation().Yaw, 0), Where), Id, 3 + Index * 2))
			{
				UE_LOG(LogHK, Display, TEXT("Car lot: %s parked %.0f m from %s"), *Id.ToString(), Step * Lot.SpacingM, *CarId().ToString());
				bPlaced = true;
			}
		}
		if (!bPlaced)
		{
			UE_LOG(LogHK, Warning, TEXT("Car lot: no free flat slot for %s beside %s"), HKHandling::ClassName(Lot.Classes[Index]), *CarId().ToString());
		}
	}
}

AHKCar* AHKCar::SpawnCar(UWorld* World, EHKCarClass Class, const FTransform& Where, FName Id, int32 PaintIndex)
{
	if (!World)
	{
		return nullptr;
	}
	AHKCar* Car = World->SpawnActorDeferred<AHKCar>(AHKCar::StaticClass(), Where, nullptr, nullptr, ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn);
	if (!Car)
	{
		return nullptr;
	}
	Car->CarClass = Class;
	Car->bClassOverride = true;
	if (!Id.IsNone())
	{
		Car->Tags.Add(Id);
	}
	Car->FinishSpawning(Where);
	const int32 Paint = ((PaintIndex % 8) + 8) % 8;
	UMaterialInterface* Body = LoadObject<UMaterialInterface>(nullptr, *FString::Printf(TEXT("/Game/HK/Vehicles/MI_Car_%d.MI_Car_%d"), Paint, Paint));
	UMaterialInterface* Wheel = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/HK/Vehicles/MI_Wheel.MI_Wheel"));
	Car->ApplyPaint(Body, Wheel);
	return Car;
}

void AHKCar::EnableChassisPhysics()
{
	USkeletalMeshComponent* Body = GetMesh();
	Body->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	Body->SetCollisionObjectType(ECC_Vehicle);
	Body->SetCollisionResponseToAllChannels(ECR_Block);
	Body->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
	// Chaos FixupSkeletalMesh sets every physics body that sits on a wheel bone to ignore all
	// channels and stop simulating. Older bakes put all four wheels on Root, the chassis bone, so
	// restore the chassis body itself, not only the component default.
	for (FBodyInstance* Instance : Body->Bodies)
	{
		if (Instance)
		{
			Instance->SetResponseToAllChannels(ECR_Block);
			Instance->SetResponseToChannel(ECC_Camera, ECR_Ignore);
		}
	}
	// AWheeledVehiclePawn leaves the mesh kinematic (bSimulatePhysics = false). Chaos only moves a
	// simulating chassis, so without this throttle does nothing and the car sits at 0 km/h.
	Body->SetSimulatePhysics(true);
}

void AHKCar::PatchWheelBones()
{
	USkeletalMesh* Skel = GetMesh()->GetSkeletalMeshAsset();
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Skel || !Move || Skel->GetRefSkeleton().GetNum() <= 0)
	{
		return;
	}
	const FReferenceSkeleton& Ref = Skel->GetRefSkeleton();
	const TArray<FName>& Wheels = WheelBoneNames();
	bool bWheelBones = true;
	for (const FName& Wheel : Wheels)
	{
		bWheelBones &= Ref.FindBoneIndex(Wheel) != INDEX_NONE;
	}
	if (!bWheelBones)
	{
		UE_LOG(LogHK, Warning, TEXT("Car %s: skeleton has no wheel bones, using %s. Re-bake the world."), *GetName(), *Ref.GetBoneName(0).ToString());
	}
	bool bChanged = false;
	for (int32 Index = 0; Index < Move->WheelSetups.Num(); ++Index)
	{
		const FName Bone = bWheelBones && Wheels.IsValidIndex(Index) ? Wheels[Index] : Ref.GetBoneName(0);
		if (Move->WheelSetups[Index].BoneName != Bone)
		{
			Move->WheelSetups[Index].BoneName = Bone;
			bChanged = true;
		}
	}
	if (bChanged && GetWorld() && GetWorld()->IsGameWorld())
	{
		GetMesh()->RecreatePhysicsState();
	}
}

void AHKCar::SetVehicleMesh(USkeletalMesh* NewMesh, UPhysicsAsset* PhysicsAsset)
{
	if (!NewMesh)
	{
		return;
	}
	GetMesh()->SetSkeletalMeshAsset(NewMesh);
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
		Cabin->SetMaterial(0, BodyMaterial);
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
	if (!NewController || !NewController->IsPlayerController())
	{
		return;
	}
	bOccupied = true;
	GetMesh()->SetEnableGravity(true);
	// No tunnelling through thin road meshes at 250 km/h.
	GetMesh()->SetUseCCD(true);
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->SetHandbrakeInput(false);
		Move->SetBrakeInput(0.f);
	}
	DriverInput = hkdrive::Input();
	AssistMemory = hkdrive::Memory();
	ChaseCamera->Snap();
}

void AHKCar::UnPossessed()
{
	bOccupied = false;
	GetMesh()->SetUseCCD(false);
	DriverInput = hkdrive::Input();
	Park();
	Super::UnPossessed();
}

void AHKCar::BeginTestDrive()
{
	bOccupied = true;
	bTestDrive = true;
	GetMesh()->SetEnableGravity(true);
	GetMesh()->SetUseCCD(true);
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		// No controller drives a test car; Chaos ignores inputs without one by default.
		Move->SetRequiresControllerForInputs(false);
	}
	Autopilot = hkdrive::Input();
	ChaseCamera->Snap();
}

void AHKCar::EndTestDrive()
{
	bTestDrive = false;
	bOccupied = false;
	Autopilot.Reset();
	Park();
}

void AHKCar::ResetMotion(const FVector& Location, float YawDeg)
{
	UPrimitiveComponent* Body = GetMesh();
	SetActorLocationAndRotation(Location, FRotator(0.f, YawDeg, 0.f), false, nullptr, ETeleportType::ResetPhysics);
	Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->ResetVehicle();
	}
	AssistMemory = hkdrive::Memory();
	bHasPrevVelocity = false;
	bHasPrevWheelAngle = false;
	ChaseCamera->Snap();
}

void AHKCar::AddCameraLook(float YawDeg, float PitchDeg)
{
	ChaseCamera->AddLook(YawDeg, PitchDeg);
}

void AHKCar::Park()
{
	VisualSteerDegrees = 0.f;
	if (UChaosWheeledVehicleMovementComponent* Move = Movement())
	{
		Move->SetThrottleInput(0.f);
		Move->SetSteeringInput(0.f);
		Move->SetBrakeInput(1.f);
		Move->SetHandbrakeInput(true);
	}
}

void AHKCar::ApplyDrive(float ForwardAxis, float SteerAxis, bool bHandbrake)
{
	if (!bOccupied)
	{
		return;
	}
	// Stored; DriveTick shapes it through the assist and hands it to Chaos every frame.
	const float Axis = FMath::Clamp(ForwardAxis, -1.f, 1.f);
	DriverInput.Throttle = FMath::Max(Axis, 0.f);
	DriverInput.Brake = FMath::Max(-Axis, 0.f);
	DriverInput.Steer = FMath::Clamp(SteerAxis, -1.f, 1.f);
	DriverInput.bHandbrake = bHandbrake;
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
	UpdateTelemetry(DeltaSeconds);
	if (!bOccupied)
	{
		Park();
		HoldIfGroundUnloaded();
	}
	else
	{
		DriveTick(DeltaSeconds);
	}
	SelfRightIfFlipped(DeltaSeconds);
	UpdateWheelVisuals(DeltaSeconds);
}

void AHKCar::UpdateTelemetry(float DeltaSeconds)
{
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	UPrimitiveComponent* Body = GetMesh();
	const FVector Fwd = GetActorForwardVector();
	const FVector Right = GetActorRightVector();
	const FVector Up = GetActorUpVector();
	const FVector Velocity = Body->GetPhysicsLinearVelocity();
	const FVector Omega = Body->GetPhysicsAngularVelocityInRadians();
	FHKCarTelemetry& T = Telem;
	T.SpeedFwd = FVector::DotProduct(Velocity, Fwd) / 100.f;
	T.Kmh = Velocity.Size() * 0.036f;
	T.YawRateDeg = FMath::RadiansToDegrees(FVector::DotProduct(Omega, Up));
	T.RollDeg = FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(-Right.Z, -1.f, 1.f)));
	T.PitchDeg = FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(Fwd.Z, -1.f, 1.f)));
	if (DeltaSeconds > 0.f && bHasPrevVelocity)
	{
		const FVector Accel = (Velocity - PrevVelocity) / DeltaSeconds / 981.f;
		T.LatG = FVector::DotProduct(Accel, Right);
		T.LongG = FVector::DotProduct(Accel, Fwd);
		T.VertG = FVector::DotProduct(Accel, Up);
	}
	PrevVelocity = Velocity;
	bHasPrevVelocity = true;
	if (!Move)
	{
		return;
	}
	if (!Move->PhysicsVehicleOutput())
	{
		return; // the Chaos vehicle is not built yet
	}
	T.Gear = Move->GetCurrentGear();
	T.Rpm = Move->GetEngineRotationSpeed();
	int32 Grounded = 0;
	int32 Locked = 0;
	for (int32 Index = 0; Index < Move->Wheels.Num() && Index < 4; ++Index)
	{
		UChaosVehicleWheel* Wheel = Move->Wheels[Index];
		if (!Wheel)
		{
			continue;
		}
		Grounded += Wheel->IsInAir() ? 0 : 1;
		// Spin from the change of the wheel's rotation angle (deg); fine up to ~150 km/h at 60 fps.
		const float Angle = Wheel->GetRotationAngle();
		if (bHasPrevWheelAngle && DeltaSeconds > 0.f)
		{
			const float Spin = FMath::DegreesToRadians(FMath::Abs(FMath::FindDeltaAngleDegrees(PrevWheelAngle[Index], Angle))) / DeltaSeconds;
			const float Surface = Spin * WheelRadiusCm / 100.f;
			Locked += (FMath::Abs(T.SpeedFwd) > 3.f && Surface < 0.2f * FMath::Abs(T.SpeedFwd)) ? 1 : 0;
		}
		PrevWheelAngle[Index] = Angle;
	}
	bHasPrevWheelAngle = true;
	T.LockedWheels = Locked;
	T.bGrounded = Grounded > 0;

	// Surface: landscape counts as off-road, any road or building mesh as road.
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKCarSurface), false, this);
	const FVector Start = GetActorLocation() + Up * 50.f;
	T.bOffroad = GetWorld()->LineTraceSingleByChannel(Hit, Start, Start - Up * 250.f, ECC_Visibility, Params)
		&& Hit.GetActor() && Hit.GetActor()->GetClass()->GetName().Contains(TEXT("Landscape"));
}

void AHKCar::DriveTick(float DeltaSeconds)
{
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	if (!Move || DeltaSeconds <= 0.f)
	{
		return;
	}
	const FHKHandling& H = HKHandling::Get(CarClass);
	const hkdrive::Input In = Autopilot.IsSet() ? Autopilot.GetValue() : DriverInput;
	if (CVarDriveAssist.GetValueOnGameThread() == 0)
	{
		Move->SetThrottleInput(In.Throttle);
		Move->SetBrakeInput(In.Brake);
		Move->SetSteeringInput(In.Steer);
		Move->SetHandbrakeInput(In.bHandbrake);
		VisualSteerDegrees = In.Steer * H.Assist.MaxSteerDeg;
		Telem.Assist = hkdrive::Output();
		return;
	}

	UPrimitiveComponent* Body = GetMesh();
	const FVector Fwd = GetActorForwardVector();
	const FVector Right = GetActorRightVector();
	const FVector Up = GetActorUpVector();
	const FVector Velocity = Body->GetPhysicsLinearVelocity();
	const FVector Omega = Body->GetPhysicsAngularVelocityInRadians();

	hkdrive::State S;
	S.SpeedFwd = FVector::DotProduct(Velocity, Fwd) / 100.f;
	S.VelLat = FVector::DotProduct(Velocity, Right) / 100.f;
	// Rotation about +Up turns Fwd toward Right (nose right); about -Fwd puts the right side down.
	S.YawRate = FVector::DotProduct(Omega, Up);
	S.RollDeg = Telem.RollDeg;
	S.RollRate = FVector::DotProduct(Omega, -Fwd);
	S.PitchRate = FVector::DotProduct(Omega, Right);
	S.bGrounded = Telem.bGrounded;
	S.bOffroad = Telem.bOffroad;

	const hkdrive::Output Out = hkdrive::Step(H.Assist, S, In, AssistMemory, DeltaSeconds);
	Telem.Assist = Out;
	Telem.SlipDeg = Out.SlipDeg;

	Move->SetThrottleInput(Out.Throttle);
	Move->SetBrakeInput(Out.Brake);
	Move->SetSteeringInput(Out.Steer);
	Move->SetHandbrakeInput(Out.Handbrake > 0.5f);
	VisualSteerDegrees = Out.Steer * H.Assist.MaxSteerDeg;

	for (int32 Index = 0; Index < Move->GetNumWheels() && Index < 4; ++Index)
	{
		const float Target = BaseFriction[Index] * (Index < 2 ? Out.FrontGrip : Out.RearGrip);
		if (FMath::Abs(Target - AppliedFriction[Index]) > 0.01f * BaseFriction[Index])
		{
			Move->SetWheelFrictionMultiplier(Index, Target);
			AppliedFriction[Index] = Target;
		}
	}

	// Accelerations, so mass and inertia do not matter (bAccelChange).
	const FVector Torque = Up * Out.YawAccel - Fwd * Out.RollAccel + Right * Out.PitchAccel;
	if (!Torque.IsNearlyZero(1e-4))
	{
		Body->AddTorqueInRadians(Torque, NAME_None, true);
	}
	const FVector Force = (Right * Out.LatAccel - Up * Out.DownAccel) * 100.f;
	if (!Force.IsNearlyZero(1e-3))
	{
		Body->AddForce(Force, NAME_None, true);
	}
}

void AHKCar::SelfRightIfFlipped(float DeltaSeconds)
{
	// On its side or roof and almost stopped for FlipHoldSeconds: put it back on its wheels,
	// same place and heading, 1 m up so it drops onto the road.
	const bool bFlipped = GetActorUpVector().Z < 0.3f;
	const bool bSlow = GetVelocity().SizeSquared() < FMath::Square(150.f);
	FlippedSeconds = (bFlipped && bSlow) ? FlippedSeconds + DeltaSeconds : 0.f;
	if (FlippedSeconds < FlipHoldSeconds)
	{
		return;
	}
	FlippedSeconds = 0.f;
	const FVector Forward = GetActorForwardVector();
	const float Yaw = FMath::Abs(Forward.Z) < 0.99f ? FMath::RadiansToDegrees(FMath::Atan2(Forward.Y, Forward.X)) : GetActorRotation().Yaw;
	UPrimitiveComponent* Body = GetMesh();
	Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
	SetActorLocationAndRotation(GetActorLocation() + FVector(0.f, 0.f, 100.f), FRotator(0.f, Yaw, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
	UE_LOG(LogHK, Display, TEXT("Car %s was flipped; set back on its wheels"), *GetName());
}

void AHKCar::HoldIfGroundUnloaded()
{
	// Cars are always loaded, but the streamed landscape and roads under a far car are not.
	// Without ground a parked car would fall to KillZ and be destroyed, so hold it in place.
	FHitResult Ground;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKCarGround), false, this);
	// The actor origin is the wheel contact plane, 2 cm above the road at spawn. Start the trace
	// 1 m higher so a slightly sunk or pitched car still finds the road under it.
	const FVector Start = GetActorLocation() + FVector(0.f, 0.f, 100.f);
	const bool bGround = GetWorld()->LineTraceSingleByChannel(Ground, Start, Start - FVector(0.f, 0.f, 600.f), ECC_Visibility, Params);
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
	UChaosWheeledVehicleMovementComponent* Move = Movement();
	const float Speed = Move ? Move->GetForwardSpeed() : 0.f;
	WheelSpinDegrees = FMath::UnwindDegrees(WheelSpinDegrees + FMath::RadiansToDegrees(Speed / WheelRadiusCm) * DeltaSeconds);
	const FRotator Front(WheelSpinDegrees, VisualSteerDegrees, 90.f);
	const FRotator Rear(WheelSpinDegrees, 0.f, 90.f);
	UStaticMeshComponent* Visuals[4] = {WheelFL, WheelFR, WheelRL, WheelRR};
	const float Sign = CVarWheelSuspensionSign.GetValueOnGameThread();
	for (int32 Index = 0; Index < 4; ++Index)
	{
		Visuals[Index]->SetRelativeRotation(Index < 2 ? Front : Rear);
		float Travel = 0.f;
		if (Move && Move->PhysicsVehicleOutput() && Move->Wheels.IsValidIndex(Index) && Move->Wheels[Index] && Sign != 0.f && bHandlingApplied)
		{
			Travel = FMath::Clamp(Sign * Move->Wheels[Index]->GetSuspensionOffset(), -30.f, 30.f);
		}
		Visuals[Index]->SetRelativeLocation(WheelXY[Index] + FVector(0.f, 0.f, WheelRadiusCm + Travel));
	}
}
