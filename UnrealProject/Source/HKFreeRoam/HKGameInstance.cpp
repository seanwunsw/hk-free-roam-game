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
#include "Misc/Paths.h"

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
	LoadLabels();
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

	if (Manifest.IsValid())
	{
		const TSharedPtr<FJsonObject>* Tiles = nullptr;
		if (Manifest->TryGetObjectField(TEXT("minimap_tiles"), Tiles) && Tiles && Tiles->IsValid())
		{
			FString Dir;
			double Nx = 0, Ny = 0;
			(*Tiles)->TryGetStringField(TEXT("dir"), Dir);
			(*Tiles)->TryGetNumberField(TEXT("tile_m"), TileM);
			(*Tiles)->TryGetNumberField(TEXT("min_x_m"), TileMinX);
			(*Tiles)->TryGetNumberField(TEXT("min_y_m"), TileMinY);
			(*Tiles)->TryGetNumberField(TEXT("nx"), Nx);
			(*Tiles)->TryGetNumberField(TEXT("ny"), Ny);
			const TArray<TSharedPtr<FJsonValue>>* Sea = nullptr;
			if ((*Tiles)->TryGetArrayField(TEXT("sea_rgb"), Sea) && Sea && Sea->Num() == 3)
			{
				TileSea = FLinearColor(FColor((uint8)(*Sea)[0]->AsNumber(), (uint8)(*Sea)[1]->AsNumber(), (uint8)(*Sea)[2]->AsNumber()));
			}
			if (!Dir.IsEmpty() && TileM > 1.0)
			{
				TileDir = FPaths::Combine(ProcessedDir(), Dir);
				TileNX = (int32)Nx;
				TileNY = (int32)Ny;
				UE_LOG(LogHK, Display, TEXT("Minimap tiles %dx%d of %.0f m in %s"), TileNX, TileNY, TileM, *TileDir);
			}
		}
	}

	const FString ImagePath = FPaths::Combine(ProcessedDir(), ImageName);
	UTexture2D* Texture = DecodePng(ImagePath);
	if (!Texture)
	{
		UE_LOG(LogHK, Warning, TEXT("Minimap PNG was not loaded: %s"), *ImagePath);
		return;
	}
	MinimapWidth = Texture->GetSizeX();
	MinimapHeight = Texture->GetSizeY();
	Minimap = Texture;
	UE_LOG(LogHK, Display, TEXT("Minimap %dx%d from %s"), MinimapWidth, MinimapHeight, *ImagePath);
}

UTexture2D* UHKGameInstance::DecodePng(const FString& ImagePath) const
{
	TArray<uint8> Compressed;
	if (!FFileHelper::LoadFileToArray(Compressed, *ImagePath, FILEREAD_Silent))
	{
		return nullptr;
	}
	IImageWrapperModule& Images = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
	const TSharedPtr<IImageWrapper> Wrapper = Images.CreateImageWrapper(EImageFormat::PNG);
	if (!Wrapper.IsValid() || !Wrapper->SetCompressed(Compressed.GetData(), Compressed.Num()))
	{
		UE_LOG(LogHK, Warning, TEXT("PNG could not be decoded: %s"), *ImagePath);
		return nullptr;
	}
	TArray<uint8> Raw;
	if (!Wrapper->GetRaw(ERGBFormat::BGRA, 8, Raw))
	{
		UE_LOG(LogHK, Warning, TEXT("PNG raw pixels were not read: %s"), *ImagePath);
		return nullptr;
	}
	const int32 Width = Wrapper->GetWidth();
	const int32 Height = Wrapper->GetHeight();
	if (Width <= 0 || Height <= 0 || Raw.Num() < Width * Height * 4)
	{
		return nullptr;
	}
	UTexture2D* Texture = UTexture2D::CreateTransient(Width, Height, PF_B8G8R8A8);
	if (!Texture || !Texture->GetPlatformData() || Texture->GetPlatformData()->Mips.Num() == 0)
	{
		UE_LOG(LogHK, Warning, TEXT("Texture could not be created for %s"), *ImagePath);
		return nullptr;
	}
	FTexture2DMipMap& Mip = Texture->GetPlatformData()->Mips[0];
	void* Data = Mip.BulkData.Lock(LOCK_READ_WRITE);
	FMemory::Memcpy(Data, Raw.GetData(), Width * Height * 4);
	Mip.BulkData.Unlock();
	Texture->SRGB = true;
	Texture->Filter = TF_Bilinear;
	Texture->AddressX = TA_Clamp;
	Texture->AddressY = TA_Clamp;
	Texture->UpdateResource();
	return Texture;
}

UTexture2D* UHKGameInstance::GetMinimapTile(int32 I, int32 J, double CentreX, double CentreY)
{
	if (I < 0 || J < 0 || I >= TileNX || J >= TileNY)
	{
		return nullptr;
	}
	const int32 Key = J * TileNX + I;
	if (const TObjectPtr<UTexture2D>* Found = MinimapTiles.Find(Key))
	{
		return *Found;
	}
	if (MissingTiles.Contains(Key) || LastTileDecodeFrame == GFrameCounter)
	{
		return nullptr;
	}
	LastTileDecodeFrame = GFrameCounter;
	UTexture2D* Texture = DecodePng(FPaths::Combine(TileDir, FString::Printf(TEXT("x%02d_y%02d.png"), I, J)));
	if (!Texture)
	{
		// Open sea: the pipeline writes no tile.
		MissingTiles.Add(Key);
		return nullptr;
	}
	MinimapTiles.Add(Key, Texture);
	TrimMinimapTiles(CentreX, CentreY);
	return Texture;
}

void UHKGameInstance::TrimMinimapTiles(double CentreX, double CentreY)
{
	while (MinimapTiles.Num() > MaxMinimapTiles)
	{
		int32 Farthest = INDEX_NONE;
		double FarthestD2 = -1.0;
		for (const TPair<int32, TObjectPtr<UTexture2D>>& Entry : MinimapTiles)
		{
			const double X = TileMinX + ((Entry.Key % TileNX) + 0.5) * TileM;
			const double Y = TileMinY + ((Entry.Key / TileNX) + 0.5) * TileM;
			const double D2 = FMath::Square(X - CentreX) + FMath::Square(Y - CentreY);
			if (D2 > FarthestD2)
			{
				FarthestD2 = D2;
				Farthest = Entry.Key;
			}
		}
		MinimapTiles.Remove(Farthest);
	}
}

void UHKGameInstance::LoadLabels()
{
	Labels = FHKMapLabels();
	FString FileName = TEXT("road_names.json");
	TSharedPtr<FJsonObject> Manifest;
	if (HKReadJsonObject(FPaths::Combine(ProcessedDir(), TEXT("manifest.json")), Manifest))
	{
		Manifest->TryGetStringField(TEXT("road_names_file"), FileName);
	}
	Labels.Load(FPaths::Combine(ProcessedDir(), FileName));
}
