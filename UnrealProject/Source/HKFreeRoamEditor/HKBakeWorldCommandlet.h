#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "HKBakeWorldCommandlet.generated.h"

UCLASS()
class HKFREEROAMEDITOR_API UHKBakeWorldCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UHKBakeWorldCommandlet();
	virtual int32 Main(const FString& Params) override;
};
