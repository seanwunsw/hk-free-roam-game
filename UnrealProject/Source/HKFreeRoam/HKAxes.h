#pragma once

#include "CoreMinimal.h"

// The one place that maps pipeline game metres to Unreal centimetres and back.
// Pipeline data (manifest, spawns, landmarks, warp, glTF) is right-handed: +X east, +Y north, +Z up.
// Unreal is left-handed: with +X east and +Z up, +Y points south. So north maps to -Y.
// Mapping +Y north straight onto UE +Y mirrors the city east-west on screen.
namespace HKAxes
{
	inline FVector GameToUnreal(double EastM, double NorthM, double UpM)
	{
		return FVector(EastM * 100.0, -NorthM * 100.0, UpM * 100.0);
	}

	// Returns (east, north) in game metres.
	inline FVector2D UnrealToGame(const FVector& Cm)
	{
		return FVector2D(Cm.X / 100.0, -Cm.Y / 100.0);
	}

	// Pipeline yaw is degrees counter-clockwise from east seen from above. UE yaw turns +X toward +Y,
	// which is clockwise from east once north is -Y.
	inline float GameYawToUnreal(double YawDegrees)
	{
		return (float)-YawDegrees;
	}

	// glTF tiles are Y-up metres: (east, up, north).
	inline FVector3f GltfToUnreal(const FVector3f& Gltf, float Scale)
	{
		return FVector3f(Gltf.X * Scale, -Gltf.Z * Scale, Gltf.Y * Scale);
	}
}
