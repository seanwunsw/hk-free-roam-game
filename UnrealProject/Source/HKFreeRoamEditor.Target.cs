using UnrealBuildTool;
using System.Collections.Generic;

public class HKFreeRoamEditorTarget : TargetRules
{
	public HKFreeRoamEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("HKFreeRoam");
		ExtraModuleNames.Add("HKFreeRoamEditor");
	}
}
