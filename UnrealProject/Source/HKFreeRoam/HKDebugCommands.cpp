#include "HKFreeRoam.h"
#include "HKCar.h"
#include "HKDriveTest.h"
#include "HKHandling.h"
#include "HKPlayerController.h"

#include "Engine/World.h"
#include "EngineUtils.h"
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
	TEXT("Print latitude and longitude for Unreal centimetres (north is -Y), or for the player if omitted."),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKToLatLon));

// --- Driving (see docs/DRIVING_PLAN.md) ---

// The car being driven, else the nearest car within 10 m of the player.
static AHKCar* HKCarNearPlayer(UWorld* World)
{
	AHKPlayerController* Player = HKPlayer(World);
	APawn* Pawn = Player ? Player->GetPawn() : nullptr;
	if (!Pawn)
	{
		return nullptr;
	}
	if (AHKCar* Driven = Cast<AHKCar>(Pawn))
	{
		return Driven;
	}
	AHKCar* Best = nullptr;
	double BestSq = FMath::Square(1000.0);
	for (TActorIterator<AHKCar> It(World); It; ++It)
	{
		const double DistSq = FVector::DistSquared(It->GetActorLocation(), Pawn->GetActorLocation());
		if (DistSq < BestSq)
		{
			BestSq = DistSq;
			Best = *It;
		}
	}
	return Best;
}

static void HKCarClass(const TArray<FString>& Args, UWorld* World)
{
	AHKCar* Car = HKCarNearPlayer(World);
	if (!Car)
	{
		UE_LOG(LogHK, Display, TEXT("HK.CarClass: drive a car or stand within 10 m of one"));
		return;
	}
	if (Args.Num() < 1)
	{
		UE_LOG(LogHK, Display, TEXT("HK.CarClass: %s is %s (FR | FF | AWD)"), *Car->CarId().ToString(), HKHandling::ClassName(Car->GetCarClass()));
		return;
	}
	EHKCarClass Class;
	if (!HKHandling::ParseClass(Args[0], Class))
	{
		UE_LOG(LogHK, Display, TEXT("Usage: HK.CarClass [FR|FF|AWD|4WD]"));
		return;
	}
	Car->SetCarClass(Class);
	UE_LOG(LogHK, Display, TEXT("HK.CarClass: %s -> %s"), *Car->CarId().ToString(), HKHandling::ClassName(Class));
}

static void HKSpawnCar(const TArray<FString>& Args, UWorld* World)
{
	AHKPlayerController* Player = HKPlayer(World);
	APawn* Pawn = Player ? Player->GetPawn() : nullptr;
	EHKCarClass Class = EHKCarClass::FR;
	if (!Pawn || (Args.Num() > 0 && !HKHandling::ParseClass(Args[0], Class)))
	{
		UE_LOG(LogHK, Display, TEXT("Usage: HK.SpawnCar [FR|FF|AWD|4WD]  (6 m in front of the player)"));
		return;
	}
	const FRotator Yaw(0.f, Pawn->GetActorRotation().Yaw, 0.f);
	FVector Where = Pawn->GetActorLocation() + Yaw.Vector() * 600.f;
	FHitResult Hit;
	FCollisionQueryParams Query(SCENE_QUERY_STAT(HKSpawnCar), false, Pawn);
	if (World->LineTraceSingleByChannel(Hit, Where + FVector(0, 0, 500), Where - FVector(0, 0, 2000), ECC_Visibility, Query))
	{
		Where = Hit.ImpactPoint;
	}
	static int32 Count = 0;
	const FName Id(*FString::Printf(TEXT("Spawned_%s_%d"), HKHandling::ClassName(Class), Count++));
	AHKCar* Car = AHKCar::SpawnCar(World, Class, FTransform(Yaw, Where + FVector(0, 0, 30)), Id, Count % 8);
	UE_LOG(LogHK, Display, TEXT("HK.SpawnCar: %s %s"), Car ? *Id.ToString() : TEXT("failed"), HKHandling::ClassName(Class));
}

static void HKReloadHandling(const TArray<FString>& Args, UWorld* World)
{
	const FString Overlay = Args.Num() > 0 ? Args[0] : FString();
	if (!HKHandling::Reload(Overlay))
	{
		UE_LOG(LogHK, Warning, TEXT("HK.ReloadHandling: overlay %s did not load, kept the old values"), *Overlay);
		return;
	}
	int32 Count = 0;
	for (TActorIterator<AHKCar> It(World); It; ++It)
	{
		It->ApplyHandling();
		++Count;
	}
	UE_LOG(LogHK, Display, TEXT("HK.ReloadHandling: reapplied to %d cars (overlay: %s)"), Count,
		HKHandling::OverlayFile().IsEmpty() ? TEXT("none") : *HKHandling::OverlayFile());
}

static void HKDriveTest(const TArray<FString>& Args, UWorld* World)
{
	TArray<EHKCarClass> Classes;
	bool bQuit = false;
	for (const FString& Arg : Args)
	{
		EHKCarClass Class;
		if (Arg.Equals(TEXT("quit"), ESearchCase::IgnoreCase))
		{
			bQuit = true;
		}
		else if (Arg.Equals(TEXT("all"), ESearchCase::IgnoreCase))
		{
			Classes = {EHKCarClass::FR, EHKCarClass::FF, EHKCarClass::AWD};
		}
		else if (HKHandling::ParseClass(Arg, Class))
		{
			Classes.AddUnique(Class);
		}
		else
		{
			UE_LOG(LogHK, Display, TEXT("Usage: HK.DriveTest [all|FR|FF|AWD ...] [quit]"));
			return;
		}
	}
	if (Classes.Num() == 0)
	{
		Classes = {EHKCarClass::FR, EHKCarClass::FF, EHKCarClass::AWD};
	}
	AHKDriveTestRunner::Start(World, Classes, bQuit);
}

static FAutoConsoleCommandWithWorldAndArgs CmdCarClass(
	TEXT("HK.CarClass"),
	TEXT("Show or set the driving class of the car you drive or stand next to. Example: HK.CarClass AWD"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKCarClass));

static FAutoConsoleCommandWithWorldAndArgs CmdSpawnCar(
	TEXT("HK.SpawnCar"),
	TEXT("Spawn a car of a class 6 m in front of you. Example: HK.SpawnCar FF"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKSpawnCar));

static FAutoConsoleCommandWithWorldAndArgs CmdReloadHandling(
	TEXT("HK.ReloadHandling"),
	TEXT("Reload data/config/vehicles.json and reapply it to every car. Optional overlay merged on top, relative to data/config: HK.ReloadHandling sweeps/awd_f180.json"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKReloadHandling));

static FAutoConsoleCommandWithWorldAndArgs CmdDriveTest(
	TEXT("HK.DriveTest"),
	TEXT("Measure the driving classes on a test pad; writes Saved/HKDriveTest/*.csv. Example: HK.DriveTest all quit"),
	FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&HKDriveTest));
