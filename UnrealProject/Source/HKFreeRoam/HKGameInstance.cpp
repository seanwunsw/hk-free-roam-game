#include "HKGameInstance.h"

#include "HKFreeRoam.h"
#include "hk_warp.h"

#include "Dom/JsonObject.h"
#include "Engine/Texture2D.h"
#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Misc/FileHelper.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

struct FHKWarpState
{
	HKWarpLUT Lut;
};

UHKGameInstance::UHKGameInstance() = default;

UHKGameInstance::~UHKGameInstance()
{
	ReleaseWarp();
}

void UHKGameInstance::BeginDestroy()
{
	ReleaseWarp();
	Super::BeginDestroy();
}

void UHKGameInstance::ReleaseWarp()
{
	delete WarpState;
	WarpState = nullptr;
}

FString UHKGameInstance::ProcessedDir()
{
	return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("../data/processed")));
}

void UHKGameInstance::Init()
{
	Super::Init();
	LoadWarp();
	LoadPlaces();
	LoadMinimap();
}

bool UHKGameInstance::IsWarpReady() const
{
	return WarpState && WarpState->Lut.bValid;
}

bool UHKGameInstance::LonLatToGameMetres(double Lon, double Lat, double& OutX, double& OutY) const
{
	if (!IsWarpReady())
	{
		return false;
	}
	HKWarpLonLatToGameM(WarpState->Lut, Lon, Lat, OutX, OutY);
	return true;
}

bool UHKGameInstance::GameMetresToLonLat(double X, double Y, double& OutLon, double& OutLat) const
{
	if (!IsWarpReady())
	{
		return false;
	}
	HKWarpGameMToLonLat(WarpState->Lut, X, Y, OutLon, OutLat);
	return true;
}

const FHKPlace* UHKGameInstance::FindPlace(const FString& Id) const
{
	for (const FHKPlace& Place : Places)
	{
		if (Place.Id.Equals(Id, ESearchCase::IgnoreCase))
		{
			return &Place;
		}
	}
	return nullptr;
}

const FHKPlace* UHKGameInstance::FindNearestPlace(double XMetres, double YMetres) const
{
	const FHKPlace* Best = nullptr;
	double BestDist = TNumericLimits<double>::Max();
	for (const FHKPlace& Place : Places)
	{
		const double DX = Place.XMetres - XMetres;
		const double DY = Place.YMetres - YMetres;
		const double Dist = DX * DX + DY * DY;
		if (Dist < BestDist)
		{
			BestDist = Dist;
			Best = &Place;
		}
	}
	return Best;
}

void UHKGameInstance::GetMinimapBounds(double& OutMinX, double& OutMinY, double& OutMaxX, double& OutMaxY) const
{
	OutMinX = MapMinX;
	OutMinY = MapMinY;
	OutMaxX = MapMaxX;
	OutMaxY = MapMaxY;
}

void UHKGameInstance::LoadWarp()
{
	ReleaseWarp();
	WarpState = new FHKWarpState();
	const FString Path = FPaths::Combine(ProcessedDir(), TEXT("warp_lut.bin"));
	std::string Error;
	if (!HKWarpLoadFile(TCHAR_TO_UTF8(*Path), WarpState->Lut, Error))
	{
		UE_LOG(LogHK, Warning, TEXT("Warp LUT was not loaded (%s): %s"), *Path, UTF8_TO_TCHAR(Error.c_str()));
		ReleaseWarp();
		return;
	}
	UE_LOG(LogHK, Display, TEXT("Warp LUT loaded from %s"), *Path);
}

static bool HKReadJsonObject(const FString& Path, TSharedPtr<FJsonObject>& OutObject)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		return false;
	}
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	return FJsonSerializer::Deserialize(Reader, OutObject) && OutObject.IsValid();
}

static void HKReadPlace(const TSharedPtr<FJsonObject>& Object, FHKPlace& Place)
{
	Object->TryGetStringField(TEXT("id"), Place.Id);
	Object->TryGetStringField(TEXT("name_zh"), Place.NameZh);
	Object->TryGetStringField(TEXT("kind"), Place.Kind);
	Object->TryGetStringField(TEXT("hotkey"), Place.Hotkey);
	Object->TryGetNumberField(TEXT("lon"), Place.Lon);
	Object->TryGetNumberField(TEXT("lat"), Place.Lat);
	Object->TryGetNumberField(TEXT("x_m"), Place.XMetres);
	Object->TryGetNumberField(TEXT("y_m"), Place.YMetres);
	Object->TryGetNumberField(TEXT("z_m"), Place.ZMetres);
	Object->TryGetNumberField(TEXT("yaw_deg"), Place.YawDegrees);
}

void UHKGameInstance::LoadPlaces()
{
	Places.Reset();
	TSharedPtr<FJsonObject> Root;
	const FString Path = FPaths::Combine(ProcessedDir(), TEXT("landmarks.json"));
	if (!HKReadJsonObject(Path, Root))
	{
		UE_LOG(LogHK, Warning, TEXT("landmarks.json was not loaded: %s"), *Path);
		return;
	}
	const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
	if (!Root->TryGetArrayField(TEXT("places"), Array) || !Array)
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Array)
	{
		const TSharedPtr<FJsonObject> Object = Value->AsObject();
		if (!Object)
		{
			continue;
		}
		FHKPlace Place;
		HKReadPlace(Object, Place);
		if (!Place.Id.IsEmpty())
		{
			Places.Add(Place);
		}
	}
	UE_LOG(LogHK, Display, TEXT("Loaded %d landmarks"), Places.Num());
}

void UHKGameInstance::LoadMinimap()
{
	Minimap = nullptr;
	TSharedPtr<FJsonObject> Manifest;
	const FString ManifestPath = FPaths::Combine(ProcessedDir(), TEXT("manifest.json"));
	FString ImageName = TEXT("minimap.png");
	if (HKReadJsonObject(ManifestPath, Manifest))
	{
		const TSharedPtr<FJsonObject>* Mini = nullptr;
		if (Manifest->TryGetObjectField(TEXT("minimap"), Mini) && Mini && Mini->IsValid())
		{
			(*Mini)->TryGetStringField(TEXT("file"), ImageName);
			(*Mini)->TryGetNumberField(TEXT("min_x_m"), MapMinX);
			(*Mini)->TryGetNumberField(TEXT("min_y_m"), MapMinY);
			(*Mini)->TryGetNumberField(TEXT("max_x_m"), MapMaxX);
			(*Mini)->TryGetNumberField(TEXT("max_y_m"), MapMaxY);
			double Width = MinimapWidth;
			double Height = MinimapHeight;
			if ((*Mini)->TryGetNumberField(TEXT("width_px"), Width))
			{
				MinimapWidth = FMath::Max(1, (int32)Width);
			}
			if ((*Mini)->TryGetNumberField(TEXT("height_px"), Height))
			{
				MinimapHeight = FMath::Max(1, (int32)Height);
			}
		}
	}

	const FString ImagePath = FPaths::Combine(ProcessedDir(), ImageName);
	TArray<uint8> Compressed;
	if (!FFileHelper::LoadFileToArray(Compressed, *ImagePath))
	{
		UE_LOG(LogHK, Warning, TEXT("Minimap PNG was not loaded: %s"), *ImagePath);
		return;
	}
	IImageWrapperModule& Images = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
	const TSharedPtr<IImageWrapper> Wrapper = Images.CreateImageWrapper(EImageFormat::PNG);
	if (!Wrapper.IsValid() || !Wrapper->SetCompressed(Compressed.GetData(), Compressed.Num()))
	{
		UE_LOG(LogHK, Warning, TEXT("Minimap PNG could not be decoded: %s"), *ImagePath);
		return;
	}
	TArray<uint8> Raw;
	if (!Wrapper->GetRaw(ERGBFormat::BGRA, 8, Raw))
	{
		UE_LOG(LogHK, Warning, TEXT("Minimap PNG raw pixels were not read: %s"), *ImagePath);
		return;
	}
	const int32 Width = Wrapper->GetWidth();
	const int32 Height = Wrapper->GetHeight();
	if (Width <= 0 || Height <= 0 || Raw.Num() < Width * Height * 4)
	{
		return;
	}
	MinimapWidth = Width;
	MinimapHeight = Height;
	UTexture2D* Texture = UTexture2D::CreateTransient(Width, Height, PF_B8G8R8A8);
	if (!Texture || !Texture->GetPlatformData() || Texture->GetPlatformData()->Mips.Num() == 0)
	{
		UE_LOG(LogHK, Warning, TEXT("Minimap texture could not be created"));
		return;
	}
	FTexture2DMipMap& Mip = Texture->GetPlatformData()->Mips[0];
	void* Data = Mip.BulkData.Lock(LOCK_READ_WRITE);
	FMemory::Memcpy(Data, Raw.GetData(), Raw.Num());
	Mip.BulkData.Unlock();
	Texture->SRGB = true;
	Texture->UpdateResource();
	Minimap = Texture;
	UE_LOG(LogHK, Display, TEXT("Minimap %dx%d from %s"), Width, Height, *ImagePath);
}
