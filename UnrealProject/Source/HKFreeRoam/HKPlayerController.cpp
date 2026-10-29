#include "HKPlayerController.h"

#include "HKAxes.h"
#include "HKCar.h"
#include "HKFreeRoam.h"
#include "HKFreeRoamCharacter.h"
#include "HKFreeRoamHUD.h"
#include "HKGameInstance.h"
#include "HKHelicopter.h"
#include "HKRideable.h"
#include "HKTypes.h"

#include "Camera/PlayerCameraManager.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/Engine.h"
#include "Engine/LocalPlayer.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "InputCoreTypes.h"
#include "InputAction.h"
#include "InputActionValue.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "Kismet/GameplayStatics.h"

AHKPlayerController::AHKPlayerController()
{
	bShowMouseCursor = false;
	bEnableClickEvents = true;
	bEnableMouseOverEvents = true;
	// UE5 renamed these members to *_DEPRECATED. The setters keep the legacy scale at 1 so
	// OnLook owns sensitivity and sign even while bEnableLegacyInputScales is on (the default).
	SetDeprecatedInputYawScale(1.f);
	SetDeprecatedInputPitchScale(1.f);
	BuildInput();
}

void AHKPlayerController::AddAxisKey(UInputMappingContext* Context, UInputAction* Action, FKey Key, bool bNegate, bool bSwizzleToY)
{
	FEnhancedActionKeyMapping& Mapping = Context->MapKey(Action, Key);
	if (bSwizzleToY)
	{
		UInputModifierSwizzleAxis* Swizzle = NewObject<UInputModifierSwizzleAxis>(Context);
		Swizzle->Order = EInputAxisSwizzle::YXZ;
		Mapping.Modifiers.Add(Swizzle);
	}
	if (bNegate)
	{
		Mapping.Modifiers.Add(NewObject<UInputModifierNegate>(Context));
	}
}

void AHKPlayerController::MapMoveKeys(UInputMappingContext* Context, UInputAction* Action)
{
	AddAxisKey(Context, Action, EKeys::W, false, true);
	AddAxisKey(Context, Action, EKeys::S, true, true);
	AddAxisKey(Context, Action, EKeys::D, false, false);
	AddAxisKey(Context, Action, EKeys::A, true, false);
}

void AHKPlayerController::MapCyclicKeys(UInputMappingContext* Context, UInputAction* Action)
{
	AddAxisKey(Context, Action, EKeys::Up, false, true);
	AddAxisKey(Context, Action, EKeys::Down, true, true);
	AddAxisKey(Context, Action, EKeys::I, false, true);
	AddAxisKey(Context, Action, EKeys::K, true, true);
	AddAxisKey(Context, Action, EKeys::Right, false, false);
	AddAxisKey(Context, Action, EKeys::Left, true, false);
	AddAxisKey(Context, Action, EKeys::L, false, false);
	AddAxisKey(Context, Action, EKeys::J, true, false);
}

void AHKPlayerController::BuildInput()
{
	MoveAction = NewObject<UInputAction>(this, TEXT("IA_Move"));
	MoveAction->ValueType = EInputActionValueType::Axis2D;
	LookAction = NewObject<UInputAction>(this, TEXT("IA_Look"));
	LookAction->ValueType = EInputActionValueType::Axis2D;
	JumpAction = NewObject<UInputAction>(this, TEXT("IA_Jump"));
	JumpAction->ValueType = EInputActionValueType::Boolean;
	SprintAction = NewObject<UInputAction>(this, TEXT("IA_Sprint"));
	SprintAction->ValueType = EInputActionValueType::Boolean;
	InteractAction = NewObject<UInputAction>(this, TEXT("IA_Interact"));
	InteractAction->ValueType = EInputActionValueType::Boolean;
	HandbrakeAction = NewObject<UInputAction>(this, TEXT("IA_Handbrake"));
	HandbrakeAction->ValueType = EInputActionValueType::Boolean;
	YawAction = NewObject<UInputAction>(this, TEXT("IA_Yaw"));
	YawAction->ValueType = EInputActionValueType::Axis1D;
	CyclicAction = NewObject<UInputAction>(this, TEXT("IA_Cyclic"));
	CyclicAction->ValueType = EInputActionValueType::Axis2D;
	CollectiveUpAction = NewObject<UInputAction>(this, TEXT("IA_CollectiveUp"));
	CollectiveUpAction->ValueType = EInputActionValueType::Boolean;
	CollectiveDownAction = NewObject<UInputAction>(this, TEXT("IA_CollectiveDown"));
	CollectiveDownAction->ValueType = EInputActionValueType::Boolean;
	HoverAction = NewObject<UInputAction>(this, TEXT("IA_Hover"));
	HoverAction->ValueType = EInputActionValueType::Boolean;
	MapAction = NewObject<UInputAction>(this, TEXT("IA_Map"));
	MapAction->ValueType = EInputActionValueType::Boolean;
	HelpAction = NewObject<UInputAction>(this, TEXT("IA_Help"));
	HelpAction->ValueType = EInputActionValueType::Boolean;
	QualityAction = NewObject<UInputAction>(this, TEXT("IA_Quality"));
	QualityAction->ValueType = EInputActionValueType::Boolean;

	FootContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Foot"));
	CarContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Car"));
	HeliContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Heli"));
	AlwaysContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Always"));

	MapMoveKeys(FootContext, MoveAction);
	FootContext->MapKey(JumpAction, EKeys::SpaceBar);
	FootContext->MapKey(SprintAction, EKeys::LeftShift);
	FootContext->MapKey(SprintAction, EKeys::RightShift);

	MapMoveKeys(CarContext, MoveAction);
	CarContext->MapKey(HandbrakeAction, EKeys::SpaceBar);

	AddAxisKey(HeliContext, YawAction, EKeys::D, false, false);
	AddAxisKey(HeliContext, YawAction, EKeys::A, true, false);
	MapCyclicKeys(HeliContext, CyclicAction);
	HeliContext->MapKey(CollectiveUpAction, EKeys::E);
	HeliContext->MapKey(CollectiveDownAction, EKeys::Q);
	HeliContext->MapKey(HoverAction, EKeys::H);

	FEnhancedActionKeyMapping& Look = AlwaysContext->MapKey(LookAction, EKeys::Mouse2D);
	UInputModifierScalar* Scale = NewObject<UInputModifierScalar>(AlwaysContext);
	Scale->Scalar = FVector(0.08, 0.08, 1.0);
	Look.Modifiers.Add(Scale);
	AlwaysContext->MapKey(InteractAction, EKeys::F);
	AlwaysContext->MapKey(MapAction, EKeys::M);
	AlwaysContext->MapKey(HelpAction, EKeys::F1);
	AlwaysContext->MapKey(QualityAction, EKeys::F9);
}

void AHKPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();
	UEnhancedInputComponent* Input = Cast<UEnhancedInputComponent>(InputComponent);
	if (!Input)
	{
		UE_LOG(LogHK, Error, TEXT("Enhanced Input component is missing. DefaultInput.ini must select EnhancedPlayerInput."));
		return;
	}
	Input->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AHKPlayerController::OnMove);
	Input->BindAction(MoveAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnMoveCompleted);
	Input->BindAction(LookAction, ETriggerEvent::Triggered, this, &AHKPlayerController::OnLook);
	Input->BindAction(JumpAction, ETriggerEvent::Started, this, &AHKPlayerController::OnJumpStarted);
	Input->BindAction(JumpAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnJumpCompleted);
	Input->BindAction(SprintAction, ETriggerEvent::Started, this, &AHKPlayerController::OnSprintStarted);
	Input->BindAction(SprintAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnSprintCompleted);
	Input->BindAction(InteractAction, ETriggerEvent::Started, this, &AHKPlayerController::OnInteract);
	Input->BindAction(HandbrakeAction, ETriggerEvent::Started, this, &AHKPlayerController::OnHandbrakeStarted);
	Input->BindAction(HandbrakeAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnHandbrakeCompleted);
	Input->BindAction(YawAction, ETriggerEvent::Triggered, this, &AHKPlayerController::OnYaw);
	Input->BindAction(YawAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnYawCompleted);
	Input->BindAction(CyclicAction, ETriggerEvent::Triggered, this, &AHKPlayerController::OnCyclic);
	Input->BindAction(CyclicAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnCyclicCompleted);
	Input->BindAction(CollectiveUpAction, ETriggerEvent::Started, this, &AHKPlayerController::OnCollectiveUpStarted);
	Input->BindAction(CollectiveUpAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnCollectiveUpCompleted);
	Input->BindAction(CollectiveDownAction, ETriggerEvent::Started, this, &AHKPlayerController::OnCollectiveDownStarted);
	Input->BindAction(CollectiveDownAction, ETriggerEvent::Completed, this, &AHKPlayerController::OnCollectiveDownCompleted);
	Input->BindAction(HoverAction, ETriggerEvent::Started, this, &AHKPlayerController::OnHover);
	Input->BindAction(MapAction, ETriggerEvent::Started, this, &AHKPlayerController::OnToggleMap);
	Input->BindAction(HelpAction, ETriggerEvent::Started, this, &AHKPlayerController::OnToggleHelp);
	Input->BindAction(QualityAction, ETriggerEvent::Started, this, &AHKPlayerController::OnCycleQuality);
}

void AHKPlayerController::BeginPlay()
{
	Super::BeginPlay();
	if (PlayerCameraManager)
	{
		PlayerCameraManager->ViewPitchMin = -80.f;
		PlayerCameraManager->ViewPitchMax = 75.f;
	}
	EnsureMappings();
	ApplyQuality(QualityIndex);
}

void AHKPlayerController::EnsureMappings()
{
	ULocalPlayer* Local = GetLocalPlayer();
	if (!Local)
	{
		return;
	}
	UEnhancedInputLocalPlayerSubsystem* Subsystem = Local->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>();
	if (!Subsystem)
	{
		return;
	}
	Subsystem->ClearAllMappings();
	Subsystem->AddMappingContext(AlwaysContext, 1);
	if (Cast<AHKCar>(GetPawn()))
	{
		Subsystem->AddMappingContext(CarContext, 0);
	}
	else if (Cast<AHKHelicopter>(GetPawn()))
	{
		Subsystem->AddMappingContext(HeliContext, 0);
	}
	else
	{
		Subsystem->AddMappingContext(FootContext, 0);
	}
	bMappingsApplied = true;
}

void AHKPlayerController::OnPossess(APawn* InPawn)
{
	AActor* PreviousView = PlayerCameraManager ? PlayerCameraManager->GetViewTarget() : nullptr;
	const bool bBlend = GetPawn() && GetPawn() != InPawn && PreviousView && PreviousView != InPawn;
	Super::OnPossess(InPawn);
	if (bBlend && PlayerCameraManager)
	{
		PlayerCameraManager->SetViewTarget(PreviousView);
		SetViewTargetWithBlend(InPawn, 0.6f, EViewTargetBlendFunction::VTBlend_Cubic);
	}
	DriveAxis = FVector2D::ZeroVector;
	bHandbrakeHeld = false;
	EnsureMappings();
}

void AHKPlayerController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);
	if (!bMappingsApplied)
	{
		EnsureMappings();
	}
	TryHotkeys();
	TryMapClick();
}

void AHKPlayerController::OnMove(const FInputActionValue& Value)
{
	const FVector2D Axis = Value.Get<FVector2D>();
	if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
	{
		const FRotator Yaw(0.f, GetControlRotation().Yaw, 0.f);
		Walker->AddMovementInput(FRotationMatrix(Yaw).GetUnitAxis(EAxis::X), Axis.Y);
		Walker->AddMovementInput(FRotationMatrix(Yaw).GetUnitAxis(EAxis::Y), Axis.X);
		return;
	}
	DriveAxis = Axis;
	PushDrive();
}

void AHKPlayerController::OnMoveCompleted(const FInputActionValue& Value)
{
	DriveAxis = FVector2D::ZeroVector;
	PushDrive();
}

void AHKPlayerController::PushDrive()
{
	if (AHKCar* Car = Cast<AHKCar>(GetPawn()))
	{
		Car->ApplyDrive(DriveAxis.Y, DriveAxis.X, bHandbrakeHeld);
	}
}

void AHKPlayerController::OnLook(const FInputActionValue& Value)
{
	if (bMapOpen)
	{
		return;
	}
	const FVector2D Look = Value.Get<FVector2D>();
	// Mouse2D +Y follows the screen and points downward, so pitch is inverted.
	AddYawInput(Look.X);
	AddPitchInput(-Look.Y);
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetMouseCyclic(FMath::Clamp(Look.X * 0.35f, -1.f, 1.f), FMath::Clamp(-Look.Y * 0.35f, -1.f, 1.f));
	}
}

void AHKPlayerController::OnJumpStarted()
{
	if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
	{
		Walker->Jump();
	}
}

void AHKPlayerController::OnJumpCompleted()
{
	if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
	{
		Walker->StopJumping();
	}
}

void AHKPlayerController::OnSprintStarted()
{
	if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
	{
		Walker->SetSprinting(true);
	}
}

void AHKPlayerController::OnSprintCompleted()
{
	if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
	{
		Walker->SetSprinting(false);
	}
}

void AHKPlayerController::OnHandbrakeStarted()
{
	bHandbrakeHeld = true;
	PushDrive();
}

void AHKPlayerController::OnHandbrakeCompleted()
{
	bHandbrakeHeld = false;
	PushDrive();
}

void AHKPlayerController::OnYaw(const FInputActionValue& Value)
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetYawInput(Value.Get<float>());
	}
}

void AHKPlayerController::OnYawCompleted(const FInputActionValue& Value)
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetYawInput(0.f);
	}
}

void AHKPlayerController::OnCyclic(const FInputActionValue& Value)
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		const FVector2D Axis = Value.Get<FVector2D>();
		Heli->SetKeyCyclic(FMath::Clamp(Axis.X, -1.f, 1.f), FMath::Clamp(Axis.Y, -1.f, 1.f));
	}
}

void AHKPlayerController::OnCyclicCompleted(const FInputActionValue& Value)
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetKeyCyclic(0.f, 0.f);
	}
}

void AHKPlayerController::OnCollectiveUpStarted()
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetCollectiveUp(true);
	}
}

void AHKPlayerController::OnCollectiveUpCompleted()
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetCollectiveUp(false);
	}
}

void AHKPlayerController::OnCollectiveDownStarted()
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetCollectiveDown(true);
	}
}

void AHKPlayerController::OnCollectiveDownCompleted()
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->SetCollectiveDown(false);
	}
}

void AHKPlayerController::OnHover()
{
	if (AHKHelicopter* Heli = Cast<AHKHelicopter>(GetPawn()))
	{
		Heli->ToggleHoverAssist();
	}
}

void AHKPlayerController::OnToggleMap()
{
	bMapOpen = !bMapOpen;
	bShowMouseCursor = bMapOpen;
	if (bMapOpen)
	{
		FInputModeGameAndUI Mode;
		Mode.SetHideCursorDuringCapture(false);
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		SetInputMode(Mode);
	}
	else
	{
		SetInputMode(FInputModeGameOnly());
	}
}

void AHKPlayerController::OnToggleHelp()
{
	bShowHelp = !bShowHelp;
}

void AHKPlayerController::OnCycleQuality()
{
	ApplyQuality(QualityIndex == 0 ? 1 : 0);
}

void AHKPlayerController::ApplyQuality(int32 Index)
{
	QualityIndex = Index == 0 ? 0 : 1;
	if (!GEngine)
	{
		return;
	}
	GEngine->Exec(GetWorld(), TEXT("r.Lumen.HardwareRayTracing 0"));
	if (QualityIndex == 0)
	{
		GEngine->Exec(GetWorld(), TEXT("r.DynamicGlobalIlluminationMethod 0"));
		GEngine->Exec(GetWorld(), TEXT("r.ReflectionMethod 0"));
		GEngine->Exec(GetWorld(), TEXT("r.Shadow.Virtual.Enable 0"));
		GEngine->Exec(GetWorld(), TEXT("r.Nanite 0"));
	}
	else
	{
		GEngine->Exec(GetWorld(), TEXT("r.DynamicGlobalIlluminationMethod 1"));
		GEngine->Exec(GetWorld(), TEXT("r.ReflectionMethod 1"));
		GEngine->Exec(GetWorld(), TEXT("r.Shadow.Virtual.Enable 1"));
		GEngine->Exec(GetWorld(), TEXT("r.Nanite 1"));
	}
}

void AHKPlayerController::OnInteract()
{
	if (Cast<IHKRideable>(GetPawn()))
	{
		ExitVehicle();
		return;
	}
	if (APawn* Ride = Cast<APawn>(FindRide()))
	{
		if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(GetPawn()))
		{
			OnFootPawn = Walker;
			Walker->GetCharacterMovement()->StopMovementImmediately();
			Walker->GetCharacterMovement()->Deactivate();
			Walker->SetActorHiddenInGame(true);
			Walker->SetActorEnableCollision(false);
			Walker->AttachToActor(Ride, FAttachmentTransformRules::SnapToTargetNotIncludingScale);
			Possess(Ride);
		}
	}
}

AActor* AHKPlayerController::FindRide() const
{
	APawn* ControlledPawn = GetPawn();
	if (!ControlledPawn)
	{
		return nullptr;
	}
	TArray<AActor*> Rides;
	UGameplayStatics::GetAllActorsWithInterface(GetWorld(), UHKRideable::StaticClass(), Rides);
	AActor* Best = nullptr;
	float BestDist = TNumericLimits<float>::Max();
	for (AActor* Actor : Rides)
	{
		const IHKRideable* Ride = Cast<IHKRideable>(Actor);
		if (!Ride || Ride->IsOccupied())
		{
			continue;
		}
		const float Dist = FVector::Dist(ControlledPawn->GetActorLocation(), Actor->GetActorLocation());
		if (Dist <= Ride->GetInteractRadiusCm() && Dist < BestDist)
		{
			BestDist = Dist;
			Best = Actor;
		}
	}
	return Best;
}

void AHKPlayerController::ExitVehicle()
{
	APawn* Vehicle = GetPawn();
	AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(OnFootPawn);
	if (!Vehicle || !Walker)
	{
		return;
	}
	FVector Exit = Vehicle->GetActorLocation() + Vehicle->GetActorRightVector() * 220.f;
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKExit), false, Vehicle);
	Params.AddIgnoredActor(Walker);
	const FVector Start = Exit + FVector(0.f, 0.f, 300.f);
	const FVector End = Exit - FVector(0.f, 0.f, 900.f);
	const float Lift = Walker->GetGroundLift();
	if (GetWorld()->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params))
	{
		Exit = Hit.Location + FVector(0.f, 0.f, Lift);
	}
	else
	{
		Exit.Z = Vehicle->GetActorLocation().Z + Lift;
	}
	Walker->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
	Walker->SetActorLocation(Exit, false, nullptr, ETeleportType::TeleportPhysics);
	Walker->SetActorHiddenInGame(false);
	Walker->SetActorEnableCollision(true);
	Walker->GetCharacterMovement()->Activate();
	Walker->GetCharacterMovement()->SetMovementMode(MOVE_Walking);
	Walker->GetCharacterMovement()->StopMovementImmediately();
	Possess(Walker);
}

void AHKPlayerController::TryHotkeys()
{
	const bool bCtrl = IsInputKeyDown(EKeys::LeftControl) || IsInputKeyDown(EKeys::RightControl);
	if (!bCtrl)
	{
		return;
	}
	UHKGameInstance* Game = GetGameInstance<UHKGameInstance>();
	if (!Game)
	{
		return;
	}
	for (const FHKPlace& Place : Game->GetPlaces())
	{
		if (Place.Hotkey.IsEmpty())
		{
			continue;
		}
		const FKey Key(*Place.Hotkey);
		if (Key.IsValid() && WasInputKeyJustPressed(Key))
		{
			TeleportToPlace(Place.Id);
			return;
		}
	}
}

void AHKPlayerController::TryMapClick()
{
	if (!bMapOpen || !WasInputKeyJustPressed(EKeys::LeftMouseButton))
	{
		return;
	}
	AHKFreeRoamHUD* MapHud = Cast<AHKFreeRoamHUD>(GetHUD());
	UHKGameInstance* Game = GetGameInstance<UHKGameInstance>();
	if (!MapHud || !Game || !MapHud->bFullMapVisible || MapHud->FullMapW < 2.f || MapHud->FullMapH < 2.f)
	{
		return;
	}
	float MouseX = 0.f, MouseY = 0.f;
	if (!GetMousePosition(MouseX, MouseY))
	{
		return;
	}
	if (MouseX < MapHud->FullMapX || MouseY < MapHud->FullMapY || MouseX > MapHud->FullMapX + MapHud->FullMapW || MouseY > MapHud->FullMapY + MapHud->FullMapH)
	{
		return;
	}
	const float U = (MouseX - MapHud->FullMapX) / MapHud->FullMapW;
	const float V = (MouseY - MapHud->FullMapY) / MapHud->FullMapH;
	double MinX = 0, MinY = 0, MaxX = 1, MaxY = 1;
	Game->GetMinimapBounds(MinX, MinY, MaxX, MaxY);
	const double X = MinX + (double)U * (MaxX - MinX);
	const double Y = MaxY - (double)V * (MaxY - MinY);
	TeleportToGameMetres(X, Y, 0.0, false, 0.0);
}

void AHKPlayerController::TeleportToPlace(const FString& PlaceId)
{
	UHKGameInstance* Game = GetGameInstance<UHKGameInstance>();
	const FHKPlace* Place = Game ? Game->FindPlace(PlaceId) : nullptr;
	if (!Place)
	{
		UE_LOG(LogHK, Warning, TEXT("HK.Go could not find '%s'"), *PlaceId);
		return;
	}
	TeleportToGameMetres(Place->XMetres, Place->YMetres, Place->ZMetres, true, Place->YawDegrees);
	UE_LOG(LogHK, Display, TEXT("Teleported to %s"), *Place->Id);
}

void AHKPlayerController::TeleportToLonLat(double Lat, double Lon)
{
	UHKGameInstance* Game = GetGameInstance<UHKGameInstance>();
	double X = 0, Y = 0;
	if (!Game || !Game->LonLatToGameMetres(Lon, Lat, X, Y))
	{
		UE_LOG(LogHK, Warning, TEXT("Warp LUT is not loaded; HK.ToGame needs data/processed/warp_lut.bin"));
		return;
	}
	TeleportToGameMetres(X, Y, 0.0, false, 0.0);
}

void AHKPlayerController::TeleportToGameMetres(double XMetres, double YMetres, double ZHintMetres, bool bFaceYaw, double YawDegrees)
{
	APawn* ControlledPawn = GetPawn();
	if (!ControlledPawn || !GetWorld())
	{
		return;
	}
	const FVector Target = HKAxes::GameToUnreal(XMetres, YMetres, 0.0);
	const double Xcm = Target.X;
	const double Ycm = Target.Y;
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(HKTeleport), false, ControlledPawn);
	double Z = ZHintMetres * 100.0;
	if (GetWorld()->LineTraceSingleByChannel(Hit, FVector(Xcm, Ycm, 1500000.0), FVector(Xcm, Ycm, -200000.0), ECC_Visibility, Params))
	{
		Z = Hit.Location.Z;
	}
	double Lift = 130.0;
	if (const AHKFreeRoamCharacter* OnFoot = Cast<AHKFreeRoamCharacter>(ControlledPawn))
	{
		Lift = OnFoot->GetGroundLift();
	}
	else if (Cast<AHKCar>(ControlledPawn))
	{
		Lift = 90.0;
	}
	else if (Cast<AHKHelicopter>(ControlledPawn))
	{
		Lift = 200.0;
	}
	ControlledPawn->SetActorLocation(FVector(Xcm, Ycm, Z + Lift), false, nullptr, ETeleportType::TeleportPhysics);
	if (AHKCar* Car = Cast<AHKCar>(ControlledPawn))
	{
		Car->StopPhysics();
	}
	else if (AHKHelicopter* Heli = Cast<AHKHelicopter>(ControlledPawn))
	{
		Heli->StopPhysics();
	}
	else if (AHKFreeRoamCharacter* Walker = Cast<AHKFreeRoamCharacter>(ControlledPawn))
	{
		Walker->GetCharacterMovement()->StopMovementImmediately();
	}
	if (bFaceYaw)
	{
		SetControlRotation(FRotator(-12.f, HKAxes::GameYawToUnreal(YawDegrees), 0.f));
	}
}

void AHKPlayerController::PrintLonLat(double XCm, double YCm) const
{
	UHKGameInstance* Game = GetGameInstance<UHKGameInstance>();
	double Lon = 0, Lat = 0;
	const FVector2D Game2D = HKAxes::UnrealToGame(FVector(XCm, YCm, 0.0));
	if (!Game || !Game->GameMetresToLonLat(Game2D.X, Game2D.Y, Lon, Lat))
	{
		UE_LOG(LogHK, Warning, TEXT("Warp LUT is not loaded"));
		return;
	}
	UE_LOG(LogHK, Display, TEXT("x_cm %.1f y_cm %.1f -> lat %.8f lon %.8f"), XCm, YCm, Lat, Lon);
}
