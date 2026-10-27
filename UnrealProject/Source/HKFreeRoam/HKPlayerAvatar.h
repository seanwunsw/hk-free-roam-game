#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "HKPlayerAvatar.generated.h"

class UAnimSequence;
class UMaterialInterface;
class USkeletalMesh;

/**
 * Everything the on-foot player needs to look and move like the imported
 * character. Written by the bake (HKBakePlayer::Bake) to a fixed path,
 * read by AHKFreeRoamCharacter::BeginPlay. Missing asset = cube fallback.
 */
UCLASS(BlueprintType)
class HKFREEROAM_API UHKPlayerAvatar : public UDataAsset
{
	GENERATED_BODY()

public:
	/** Package and object path the bake writes and the game loads. */
	static const TCHAR* PackagePath() { return TEXT("/Game/HK/Player/DA_PlayerAvatar"); }
	static const TCHAR* ObjectPath() { return TEXT("/Game/HK/Player/DA_PlayerAvatar.DA_PlayerAvatar"); }

	UPROPERTY(EditAnywhere, Category = "Mesh")
	TObjectPtr<USkeletalMesh> Mesh;

	/** Repo-relative source file, for logs only. */
	UPROPERTY(EditAnywhere, Category = "Mesh")
	FString SourceFile;

	/** Uniform scale applied on the mesh component. */
	UPROPERTY(EditAnywhere, Category = "Mesh")
	float MeshScale = 1.f;

	/** Height of the scaled mesh in cm. Drives capsule and camera. */
	UPROPERTY(EditAnywhere, Category = "Mesh")
	float HeightCm = 120.f;

	/** Lowest point of the scaled mesh, in component space (cm). */
	UPROPERTY(EditAnywhere, Category = "Mesh")
	float FootZCm = 0.f;

	UPROPERTY(EditAnywhere, Category = "Mesh")
	float MeshYawDeg = -90.f;

	/** Optional inverted-hull outline, set as the mesh overlay material. */
	UPROPERTY(EditAnywhere, Category = "Mesh")
	TObjectPtr<UMaterialInterface> OutlineMaterial;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Idle;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Walk;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Jog;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Sprint;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> JumpStart;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> JumpLoop;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Land;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> SwimIdle;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> SwimFwd;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Sit;

	UPROPERTY(EditAnywhere, Category = "Anim")
	TObjectPtr<UAnimSequence> Drive;

	/** Ground speed (cm/s) at which each clip's feet do not slide, already scaled to HeightCm. */
	UPROPERTY(EditAnywhere, Category = "Anim")
	float WalkRefSpeed = 100.f;

	UPROPERTY(EditAnywhere, Category = "Anim")
	float JogRefSpeed = 227.f;

	UPROPERTY(EditAnywhere, Category = "Anim")
	float SprintRefSpeed = 373.f;

	UPROPERTY(EditAnywhere, Category = "Anim")
	float SwimRefSpeed = 133.f;
};
