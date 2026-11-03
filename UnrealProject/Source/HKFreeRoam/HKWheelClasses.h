#pragma once

// One wheel UCLASS per car class and axle. Chaos creates each wheel with NewObject from
// WheelSetups[i].WheelClass, so its class default object is the template;
// HKHandling::WriteWheelDefaults fills these CDOs from data/config/vehicles.json.

#include "CoreMinimal.h"
#include "HKWheelFront.h"
#include "HKWheelRear.h"
#include "HKWheelClasses.generated.h"

UCLASS()
class HKFREEROAM_API UHKWheelFront_FR : public UHKWheelFront
{
	GENERATED_BODY()
};

UCLASS()
class HKFREEROAM_API UHKWheelRear_FR : public UHKWheelRear
{
	GENERATED_BODY()
};

UCLASS()
class HKFREEROAM_API UHKWheelFront_FF : public UHKWheelFront
{
	GENERATED_BODY()
};

UCLASS()
class HKFREEROAM_API UHKWheelRear_FF : public UHKWheelRear
{
	GENERATED_BODY()
};

UCLASS()
class HKFREEROAM_API UHKWheelFront_AWD : public UHKWheelFront
{
	GENERATED_BODY()
};

UCLASS()
class HKFREEROAM_API UHKWheelRear_AWD : public UHKWheelRear
{
	GENERATED_BODY()
};
