#include "HKBakeWorldCommandlet.h"

#include "HKBakeLibrary.h"
#include "HKFreeRoam.h"

UHKBakeWorldCommandlet::UHKBakeWorldCommandlet()
{
	IsClient = false;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
	ShowErrorCount = true;
}

int32 UHKBakeWorldCommandlet::Main(const FString& Params)
{
	UE_LOG(LogHK, Display, TEXT("HKBakeWorld %s"), *Params);
	if (FParse::Param(*Params, TEXT("PlayerOnly")))
	{
		return UHKBakeLibrary::BakePlayer() ? 0 : 1;
	}
	return UHKBakeLibrary::BakeWorld() ? 0 : 1;
}
