#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "HKFreeRoamHUD.generated.h"

UCLASS()
class HKFREEROAM_API AHKFreeRoamHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;

	bool bFullMapVisible = false;
	float FullMapX = 0.f;
	float FullMapY = 0.f;
	float FullMapW = 0.f;
	float FullMapH = 0.f;

private:
	void DrawMap(float X, float Y, float W, float H, bool bFull);
	void DrawLocalMap(float X, float Y, float W, float H);
	void DrawHelp();
	void DrawReadout();
	void UpdateStreaming();
	void UpdateLabels();
	void DrawStreetName();

	float SmoothedFps = 60.f;
	float StreamTimer = 0.f;
	int32 LoadedSpatialActors = 0;
	bool bStreamingComplete = true;
	int32 CountTick = 0;
	bool bHasWorldPartition = false;

	float LabelTimer = 0.f;
	FString StreetZh;
	FString StreetEn;
	FString AreaText;
};
