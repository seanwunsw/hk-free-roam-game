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
			"WorldPartitionEditor",
			"EditorScriptingUtilities",
			"AssetTools",
			"IKRig",
			"IKRigEditor",
			// RetargetEditor headers pull in STableRow/SBorder; their attribute
			// registration lives in these two modules (LNK2019 on UE 5.8.4 without them).
			"Slate",
			"SlateCore"
		});

		// VRM4U is optional and gitignored (tools/get_vrm4u.ps1 fetches it). Link it only when
		// it is on disk, so a clone without it still builds; the bake then skips .vrm files.
		string Vrm4uPlugin = Path.Combine(ModuleDirectory, "..", "..", "Plugins", "VRM4U", "VRM4U.uplugin");
		if (File.Exists(Vrm4uPlugin))
		{
			PrivateDependencyModuleNames.AddRange(new string[] { "VRM4U", "VRM4UImporter" });
			PrivateDefinitions.Add("HK_WITH_VRM4U=1");
		}
		else
		{
			PrivateDefinitions.Add("HK_WITH_VRM4U=0");
		}
	}
}
