#include "HKBakePlayer.h"

#include "HKFreeRoam.h"
#include "HKPlayerAvatar.h"

#include "Animation/AnimSequence.h"
#include "Animation/Skeleton.h"
#include "AssetImportTask.h"
#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetToolsModule.h"
#include "Dom/JsonObject.h"
#include "EditorAssetLibrary.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/Texture.h"
#include "Engine/Texture2D.h"
#include "FileHelpers.h"
#include "IAssetTools.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionCameraVectorWS.h"
#include "Materials/MaterialExpressionConstant.h"
#include "Materials/MaterialExpressionCustom.h"
#include "Materials/MaterialExpressionMultiply.h"
#include "Materials/MaterialExpressionScalarParameter.h"
#include "Materials/MaterialExpressionTextureSampleParameter2D.h"
#include "Materials/MaterialExpressionTwoSidedSign.h"
#include "Materials/MaterialExpressionVectorParameter.h"
#include "Materials/MaterialExpressionVertexNormalWS.h"
#include "Materials/MaterialInstance.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Retargeter/IKRetargeter.h"
#include "RetargetEditor/IKRetargeterController.h"
#include "Rig/IKRigDefinition.h"
#include "RigEditor/IKRigController.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "UObject/UObjectIterator.h"
#include "UObject/UnrealType.h"

#if HK_WITH_VRM4U
#include "VrmAssetListObject.h"
#include "VrmImporterBPFunctionLibrary.h"
#include "VrmUtil.h"
#endif

namespace
{
const TCHAR* PlayerRoot = TEXT("/Game/HK/Player");
const TCHAR* ModelDir = TEXT("/Game/HK/Player/Model");
const TCHAR* AnimDir = TEXT("/Game/HK/Player/Anim");
const TCHAR* RigDir = TEXT("/Game/HK/Player/Rig");
const TCHAR* MaterialDir = TEXT("/Game/HK/Player/Materials");
const TCHAR* RetargetSuffix = TEXT("_HK");

struct FHKPlayerConfig
{
	FString Model;
	FString Placeholder;
	FString Animations;
	TMap<FString, FString> Clips;
	TMap<FString, float> RefSpeeds;
	float TargetHeightCm = 120.f;
	float MeshYawDeg = -90.f;
	FString Materials = TEXT("figure");
	bool bOutline = false;
};

FString RepoRoot()
{
	return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("..")));
}

FString RepoPath(const FString& Relative)
{
	return FPaths::ConvertRelativePathToFull(FPaths::Combine(RepoRoot(), Relative));
}

bool ReadConfig(FHKPlayerConfig& Out)
{
	const FString Path = RepoPath(TEXT("data/config/player.json"));
	FString Text;
	TSharedPtr<FJsonObject> Json;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: %s is missing"), *Path);
		return false;
	}
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
	{
		UE_LOG(LogHK, Error, TEXT("Player: %s is not valid JSON"), *Path);
		return false;
	}
	Json->TryGetStringField(TEXT("model"), Out.Model);
	// Optional: tools/characters/remove_placeholder.py deletes this key.
	Json->TryGetStringField(TEXT("placeholder_model"), Out.Placeholder);
	Json->TryGetStringField(TEXT("animations"), Out.Animations);
	Json->TryGetStringField(TEXT("materials"), Out.Materials);
	Json->TryGetBoolField(TEXT("outline"), Out.bOutline);
	double Number = 0.0;
	if (Json->TryGetNumberField(TEXT("target_height_cm"), Number))
	{
		Out.TargetHeightCm = static_cast<float>(Number);
	}
	if (Json->TryGetNumberField(TEXT("mesh_yaw_deg"), Number))
	{
		Out.MeshYawDeg = static_cast<float>(Number);
	}
	const TSharedPtr<FJsonObject>* Clips = nullptr;
	if (Json->TryGetObjectField(TEXT("clips"), Clips) && Clips)
	{
		for (const auto& Pair : (*Clips)->Values)
		{
			FString Value;
			if (Pair.Value.IsValid() && Pair.Value->TryGetString(Value))
			{
				Out.Clips.Add(Pair.Key, Value);
			}
		}
	}
	const TSharedPtr<FJsonObject>* Speeds = nullptr;
	if (Json->TryGetObjectField(TEXT("anim_ref_speed_cm_s"), Speeds) && Speeds)
	{
		for (const auto& Pair : (*Speeds)->Values)
		{
			double Value = 0.0;
			if (Pair.Value.IsValid() && Pair.Value->TryGetNumber(Value))
			{
				Out.RefSpeeds.Add(Pair.Key, static_cast<float>(Value));
			}
		}
	}
	return true;
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
	FSavePackageArgs Args;
	Args.TopLevelFlags = RF_Public | RF_Standalone;
	Args.SaveFlags = SAVE_NoError;
	return UPackage::SavePackage(Package, Object, *Filename, Args);
}

template <typename T>
T* NewAsset(const FString& Dir, const FString& Name)
{
	UPackage* Package = CreatePackage(*(Dir / Name));
	if (UObject* Existing = StaticFindObject(nullptr, Package, *Name))
	{
		Existing->ClearFlags(RF_Standalone | RF_Public);
		Existing->Rename(nullptr, GetTransientPackage(), REN_DontCreateRedirectors | REN_NonTransactional | REN_ForceNoResetLoaders);
	}
	T* Asset = NewObject<T>(Package, *Name, RF_Public | RF_Standalone);
	FAssetRegistryModule::AssetCreated(Asset);
	return Asset;
}

/** Every loaded asset of class T under a content folder (recursive). */
template <typename T>
TArray<T*> AssetsUnder(const FString& Dir)
{
	TArray<T*> Out;
	for (const FString& Path : UEditorAssetLibrary::ListAssets(Dir, true, false))
	{
		if (T* Asset = Cast<T>(UEditorAssetLibrary::LoadAsset(Path)))
		{
			Out.AddUnique(Asset);
		}
	}
	// Assets created in memory by an importer may not be in the registry yet.
	const FString Prefix = Dir + TEXT("/");
	for (TObjectIterator<T> It; It; ++It)
	{
		if (It->GetOutermost()->GetName().StartsWith(Prefix) && !It->HasAnyFlags(RF_ClassDefaultObject | RF_Transient))
		{
			Out.AddUnique(*It);
		}
	}
	return Out;
}

/** Imports one glb/gltf/fbx through the editor's import path (Interchange for glTF in 5.6). */
bool ImportFile(const FString& File, const FString& Dir)
{
	UAssetImportTask* Task = NewObject<UAssetImportTask>();
	Task->Filename = File;
	Task->DestinationPath = Dir;
	Task->bAutomated = true;
	Task->bReplaceExisting = true;
	Task->bSave = false;
	Task->bAsync = false;
	IAssetTools& Tools = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools")).Get();
	Tools.ImportAssetTasks({Task});
	return Task->ImportedObjectPaths.Num() > 0 || UEditorAssetLibrary::ListAssets(Dir, true, false).Num() > 0;
}

// ---------------------------------------------------------------------------------------------
// Reflection calls. These UFUNCTIONs live in IKRigEditor; calling them by name avoids depending
// on whether each symbol is exported from the module DLL.

struct FHKCall
{
	UObject* Target = nullptr;
	UFunction* Function = nullptr;
	TArray<uint8> Buffer;

	FHKCall(UObject* InTarget, FName Name)
		: Target(InTarget)
	{
		Function = Target ? Target->FindFunction(Name) : nullptr;
		if (Function)
		{
			Buffer.SetNumZeroed(Function->ParmsSize);
			Function->InitializeStruct(Buffer.GetData());
		}
	}
	~FHKCall()
	{
		if (Function)
		{
			Function->DestroyStruct(Buffer.GetData());
		}
	}
	FHKCall(const FHKCall&) = delete;
	FHKCall& operator=(const FHKCall&) = delete;

	explicit operator bool() const { return Function != nullptr; }

	bool SetBool(const TCHAR* Name, bool bValue)
	{
		FBoolProperty* Prop = Function ? FindFProperty<FBoolProperty>(Function, Name) : nullptr;
		if (Prop)
		{
			Prop->SetPropertyValue_InContainer(Buffer.GetData(), bValue);
		}
		return Prop != nullptr;
	}

	bool GetBool(const TCHAR* Name) const
	{
		const FBoolProperty* Prop = Function ? FindFProperty<FBoolProperty>(Function, Name) : nullptr;
		return Prop && Prop->GetPropertyValue_InContainer(Buffer.GetData());
	}

	template <typename PropertyType, typename ValueType>
	ValueType* Param(const TCHAR* Name)
	{
		PropertyType* Prop = Function ? FindFProperty<PropertyType>(Function, Name) : nullptr;
		return Prop ? Prop->template ContainerPtrToValuePtr<ValueType>(Buffer.GetData()) : nullptr;
	}

	bool SetEnum(const TCHAR* Name, int64 Value)
	{
		FProperty* Prop = Function ? FindFProperty<FProperty>(Function, Name) : nullptr;
		void* Ptr = Prop ? Prop->ContainerPtrToValuePtr<void>(Buffer.GetData()) : nullptr;
		if (const FEnumProperty* Enum = CastField<FEnumProperty>(Prop))
		{
			Enum->GetUnderlyingProperty()->SetIntPropertyValue(Ptr, Value);
			return true;
		}
		if (const FByteProperty* Byte = CastField<FByteProperty>(Prop))
		{
			Byte->SetIntPropertyValue(Ptr, Value);
			return true;
		}
		return false;
	}

	bool SetObject(const TCHAR* Name, UObject* Value)
	{
		FObjectPropertyBase* Prop = Function ? FindFProperty<FObjectPropertyBase>(Function, Name) : nullptr;
		if (!Prop || (Value && !Value->IsA(Prop->PropertyClass)))
		{
			return false;
		}
		Prop->SetObjectPropertyValue_InContainer(Buffer.GetData(), Value);
		return true;
	}

	void Invoke() { Target->ProcessEvent(Function, Buffer.GetData()); }
};

int64 EnumValue(const TCHAR* EnumPath, const TCHAR* Name, int64 Fallback)
{
	if (const UEnum* Enum = FindObject<UEnum>(nullptr, EnumPath))
	{
		const int64 Value = Enum->GetValueByNameString(Name);
		if (Value != INDEX_NONE)
		{
			return Value;
		}
	}
	return Fallback;
}

bool AutoRetargetDefinition(UIKRigDefinition* Rig)
{
	UIKRigController* Controller = UIKRigController::GetController(Rig);
	FHKCall Call(Controller, TEXT("ApplyAutoGeneratedRetargetDefinition"));
	if (!Call)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: UIKRigController::ApplyAutoGeneratedRetargetDefinition not found"));
		return false;
	}
	Call.Invoke();
	return Call.GetBool(TEXT("ReturnValue"));
}

UIKRigDefinition* MakeIKRig(const FString& Name, USkeletalMesh* Mesh)
{
	UIKRigDefinition* Rig = NewAsset<UIKRigDefinition>(RigDir, Name);
	UIKRigController* Controller = UIKRigController::GetController(Rig);
	if (!Controller || !Controller->SetSkeletalMesh(Mesh))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: could not set %s on IK rig %s"), *GetNameSafe(Mesh), *Name);
		return nullptr;
	}
	if (!AutoRetargetDefinition(Rig))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: %s: the skeleton of %s matched no built-in retarget template"), *Name, *GetNameSafe(Mesh));
		return nullptr;
	}
	SaveAsset(Rig);
	return Rig;
}

UIKRetargeter* MakeRetargeter(UIKRigDefinition* Source, UIKRigDefinition* Target)
{
	UIKRetargeter* Retargeter = NewAsset<UIKRetargeter>(RigDir, TEXT("RTG_UAL_To_Player"));
	UIKRetargeterController* Controller = UIKRetargeterController::GetController(Retargeter);
	if (!Controller)
	{
		return nullptr;
	}
	Controller->SetIKRig(ERetargetSourceOrTarget::Source, Source);
	Controller->SetIKRig(ERetargetSourceOrTarget::Target, Target);
	// 5.6 retargeters are an op stack; a new asset has none. Same call VRM4U makes.
	Controller->AddDefaultOps();

	if (FHKCall Map(Controller, TEXT("AutoMapChains")); Map)
	{
		Map.SetEnum(TEXT("AutoMapType"), EnumValue(TEXT("/Script/IKRig.EAutoMapChainType"), TEXT("Fuzzy"), 1));
		Map.SetBool(TEXT("bForceRemap"), true);
		Map.Invoke();
	}
	else
	{
		UE_LOG(LogHK, Warning, TEXT("Player: UIKRetargeterController::AutoMapChains not found; chains keep the default mapping"));
	}
	// Pose the target to match the source rest pose (the UAL rig is not in a VRM T-pose).
	Controller->AutoAlignAllBones(ERetargetSourceOrTarget::Target, ERetargetAutoAlignMethod::ChainToChain);
	SaveAsset(Retargeter);
	return Retargeter;
}

TArray<FAssetData> DuplicateAndRetarget(const TArray<FAssetData>& Assets, USkeletalMesh* Source, USkeletalMesh* Target, UIKRetargeter* Retargeter)
{
	TArray<FAssetData> Result;
	UClass* Class = FindObject<UClass>(nullptr, TEXT("/Script/IKRigEditor.IKRetargetBatchOperation"));
	FHKCall Call(Class ? Class->GetDefaultObject() : nullptr, TEXT("DuplicateAndRetarget"));
	if (!Call)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: UIKRetargetBatchOperation::DuplicateAndRetarget not found"));
		return Result;
	}
	// Parameter names from the 5.6 Python docs (assets_to_retarget, source_mesh, ...).
	TArray<FAssetData>* In = Call.Param<FArrayProperty, TArray<FAssetData>>(TEXT("AssetsToRetarget"));
	if (!In || !Call.SetObject(TEXT("SourceMesh"), Source) || !Call.SetObject(TEXT("TargetMesh"), Target)
		|| !Call.SetObject(TEXT("IKRetargetAsset"), Retargeter))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: DuplicateAndRetarget has unexpected parameters"));
		return Result;
	}
	*In = Assets;
	if (FString* Suffix = Call.Param<FStrProperty, FString>(TEXT("Suffix")))
	{
		*Suffix = RetargetSuffix;
	}
	Call.SetBool(TEXT("bIncludeReferencedAssets"), false);
	Call.Invoke();
	if (TArray<FAssetData>* Out = Call.Param<FArrayProperty, TArray<FAssetData>>(TEXT("ReturnValue")))
	{
		Result = *Out;
	}
	return Result;
}

/** Exact name, else the shortest name ending in "_<Clip>" (so "Idle_Loop" is not "Swim_Idle_Loop"). */
UAnimSequence* FindClip(const TArray<UAnimSequence*>& Anims, const FString& Clip, const FString& Suffix)
{
	if (Clip.IsEmpty())
	{
		return nullptr;
	}
	const FString Exact = Clip + Suffix;
	const FString Tail = TEXT("_") + Exact;
	UAnimSequence* Best = nullptr;
	for (UAnimSequence* Anim : Anims)
	{
		const FString Name = Anim->GetName();
		if (Name.Equals(Exact, ESearchCase::IgnoreCase))
		{
			return Anim;
		}
		if (Name.EndsWith(Tail, ESearchCase::IgnoreCase) && (!Best || Name.Len() < Best->GetName().Len()))
		{
			Best = Anim;
		}
	}
	return Best;
}

// ---------------------------------------------------------------------------------------------
// Figure materials: soft vinyl/PVC look on top of the model's own base-colour texture.

enum class EHKSlotKind : uint8
{
	Skin,
	Hair,
	Eye,
	Line,
	Cloth
};

EHKSlotKind ClassifySlot(const FString& SlotName, const FString& MaterialName)
{
	const FString Key = (SlotName + TEXT(" ") + MaterialName).ToLower();
	auto Has = [&Key](std::initializer_list<const TCHAR*> Words)
	{
		for (const TCHAR* Word : Words)
		{
			if (Key.Contains(Word))
			{
				return true;
			}
		}
		return false;
	};
	// Order matters: VRoid names such as "EyeHighlight", "FaceEyeline", "HairBack".
	if (Has({TEXT("eyeline"), TEXT("eyelash"), TEXT("brow"), TEXT("lash"), TEXT("line")}))
	{
		return EHKSlotKind::Line;
	}
	if (Has({TEXT("eye"), TEXT("iris"), TEXT("highlight"), TEXT("pupil")}))
	{
		return EHKSlotKind::Eye;
	}
	if (Has({TEXT("hair")}))
	{
		return EHKSlotKind::Hair;
	}
	if (Has({TEXT("skin"), TEXT("face"), TEXT("body"), TEXT("mouth")}))
	{
		return EHKSlotKind::Skin;
	}
	return EHKSlotKind::Cloth;
}

UTexture* FindBaseTexture(UMaterialInterface* Material)
{
	const UMaterialInstance* Instance = Cast<UMaterialInstance>(Material);
	if (!Instance)
	{
		return nullptr;
	}
	static const TCHAR* Preferred[] = {
		TEXT("mtoon_tex_maintex"), TEXT("gltf_tex_diffuse"), TEXT("basecolor"), TEXT("base_color"), TEXT("diffuse"),
		TEXT("albedo"), TEXT("maintex"), TEXT("base"), TEXT("color")};
	static const TCHAR* Rejected[] = {
		TEXT("normal"), TEXT("bump"), TEXT("shade"), TEXT("emiss"), TEXT("rough"), TEXT("metal"), TEXT("occlusion"),
		TEXT("mask"), TEXT("matcap"), TEXT("outline"), TEXT("rim"), TEXT("sphere")};
	UTexture* First = nullptr;
	for (const TCHAR* Want : Preferred)
	{
		for (const FTextureParameterValue& Value : Instance->TextureParameterValues)
		{
			const FString Name = Value.ParameterInfo.Name.ToString().ToLower();
			bool bRejected = false;
			for (const TCHAR* Bad : Rejected)
			{
				bRejected |= Name.Contains(Bad);
			}
			if (!Value.ParameterValue || bRejected)
			{
				continue;
			}
			if (!First)
			{
				First = Value.ParameterValue;
			}
			if (Name.Contains(Want))
			{
				return Value.ParameterValue;
			}
		}
	}
	return First;
}

void Add(UMaterial* Material, UMaterialExpression* Expression)
{
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->ExpressionCollection.AddExpression(Expression);
	}
}

UMaterialExpressionScalarParameter* Scalar(UMaterial* Material, const TCHAR* Name, float Default)
{
	UMaterialExpressionScalarParameter* Param = NewObject<UMaterialExpressionScalarParameter>(Material);
	Param->ParameterName = Name;
	Param->DefaultValue = Default;
	Add(Material, Param);
	return Param;
}

UMaterialExpressionVectorParameter* Vector(UMaterial* Material, const TCHAR* Name, const FLinearColor& Default)
{
	UMaterialExpressionVectorParameter* Param = NewObject<UMaterialExpressionVectorParameter>(Material);
	Param->ParameterName = Name;
	Param->DefaultValue = Default;
	Add(Material, Param);
	return Param;
}

UMaterialExpressionMultiply* Multiply(UMaterial* Material, UMaterialExpression* A, int32 AOut, UMaterialExpression* B, int32 BOut)
{
	UMaterialExpressionMultiply* Mul = NewObject<UMaterialExpressionMultiply>(Material);
	Mul->A.Connect(AOut, A);
	Mul->B.Connect(BOut, B);
	Add(Material, Mul);
	return Mul;
}

struct FHKCustomInput
{
	const TCHAR* Name;
	UMaterialExpression* Expression;
};

UMaterialExpressionCustom* Custom(UMaterial* Material, const TCHAR* Description, const FString& Code, ECustomMaterialOutputType Type,
	std::initializer_list<FHKCustomInput> Inputs)
{
	UMaterialExpressionCustom* Node = NewObject<UMaterialExpressionCustom>(Material);
	Node->Description = Description;
	Node->Code = Code;
	Node->OutputType = Type;
	Node->Inputs.Reset();
	for (const FHKCustomInput& Input : Inputs)
	{
		FCustomInput& In = Node->Inputs.AddDefaulted_GetRef();
		In.InputName = Input.Name;
		In.Input.Connect(0, Input.Expression);
	}
	Add(Material, Node);
	return Node;
}

UMaterialExpressionTextureSampleParameter2D* BaseTexture(UMaterial* Material)
{
	UMaterialExpressionTextureSampleParameter2D* Tex = NewObject<UMaterialExpressionTextureSampleParameter2D>(Material);
	Tex->ParameterName = TEXT("BaseTex");
	Tex->Texture = LoadObject<UTexture2D>(nullptr, TEXT("/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture"));
	Tex->SamplerType = SAMPLERTYPE_Color;
	Add(Material, Tex);
	return Tex;
}

UMaterial* FinishMaterial(UMaterial* Material)
{
	bool bNeedsRecompile = false;
	Material->SetMaterialUsage(bNeedsRecompile, MATUSAGE_SkeletalMesh);
	Material->SetMaterialUsage(bNeedsRecompile, MATUSAGE_MorphTargets);
	Material->bAutomaticallySetUsageInEditor = true;
	Material->PreEditChange(nullptr);
	Material->PostEditChange();
	SaveAsset(Material);
	return Material;
}

// Texture sample outputs: 0 RGB, 1 R, 2 G, 3 B, 4 A.
constexpr int32 TexRGB = 0;
constexpr int32 TexA = 4;

/** Subsurface "soft vinyl" master. Rim light and the hair highlight ring go to emissive. */
UMaterial* MakeSoftMaster()
{
	UMaterial* Material = NewAsset<UMaterial>(MaterialDir, TEXT("M_HKFigureSoft"));
	Material->SetShadingModel(MSM_Subsurface);
	Material->BlendMode = BLEND_Masked;
	Material->OpacityMaskClipValue = 0.33f;
	Material->TwoSided = false;

	UMaterialExpressionTextureSampleParameter2D* Tex = BaseTexture(Material);
	UMaterialExpressionVectorParameter* Tint = Vector(Material, TEXT("Tint"), FLinearColor::White);
	UMaterialExpressionMultiply* Base = Multiply(Material, Tex, TexRGB, Tint, 0);
	UMaterialExpressionVectorParameter* SSSColor = Vector(Material, TEXT("SubsurfaceTint"), FLinearColor(1.f, 0.55f, 0.45f));
	UMaterialExpressionMultiply* Sub = Multiply(Material, Base, 0, SSSColor, 0);
	UMaterialExpressionScalarParameter* SSSAmount = Scalar(Material, TEXT("SubsurfaceAmount"), 0.35f);
	UMaterialExpressionScalarParameter* Rough = Scalar(Material, TEXT("Roughness"), 0.42f);
	UMaterialExpressionScalarParameter* Spec = Scalar(Material, TEXT("Specular"), 0.4f);

	UMaterialExpressionVertexNormalWS* Normal = NewObject<UMaterialExpressionVertexNormalWS>(Material);
	UMaterialExpressionCameraVectorWS* View = NewObject<UMaterialExpressionCameraVectorWS>(Material);
	Add(Material, Normal);
	Add(Material, View);
	const FString Code = TEXT(
		"float3 n = normalize(N);\n"
		"float ndv = saturate(dot(n, normalize(V)));\n"
		"float rim = pow(1.0 - ndv, max(RimPower, 0.5)) * RimStrength;\n"
		"float ring = Ring * saturate(1.0 - abs(n.z - RingHeight) * RingSharpness) * saturate(ndv * 2.0);\n"
		"return RimColor * rim + Base * ring * 0.6;");
	UMaterialExpressionCustom* Emissive = Custom(Material, TEXT("HKFigureRim"), Code, CMOT_Float3, {
		{TEXT("Base"), Base},
		{TEXT("N"), Normal},
		{TEXT("V"), View},
		{TEXT("RimColor"), Vector(Material, TEXT("RimColor"), FLinearColor(1.f, 0.93f, 0.88f))},
		{TEXT("RimPower"), Scalar(Material, TEXT("RimPower"), 3.f)},
		{TEXT("RimStrength"), Scalar(Material, TEXT("RimStrength"), 0.12f)},
		{TEXT("Ring"), Scalar(Material, TEXT("HairRing"), 0.f)},
		{TEXT("RingHeight"), Scalar(Material, TEXT("RingHeight"), 0.55f)},
		{TEXT("RingSharpness"), Scalar(Material, TEXT("RingSharpness"), 9.f)}});

	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->BaseColor.Connect(0, Base);
		Editor->SubsurfaceColor.Connect(0, Sub);
		Editor->Opacity.Connect(0, SSSAmount);
		Editor->OpacityMask.Connect(TexA, Tex);
		Editor->Roughness.Connect(0, Rough);
		Editor->Specular.Connect(0, Spec);
		Editor->EmissiveColor.Connect(0, Emissive);
	}
	return FinishMaterial(Material);
}

/** Glossy eye master: sharp specular plus a little self-illumination so eyes read in shadow. */
UMaterial* MakeEyeMaster()
{
	UMaterial* Material = NewAsset<UMaterial>(MaterialDir, TEXT("M_HKFigureEye"));
	Material->BlendMode = BLEND_Masked;
	Material->OpacityMaskClipValue = 0.33f;
	UMaterialExpressionTextureSampleParameter2D* Tex = BaseTexture(Material);
	UMaterialExpressionVectorParameter* Tint = Vector(Material, TEXT("Tint"), FLinearColor::White);
	UMaterialExpressionMultiply* Base = Multiply(Material, Tex, TexRGB, Tint, 0);
	UMaterialExpressionMultiply* Glow = Multiply(Material, Base, 0, Scalar(Material, TEXT("EyeGlow"), 0.25f), 0);
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->BaseColor.Connect(0, Base);
		Editor->EmissiveColor.Connect(0, Glow);
		Editor->OpacityMask.Connect(TexA, Tex);
		Editor->Roughness.Connect(0, Scalar(Material, TEXT("Roughness"), 0.12f));
		Editor->Specular.Connect(0, Scalar(Material, TEXT("Specular"), 0.8f));
	}
	return FinishMaterial(Material);
}

/** Inverted-hull outline for UMeshComponent::SetOverlayMaterial: back faces only, pushed out along the normal. */
UMaterial* MakeOutlineMaterial()
{
	UMaterial* Material = NewAsset<UMaterial>(MaterialDir, TEXT("M_HKFigureOutline"));
	Material->SetShadingModel(MSM_Unlit);
	Material->BlendMode = BLEND_Masked;
	Material->OpacityMaskClipValue = 0.5f;
	Material->TwoSided = true;
	UMaterialExpressionTwoSidedSign* Side = NewObject<UMaterialExpressionTwoSidedSign>(Material);
	Add(Material, Side);
	UMaterialExpressionCustom* BackOnly = Custom(Material, TEXT("HKBackFacesOnly"), TEXT("return S < 0.0 ? 1.0 : 0.0;"), CMOT_Float1, {{TEXT("S"), Side}});
	UMaterialExpressionVertexNormalWS* Normal = NewObject<UMaterialExpressionVertexNormalWS>(Material);
	Add(Material, Normal);
	UMaterialExpressionMultiply* Push = Multiply(Material, Normal, 0, Scalar(Material, TEXT("Thickness"), 0.35f), 0);
	if (UMaterialEditorOnlyData* Editor = Material->GetEditorOnlyData())
	{
		Editor->EmissiveColor.Connect(0, Vector(Material, TEXT("OutlineColor"), FLinearColor(0.09f, 0.05f, 0.04f)));
		Editor->OpacityMask.Connect(0, BackOnly);
		Editor->WorldPositionOffset.Connect(0, Push);
	}
	return FinishMaterial(Material);
}

UMaterialInstanceConstant* MakeSlotInstance(UMaterial* Parent, const FString& Name, EHKSlotKind Kind, UTexture* Texture)
{
	UMaterialInstanceConstant* Instance = NewAsset<UMaterialInstanceConstant>(MaterialDir, Name);
	Instance->SetParentEditorOnly(Parent);
	if (Texture)
	{
		Instance->SetTextureParameterValueEditorOnly(FMaterialParameterInfo(FName(TEXT("BaseTex"))), Texture);
	}
	auto SetScalar = [Instance](const TCHAR* Param, float Value)
	{
		Instance->SetScalarParameterValueEditorOnly(FMaterialParameterInfo(FName(Param)), Value);
	};
	switch (Kind)
	{
	case EHKSlotKind::Skin:
		SetScalar(TEXT("SubsurfaceAmount"), 0.6f);
		SetScalar(TEXT("Roughness"), 0.48f);
		SetScalar(TEXT("RimStrength"), 0.16f);
		break;
	case EHKSlotKind::Hair:
		SetScalar(TEXT("HairRing"), 1.f);
		SetScalar(TEXT("Roughness"), 0.32f);
		SetScalar(TEXT("Specular"), 0.55f);
		break;
	case EHKSlotKind::Line:
		SetScalar(TEXT("SubsurfaceAmount"), 0.f);
		SetScalar(TEXT("RimStrength"), 0.f);
		SetScalar(TEXT("Roughness"), 0.6f);
		break;
	case EHKSlotKind::Cloth:
		SetScalar(TEXT("SubsurfaceAmount"), 0.2f);
		SetScalar(TEXT("Roughness"), 0.55f);
		break;
	case EHKSlotKind::Eye:
		break;
	}
	Instance->PostEditChange();
	SaveAsset(Instance);
	return Instance;
}

void ApplyFigureMaterials(USkeletalMesh* Mesh)
{
	UMaterial* Soft = MakeSoftMaster();
	UMaterial* Eye = MakeEyeMaster();
	TArray<FSkeletalMaterial>& Slots = Mesh->GetMaterials();
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		FSkeletalMaterial& Slot = Slots[Index];
		const FString Original = GetNameSafe(Slot.MaterialInterface);
		const EHKSlotKind Kind = ClassifySlot(Slot.MaterialSlotName.ToString(), Original);
		UTexture* Texture = FindBaseTexture(Slot.MaterialInterface);
		const FString Name = FString::Printf(TEXT("MI_HKFigure_%02d"), Index);
		Slot.MaterialInterface = MakeSlotInstance(Kind == EHKSlotKind::Eye ? Eye : Soft, Name, Kind, Texture);
		UE_LOG(LogHK, Display, TEXT("Player: slot %d %s (%s) -> %s, texture %s"), Index, *Slot.MaterialSlotName.ToString(), *Original,
			Kind == EHKSlotKind::Eye ? TEXT("eye") : Kind == EHKSlotKind::Hair ? TEXT("hair") : Kind == EHKSlotKind::Skin ? TEXT("skin")
				: Kind == EHKSlotKind::Line ? TEXT("line") : TEXT("cloth"),
			*GetNameSafe(Texture));
	}
	Mesh->PostEditChange();
	Mesh->MarkPackageDirty();
}

// ---------------------------------------------------------------------------------------------
// Model import.

struct FHKImportedModel
{
	USkeletalMesh* Mesh = nullptr;
	/** VRM4U's IK rig with mannequin chain names, when the model came from a .vrm. */
	UIKRigDefinition* TargetRig = nullptr;
	FString SourceFile;
};

bool ImportVrm(const FString& File, FHKImportedModel& Out)
{
#if HK_WITH_VRM4U
	FImportOptionData Options;
	// Not a UPROPERTY, so only C++ can set it. Makes VRM4U write IK_<name>_Mannequin.
	Options.bGenerateRigIK = true;
	const FString Base = FPaths::GetBaseFilename(File);
	UVrmAssetListObject* Result = UVrmImporterBPFunctionLibrary::ImportVRMFileWithOptions(File, FString(ModelDir) / Base, Options);
	if (!Result || !Result->SkeletalMesh)
	{
		UE_LOG(LogHK, Error, TEXT("Player: VRM4U could not import %s"), *File);
		return false;
	}
	Out.Mesh = Result->SkeletalMesh;
	for (UIKRigDefinition* Rig : AssetsUnder<UIKRigDefinition>(ModelDir))
	{
		const FString Name = Rig->GetName();
		if (Name.StartsWith(TEXT("IK_")) && Name.EndsWith(TEXT("_Mannequin")) && !Name.StartsWith(TEXT("IK_UEFN_")))
		{
			Out.TargetRig = Rig;
			break;
		}
	}
	if (!Out.TargetRig)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: VRM4U made no IK_*_Mannequin rig; generating one"));
	}
	UEditorLoadingAndSavingUtils::SaveDirtyPackages(false, true);
	return true;
#else
	UE_LOG(LogHK, Error, TEXT("Player: %s is a VRM but VRM4U is not built into this editor. Run tools/get_vrm4u.ps1, regenerate project files and rebuild."), *File);
	return false;
#endif
}

bool ImportModel(const FString& Relative, FHKImportedModel& Out)
{
	const FString File = RepoPath(Relative);
	const FString Ext = FPaths::GetExtension(File).ToLower();
	Out = FHKImportedModel();
	Out.SourceFile = Relative;
	if (Ext == TEXT("vrm"))
	{
		UE_LOG(LogHK, Display, TEXT("Player: importing VRM %s"), *Relative);
		return ImportVrm(File, Out);
	}
	if (Ext != TEXT("glb") && Ext != TEXT("gltf") && Ext != TEXT("fbx"))
	{
		UE_LOG(LogHK, Error, TEXT("Player: %s: use .vrm, .glb, .gltf or .fbx"), *Relative);
		return false;
	}
	UE_LOG(LogHK, Display, TEXT("Player: importing %s"), *Relative);
	if (!ImportFile(File, ModelDir))
	{
		UE_LOG(LogHK, Error, TEXT("Player: import of %s produced nothing"), *Relative);
		return false;
	}
	TArray<USkeletalMesh*> Meshes = AssetsUnder<USkeletalMesh>(ModelDir);
	if (Meshes.IsEmpty())
	{
		UE_LOG(LogHK, Error, TEXT("Player: %s has no skinned mesh"), *Relative);
		return false;
	}
	Out.Mesh = Meshes[0];
	return true;
}

bool IsLfsPointer(const FString& File)
{
	FString Head;
	return IFileManager::Get().FileSize(*File) < 1024 && FFileHelper::LoadFileToString(Head, *File)
		&& Head.StartsWith(TEXT("version https://git-lfs.github.com/spec/"));
}

bool Usable(const FString& Relative)
{
	if (Relative.IsEmpty())
	{
		return false;
	}
	const FString File = RepoPath(Relative);
	if (!FPaths::FileExists(File))
	{
		return false;
	}
	if (IsLfsPointer(File))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: %s is a Git LFS pointer. Run: git lfs pull"), *Relative);
		return false;
	}
	return true;
}

// ---------------------------------------------------------------------------------------------
// Animation.

struct FHKClips
{
	TMap<FString, UAnimSequence*> ByKey;
};

bool RetargetClips(const FHKPlayerConfig& Config, const FHKImportedModel& Model, FHKClips& Out)
{
	if (!Usable(Config.Animations))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: animation file %s is missing; the avatar will hold its reference pose"), *Config.Animations);
		return false;
	}
	if (!ImportFile(RepoPath(Config.Animations), AnimDir))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: import of %s produced nothing"), *Config.Animations);
		return false;
	}
	TArray<USkeletalMesh*> SourceMeshes = AssetsUnder<USkeletalMesh>(AnimDir);
	TArray<UAnimSequence*> SourceAnims = AssetsUnder<UAnimSequence>(AnimDir);
	if (SourceMeshes.IsEmpty() || SourceAnims.IsEmpty())
	{
		UE_LOG(LogHK, Warning, TEXT("Player: %s gave %d meshes and %d clips"), *Config.Animations, SourceMeshes.Num(), SourceAnims.Num());
		return false;
	}
	USkeletalMesh* SourceMesh = SourceMeshes[0];

	TMap<FString, UAnimSequence*> Wanted;
	TArray<FAssetData> ToRetarget;
	for (const TPair<FString, FString>& Clip : Config.Clips)
	{
		if (UAnimSequence* Anim = FindClip(SourceAnims, Clip.Value, FString()))
		{
			Wanted.Add(Clip.Key, Anim);
			ToRetarget.AddUnique(FAssetData(Anim));
		}
		else
		{
			UE_LOG(LogHK, Warning, TEXT("Player: clip %s (%s) is not in %s"), *Clip.Value, *Clip.Key, *Config.Animations);
		}
	}

	UIKRigDefinition* SourceRig = MakeIKRig(TEXT("IK_UAL"), SourceMesh);
	UIKRigDefinition* TargetRig = Model.TargetRig ? Model.TargetRig : MakeIKRig(TEXT("IK_Player"), Model.Mesh);
	if (!SourceRig || !TargetRig)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: no IK rigs, so no retarget. Make them by hand in the editor (docs in data/characters/README.md)."));
		return false;
	}
	UIKRetargeter* Retargeter = MakeRetargeter(SourceRig, TargetRig);
	if (!Retargeter)
	{
		return false;
	}
	const TArray<FAssetData> NewAssets = DuplicateAndRetarget(ToRetarget, SourceMesh, Model.Mesh, Retargeter);
	TArray<UAnimSequence*> Retargeted;
	for (const FAssetData& Data : NewAssets)
	{
		if (UAnimSequence* Anim = Cast<UAnimSequence>(Data.GetAsset()))
		{
			Retargeted.Add(Anim);
		}
	}
	for (const TPair<FString, UAnimSequence*>& Pair : Wanted)
	{
		const FString Name = Pair.Value->GetName();
		for (UAnimSequence* Anim : Retargeted)
		{
			if (Anim->GetName().Equals(Name + RetargetSuffix, ESearchCase::IgnoreCase))
			{
				Out.ByKey.Add(Pair.Key, Anim);
				break;
			}
		}
	}
	UE_LOG(LogHK, Display, TEXT("Player: retargeted %d clips"), Out.ByKey.Num());
	return Out.ByKey.Num() > 0;
}

void FillAvatar(UHKPlayerAvatar* Avatar, const FHKPlayerConfig& Config, const FHKImportedModel& Model, const FHKClips& Clips)
{
	Avatar->Mesh = Model.Mesh;
	Avatar->SourceFile = Model.SourceFile;
	Avatar->MeshYawDeg = Config.MeshYawDeg;

	const FBox Box = Model.Mesh->GetImportedBounds().GetBox();
	const float RawHeight = static_cast<float>(Box.Max.Z - Box.Min.Z);
	const float Scale = (Config.TargetHeightCm > 1.f && RawHeight > 1.f) ? Config.TargetHeightCm / RawHeight : 1.f;
	Avatar->MeshScale = Scale;
	Avatar->HeightCm = RawHeight * Scale;
	Avatar->FootZCm = static_cast<float>(Box.Min.Z) * Scale;

	// Config speeds are for a 180 cm body; a smaller body covers less ground per cycle.
	const float BodyRatio = Avatar->HeightCm / 180.f;
	auto Speed = [&Config, BodyRatio](const TCHAR* Key, float Fallback)
	{
		const float* Value = Config.RefSpeeds.Find(Key);
		return FMath::Max((Value ? *Value : Fallback) * BodyRatio, 10.f);
	};
	Avatar->WalkRefSpeed = Speed(TEXT("walk"), 150.f);
	Avatar->JogRefSpeed = Speed(TEXT("jog"), 340.f);
	Avatar->SprintRefSpeed = Speed(TEXT("sprint"), 560.f);
	Avatar->SwimRefSpeed = Speed(TEXT("swim"), 200.f);

	auto Clip = [&Clips](const TCHAR* Key) -> UAnimSequence*
	{
		UAnimSequence* const* Found = Clips.ByKey.Find(Key);
		return Found ? *Found : nullptr;
	};
	Avatar->Idle = Clip(TEXT("idle"));
	Avatar->Walk = Clip(TEXT("walk"));
	Avatar->Jog = Clip(TEXT("jog"));
	Avatar->Sprint = Clip(TEXT("sprint"));
	Avatar->JumpStart = Clip(TEXT("jump_start"));
	Avatar->JumpLoop = Clip(TEXT("jump_loop"));
	Avatar->Land = Clip(TEXT("land"));
	Avatar->SwimIdle = Clip(TEXT("swim_idle"));
	Avatar->SwimFwd = Clip(TEXT("swim_fwd"));
	Avatar->Sit = Clip(TEXT("sit"));
	Avatar->Drive = Clip(TEXT("drive"));
}
}

bool HKBakePlayer::Bake()
{
	FHKPlayerConfig Config;
	if (!ReadConfig(Config))
	{
		return false;
	}
	// Start clean so a removed or swapped model leaves no stale assets behind.
	if (UEditorAssetLibrary::DoesDirectoryExist(PlayerRoot) && !UEditorAssetLibrary::DeleteDirectory(PlayerRoot))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: could not delete %s; close any open player assets and bake again"), PlayerRoot);
	}

	FHKImportedModel Model;
	bool bImported = false;
	for (const FString& Candidate : {Config.Model, Config.Placeholder})
	{
		if (Usable(Candidate) && ImportModel(Candidate, Model))
		{
			bImported = true;
			break;
		}
	}
	if (!bImported)
	{
		UE_LOG(LogHK, Warning, TEXT("Player: no model found (model %s, placeholder_model %s). The game uses the cube. See data/characters/README.md."),
			*Config.Model, Config.Placeholder.IsEmpty() ? TEXT("(none)") : *Config.Placeholder);
		return false;
	}

	if (Config.Materials.Equals(TEXT("figure"), ESearchCase::IgnoreCase))
	{
		ApplyFigureMaterials(Model.Mesh);
	}

	FHKClips Clips;
	if (!RetargetClips(Config, Model, Clips))
	{
		UE_LOG(LogHK, Warning, TEXT("Player: no retargeted clips; the avatar keeps its reference pose"));
	}

	UHKPlayerAvatar* Avatar = NewAsset<UHKPlayerAvatar>(PlayerRoot, TEXT("DA_PlayerAvatar"));
	FillAvatar(Avatar, Config, Model, Clips);
	if (Config.bOutline)
	{
		Avatar->OutlineMaterial = MakeOutlineMaterial();
	}
	UEditorLoadingAndSavingUtils::SaveDirtyPackages(false, true);
	if (!SaveAsset(Avatar))
	{
		UE_LOG(LogHK, Error, TEXT("Player: could not save %s"), UHKPlayerAvatar::PackagePath());
		return false;
	}
	UE_LOG(LogHK, Display, TEXT("Player: wrote %s from %s (%.0f cm, scale %.3f)"), UHKPlayerAvatar::PackagePath(), *Model.SourceFile,
		Avatar->HeightCm, Avatar->MeshScale);
	return true;
}
