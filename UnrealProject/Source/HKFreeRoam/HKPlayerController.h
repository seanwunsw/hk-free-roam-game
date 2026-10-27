#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "HKPlayerController.generated.h"

class UInputAction;
class UInputMappingContext;
class AHKFreeRoamCharacter;

UCLASS()
class HKFREEROAM_API AHKPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	AHKPlayerController();

	virtual void BeginPlay() override;
	virtual void SetupInputComponent() override;
	virtual void Possess(APawn* InPawn) override;
	virtual void PlayerTick(float DeltaTime) override;

	bool IsMapOpen() const { return bMapOpen; }
	bool IsHelpVisible() const { return bShowHelp; }
	int32 GetQualityIndex() const { return QualityIndex; }

	void TeleportToPlace(const FString& PlaceId);
	void TeleportToLonLat(double Lat, double Lon);
	void TeleportToGameMetres(double XMetres, double YMetres, double ZHintMetres, bool bFaceYaw, double YawDegrees);
	void PrintLonLat(double XCm, double YCm) const;

private:
	void BuildInput();
	void MapMoveKeys(UInputMappingContext* Context, UInputAction* Action);
	void MapCyclicKeys(UInputMappingContext* Context, UInputAction* Action);
	void AddAxisKey(UInputMappingContext* Context, UInputAction* Action, FKey Key, bool bNegate, bool bSwizzleToY);
	void EnsureMappings();
	void ApplyQuality(int32 Index);
	void TryMapClick();
	void TryHotkeys();
	void ExitVehicle();
	AActor* FindRide() const;

	void OnMove(const struct FInputActionValue& Value);
	void OnMoveCompleted(const struct FInputActionValue& Value);
	void OnLook(const struct FInputActionValue& Value);
	void OnJumpStarted();
	void OnJumpCompleted();
	void OnSprintStarted();
	void OnSprintCompleted();
	void OnInteract();
	void OnHandbrakeStarted();
	void OnHandbrakeCompleted();
	void OnYaw(const struct FInputActionValue& Value);
	void OnYawCompleted(const struct FInputActionValue& Value);
	void OnCyclic(const struct FInputActionValue& Value);
	void OnCyclicCompleted(const struct FInputActionValue& Value);
	void OnCollectiveUpStarted();
	void OnCollectiveUpCompleted();
	void OnCollectiveDownStarted();
	void OnCollectiveDownCompleted();
	void OnHover();
	void OnToggleMap();
	void OnToggleHelp();
	void OnCycleQuality();

	void PushDrive();

	UPROPERTY()
	TObjectPtr<UInputAction> MoveAction;
	UPROPERTY()
	TObjectPtr<UInputAction> LookAction;
	UPROPERTY()
	TObjectPtr<UInputAction> JumpAction;
	UPROPERTY()
	TObjectPtr<UInputAction> SprintAction;
	UPROPERTY()
	TObjectPtr<UInputAction> InteractAction;
	UPROPERTY()
	TObjectPtr<UInputAction> HandbrakeAction;
	UPROPERTY()
	TObjectPtr<UInputAction> YawAction;
	UPROPERTY()
	TObjectPtr<UInputAction> CyclicAction;
	UPROPERTY()
	TObjectPtr<UInputAction> CollectiveUpAction;
	UPROPERTY()
	TObjectPtr<UInputAction> CollectiveDownAction;
	UPROPERTY()
	TObjectPtr<UInputAction> HoverAction;
	UPROPERTY()
	TObjectPtr<UInputAction> MapAction;
	UPROPERTY()
	TObjectPtr<UInputAction> HelpAction;
	UPROPERTY()
	TObjectPtr<UInputAction> QualityAction;

	UPROPERTY()
	TObjectPtr<UInputMappingContext> FootContext;
	UPROPERTY()
	TObjectPtr<UInputMappingContext> CarContext;
	UPROPERTY()
	TObjectPtr<UInputMappingContext> HeliContext;
	UPROPERTY()
	TObjectPtr<UInputMappingContext> AlwaysContext;

	UPROPERTY()
	TObjectPtr<APawn> OnFootPawn;

	FVector2D DriveAxis = FVector2D::ZeroVector;
	bool bHandbrakeHeld = false;
	bool bMapOpen = false;
	bool bShowHelp = true;
	int32 QualityIndex = 1;
	bool bMappingsApplied = false;
};
