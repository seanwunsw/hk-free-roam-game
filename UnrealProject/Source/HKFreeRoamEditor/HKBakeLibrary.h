#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "HKBakeLibrary.generated.h"

UCLASS()
class HKFREEROAMEDITOR_API UHKBakeLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "HK")
	static bool BakeWorld();

	/** Player avatar only (data/config/player.json -> /Game/HK/Player). Fast; no world rebuild. */
	UFUNCTION(BlueprintCallable, Category = "HK")
	static bool BakePlayer();
};
