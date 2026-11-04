#pragma once

#include "CoreMinimal.h"

// Street, place and district names baked by tools/pipeline/labels.py into
// data/processed/road_names.json. Game metres, +X east, +Y north.
struct FHKNamedRoad
{
	int32 Name = INDEX_NONE;
	FString Class;
	TArray<FVector2D> Points;
};

struct FHKLabelPoint
{
	FString Zh;
	FString En;
	FString Kind;
	double X = 0.0;
	double Y = 0.0;
	// Districts only: outer rings for the point-in-polygon test.
	TArray<TArray<FVector2D>> Rings;
};

struct FHKRoadHit
{
	int32 Road = INDEX_NONE;
	double Distance = 0.0;
	FVector2D Point = FVector2D::ZeroVector;
};

class HKFREEROAM_API FHKMapLabels
{
public:
	bool Load(const FString& Path);
	bool IsLoaded() const { return Roads.Num() > 0; }

	// Nearest named road within MaxDistance metres. With a heading, a road running the other
	// way across the junction loses to one along the heading unless it is much closer.
	bool FindRoad(double X, double Y, double MaxDistance, const FVector2D* Heading, FHKRoadHit& OutHit) const;
	// Named roads with a point inside the box, each listed once.
	void RoadsInBox(double MinX, double MinY, double MaxX, double MaxY, TArray<int32>& OutRoads) const;
	const FHKLabelPoint* FindDistrict(double X, double Y) const;
	const FHKLabelPoint* NearestPlace(double X, double Y, double MaxDistance) const;
	const FHKLabelPoint* NearestLandmark(double X, double Y, double MaxDistance) const;

	const FString& NameZh(int32 Road) const;
	const FString& NameEn(int32 Road) const;
	const TArray<FHKNamedRoad>& GetRoads() const { return Roads; }
	const TArray<FHKLabelPoint>& GetLandmarks() const { return Landmarks; }

private:
	void CellRange(double MinX, double MinY, double MaxX, double MaxY, int32& I0, int32& J0, int32& I1, int32& J1) const;

	TArray<TPair<FString, FString>> Names;
	TArray<FHKNamedRoad> Roads;
	TArray<FHKLabelPoint> Places;
	TArray<FHKLabelPoint> Districts;
	TArray<FHKLabelPoint> Landmarks;
	TArray<TArray<int32>> Cells;
	double CellM = 250.0;
	double GridMinX = 0.0;
	double GridMinY = 0.0;
	int32 NX = 0;
	int32 NY = 0;
};
