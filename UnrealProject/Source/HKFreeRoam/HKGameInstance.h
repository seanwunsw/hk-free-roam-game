#pragma once

#include "CoreMinimal.h"
#include "Engine/GameInstance.h"
#include "HKMapLabels.h"
#include "HKTypes.h"
#include "HKGameInstance.generated.h"

class UTexture2D;
struct FHKWarpState;

UCLASS()
class HKFREEROAM_API UHKGameInstance : public UGameInstance
{
	GENERATED_BODY()

public:
	UHKGameInstance();
	virtual ~UHKGameInstance() override;
	virtual void Init() override;
	virtual void BeginDestroy() override;

	bool IsWarpReady() const;
	bool LonLatToGameMetres(double Lon, double Lat, double& OutX, double& OutY) const;
	bool GameMetresToLonLat(double X, double Y, double& OutLon, double& OutLat) const;

	const TArray<FHKPlace>& GetPlaces() const { return Places; }
	const FHKPlace* FindPlace(const FString& Id) const;
	const FHKPlace* FindNearestPlace(double XMetres, double YMetres) const;

	UTexture2D* GetMinimap() const { return Minimap; }
	void GetMinimapBounds(double& OutMinX, double& OutMinY, double& OutMaxX, double& OutMaxY) const;
	int32 GetMinimapWidth() const { return MinimapWidth; }
	int32 GetMinimapHeight() const { return MinimapHeight; }

	const FHKMapLabels& GetLabels() const { return Labels; }

	// Local minimap tiles (tools/pipeline/minimap_tiles.py): square tiles of TileM metres,
	// row 0 at the south. Returns nullptr while a tile is not decoded yet or is open sea;
	// decodes at most one tile per frame and keeps the nearest MaxMinimapTiles.
	bool HasMinimapTiles() const { return TileNX > 0 && TileNY > 0; }
	double GetMinimapTileMetres() const { return TileM; }
	void GetMinimapTileOrigin(double& OutMinX, double& OutMinY) const { OutMinX = TileMinX; OutMinY = TileMinY; }
	FLinearColor GetMinimapSeaColour() const { return TileSea; }
	UTexture2D* GetMinimapTile(int32 I, int32 J, double CentreX, double CentreY);

	static FString ProcessedDir();

private:
	void ReleaseWarp();
	void LoadWarp();
	void LoadPlaces();
	void LoadMinimap();
	void LoadLabels();
	UTexture2D* DecodePng(const FString& Path) const;
	void TrimMinimapTiles(double CentreX, double CentreY);

	UPROPERTY()
	TMap<int32, TObjectPtr<UTexture2D>> MinimapTiles;
	TSet<int32> MissingTiles;
	FString TileDir;
	double TileM = 1024.0;
	double TileMinX = 0.0;
	double TileMinY = 0.0;
	int32 TileNX = 0;
	int32 TileNY = 0;
	FLinearColor TileSea = FLinearColor(0.011f, 0.076f, 0.133f, 1.f);
	uint64 LastTileDecodeFrame = 0;
	static constexpr int32 MaxMinimapTiles = 16;

	FHKMapLabels Labels;

	FHKWarpState* WarpState = nullptr;

	UPROPERTY()
	TArray<FHKPlace> Places;

	UPROPERTY()
	TObjectPtr<UTexture2D> Minimap;

	double MapMinX = -12543.0;
	double MapMinY = -10165.0;
	double MapMaxX = 11576.0;
	double MapMaxY = 12165.0;
	int32 MinimapWidth = 2048;
	int32 MinimapHeight = 1896;
};
