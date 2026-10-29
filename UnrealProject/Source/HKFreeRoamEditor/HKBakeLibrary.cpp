#include "HKBakeLibrary.h"

#include "HKAxes.h"
#include "HKBakePlayer.h"
#include "HKFreeRoamCharacter.h"
#include "HKCar.h"
#include "HKFreeRoam.h"
#include "HKFreeRoamGameMode.h"
#include "HKGlb.h"
#include "HKHelicopter.h"

#include "Animation/Skeleton.h"
#include "ActorFactories/ActorFactory.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Builders/CubeBuilder.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "FileHelpers.h"
#include "GameFramework/PhysicsVolume.h"
#include "GameFramework/PlayerStart.h"
#include "GameMapsSettings.h"
#include "Landscape.h"
#include "LandscapeInfo.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionConstant.h"
#include "Materials/MaterialExpressionConstant3Vector.h"
#include "Materials/MaterialExpressionCustom.h"
#include "Materials/MaterialExpressionTextureCoordinate.h"
#include "Materials/MaterialExpressionVectorParameter.h"
#include "Materials/MaterialExpressionVertexColor.h"
#include "Materials/MaterialExpressionWorldPosition.h"
#include "Materials/MaterialInstance.h"
#include "Materials/MaterialInstanceConstant.h"
#include "MeshDescription.h"
#include "Misc/FileHelper.h"
#include "PhysicsEngine/BodySetup.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "ReferenceSkeleton.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "StaticMeshAttributes.h"
#include "StaticToSkeletalMeshConverter.h"
#include "UObject/Linker.h"
#include "UObject/SavePackage.h"
#include "UObject/UnrealType.h"
#include "WorldPartition/HLOD/HLODLayer.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/WorldPartitionEditorSpatialHash.h"
#include "WorldPartition/WorldPartitionRuntimeSpatialHash.h"

namespace
{
struct FHKSpawn
{
	FString Id;
	double X = 0.0;
	double Y = 0.0;
	double Z = 0.0;
	double Yaw = 0.0;
};

enum class EHKMeshCollision : uint8
{
	// One convex hull per building primitive. An AABB per building covered streets.
	Hulls,
	Road,
	None
};

FString ProcessedDir()
{
	return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("../data/processed")));
}

bool ReadJson(const FString& Path, TSharedPtr<FJsonObject>& Out)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		return false;
	}
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	return FJsonSerializer::Deserialize(Reader, Out) && Out.IsValid();
}

bool SaveAsset(UObject* Object)
{
	if (!Object)
	{
		return false;
	}
	UPackage* Package = Object->GetOutermost();
	const FString Filename = FPackageName::LongPackageNameToFilename(Package->GetName(), FPackageName::GetAssetPackageExtension());
	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true);
	// On a re-bake the old .uasset is still open by its loader, so Windows refuses to overwrite it
	// and every tile logged "Could not save". Detach the loader before saving.
	ResetLoaders(Package);
	FSavePackageArgs Args;
	Args.TopLevelFlags = RF_Public | RF_Standalone;
	Args.SaveFlags = SAVE_NoError;
	return UPackage::SavePackage(Package, Object, *Filename, Args);
}

UObject* ReplaceObject(UPackage* Package, const FString& Name, UClass* Class)
{
	if (UObject* Existing = StaticFindObject(Class, Package, *Name))
	{
		Existing->ClearFlags(RF_Standalone | RF_Public);
		Existing->Rename(nullptr, GetTransientPackage(), REN_DontCreateRedirectors | REN_NonTransactional | REN_ForceNoResetLoaders);
	}
	return nullptr;
}

void AddExpression(UMaterial* Material, UMaterialExpression* Expression)
{
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->ExpressionCollection.AddExpression(Expression);
	}
}

UMaterial* FinishMaterial(UMaterial* Material)
{
	Material->bAutomaticallySetUsageInEditor = true;
	Material->PreEditChange(nullptr);
	Material->PostEditChange();
	FAssetRegistryModule::AssetCreated(Material);
	return Material;
}

UMaterial* MakeCustomMaterial(const TCHAR* AssetName, const FString& Code, bool bNanite, bool bTranslucent, bool bWorldPos)
{
	const FString PackageName = FString::Printf(TEXT("/Game/HK/Materials/%s"), AssetName);
	UPackage* Package = CreatePackage(*PackageName);
	ReplaceObject(Package, AssetName, UMaterial::StaticClass());
	UMaterial* Material = NewObject<UMaterial>(Package, AssetName, RF_Public | RF_Standalone);
	Material->TwoSided = true;
	Material->BlendMode = bTranslucent ? BLEND_Translucent : BLEND_Opaque;
	if (bNanite)
	{
		// bUsedWithNanite is UE_DEPRECATED(5.8). SetMaterialUsage(EMaterialUsage) is the virtual replacement.
		Material->SetMaterialUsage(MATUSAGE_Nanite);
	}

	UMaterialExpressionCustom* Custom = NewObject<UMaterialExpressionCustom>(Material);
	Custom->OutputType = CMOT_Float3;
	Custom->Description = AssetName;
	Custom->Code = Code;
	// The constructor adds one unnamed input. Clear it so Inputs[0..2] are UV, VertColor, WorldPos.
	Custom->Inputs.Reset();
	FCustomInput& UV = Custom->Inputs.AddDefaulted_GetRef();
	UV.InputName = TEXT("UV");
	FCustomInput& Color = Custom->Inputs.AddDefaulted_GetRef();
	Color.InputName = TEXT("VertColor");
	UMaterialExpressionTextureCoordinate* TexCoord = NewObject<UMaterialExpressionTextureCoordinate>(Material);
	UMaterialExpressionVertexColor* VertColor = NewObject<UMaterialExpressionVertexColor>(Material);
	AddExpression(Material, Custom);
	AddExpression(Material, TexCoord);
	AddExpression(Material, VertColor);
	Custom->Inputs[0].Input.Connect(0, TexCoord);
	Custom->Inputs[1].Input.Connect(0, VertColor);
	if (bWorldPos)
	{
		FCustomInput& WorldIn = Custom->Inputs.AddDefaulted_GetRef();
		WorldIn.InputName = TEXT("WorldPos");
		UMaterialExpressionWorldPosition* World = NewObject<UMaterialExpressionWorldPosition>(Material);
		AddExpression(Material, World);
		Custom->Inputs[2].Input.Connect(0, World);
	}
	UMaterialExpressionConstant* Rough = NewObject<UMaterialExpressionConstant>(Material);
	Rough->R = bTranslucent ? 0.15f : 0.75f;
	AddExpression(Material, Rough);
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->BaseColor.Connect(0, Custom);
		Editor->Roughness.Connect(0, Rough);
		if (bTranslucent)
		{
			UMaterialExpressionConstant* Opacity = NewObject<UMaterialExpressionConstant>(Material);
			Opacity->R = 0.72f;
			AddExpression(Material, Opacity);
			Editor->Opacity.Connect(0, Opacity);
		}
	}
	// Landscape materials need no EMaterialUsage flag; there is no MATUSAGE_Landscape.
	return FinishMaterial(Material);
}

UMaterial* MakeCarMaterial()
{
	const TCHAR* AssetName = TEXT("M_HKCar");
	UPackage* Package = CreatePackage(TEXT("/Game/HK/Materials/M_HKCar"));
	ReplaceObject(Package, AssetName, UMaterial::StaticClass());
	UMaterial* Material = NewObject<UMaterial>(Package, AssetName, RF_Public | RF_Standalone);
	Material->TwoSided = false;
	UMaterialExpressionVectorParameter* Color = NewObject<UMaterialExpressionVectorParameter>(Material);
	Color->ParameterName = TEXT("Color");
	Color->DefaultValue = FLinearColor(0.72f, 0.12f, 0.08f);
	UMaterialExpressionConstant* Rough = NewObject<UMaterialExpressionConstant>(Material);
	Rough->R = 0.45f;
	AddExpression(Material, Color);
	AddExpression(Material, Rough);
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->BaseColor.Connect(0, Color);
		Editor->Roughness.Connect(0, Rough);
	}
	Material->SetMaterialUsage(MATUSAGE_SkeletalMesh);
	return FinishMaterial(Material);
}

UMaterialInstanceConstant* MakeColorInstance(UMaterial* Parent, const TCHAR* Name, const FLinearColor& Color)
{
	const FString PackageName = FString::Printf(TEXT("/Game/HK/Vehicles/%s"), Name);
	UPackage* Package = CreatePackage(*PackageName);
	ReplaceObject(Package, Name, UMaterialInstanceConstant::StaticClass());
	UMaterialInstanceConstant* Instance = NewObject<UMaterialInstanceConstant>(Package, Name, RF_Public | RF_Standalone);
	Instance->SetParentEditorOnly(Parent);
	Instance->SetVectorParameterValueEditorOnly(FMaterialParameterInfo(FName(TEXT("Color"))), Color);
	Instance->PostEditChange();
	FAssetRegistryModule::AssetCreated(Instance);
	SaveAsset(Instance);
	return Instance;
}

void ConfigurePartition(UWorld* World)
{
	UWorldPartition* Partition = UWorldPartition::CreateOrRepairWorldPartition(
		World->GetWorldSettings(),
		UWorldPartitionEditorSpatialHash::StaticClass(),
		UWorldPartitionRuntimeSpatialHash::StaticClass());
	if (!Partition)
	{
		UE_LOG(LogHK, Error, TEXT("World Partition was not created"));
		return;
	}
	if (FBoolProperty* Streaming = FindFProperty<FBoolProperty>(Partition->GetClass(), TEXT("bEnableStreaming")))
	{
		Streaming->SetPropertyValue_InContainer(Partition, true);
	}
	if (World->PersistentLevel)
	{
		if (FBoolProperty* External = FindFProperty<FBoolProperty>(World->PersistentLevel->GetClass(), TEXT("bUseExternalActors")))
		{
			External->SetPropertyValue_InContainer(World->PersistentLevel, true);
		}
	}
	UObject* Hash = nullptr;
	if (FObjectProperty* RuntimeHash = FindFProperty<FObjectProperty>(Partition->GetClass(), TEXT("RuntimeHash")))
	{
		Hash = RuntimeHash->GetObjectPropertyValue_InContainer(Partition);
	}
	FArrayProperty* Grids = Hash ? FindFProperty<FArrayProperty>(Hash->GetClass(), TEXT("Grids")) : nullptr;
	FStructProperty* Inner = Grids ? CastField<FStructProperty>(Grids->Inner) : nullptr;
	if (!Hash || !Grids || !Inner)
	{
		UE_LOG(LogHK, Warning, TEXT("Runtime grid was not found. In World Settings set Loading Range to 250000."));
		return;
	}
	FScriptArrayHelper Helper(Grids, Grids->ContainerPtrToValuePtr<void>(Hash));
	if (Helper.Num() == 0)
	{
		Helper.AddValue();
	}
	void* Grid = Helper.GetRawPtr(0);
	if (FNameProperty* GridName = FindFProperty<FNameProperty>(Inner->Struct, TEXT("GridName")))
	{
		GridName->SetPropertyValue_InContainer(Grid, FName(TEXT("MainGrid")));
	}
	if (FIntProperty* Cell = FindFProperty<FIntProperty>(Inner->Struct, TEXT("CellSize")))
	{
		Cell->SetPropertyValue_InContainer(Grid, 12800);
	}
	if (FFloatProperty* Range = FindFProperty<FFloatProperty>(Inner->Struct, TEXT("LoadingRange")))
	{
		Range->SetPropertyValue_InContainer(Grid, 250000.f);
		UE_LOG(LogHK, Display, TEXT("World Partition loading range is 250000 cm"));
	}
	else
	{
		UE_LOG(LogHK, Warning, TEXT("LoadingRange was not found. Set it to 250000 manually or buildings pop in at the default distance."));
	}
}

void MarkSpatial(AActor* Actor, UHLODLayer* Layer, bool bSpatial)
{
	if (!Actor)
	{
		return;
	}
	Actor->SetIsSpatiallyLoaded(bSpatial);
	if (bSpatial)
	{
		Actor->SetRuntimeGrid(FName(TEXT("MainGrid")));
		Actor->Tags.Add(TEXT("HKSpatial"));
		if (Layer)
		{
			Actor->SetHLODLayer(Layer);
		}
	}
}

FVector3f ToUnreal(const FVector3f& GlTf, bool bNormal)
{
	return HKAxes::GltfToUnreal(GlTf, bNormal ? 1.f : 100.f);
}

void AddTriangle(FMeshDescription& Mesh, FPolygonGroupID Group, FVertexInstanceID A, FVertexInstanceID B, FVertexInstanceID C)
{
	TArray<FVertexInstanceID> Corners;
	Corners.Add(A);
	Corners.Add(B);
	Corners.Add(C);
	Mesh.CreateTriangle(Group, Corners);
}

UStaticMesh* BuildMesh(
	const FString& AssetPath,
	const FString& AssetName,
	FMeshDescription& Description,
	UMaterialInterface* Material,
	const FName& Slot,
	bool bNanite,
	EHKMeshCollision Collision,
	const TArray<FKConvexElem>& Hulls)
{
	const FString PackageName = AssetPath / AssetName;
	UPackage* Package = CreatePackage(*PackageName);
	ReplaceObject(Package, AssetName, UStaticMesh::StaticClass());
	UStaticMesh* Mesh = NewObject<UStaticMesh>(Package, *AssetName, RF_Public | RF_Standalone);
	Mesh->GetStaticMaterials().Add(FStaticMaterial(Material, Slot));
	TArray<const FMeshDescription*> Descriptions;
	Descriptions.Add(&Description);
	UStaticMesh::FBuildMeshDescriptionsParams Params;
	Params.bBuildSimpleCollision = false;
	Params.bFastBuild = true;
	Params.bCommitMeshDescription = true;
	Mesh->BuildFromMeshDescriptions(Descriptions, Params);

	FMeshNaniteSettings Nanite = Mesh->GetNaniteSettings();
	Nanite.bEnabled = bNanite;
	Mesh->SetNaniteSettings(Nanite);
	if (Mesh->GetNumSourceModels() > 0)
	{
		FStaticMeshSourceModel& Model = Mesh->GetSourceModel(0);
		Model.BuildSettings.bRecomputeNormals = false;
		Model.BuildSettings.bRecomputeTangents = true;
		Model.BuildSettings.DistanceFieldResolutionScale = 0.25f;
	}
	// 5.6 and 5.8 both have Build(const FBuildParameters&) and Build(bool, TArray<FText>*). One argument does not match either.
	Mesh->Build(true, nullptr);

	Mesh->CreateBodySetup();
	if (UBodySetup* Body = Mesh->GetBodySetup())
	{
		if (Collision == EHKMeshCollision::Road)
		{
			Body->CollisionTraceFlag = CTF_UseComplexAsSimple;
			Body->bDoubleSidedGeometry = true;
		}
		else if (Collision == EHKMeshCollision::Hulls)
		{
			Body->CollisionTraceFlag = CTF_UseSimpleAsComplex;
			Body->AggGeom.ConvexElems = Hulls;
		}
		else
		{
			Body->DefaultInstance.SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Body->CollisionTraceFlag = CTF_UseSimpleAsComplex;
		}
		Body->CreatePhysicsMeshes();
	}
	if (Mesh->GetStaticMaterials().Num() == 0 || Mesh->GetStaticMaterials()[0].MaterialInterface != Material)
	{
		Mesh->GetStaticMaterials().Reset();
		Mesh->GetStaticMaterials().Add(FStaticMaterial(Material, Slot));
	}
	Mesh->PostEditChange();
	FAssetRegistryModule::AssetCreated(Mesh);
	if (!SaveAsset(Mesh))
	{
		UE_LOG(LogHK, Warning, TEXT("Could not save %s"), *PackageName);
	}
	return Mesh;
}

bool AppendPrim(FMeshDescription& Mesh, FStaticMeshAttributes& Attributes, FPolygonGroupID Group, const FHKGlbPrim& Prim, TArray<FKConvexElem>& Hulls, bool bHulls)
{
	const int32 Count = Prim.Positions.Num();
	if (Count == 0 || Prim.Normals.Num() != Count || Prim.UVs.Num() != Count || Prim.Colors.Num() != Count)
	{
		return false;
	}
	TArray<FVertexInstanceID> Instances;
	Instances.SetNum(Count);
	FBox Box(ForceInit);
	TVertexAttributesRef<FVector3f> Positions = Attributes.GetVertexPositions();
	TVertexInstanceAttributesRef<FVector3f> Normals = Attributes.GetVertexInstanceNormals();
	TVertexInstanceAttributesRef<FVector2f> UVs = Attributes.GetVertexInstanceUVs();
	TVertexInstanceAttributesRef<FVector4f> Colors = Attributes.GetVertexInstanceColors();
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const FVector3f Position = ToUnreal(Prim.Positions[Index], false);
		const FVertexID Vertex = Mesh.CreateVertex();
		Positions[Vertex] = Position;
		const FVertexInstanceID Instance = Mesh.CreateVertexInstance(Vertex);
		FVector3f Normal = ToUnreal(Prim.Normals[Index], true);
		if (Normal.SizeSquared() > KINDA_SMALL_NUMBER)
		{
			Normal.Normalize();
		}
		Normals[Instance] = Normal;
		UVs.Set(Instance, 0, Prim.UVs[Index]);
		Colors[Instance] = Prim.Colors[Index];
		Instances[Index] = Instance;
		Box += FVector(Position);
	}
	for (int32 Tri = 0; Tri + 2 < Prim.Indices.Num(); Tri += 3)
	{
		const uint32 I0 = Prim.Indices[Tri];
		uint32 I1 = Prim.Indices[Tri + 1];
		uint32 I2 = Prim.Indices[Tri + 2];
		if (I0 >= (uint32)Count || I1 >= (uint32)Count || I2 >= (uint32)Count)
		{
			continue;
		}
		const FVector P0(Positions[Mesh.GetVertexInstanceVertex(Instances[I0])]);
		const FVector P1(Positions[Mesh.GetVertexInstanceVertex(Instances[I1])]);
		const FVector P2(Positions[Mesh.GetVertexInstanceVertex(Instances[I2])]);
		const FVector Geometric = FVector::CrossProduct(P1 - P0, P2 - P0);
		if (Geometric.SizeSquared() < 0.01f)
		{
			continue;
		}
		const FVector Stored = FVector(Normals[Instances[I0]]) + FVector(Normals[Instances[I1]]) + FVector(Normals[Instances[I2]]);
		if (FVector::DotProduct(Geometric, Stored) < 0.f)
		{
			Swap(I1, I2);
		}
		AddTriangle(Mesh, Group, Instances[I0], Instances[I1], Instances[I2]);
	}
	if (bHulls)
	{
		// Physics cooking builds the hull from this point cloud. Footprints are mostly convex,
		// so the hull stays close to the real walls instead of spanning the street.
		const FVector Size = Box.GetSize();
		if (Size.X > 1.f && Size.Y > 1.f && Size.Z > 1.f)
		{
			FKConvexElem Elem;
			Elem.VertexData.Reserve(Count);
			for (int32 Index = 0; Index < Count; ++Index)
			{
				Elem.VertexData.Add(FVector(Positions[Mesh.GetVertexInstanceVertex(Instances[Index])]));
			}
			Elem.UpdateElemBox();
			Hulls.Add(MoveTemp(Elem));
		}
	}
	return true;
}

UStaticMesh* ImportGlb(const FString& GlbPath, const FString& AssetName, UMaterialInterface* Material, const FName& Slot, bool bNanite, EHKMeshCollision Collision)
{
	TArray<FHKGlbPrim> Prims;
	FString Error;
	if (!HKLoadGlb(GlbPath, Prims, Error))
	{
		UE_LOG(LogHK, Warning, TEXT("%s: %s"), *GlbPath, *Error);
		return nullptr;
	}
	FMeshDescription Description;
	FStaticMeshAttributes Attributes(Description);
	Attributes.Register();
	Attributes.GetVertexInstanceUVs().SetNumChannels(1);
	const FPolygonGroupID Group = Description.CreatePolygonGroup();
	Attributes.GetPolygonGroupMaterialSlotNames()[Group] = Slot;
	TArray<FKConvexElem> Hulls;
	int32 Used = 0;
	for (const FHKGlbPrim& Prim : Prims)
	{
		if (AppendPrim(Description, Attributes, Group, Prim, Hulls, Collision == EHKMeshCollision::Hulls))
		{
			++Used;
		}
	}
	if (Used == 0)
	{
		return nullptr;
	}
	return BuildMesh(TEXT("/Game/HK/Tiles"), AssetName, Description, Material, Slot, bNanite, Collision, Hulls);
}

AStaticMeshActor* SpawnMeshActor(UWorld* World, UStaticMesh* Mesh, const FVector& Location, UHLODLayer* Layer, const FString& Label, bool bCollision)
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(Location, FRotator::ZeroRotator, Params);
	if (!Actor)
	{
		return nullptr;
	}
	UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
	Component->SetMobility(EComponentMobility::Static);
	Component->SetStaticMesh(Mesh);
	if (!bCollision)
	{
		Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	}
	Actor->SetActorLabel(Label);
	MarkSpatial(Actor, Layer, true);
	return Actor;
}

void ReadSpawn(const TSharedPtr<FJsonObject>& Object, FHKSpawn& Spawn)
{
	Object->TryGetStringField(TEXT("id"), Spawn.Id);
	Object->TryGetNumberField(TEXT("x_m"), Spawn.X);
	Object->TryGetNumberField(TEXT("y_m"), Spawn.Y);
	Object->TryGetNumberField(TEXT("z_m"), Spawn.Z);
	Object->TryGetNumberField(TEXT("yaw_deg"), Spawn.Yaw);
}

void ReadSpawnArray(const TSharedPtr<FJsonObject>& Root, const TCHAR* Field, TArray<FHKSpawn>& Out)
{
	const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
	if (!Root->TryGetArrayField(Field, Array) || !Array)
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Array)
	{
		if (const TSharedPtr<FJsonObject> Object = Value->AsObject())
		{
			FHKSpawn Spawn;
			ReadSpawn(Object, Spawn);
			Out.Add(Spawn);
		}
	}
}

bool BuildChassis(UMaterialInterface* Material, USkeletalMesh*& OutMesh, UPhysicsAsset*& OutPhysics)
{
	FMeshDescription Description;
	FStaticMeshAttributes Attributes(Description);
	Attributes.Register();
	Attributes.GetVertexInstanceUVs().SetNumChannels(1);
	const FPolygonGroupID Group = Description.CreatePolygonGroup();
	Attributes.GetPolygonGroupMaterialSlotNames()[Group] = TEXT("Body");
	TVertexAttributesRef<FVector3f> Positions = Attributes.GetVertexPositions();
	TVertexInstanceAttributesRef<FVector3f> Normals = Attributes.GetVertexInstanceNormals();
	TVertexInstanceAttributesRef<FVector2f> UVs = Attributes.GetVertexInstanceUVs();
	auto Vertex = [&](const FVector3f& Position, const FVector3f& Normal, const FVector2f& UV)
	{
		const FVertexID Id = Description.CreateVertex();
		Positions[Id] = Position;
		const FVertexInstanceID Instance = Description.CreateVertexInstance(Id);
		Normals[Instance] = Normal;
		UVs.Set(Instance, 0, UV);
		Attributes.GetVertexInstanceColors()[Instance] = FVector4f(1, 1, 1, 1);
		return Instance;
	};
	auto Face = [&](const FVector3f& A, const FVector3f& B, const FVector3f& C, const FVector3f& D, const FVector3f& Normal)
	{
		AddTriangle(Description, Group, Vertex(A, Normal, FVector2f(0, 0)), Vertex(B, Normal, FVector2f(1, 0)), Vertex(C, Normal, FVector2f(1, 1)));
		AddTriangle(Description, Group, Vertex(A, Normal, FVector2f(0, 0)), Vertex(C, Normal, FVector2f(1, 1)), Vertex(D, Normal, FVector2f(0, 1)));
	};
	const FVector3f Min(-215.f, -95.f, 20.f);
	const FVector3f Max(215.f, 95.f, 90.f);
	Face(FVector3f(Min.X, Min.Y, Max.Z), FVector3f(Max.X, Min.Y, Max.Z), FVector3f(Max.X, Max.Y, Max.Z), FVector3f(Min.X, Max.Y, Max.Z), FVector3f(0, 0, 1));
	Face(FVector3f(Min.X, Max.Y, Min.Z), FVector3f(Max.X, Max.Y, Min.Z), FVector3f(Max.X, Min.Y, Min.Z), FVector3f(Min.X, Min.Y, Min.Z), FVector3f(0, 0, -1));
	Face(FVector3f(Max.X, Min.Y, Min.Z), FVector3f(Max.X, Max.Y, Min.Z), FVector3f(Max.X, Max.Y, Max.Z), FVector3f(Max.X, Min.Y, Max.Z), FVector3f(1, 0, 0));
	Face(FVector3f(Min.X, Max.Y, Min.Z), FVector3f(Min.X, Min.Y, Min.Z), FVector3f(Min.X, Min.Y, Max.Z), FVector3f(Min.X, Max.Y, Max.Z), FVector3f(-1, 0, 0));
	Face(FVector3f(Max.X, Max.Y, Min.Z), FVector3f(Min.X, Max.Y, Min.Z), FVector3f(Min.X, Max.Y, Max.Z), FVector3f(Max.X, Max.Y, Max.Z), FVector3f(0, 1, 0));
	Face(FVector3f(Min.X, Min.Y, Min.Z), FVector3f(Max.X, Min.Y, Min.Z), FVector3f(Max.X, Min.Y, Max.Z), FVector3f(Min.X, Min.Y, Max.Z), FVector3f(0, -1, 0));

	TArray<FKConvexElem> NoHulls;
	UStaticMesh* Chassis = BuildMesh(TEXT("/Game/HK/Vehicles"), TEXT("SM_HKChassis"), Description, Material, TEXT("Body"), false, EHKMeshCollision::None, NoHulls);
	if (!Chassis)
	{
		return false;
	}

	UPackage* Package = CreatePackage(TEXT("/Game/HK/Vehicles/SK_HKCar"));
	ReplaceObject(Package, TEXT("SKEL_HKCar"), USkeleton::StaticClass());
	ReplaceObject(Package, TEXT("SK_HKCar"), USkeletalMesh::StaticClass());
	ReplaceObject(Package, TEXT("PA_HKCar"), UPhysicsAsset::StaticClass());
	USkeleton* Skeleton = NewObject<USkeleton>(Package, TEXT("SKEL_HKCar"), RF_Public | RF_Standalone);
	{
		FReferenceSkeletonModifier Modifier(Skeleton);
		Modifier.Add(FMeshBoneInfo(TEXT("Root"), TEXT("Root"), INDEX_NONE), FTransform::Identity);
	}
	if (Skeleton->GetReferenceSkeleton().GetNum() <= 0)
	{
		FStaticToSkeletalMeshConverter::InitializeSkeletonFromStaticMesh(Skeleton, Chassis, FVector::ZeroVector);
	}
	if (Skeleton->GetReferenceSkeleton().GetNum() <= 0)
	{
		UE_LOG(LogHK, Error, TEXT("Car skeleton has no bones"));
		return false;
	}
	const FName Bone = Skeleton->GetReferenceSkeleton().GetBoneName(0);
	USkeletalMesh* Skeletal = NewObject<USkeletalMesh>(Package, TEXT("SK_HKCar"), RF_Public | RF_Standalone);
	if (!FStaticToSkeletalMeshConverter::InitializeSkeletalMeshFromStaticMesh(Skeletal, Chassis, Skeleton->GetReferenceSkeleton(), Bone))
	{
		UE_LOG(LogHK, Error, TEXT("Static mesh to skeletal mesh conversion failed"));
		return false;
	}
	Skeletal->SetSkeleton(Skeleton);

	UPhysicsAsset* Physics = NewObject<UPhysicsAsset>(Package, TEXT("PA_HKCar"), RF_Public | RF_Standalone);
	USkeletalBodySetup* BodySetup = NewObject<USkeletalBodySetup>(Physics, TEXT("RootBody"));
	BodySetup->BoneName = Bone;
	BodySetup->CollisionTraceFlag = CTF_UseSimpleAsComplex;
	FKBoxElem Box;
	Box.X = 430.f;
	Box.Y = 190.f;
	Box.Z = 70.f;
	Box.Center = FVector(0.f, 0.f, 55.f);
	BodySetup->AggGeom.BoxElems.Add(Box);
	BodySetup->CreatePhysicsMeshes();
	Physics->SkeletalBodySetups.Add(BodySetup);
	Physics->UpdateBodySetupIndexMap();
	Physics->UpdateBoundsBodiesArray();
	Skeletal->SetPhysicsAsset(Physics);
	FAssetRegistryModule::AssetCreated(Skeleton);
	FAssetRegistryModule::AssetCreated(Skeletal);
	FAssetRegistryModule::AssetCreated(Physics);
	SaveAsset(Skeleton);
	SaveAsset(Skeletal);
	SaveAsset(Physics);
	OutMesh = Skeletal;
	OutPhysics = Physics;
	UE_LOG(LogHK, Display, TEXT("Car skeletal mesh bound to bone %s"), *Bone.ToString());
	return true;
}

bool ImportLandscape(UWorld* World, const TSharedPtr<FJsonObject>& LandscapeObject, UMaterialInterface* Material)
{
	const int32 VertsX = (int32)LandscapeObject->GetNumberField(TEXT("verts_x"));
	const int32 VertsY = (int32)LandscapeObject->GetNumberField(TEXT("verts_y"));
	const int32 QuadsPerSection = (int32)LandscapeObject->GetNumberField(TEXT("quads_per_section"));
	const int32 Sections = (int32)LandscapeObject->GetNumberField(TEXT("sections_per_component"));
	const double MinX = LandscapeObject->GetNumberField(TEXT("min_x_m"));
	const double MaxY = LandscapeObject->GetNumberField(TEXT("max_y_m"));
	const double SpacingX = LandscapeObject->GetNumberField(TEXT("spacing_x_m"));
	const double SpacingY = LandscapeObject->GetNumberField(TEXT("spacing_y_m"));
	const double ZScale = LandscapeObject->GetNumberField(TEXT("z_scale_cm"));
	FString HeightName;
	LandscapeObject->TryGetStringField(TEXT("heightmap"), HeightName);
	if (VertsX < 2 || VertsY < 2 || QuadsPerSection != 63 || Sections != 1 || (VertsX - 1) % 63 != 0 || (VertsY - 1) % 63 != 0)
	{
		UE_LOG(LogHK, Error, TEXT("Heightmap %dx%d is not a 63-quad landscape"), VertsX, VertsY);
		return false;
	}
	TArray<uint8> Bytes;
	const FString HeightPath = FPaths::Combine(ProcessedDir(), HeightName);
	if (!FFileHelper::LoadFileToArray(Bytes, *HeightPath) || Bytes.Num() != VertsX * VertsY * 2)
	{
		UE_LOG(LogHK, Error, TEXT("Heightmap size mismatch: %s (%d bytes)"), *HeightPath, Bytes.Num());
		return false;
	}
	TArray<uint16> Heights;
	Heights.SetNumUninitialized(VertsX * VertsY);
	// terrain.r16 row 0 is the south edge. North is UE -Y, so landscape row 0 must be the
	// north edge: reverse the rows and anchor the actor at the northern boundary.
	for (int32 Row = 0; Row < VertsY; ++Row)
	{
		FMemory::Memcpy(&Heights[Row * VertsX], Bytes.GetData() + (VertsY - 1 - Row) * VertsX * 2, VertsX * 2);
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ALandscape* Landscape = World->SpawnActor<ALandscape>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	if (!Landscape)
	{
		return false;
	}
	const FGuid Guid = FGuid::NewGuid();
	// UE 5.7 ALandscapeProxy no longer has bCanHaveLayersContent (member list and the
	// deprecated list). CanHaveLayersContent() is only a getter; edit layers are always on.
	Landscape->SetLandscapeGuid(Guid);
	Landscape->LandscapeMaterial = Material;
	Landscape->SetActorTransform(FTransform(
		FRotator::ZeroRotator,
		HKAxes::GameToUnreal(MinX, MaxY, 0.0),
		FVector(SpacingX * 100.0, SpacingY * 100.0, ZScale)));

	// Import() looks the data up under the final edit layer's key, which is an empty FGuid
	// (LandscapeEdit.cpp: FindChecked(FGuid())), not the landscape's own guid.
	TMap<FGuid, TArray<uint16>> HeightData;
	HeightData.Add(FGuid(), Heights);
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> Layers;
	Layers.Add(FGuid(), TArray<FLandscapeImportLayerInfo>());
	// UE 5.8 keeps only the overload whose last argument is TArrayView<const FLandscapeLayer> (the
	// 5.6 TArray<FLandscapeLayer>* overload is gone), so pass the empty view explicitly.
	Landscape->Import(Guid, 0, 0, VertsX - 1, VertsY - 1, Sections, QuadsPerSection, HeightData, TEXT(""), Layers, ELandscapeImportAlphamapType::Additive,
		TArrayView<const FLandscapeLayer>());
	Landscape->StaticLightingLOD = 2;
	if (ULandscapeInfo* Info = Landscape->GetLandscapeInfo())
	{
		Info->UpdateLayerInfoMap(Landscape);
	}
	Landscape->SetActorLabel(TEXT("HKLandscape"));
	MarkSpatial(Landscape, nullptr, false);
	Landscape->PostEditChange();
	UE_LOG(LogHK, Display, TEXT("Landscape %dx%d, north-west corner at (%.0f, %.0f) m"), VertsX, VertsY, MinX, MaxY);
	return true;
}

void SpawnAtmosphere(UWorld* World)
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>(FVector(0, 0, 50000), FRotator(-16.f, 35.f, 0.f), Params);
	if (Sun)
	{
		UDirectionalLightComponent* Light = Cast<UDirectionalLightComponent>(Sun->GetLightComponent());
		Light->SetMobility(EComponentMobility::Movable);
		Light->SetIntensity(6.5f);
		Light->SetLightColor(FLinearColor(1.0f, 0.78f, 0.55f));
		Light->SetAtmosphereSunLight(true);
		Sun->SetActorLabel(TEXT("HKSun"));
		MarkSpatial(Sun, nullptr, false);
	}
	ASkyLight* Sky = World->SpawnActor<ASkyLight>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	if (Sky)
	{
		USkyLightComponent* Light = Sky->GetLightComponent();
		Light->SetMobility(EComponentMobility::Movable);
		Light->bRealTimeCapture = true;
		Light->SourceType = SLS_CapturedScene;
		Light->SetIntensity(1.05f);
		Sky->SetActorLabel(TEXT("HKSkyLight"));
		MarkSpatial(Sky, nullptr, false);
	}
	ASkyAtmosphere* Atmosphere = World->SpawnActor<ASkyAtmosphere>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	if (Atmosphere)
	{
		Atmosphere->SetActorLabel(TEXT("HKAtmosphere"));
		MarkSpatial(Atmosphere, nullptr, false);
	}
	AExponentialHeightFog* Fog = World->SpawnActor<AExponentialHeightFog>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	if (Fog)
	{
		UExponentialHeightFogComponent* Component = Fog->GetComponent();
		Component->SetFogDensity(0.01f);
		Component->SetFogHeightFalloff(0.2f);
		Component->SetFogInscatteringColor(FLinearColor(0.72f, 0.48f, 0.32f));
		Component->SetFogMaxOpacity(0.72f);
		Component->SetStartDistance(8000.f);
		Component->bEnableVolumetricFog = false;
		Fog->SetActorLabel(TEXT("HKFog"));
		MarkSpatial(Fog, nullptr, false);
	}
}

const TCHAR* MapPackage = TEXT("/Game/Maps/HKWorld");

bool DeleteOldMap()
{
	// World Partition saves every actor as its own package with a new GUID name, so saving a
	// fresh world over the old map left the previous bake's actors on disk and loaded both.
	// Delete the old map and its external packages first. Runs after NewBlankMap so the old
	// world is no longer the editor world.
	CollectGarbage(GARBAGE_COLLECTION_KEEPFLAGS);
	if (UPackage* Old = FindPackage(nullptr, MapPackage))
	{
		ResetLoaders(Old);
	}
	IFileManager& Files = IFileManager::Get();
	const FString MapFile = FPackageName::LongPackageNameToFilename(MapPackage, FPackageName::GetMapPackageExtension());
	if (Files.FileExists(*MapFile) && !Files.Delete(*MapFile, false, true, true))
	{
		UE_LOG(LogHK, Error, TEXT("Could not delete %s. Close it in the editor and bake again."), *MapFile);
		return false;
	}
	for (const TCHAR* Root : {TEXT("__ExternalActors__"), TEXT("__ExternalObjects__")})
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectContentDir(), Root, TEXT("Maps"), TEXT("HKWorld"));
		if (Files.DirectoryExists(*Dir) && !Files.DeleteDirectory(*Dir, false, true))
		{
			UE_LOG(LogHK, Error, TEXT("Could not delete %s. Close the map in the editor and bake again."), *Dir);
			return false;
		}
	}
	return true;
}
}

bool UHKBakeLibrary::BakeWorld()
{
	if (!GEditor)
	{
		UE_LOG(LogHK, Error, TEXT("BakeWorld needs the editor. Use UnrealEditor-Cmd -run=HKBakeWorld."));
		return false;
	}
	const FString Processed = ProcessedDir();
	TSharedPtr<FJsonObject> Manifest;
	if (!ReadJson(FPaths::Combine(Processed, TEXT("manifest.json")), Manifest))
	{
		UE_LOG(LogHK, Error, TEXT("manifest.json is missing in %s. Run python tools/run_pipeline.py first."), *Processed);
		return false;
	}
	const TSharedPtr<FJsonObject>* LandscapeObject = nullptr;
	if (!Manifest->TryGetObjectField(TEXT("landscape"), LandscapeObject) || !LandscapeObject)
	{
		UE_LOG(LogHK, Error, TEXT("manifest has no landscape block"));
		return false;
	}

	if (UWorld* Current = GEditor->GetEditorWorldContext().World())
	{
		Current->GetOutermost()->SetDirtyFlag(false);
	}
	UWorld* World = UEditorLoadingAndSavingUtils::NewBlankMap(false);
	if (!World)
	{
		UE_LOG(LogHK, Error, TEXT("Could not create a blank map"));
		return false;
	}
	if (!DeleteOldMap())
	{
		return false;
	}
	switch (HKBakePlayer::Bake())
	{
	case HKBakePlayer::EResult::Written:
		break;
	case HKBakePlayer::EResult::NoModel:
		UE_LOG(LogHK, Warning, TEXT("Player avatar not baked; the world bake continues and the game uses the cube body"));
		break;
	case HKBakePlayer::EResult::Failed:
		UE_LOG(LogHK, Error, TEXT("Player bake failed (see the errors above); fix it or remove the model from data/config/player.json"));
		return false;
	}
	ConfigurePartition(World);
	AWorldSettings* Settings = World->GetWorldSettings();
	Settings->DefaultGameMode = AHKFreeRoamGameMode::StaticClass();
	Settings->KillZ = -50000.f;
	Settings->bForceNoPrecomputedLighting = true;

	UMaterial* Facade = MakeCustomMaterial(
		TEXT("M_Facade"),
		TEXT("float roof = step(0.5, VertColor.a);\nfloat wx = frac(UV.x * 0.42);\nfloat wy = frac(UV.y * 0.50);\nfloat window = step(0.16, wx) * step(wx, 0.84) * step(0.12, wy) * step(wy, 0.82);\nfloat3 tint = VertColor.rgb;\nfloat3 wall = tint * lerp(0.45, 0.72, wy);\nfloat3 glass = tint * 0.12 + float3(0.04, 0.06, 0.08);\nfloat3 facade = lerp(wall, glass, window);\nreturn lerp(facade, tint * float3(0.32, 0.31, 0.30), roof);\n"),
		true, false, false);
	UMaterial* Road = MakeCustomMaterial(
		TEXT("M_Road"),
		TEXT("float edge = saturate(step(UV.y, 0.08) + step(0.92, UV.y));\nfloat dash = step(0.45, frac(UV.x * 0.12));\nfloat center = step(0.46, UV.y) * step(UV.y, 0.54) * dash;\nfloat3 asphalt = float3(0.09, 0.09, 0.095);\nfloat3 paint = float3(0.85, 0.80, 0.45);\nreturn lerp(asphalt, paint, saturate(edge + center));\n"),
		true, false, false);
	UMaterial* WaterMat = MakeCustomMaterial(
		TEXT("M_Water"),
		TEXT("return float3(0.04, 0.16, 0.24);\n"),
		false, true, false);
	UMaterial* Terrain = MakeCustomMaterial(
		TEXT("M_Terrain"),
		TEXT("float h = saturate(WorldPos.z / 18000.0);\nfloat3 low = float3(0.15, 0.28, 0.13);\nfloat3 high = float3(0.42, 0.40, 0.34);\nreturn lerp(low, high, h);\n"),
		false, false, true);
	UMaterial* CarMat = MakeCarMaterial();
	UMaterial* PadMat = MakeCustomMaterial(
		TEXT("M_Helipad"),
		TEXT("return float3(0.85, 0.72, 0.15);\n"),
		false, false, false);
	UMaterial* HeliMat = MakeCustomMaterial(
		TEXT("M_Heli"),
		TEXT("return float3(0.12, 0.16, 0.18);\n"),
		false, false, false);
	SaveAsset(Facade);
	SaveAsset(Road);
	SaveAsset(WaterMat);
	SaveAsset(Terrain);
	SaveAsset(CarMat);
	SaveAsset(PadMat);
	SaveAsset(HeliMat);

	if (!ImportLandscape(World, *LandscapeObject, Terrain))
	{
		return false;
	}
	SpawnAtmosphere(World);

	const double MinX = (*LandscapeObject)->GetNumberField(TEXT("min_x_m"));
	const double MinY = (*LandscapeObject)->GetNumberField(TEXT("min_y_m"));
	const double MaxX = (*LandscapeObject)->GetNumberField(TEXT("max_x_m"));
	const double MaxY = (*LandscapeObject)->GetNumberField(TEXT("max_y_m"));
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	if (UStaticMesh* Plane = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Plane.Plane")))
	{
		AStaticMeshActor* Sea = World->SpawnActor<AStaticMeshActor>(
			HKAxes::GameToUnreal((MinX + MaxX) * 0.5, (MinY + MaxY) * 0.5, 0.0), FRotator::ZeroRotator, Params);
		if (Sea)
		{
			UStaticMeshComponent* Component = Sea->GetStaticMeshComponent();
			Component->SetMobility(EComponentMobility::Static);
			Component->SetStaticMesh(Plane);
			Component->SetMaterial(0, WaterMat);
			Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Component->SetCastShadow(false);
			Sea->SetActorScale3D(FVector(MaxX - MinX, MaxY - MinY, 1.0));
			Sea->SetActorLabel(TEXT("HKSea"));
			MarkSpatial(Sea, nullptr, false);
		}
	}
	// CharacterMovement only swims inside a physics volume with bWaterVolume. The box spans the
	// map from the sea plane (Z = 0) down to KillZ. Land is above Z = 0, so it never reaches it.
	if (APhysicsVolume* Water = World->SpawnActor<APhysicsVolume>(
		HKAxes::GameToUnreal((MinX + MaxX) * 0.5, (MinY + MaxY) * 0.5, 0.0) + FVector(0.0, 0.0, Settings->KillZ * 0.5), FRotator::ZeroRotator, Params))
	{
		UCubeBuilder* Builder = NewObject<UCubeBuilder>();
		Builder->X = (MaxX - MinX) * 100.0;
		Builder->Y = (MaxY - MinY) * 100.0;
		Builder->Z = -Settings->KillZ;
		UActorFactory::CreateBrushForVolumeActor(Water, Builder);
		Water->bWaterVolume = true;
		Water->FluidFriction = 0.6f;
		Water->SetActorLabel(TEXT("HKSeaWater"));
		MarkSpatial(Water, nullptr, false);
	}

	UPackage* HlodPackage = CreatePackage(TEXT("/Game/HK/HL_Buildings"));
	ReplaceObject(HlodPackage, TEXT("HL_Buildings"), UHLODLayer::StaticClass());
	UHLODLayer* Hlod = NewObject<UHLODLayer>(HlodPackage, TEXT("HL_Buildings"), RF_Public | RF_Standalone);
	Hlod->SetLayerType(EHLODLayerType::Instancing);
	FAssetRegistryModule::AssetCreated(Hlod);
	SaveAsset(Hlod);

	const TArray<TSharedPtr<FJsonValue>>* Tiles = nullptr;
	Manifest->TryGetArrayField(TEXT("tiles"), Tiles);
	int32 Imported = 0;
	int32 Failed = 0;
	if (Tiles)
	{
		for (int32 Index = 0; Index < Tiles->Num(); ++Index)
		{
			const TSharedPtr<FJsonObject> Tile = (*Tiles)[Index]->AsObject();
			if (!Tile)
			{
				continue;
			}
			const int32 Ix = (int32)Tile->GetNumberField(TEXT("ix"));
			const int32 Iy = (int32)Tile->GetNumberField(TEXT("iy"));
			const FVector Origin = HKAxes::GameToUnreal(Tile->GetNumberField(TEXT("origin_x_m")), Tile->GetNumberField(TEXT("origin_y_m")), 0.0);
			auto ImportOne = [&](const TCHAR* Field, UMaterial* Material, const FName& Slot, bool bNanite, EHKMeshCollision Collision, UHLODLayer* Layer)
			{
				FString Relative;
				if (!Tile->TryGetStringField(Field, Relative) || Relative.IsEmpty())
				{
					return;
				}
				const FString AssetName = FPaths::GetBaseFilename(Relative);
				UStaticMesh* Mesh = ImportGlb(FPaths::Combine(Processed, Relative), AssetName, Material, Slot, bNanite, Collision);
				if (!Mesh)
				{
					++Failed;
					return;
				}
				SpawnMeshActor(World, Mesh, Origin, Layer, AssetName, Collision != EHKMeshCollision::None);
				++Imported;
			};
			ImportOne(TEXT("buildings"), Facade, TEXT("Facade"), true, EHKMeshCollision::Hulls, Hlod);
			// Roads are not Nanite: a Nanite mesh renders its decimated fallback on SM5 and its complex
			// collision comes from that fallback too, which tilted the flat ribbons and made the player slide.
			ImportOne(TEXT("roads"), Road, TEXT("Road"), false, EHKMeshCollision::Road, Hlod);
			ImportOne(TEXT("water"), WaterMat, TEXT("Water"), false, EHKMeshCollision::None, nullptr);
			if (Index > 0 && Index % 250 == 0)
			{
				UE_LOG(LogHK, Display, TEXT("Imported %d tile meshes (%d failed)"), Imported, Failed);
			}
		}
	}
	if (Imported == 0)
	{
		UE_LOG(LogHK, Error, TEXT("No tile meshes were imported"));
		return false;
	}

	USkeletalMesh* CarMesh = nullptr;
	UPhysicsAsset* CarPhysics = nullptr;
	const bool bCar = BuildChassis(CarMat, CarMesh, CarPhysics);
	const FLinearColor Colors[] = {
		FLinearColor(0.75f, 0.10f, 0.08f),
		FLinearColor(0.90f, 0.86f, 0.78f),
		FLinearColor(0.10f, 0.18f, 0.32f),
		FLinearColor(0.15f, 0.16f, 0.17f),
		FLinearColor(0.85f, 0.55f, 0.10f),
		FLinearColor(0.20f, 0.38f, 0.22f),
		FLinearColor(0.45f, 0.48f, 0.52f),
		FLinearColor(0.55f, 0.12f, 0.18f)};
	TArray<UMaterialInstanceConstant*> CarColors;
	if (bCar)
	{
		for (int32 ColorIndex = 0; ColorIndex < UE_ARRAY_COUNT(Colors); ++ColorIndex)
		{
			CarColors.Add(MakeColorInstance(CarMat, *FString::Printf(TEXT("MI_Car_%d"), ColorIndex), Colors[ColorIndex]));
		}
	}
	UMaterialInstanceConstant* WheelColor = bCar ? MakeColorInstance(CarMat, TEXT("MI_Wheel"), FLinearColor(0.02f, 0.02f, 0.02f)) : nullptr;

	TSharedPtr<FJsonObject> Spawns;
	if (!ReadJson(FPaths::Combine(Processed, TEXT("spawns.json")), Spawns))
	{
		UE_LOG(LogHK, Error, TEXT("spawns.json is missing"));
		return false;
	}
	if (const TSharedPtr<FJsonObject>* Player = nullptr; Spawns->TryGetObjectField(TEXT("player"), Player) && Player)
	{
		FHKSpawn Spawn;
		ReadSpawn(*Player, Spawn);
		APlayerStart* Start = World->SpawnActor<APlayerStart>(
			HKAxes::GameToUnreal(Spawn.X, Spawn.Y, Spawn.Z)
				+ FVector(0.0, 0.0, AHKFreeRoamCharacter::DefaultCapsuleHalfHeight + AHKFreeRoamCharacter::GroundClearance),
			FRotator(0.f, HKAxes::GameYawToUnreal(Spawn.Yaw), 0.f), Params);
		if (Start)
		{
			Start->SetActorLabel(FString::Printf(TEXT("PlayerStart_%s"), *Spawn.Id));
			MarkSpatial(Start, nullptr, false);
		}
	}
	TArray<FHKSpawn> Cars;
	TArray<FHKSpawn> Pads;
	TArray<FHKSpawn> Helis;
	ReadSpawnArray(Spawns, TEXT("cars"), Cars);
	ReadSpawnArray(Spawns, TEXT("helipads"), Pads);
	ReadSpawnArray(Spawns, TEXT("helicopters"), Helis);
	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	for (const FHKSpawn& Pad : Pads)
	{
		if (!Cube)
		{
			break;
		}
		AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(
			HKAxes::GameToUnreal(Pad.X, Pad.Y, Pad.Z) + FVector(0.0, 0.0, 12.5), FRotator::ZeroRotator, Params);
		if (!Actor)
		{
			continue;
		}
		UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
		Component->SetMobility(EComponentMobility::Static);
		Component->SetStaticMesh(Cube);
		Component->SetMaterial(0, PadMat);
		Actor->SetActorScale3D(FVector(8.f, 8.f, 0.25f));
		Actor->SetActorLabel(Pad.Id);
		MarkSpatial(Actor, nullptr, true);
	}
	int32 ColorCursor = 0;
	for (const FHKSpawn& Car : Cars)
	{
		AHKCar* Actor = World->SpawnActor<AHKCar>(
			HKAxes::GameToUnreal(Car.X, Car.Y, Car.Z) + FVector(0.0, 0.0, 100.0),
			FRotator(0.f, HKAxes::GameYawToUnreal(Car.Yaw), 0.f), Params);
		if (!Actor)
		{
			continue;
		}
		if (bCar)
		{
			Actor->SetVehicleMesh(CarMesh, CarPhysics);
			Actor->ApplyPaint(CarColors[ColorCursor % CarColors.Num()], WheelColor);
			++ColorCursor;
		}
		Actor->SetActorLabel(Car.Id);
		Actor->Tags.Add(*Car.Id);
		// Always loaded: World Partition would destroy a moved vehicle when its cell unloads.
		MarkSpatial(Actor, nullptr, false);
	}
	for (const FHKSpawn& Heli : Helis)
	{
		AHKHelicopter* Actor = World->SpawnActor<AHKHelicopter>(
			HKAxes::GameToUnreal(Heli.X, Heli.Y, Heli.Z) + FVector(0.0, 0.0, 120.0),
			FRotator(0.f, HKAxes::GameYawToUnreal(Heli.Yaw), 0.f), Params);
		if (!Actor)
		{
			continue;
		}
		Actor->ApplyPaint(HeliMat);
		Actor->SetActorLabel(Heli.Id);
		Actor->Tags.Add(*Heli.Id);
		// Always loaded: World Partition would destroy a moved vehicle when its cell unloads.
		MarkSpatial(Actor, nullptr, false);
	}

	const bool bSaved = UEditorLoadingAndSavingUtils::SaveMap(World, MapPackage);
	if (!bSaved)
	{
		UE_LOG(LogHK, Error, TEXT("Saving %s failed"), MapPackage);
		return false;
	}
	// GConfig->SetString on DefaultEngine.ini is not written back on UE 5.8, so go through the
	// settings object, which saves into Config/DefaultEngine.ini.
	const FString HKWorldPath = TEXT("/Game/Maps/HKWorld.HKWorld");
	UGameMapsSettings::SetGameDefaultMap(HKWorldPath);
	UGameMapsSettings* MapsSettings = GetMutableDefault<UGameMapsSettings>();
	MapsSettings->EditorStartupMap = FSoftObjectPath(HKWorldPath);
	if (!MapsSettings->TryUpdateDefaultConfigFile())
	{
		UE_LOG(LogHK, Warning, TEXT("Could not write the startup map to DefaultEngine.ini (is it read-only?)"));
	}
	UE_LOG(LogHK, Display, TEXT("Bake finished. Meshes %d, failed %d, cars %d, helicopters %d. Startup map is now HKWorld."),
		Imported, Failed, Cars.Num(), Helis.Num());
	UE_LOG(LogHK, Display, TEXT("HLOD proxies were not generated. Optional: -run=WorldPartitionBuilderCommandlet -Builder=WorldPartitionHLODsBuilder /Game/Maps/HKWorld"));
	return true;
}

bool UHKBakeLibrary::BakePlayer()
{
	if (!GEditor)
	{
		UE_LOG(LogHK, Error, TEXT("BakePlayer needs the editor. Use UnrealEditor-Cmd -run=HKBakeWorld -PlayerOnly."));
		return false;
	}
	return HKBakePlayer::Bake() == HKBakePlayer::EResult::Written;
}
