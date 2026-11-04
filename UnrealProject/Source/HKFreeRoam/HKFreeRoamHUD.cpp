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

namespace
{
	const TCHAR* LandmarkWord(const FString& Kind)
	{
		if (Kind == TEXT("station")) return TEXT("港鐵");
		if (Kind == TEXT("lrt")) return TEXT("輕鐵");
		if (Kind == TEXT("tram")) return TEXT("電車");
		if (Kind == TEXT("hospital")) return TEXT("醫院");
		if (Kind == TEXT("mall")) return TEXT("商場");
		if (Kind == TEXT("river")) return TEXT("河");
		return TEXT("");
	}

	FLinearColor LandmarkColour(const FString& Kind)
	{
		if (Kind == TEXT("station")) return FLinearColor(0.80f, 0.06f, 0.08f);
		if (Kind == TEXT("lrt")) return FLinearColor(0.92f, 0.50f, 0.06f);
		if (Kind == TEXT("tram")) return FLinearColor(0.10f, 0.50f, 0.22f);
		if (Kind == TEXT("hospital")) return FLinearColor(0.95f, 0.95f, 0.95f);
		if (Kind == TEXT("mall")) return FLinearColor(0.70f, 0.25f, 0.70f);
		return FLinearColor(0.35f, 0.65f, 0.95f);
	}
}

void AHKFreeRoamHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas)
	{
		return;
	}
	SmoothedFps = FMath::Lerp(SmoothedFps, 1.f / FMath::Max(GetWorld()->GetDeltaSeconds(), 0.0001f), 0.05f);
	UpdateStreaming();
	UpdateLabels();

	AHKPlayerController* Controller = Cast<AHKPlayerController>(GetOwningPlayerController());
	bFullMapVisible = Controller && Controller->IsMapOpen();
	const float Aspect = 2048.f / 1896.f;
	UHKGameInstance* Game = GetWorld() ? GetWorld()->GetGameInstance<UHKGameInstance>() : nullptr;
	const float MapAspect = Game && Game->GetMinimapHeight() > 0
		? (float)Game->GetMinimapWidth() / (float)Game->GetMinimapHeight()
		: Aspect;

	const float MiniW = 260.f;
	if (Controller && Controller->IsMinimapZoomed() && Game && Game->HasMinimapTiles())
	{
		DrawLocalMap(Canvas->SizeX - MiniW - 24.f, 24.f, MiniW, MiniW);
	}
	else
	{
		const float MiniH = MiniW / FMath::Max(MapAspect, 0.1f);
		DrawMap(Canvas->SizeX - MiniW - 24.f, 24.f, MiniW, MiniH, false);
	}

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

	DrawStreetName();
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
	const bool bWasComplete = bStreamingComplete;
	bHasWorldPartition = false;
	bStreamingComplete = true;
	if (UWorldPartitionSubsystem* Partition = GetWorld()->GetSubsystem<UWorldPartitionSubsystem>())
	{
		bHasWorldPartition = true;
		bStreamingComplete = Partition->IsStreamingCompleted();
	}
	// Counting walks every actor: every second while streaming, every 5 s once it has settled.
	if (++CountTick < 5 && bStreamingComplete && bWasComplete && LoadedSpatialActors > 0)
	{
		return;
	}
	CountTick = 0;
	LoadedSpatialActors = 0;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		if (It->ActorHasTag(TEXT("HKSpatial")))
		{
			++LoadedSpatialActors;
		}
	}
}

void AHKFreeRoamHUD::UpdateLabels()
{
	LabelTimer -= GetWorld()->GetDeltaSeconds();
	if (LabelTimer > 0.f)
	{
		return;
	}
	LabelTimer = 0.2f;
	StreetZh.Reset();
	StreetEn.Reset();
	AreaText.Reset();
	LandmarkText.Reset();
	UHKGameInstance* Game = GetWorld()->GetGameInstance<UHKGameInstance>();
	APawn* Pawn = GetOwningPawn();
	if (!Game || !Pawn)
	{
		return;
	}
	const FHKMapLabels& Labels = Game->GetLabels();
	const FVector2D Here = HKAxes::UnrealToGame(Pawn->GetActorLocation());
	// Driving: prefer the road along the car's heading over the cross street at a junction.
	FVector2D Heading;
	const FVector2D* HeadingPtr = nullptr;
	if (Cast<AHKCar>(Pawn))
	{
		const FVector Velocity = Pawn->GetVelocity();
		const FVector Forward = Velocity.Size2D() > 200.0 ? Velocity : Pawn->GetActorForwardVector();
		Heading = FVector2D(Forward.X, -Forward.Y).GetSafeNormal();
		if (!Heading.IsNearlyZero())
		{
			HeadingPtr = &Heading;
		}
	}
	FHKRoadHit Hit;
	if (Labels.FindRoad(Here.X, Here.Y, 30.0, HeadingPtr, Hit))
	{
		StreetZh = Labels.NameZh(Hit.Road);
		StreetEn = Labels.NameEn(Hit.Road);
		if (StreetZh.IsEmpty())
		{
			StreetZh = StreetEn;
			StreetEn.Reset();
		}
	}
	const FHKLabelPoint* District = Labels.FindDistrict(Here.X, Here.Y);
	const FHKLabelPoint* Place = Labels.NearestPlace(Here.X, Here.Y, 1500.0);
	if (District)
	{
		AreaText = District->Zh.IsEmpty() ? District->En : District->Zh;
	}
	if (Place)
	{
		const FString& PlaceName = Place->Zh.IsEmpty() ? Place->En : Place->Zh;
		AreaText = AreaText.IsEmpty() ? PlaceName : FString::Printf(TEXT("%s · %s"), *AreaText, *PlaceName);
	}
	if (const FHKLabelPoint* Mark = Labels.NearestLandmark(Here.X, Here.Y, 300.0))
	{
		const FString& MarkName = Mark->Zh.IsEmpty() ? Mark->En : Mark->Zh;
		const FString English = Mark->Zh.IsEmpty() || Mark->En.IsEmpty() ? FString() : FString::Printf(TEXT("  %s"), *Mark->En);
		LandmarkText = FString::Printf(TEXT("%s  %s%s  %.0f m"), LandmarkWord(Mark->Kind), *MarkName, *English,
			FVector2D::Distance(Here, FVector2D(Mark->X, Mark->Y)));
	}
}

void AHKFreeRoamHUD::DrawStreetName()
{
	UFont* Font = GEngine->GetSmallFont();
	const float Bottom = Canvas->SizeY - 92.f - 12.f;
	float Top = Bottom;
	if (!StreetZh.IsEmpty())
	{
		float ZhW = 0.f, ZhH = 0.f, EnW = 0.f, EnH = 0.f;
		GetTextSize(StreetZh, ZhW, ZhH, Font, 1.8f);
		if (!StreetEn.IsEmpty())
		{
			GetTextSize(StreetEn, EnW, EnH, Font, 1.0f);
		}
		Top = Bottom - (ZhH + EnH + 14.f);
	}
	if (!LandmarkText.IsEmpty())
	{
		float LW = 0.f, LH = 0.f;
		GetTextSize(LandmarkText, LW, LH, Font, 1.0f);
		const float LX = (Canvas->SizeX - LW) * 0.5f;
		const float LY = Top - LH - 10.f;
		DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.4f), LX - 10.f, LY - 3.f, LW + 20.f, LH + 6.f);
		DrawText(LandmarkText, FLinearColor(0.95f, 0.9f, 0.75f), LX, LY, Font, 1.0f);
	}
	if (StreetZh.IsEmpty())
	{
		return;
	}
	float ZhW = 0.f, ZhH = 0.f, EnW = 0.f, EnH = 0.f;
	GetTextSize(StreetZh, ZhW, ZhH, Font, 1.8f);
	if (!StreetEn.IsEmpty())
	{
		GetTextSize(StreetEn, EnW, EnH, Font, 1.0f);
	}
	const float BoxW = FMath::Max(ZhW, EnW) + 32.f;
	const float BoxH = ZhH + EnH + 14.f;
	const float BoxX = (Canvas->SizeX - BoxW) * 0.5f;
	const float BoxY = Canvas->SizeY - 92.f - BoxH - 12.f;
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.5f), BoxX, BoxY, BoxW, BoxH);
	DrawText(StreetZh, FLinearColor(1.f, 0.97f, 0.85f), (Canvas->SizeX - ZhW) * 0.5f, BoxY + 5.f, Font, 1.8f);
	if (!StreetEn.IsEmpty())
	{
		DrawText(StreetEn, FLinearColor(0.8f, 0.82f, 0.85f), (Canvas->SizeX - EnW) * 0.5f, BoxY + 7.f + ZhH, Font, 1.0f);
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

void AHKFreeRoamHUD::DrawLocalMap(float X, float Y, float W, float H)
{
	// About 1 km across, north up, centred on the player; the arrow turns with the pawn.
	const double SpanM = 1000.0;
	UHKGameInstance* Game = GetWorld()->GetGameInstance<UHKGameInstance>();
	APawn* Pawn = GetOwningPawn();
	DrawRect(FLinearColor(0.02f, 0.04f, 0.05f, 0.9f), X - 4.f, Y - 4.f, W + 8.f, H + 8.f);
	if (!Game || !Pawn)
	{
		return;
	}
	DrawRect(Game->GetMinimapSeaColour(), X, Y, W, H);
	const FVector2D Centre = HKAxes::UnrealToGame(Pawn->GetActorLocation());
	const double MPerPx = SpanM / W;
	const double ViewMinX = Centre.X - 0.5 * W * MPerPx;
	const double ViewMaxX = Centre.X + 0.5 * W * MPerPx;
	const double ViewMinY = Centre.Y - 0.5 * H * MPerPx;
	const double ViewMaxY = Centre.Y + 0.5 * H * MPerPx;
	const double TileM = Game->GetMinimapTileMetres();
	double OriginX = 0, OriginY = 0;
	Game->GetMinimapTileOrigin(OriginX, OriginY);
	const int32 I0 = FMath::FloorToInt32((ViewMinX - OriginX) / TileM);
	const int32 I1 = FMath::FloorToInt32((ViewMaxX - OriginX) / TileM);
	const int32 J0 = FMath::FloorToInt32((ViewMinY - OriginY) / TileM);
	const int32 J1 = FMath::FloorToInt32((ViewMaxY - OriginY) / TileM);
	for (int32 J = J0; J <= J1; ++J)
	{
		for (int32 I = I0; I <= I1; ++I)
		{
			UTexture2D* Tile = Game->GetMinimapTile(I, J, Centre.X, Centre.Y);
			if (!Tile)
			{
				continue;
			}
			const double TX0 = OriginX + I * TileM;
			const double TY0 = OriginY + J * TileM;
			const double X0 = FMath::Max(TX0, ViewMinX);
			const double X1 = FMath::Min(TX0 + TileM, ViewMaxX);
			const double Y0 = FMath::Max(TY0, ViewMinY);
			const double Y1 = FMath::Min(TY0 + TileM, ViewMaxY);
			if (X1 <= X0 || Y1 <= Y0)
			{
				continue;
			}
			// Tile rows run north to south.
			const float U = (float)((X0 - TX0) / TileM);
			const float V = (float)((TY0 + TileM - Y1) / TileM);
			DrawTexture(Tile, X + (float)((X0 - ViewMinX) / MPerPx), Y + (float)((ViewMaxY - Y1) / MPerPx),
				(float)((X1 - X0) / MPerPx), (float)((Y1 - Y0) / MPerPx), U, V, (float)((X1 - X0) / TileM), (float)((Y1 - Y0) / TileM));
		}
	}
	auto ToScreen = [&](double Xm, double Ym)
	{
		return FVector2D(X + (Xm - ViewMinX) / MPerPx, Y + (ViewMaxY - Ym) / MPerPx);
	};
	auto Inside = [&](const FVector2D& P, float Margin)
	{
		return P.X >= X + Margin && P.X <= X + W - Margin && P.Y >= Y + Margin && P.Y <= Y + H - Margin;
	};

	// Up to 12 street names: bigger roads first, then the ones nearest the player, spaced apart.
	const FHKMapLabels& Labels = Game->GetLabels();
	TArray<int32> Visible;
	Labels.RoadsInBox(ViewMinX, ViewMinY, ViewMaxX, ViewMaxY, Visible);
	struct FCandidate
	{
		int32 Road;
		int32 Rank;
		double D2;
		FVector2D Screen;
	};
	auto RankOf = [](const FString& Class)
	{
		if (Class.StartsWith(TEXT("motorway")) || Class.StartsWith(TEXT("trunk"))) return 0;
		if (Class.StartsWith(TEXT("primary"))) return 1;
		if (Class.StartsWith(TEXT("secondary"))) return 2;
		if (Class.StartsWith(TEXT("tertiary"))) return 3;
		return 4;
	};
	TArray<FCandidate> Candidates;
	TSet<FString> SeenNames;
	for (const int32 RoadIndex : Visible)
	{
		const FHKNamedRoad& Road = Labels.GetRoads()[RoadIndex];
		double BestD2 = TNumericLimits<double>::Max();
		FVector2D BestPoint = FVector2D::ZeroVector;
		for (int32 K = 0; K + 1 < Road.Points.Num(); ++K)
		{
			const FVector2D Mid = 0.5 * (Road.Points[K] + Road.Points[K + 1]);
			const double D2 = FVector2D::DistSquared(Mid, Centre);
			if (D2 < BestD2 && Inside(ToScreen(Mid.X, Mid.Y), 18.f))
			{
				BestD2 = D2;
				BestPoint = Mid;
			}
		}
		if (BestD2 < TNumericLimits<double>::Max())
		{
			Candidates.Add({RoadIndex, RankOf(Road.Class), BestD2, ToScreen(BestPoint.X, BestPoint.Y)});
		}
	}
	Candidates.Sort([](const FCandidate& A, const FCandidate& B) { return A.Rank != B.Rank ? A.Rank < B.Rank : A.D2 < B.D2; });
	TArray<FVector2D> Placed;
	UFont* Font = GEngine->GetSmallFont();

	// Landmark icons; station and Light Rail stop names beside them (up to six).
	int32 MarkNames = 0;
	for (const FHKLabelPoint& Mark : Labels.GetLandmarks())
	{
		if (Mark.Kind == TEXT("river"))
		{
			continue;
		}
		const FVector2D P = ToScreen(Mark.X, Mark.Y);
		if (!Inside(P, 6.f))
		{
			continue;
		}
		DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.8f), P.X - 5.f, P.Y - 5.f, 10.f, 10.f);
		DrawRect(LandmarkColour(Mark.Kind), P.X - 4.f, P.Y - 4.f, 8.f, 8.f);
		if (Mark.Kind == TEXT("hospital"))
		{
			DrawRect(FLinearColor(0.85f, 0.05f, 0.05f), P.X - 3.f, P.Y - 1.f, 6.f, 2.f);
			DrawRect(FLinearColor(0.85f, 0.05f, 0.05f), P.X - 1.f, P.Y - 3.f, 2.f, 6.f);
		}
		if ((Mark.Kind == TEXT("station") || Mark.Kind == TEXT("lrt")) && MarkNames < 6)
		{
			const FString& MarkName = Mark.Zh.IsEmpty() ? Mark.En : Mark.Zh;
			float TW = 0.f, TH = 0.f;
			GetTextSize(MarkName, TW, TH, Font, 0.75f);
			const float LX = FMath::Clamp((float)P.X + 7.f, X + 2.f, X + W - TW - 2.f);
			const float LY = FMath::Clamp((float)P.Y - TH * 0.5f, Y + 2.f, Y + H - TH - 2.f);
			DrawText(MarkName, FLinearColor(0.f, 0.f, 0.f, 0.85f), LX + 1.f, LY + 1.f, Font, 0.75f);
			DrawText(MarkName, FLinearColor(1.f, 0.92f, 0.8f), LX, LY, Font, 0.75f);
			Placed.Add(FVector2D(LX + TW * 0.5f, P.Y));
			++MarkNames;
		}
	}

	for (const FCandidate& Candidate : Candidates)
	{
		if (Placed.Num() >= 12)
		{
			break;
		}
		const FString& Name = Labels.NameZh(Candidate.Road).IsEmpty() ? Labels.NameEn(Candidate.Road) : Labels.NameZh(Candidate.Road);
		if (Name.IsEmpty() || SeenNames.Contains(Name))
		{
			continue;
		}
		bool bCrowded = false;
		for (const FVector2D& Other : Placed)
		{
			bCrowded |= FMath::Abs(Other.X - Candidate.Screen.X) < 70.f && FMath::Abs(Other.Y - Candidate.Screen.Y) < 16.f;
		}
		if (bCrowded)
		{
			continue;
		}
		float TW = 0.f, TH = 0.f;
		GetTextSize(Name, TW, TH, Font, 0.85f);
		const float LX = FMath::Clamp((float)Candidate.Screen.X - TW * 0.5f, X + 2.f, X + W - TW - 2.f);
		const float LY = FMath::Clamp((float)Candidate.Screen.Y - TH * 0.5f, Y + 2.f, Y + H - TH - 2.f);
		DrawText(Name, FLinearColor(0.f, 0.f, 0.f, 0.85f), LX + 1.f, LY + 1.f, Font, 0.85f);
		DrawText(Name, FLinearColor(1.f, 1.f, 1.f), LX, LY, Font, 0.85f);
		Placed.Add(Candidate.Screen);
		SeenNames.Add(Name);
	}

	// Player arrow, pointing where the pawn faces (UE +X east, +Y south = screen right, down).
	const FVector Forward = Pawn->GetActorForwardVector();
	const FVector2D Dir = FVector2D(Forward.X, Forward.Y).GetSafeNormal();
	const FVector2D Side(-Dir.Y, Dir.X);
	const FVector2D Mid(X + W * 0.5f, Y + H * 0.5f);
	const FVector2D Tip = Mid + Dir * 11.0;
	const FVector2D Left = Mid - Dir * 7.0 + Side * 7.0;
	const FVector2D Right = Mid - Dir * 7.0 - Side * 7.0;
	const FVector2D Back = Mid - Dir * 3.0;
	const FLinearColor ArrowColour(1.f, 0.25f, 0.15f, 1.f);
	DrawLine(Tip.X, Tip.Y, Left.X, Left.Y, ArrowColour, 3.f);
	DrawLine(Tip.X, Tip.Y, Right.X, Right.Y, ArrowColour, 3.f);
	DrawLine(Left.X, Left.Y, Back.X, Back.Y, ArrowColour, 3.f);
	DrawLine(Right.X, Right.Y, Back.X, Back.Y, ArrowColour, 3.f);
	DrawText(TEXT("N"), FLinearColor::White, X + 6.f, Y + 4.f, Font, 1.f);
	DrawText(TEXT("1 km   N 全圖"), FLinearColor(0.85f, 0.85f, 0.85f), X + 6.f, Y + H - 16.f, Font, 0.8f);
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
		if (!AreaText.IsEmpty())
		{
			PlaceName = AreaText;
		}
		else if (const FHKPlace* Place = Game->FindNearestPlace(Xm, Ym))
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
	if (const AHKCar* Car = Cast<AHKCar>(Pawn))
	{
		const int32 Gear = Car->Telemetry().Gear;
		const FString GearText = Gear > 0 ? FString::Printf(TEXT("%d檔"), Gear) : (Gear < 0 ? FString(TEXT("倒車")) : FString(TEXT("N")));
		Ride = FString::Printf(TEXT("駕車 %s  %s"), HKHandling::ClassName(Car->GetCarClass()), *GearText);
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
		TEXT("步行  WASD 移動   Shift 跑   Space 跳   滑鼠望   滾輪拉近／拉遠"),
		TEXT("F 靠近車輛或直升機上車，再按 F 落車"),
		TEXT("車  W 油門  S 煞車／倒車  A D 轉向  Space 手煞  滑鼠環迴望（停手自動回正）  滾輪拉近／拉遠"),
		TEXT("直升機  滑鼠週期變距  A D 偏航  E Q 總距  H 懸停"),
		TEXT("方向鍵或 I J K L 係直升機後備操控"),
		TEXT("M 地圖，撳地圖傳送    N 小地圖：近距 1 km／全港    F9 切換畫質"),
		TEXT("Ctrl+1 至 0 傳送到地區    控制台 HK.Go 名稱"),
		TEXT("地圖資料 © OpenStreetMap contributors (ODbL)"),
		TEXT("3D 模型：\"Hong Kong Safe Island\"、\"Hong Kong Traffic Light\" by businessyuen (Sketchfab, CC BY 4.0)")};
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.62f), 16.f, 16.f, 900.f, 212.f);
	for (int32 Line = 0; Line < UE_ARRAY_COUNT(Lines); ++Line)
	{
		DrawText(Lines[Line], FLinearColor(0.94f, 0.94f, 0.9f), 26.f, 24.f + Line * 18.f, GEngine->GetSmallFont(), 1.05f);
	}
}
