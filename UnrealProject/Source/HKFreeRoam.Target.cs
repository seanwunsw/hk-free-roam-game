using UnrealBuildTool;
using System.Collections.Generic;

public class HKFreeRoamTarget : TargetRules
{
	public HKFreeRoamTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("HKFreeRoam");
	}
}
