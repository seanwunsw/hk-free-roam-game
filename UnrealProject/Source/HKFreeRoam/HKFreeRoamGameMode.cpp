#include "HKFreeRoamGameMode.h"

#include "HKFreeRoamCharacter.h"
#include "HKFreeRoamHUD.h"
#include "HKPlayerController.h"

AHKFreeRoamGameMode::AHKFreeRoamGameMode()
{
	DefaultPawnClass = AHKFreeRoamCharacter::StaticClass();
	PlayerControllerClass = AHKPlayerController::StaticClass();
	HUDClass = AHKFreeRoamHUD::StaticClass();
}
