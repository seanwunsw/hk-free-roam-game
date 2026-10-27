#include "HKFreeRoam.h"
#include "HKPlayerController.h"

#include "Engine/World.h"
#include "HAL/IConsoleManager.h"

static AHKPlayerController* HKPlayer(UWorld* World)
{
	return World ? Cast<AHKPlayerController>(World->GetFirstPlayerController()) : nullptr;
}

static void HKGo(const TArray<FString>& Args, UWorld* World)
{
	AHKPlayerController* Player = HKPlayer(World);
	if (!Player)
	{
		return;
	}
	if (Args.Num() < 1)
	{
		UE_LOG(LogHK, Display, TEXT("Usage: HK.Go <PlaceId>    example: HK.Go Central"));
		return;
	}
	Player->TeleportToPlace(Args[0]);
}

static void HKToGame(const TArray<FString>& Args, UWorld* World)
{
	AHKPlayerController* Player = HKPlayer(World);
	if (!Player)
	{
		return;
	}
	if (Args.Num() < 2)
	{
		UE_LOG(LogHK, Display, TEXT("Usage: HK.ToGame <lat> <lon>    example: HK.ToGame 22.2849 114.1583"));
		return;
	}
	double A = FCString::Atod(*Args[0]);
	double B = FCString::Atod(*Args[1]);
	double Lat = A;
	double Lon = B;
	if (FMath::Abs(A) > 90.0 && FMath::Abs(B) <= 90.0)
	{
		Lon = A;
		Lat = B;
	}
	Player->TeleportToLonLat(Lat, Lon);
}

static void HKToLatLon(const TArray<FString>& Args, UWorld* World)
{
	AHKPlayerController* Player = HKPlayer(World);
	if (!Player)
	{
		return;
	}
	double X = 0.0;
	double Y = 0.0;
	if (Args.Num() >= 2)
	{
		X = FCString::Atod(*Args[0]);
		Y = FCString::Atod(*Args[1]);
	}
	else if (APawn* Pawn = Player->GetPawn())
	{
		X = Pawn->GetActorLocation().X;
		Y = Pawn->GetActorLocation().Y;
	}
	else
	{
		UE_LOG(LogHK, Display, TEXT("Usage: HK.ToLatLon <x_cm> <y_cm>"));
		return;
	}
	Player->PrintLonLat(X, Y);
}

static FAutoConsoleCommandWithWorldAndArgs CmdGo(
	TEXT("HK.Go"),
	TEXT("Teleport to a baked landmark. Example: HK.Go ShaTin"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKGo));

static FAutoConsoleCommandWithWorldAndArgs CmdToGame(
	TEXT("HK.ToGame"),
	TEXT("Teleport using latitude and longitude. Example: HK.ToGame 22.2849 114.1583"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKToGame));

static FAutoConsoleCommandWithWorldAndArgs CmdToLatLon(
	TEXT("HK.ToLatLon"),
	TEXT("Print latitude and longitude for game centimetres, or for the player if omitted."),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKToLatLon));
