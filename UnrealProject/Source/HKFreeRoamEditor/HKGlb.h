#pragma once

#include "CoreMinimal.h"

struct FHKGlbPrim
{
	TArray<FVector3f> Positions;
	TArray<FVector3f> Normals;
	TArray<FVector2f> UVs;
	// TEXCOORD_1 (HKGM flag 2): road width and lane marking code. Empty when absent.
	TArray<FVector2f> UV1s;
	TArray<FVector4f> Colors;
	TArray<uint32> Indices;
	int32 Material = 0;
};

bool HKLoadGlb(const FString& Path, TArray<FHKGlbPrim>& OutPrims, FString& OutError);
