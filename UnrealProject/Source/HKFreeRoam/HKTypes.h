#pragma once

#include "CoreMinimal.h"
#include "HKTypes.generated.h"

USTRUCT(BlueprintType)
struct FHKPlace
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, Category = "HK")
	FString Id;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	FString NameZh;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	FString Kind;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	FString Hotkey;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double Lon = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double Lat = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double XMetres = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double YMetres = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double ZMetres = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "HK")
	double YawDegrees = 0.0;
};
