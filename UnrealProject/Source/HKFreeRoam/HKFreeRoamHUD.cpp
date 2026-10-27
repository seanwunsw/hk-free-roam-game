#include "HKFreeRoamHUD.h"

#include "HKAxes.h"
#include "HKCar.h"
#include "HKGameInstance.h"
#include "HKHelicopter.h"
#include "HKPlayerController.h"
#include "HKTypes.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "WorldPartition/WorldPartitionSubsystem.h"

void AHKFreeRoamHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas)
	{
		return;
	}
	SmoothedFps = FMath::Lerp(SmoothedFps, 1.f / FMath::Max(GetWorld()->GetDeltaSeconds(), 0.0001f), 0.05f);
	UpdateStreaming();

	AHKPlayerController* Controller = Cast<AHKPlayerController>(GetOwningPlayerController());
	bFullMapVisible = Controller && Controller->IsMapOpen();
	const float Aspect = 2048.f / 1896.f;
	UHKGameInstance* Game = GetWorld() ? GetWorld()->GetGameInstance<UHKGameInstance>() : nullptr;
	const float MapAspect = Game && Game->GetMinimapHeight() > 0
		? (float)Game->GetMinimapWidth() / (float)Game->GetMinimapHeight()
		: Aspect;

	const float MiniW = 260.f;
	const float MiniH = MiniW / FMath::Max(MapAspect, 0.1f);
	DrawMap(Canvas->SizeX - MiniW - 24.f, 24.f, MiniW, MiniH, false);

	if (bFullMapVisible)
	{
		FullMapH = Canvas->SizeY * 0.78f;
		FullMapW = FullMapH * MapAspect;
		if (FullMapW > Canvas->SizeX * 0.86f)
		{
			FullMapW = Canvas->SizeX * 0.86f;
			FullMapH = FullMapW / FMath::Max(MapAspect, 0.1f);
		}
		FullMapX = (Canvas->SizeX - FullMapW) * 0.5f;
		FullMapY = (Canvas->SizeY - FullMapH) * 0.5f;
		DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.55f), 0.f, 0.f, Canvas->SizeX, Canvas->SizeY);
		DrawMap(FullMapX, FullMapY, FullMapW, FullMapH, true);
	}

	DrawReadout();
	if (Controller && Controller->IsHelpVisible())
	{
		DrawHelp();
	}
}

void AHKFreeRoamHUD::UpdateStreaming()
{
	StreamTimer += GetWorld()->GetDeltaSeconds();
	if (StreamTimer < 1.f)
	{
		return;
	}
	StreamTimer = 0.f;
	LoadedSpatialActors = 0;
	bHasWorldPartition = false;
	bStreamingComplete = true;
	if (UWorldPartitionSubsystem* Partition = GetWorld()->GetSubsystem<UWorldPartitionSubsystem>())
	{
		bHasWorldPartition = true;
		bStreamingComplete = Partition->IsStreamingCompleted();
	}
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		if (It->ActorHasTag(TEXT("HKSpatial")))
		{
			++LoadedSpatialActors;
		}
	}
}

void AHKFreeRoamHUD::DrawMap(float X, float Y, float W, float H, bool bFull)
{
	DrawRect(FLinearColor(0.02f, 0.04f, 0.05f, 0.9f), X - 4.f, Y - 4.f, W + 8.f, H + 8.f);
	UHKGameInstance* Game = GetWorld()->GetGameInstance<UHKGameInstance>();
	if (Game && Game->GetMinimap())
	{
		DrawTexture(Game->GetMinimap(), X, Y, W, H, 0.f, 0.f, 1.f, 1.f);
	}
	if (!Game)
	{
		return;
	}
	double MinX = 0, MinY = 0, MaxX = 1, MaxY = 1;
	Game->GetMinimapBounds(MinX, MinY, MaxX, MaxY);
	const double SpanX = FMath::Max(MaxX - MinX, 1.0);
	const double SpanY = FMath::Max(MaxY - MinY, 1.0);
	auto ToScreen = [&](double Xm, double Ym, float& OutX, float& OutY)
	{
		const float U = (float)((Xm - MinX) / SpanX);
		const float V = (float)((MaxY - Ym) / SpanY);
		OutX = X + U * W;
		OutY = Y + V * H;
	};
	if (bFull)
	{
		for (const FHKPlace& Place : Game->GetPlaces())
		{
			float PX = 0, PY = 0;
			ToScreen(Place.XMetres, Place.YMetres, PX, PY);
			DrawRect(FLinearColor(0.95f, 0.85f, 0.35f, 1.f), PX - 2.f, PY - 2.f, 4.f, 4.f);
		}
	}
	if (APawn* Pawn = GetOwningPawn())
	{
		float PX = 0, PY = 0;
		const FVector2D Game2D = HKAxes::UnrealToGame(Pawn->GetActorLocation());
		ToScreen(Game2D.X, Game2D.Y, PX, PY);
		DrawRect(FLinearColor(1.f, 0.25f, 0.15f, 1.f), PX - 4.f, PY - 4.f, 8.f, 8.f);
	}
	DrawText(TEXT("N"), FLinearColor::White, X + 6.f, Y + 4.f, GEngine->GetSmallFont(), 1.f);
}

void AHKFreeRoamHUD::DrawReadout()
{
	APawn* Pawn = GetOwningPawn();
	float CmPerSec = 0.f;
	float AltitudeM = 0.f;
	if (Pawn)
	{
		CmPerSec = Pawn->GetVelocity().Size();
		AltitudeM = Pawn->GetActorLocation().Z / 100.f;
	}
	const float Kmh = CmPerSec * 0.036f;
	UHKGameInstance* Game = GetWorld()->GetGameInstance<UHKGameInstance>();
	FString PlaceName;
	FString Coord = TEXT("經緯未載入");
	if (Pawn && Game)
	{
		const FVector2D Game2D = HKAxes::UnrealToGame(Pawn->GetActorLocation());
		const double Xm = Game2D.X;
		const double Ym = Game2D.Y;
		if (const FHKPlace* Place = Game->FindNearestPlace(Xm, Ym))
		{
			PlaceName = Place->NameZh.IsEmpty() ? Place->Id : Place->NameZh;
		}
		double Lon = 0, Lat = 0;
		if (Game->GameMetresToLonLat(Xm, Ym, Lon, Lat))
		{
			Coord = FString::Printf(TEXT("%.5f N  %.5f E"), Lat, Lon);
		}
	}
	AHKPlayerController* Controller = Cast<AHKPlayerController>(GetOwningPlayerController());
	const TCHAR* Quality = (Controller && Controller->GetQualityIndex() == 0) ? TEXT("低") : TEXT("中");
	const FString Stream = bHasWorldPartition
		? FString::Printf(TEXT("%s  空間Actor %d"), bStreamingComplete ? TEXT("串流完成") : TEXT("串流中"), LoadedSpatialActors)
		: FString(TEXT("未烘焙 World Partition"));
	FString Ride;
	if (Cast<AHKCar>(Pawn))
	{
		Ride = TEXT("駕車");
	}
	else if (const AHKHelicopter* Heli = Cast<AHKHelicopter>(Pawn))
	{
		Ride = FString::Printf(TEXT("飛行  總距 %.2f  %s"), Heli->GetCollective(), Heli->HoverAssistEnabled() ? TEXT("懸停開") : TEXT("懸停關"));
	}
	else
	{
		Ride = TEXT("步行");
	}
	const FString Lines[] = {
		FString::Printf(TEXT("%s   %.0f km/h   高度 %.0f m   %s"), *Ride, Kmh, AltitudeM, *PlaceName),
		Coord,
		FString::Printf(TEXT("%s   畫質%s   FPS %.0f"), *Stream, Quality, SmoothedFps)};
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.45f), 16.f, Canvas->SizeY - 92.f, 780.f, 74.f);
	for (int32 Line = 0; Line < 3; ++Line)
	{
		DrawText(Lines[Line], FLinearColor::White, 24.f, Canvas->SizeY - 84.f + Line * 18.f, GEngine->GetSmallFont(), 1.1f);
	}
}

void AHKFreeRoamHUD::DrawHelp()
{
	const TCHAR* Lines[] = {
		TEXT("HK Free Roam    F1 關閉"),
		TEXT("步行  WASD 移動   Shift 跑   Space 跳   滑鼠望"),
		TEXT("F 靠近車輛或直升機上車，再按 F 落車"),
		TEXT("車  W 油門  S 煞車／倒車  A D 轉向  Space 手煞"),
		TEXT("直升機  滑鼠週期變距  A D 偏航  E Q 總距  H 懸停"),
		TEXT("方向鍵或 I J K L 係直升機後備操控"),
		TEXT("M 地圖，撳地圖傳送    F9 切換畫質"),
		TEXT("Ctrl+1 至 0 傳送到地區    控制台 HK.Go 名稱")};
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.62f), 16.f, 16.f, 680.f, 176.f);
	for (int32 Line = 0; Line < UE_ARRAY_COUNT(Lines); ++Line)
	{
		DrawText(Lines[Line], FLinearColor(0.94f, 0.94f, 0.9f), 26.f, 24.f + Line * 18.f, GEngine->GetSmallFont(), 1.05f);
	}
}
