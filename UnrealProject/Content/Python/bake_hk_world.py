"""Bake the fixed Hong Kong world from data/processed.

Run from Unreal Editor (Python) or:

    UnrealEditor-Cmd.exe HKFreeRoam.uproject -ExecutePythonScript=Content/Python/bake_hk_world.py -unattended -AllowCommandletRendering -nosplash

The commandlet -run=HKBakeWorld calls the same function.
"""

import unreal


def main() -> None:
    unreal.log("HK bake start")
    ok = unreal.HKBakeLibrary.bake_world()
    if not ok:
        raise RuntimeError("HKBakeLibrary.bake_world returned false")
    unreal.log("HK bake finished")


if __name__ == "__main__":
    main()
