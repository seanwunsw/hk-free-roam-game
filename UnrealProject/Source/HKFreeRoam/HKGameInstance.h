#pragma once

#include "CoreMinimal.h"
#include "Engine/GameInstance.h"
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

	static FString ProcessedDir();

private:
	void ReleaseWarp();
	void LoadWarp();
	void LoadPlaces();
	void LoadMinimap();

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
