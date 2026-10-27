using UnrealBuildTool;
using System.IO;

public class HKFreeRoam : ModuleRules
{
	public HKFreeRoam(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicIncludePaths.Add(Path.GetFullPath(Path.Combine(ModuleDirectory, "..", "..", "..", "shared")));

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"ChaosVehicles",
			"PhysicsCore",
			"Json",
			"JsonUtilities",
			"ImageWrapper"
		});
	}
}
