using UnrealBuildTool;
using System.IO;

public class HKFreeRoamEditor : ModuleRules
{
	public HKFreeRoamEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PrivateIncludePaths.Add(Path.GetFullPath(Path.Combine(ModuleDirectory, "..", "HKFreeRoam")));

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"HKFreeRoam"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"Landscape",
			"MaterialEditor",
			"Json",
			"JsonUtilities",
			"MeshDescription",
			"StaticMeshDescription",
			"SkeletalMeshUtilitiesCommon",
			"AssetRegistry",
			"ChaosVehicles",
			"PhysicsCore",
			"RenderCore",
			"WorldPartition",
			"WorldPartitionEditor",
			"EditorScriptingUtilities"
		});
	}
}
