#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "HKRideable.generated.h"

UINTERFACE(MinimalAPI)
class UHKRideable : public UInterface
{
	GENERATED_BODY()
};

class HKFREEROAM_API IHKRideable
{
	GENERATED_BODY()

public:
	virtual float GetInteractRadiusCm() const = 0;
	virtual bool IsOccupied() const = 0;
};
