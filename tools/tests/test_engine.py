"""Engine version pins: the VRM4U fetch scripts and renderer config follow the .uproject.

EngineAssociation is the only place the engine version is written (AGENTS.md), so the tests
read it from there instead of repeating it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import get_vrm4u  # noqa: E402

UPROJECT = ROOT / "UnrealProject" / "HKFreeRoam.uproject"
PS1 = ROOT / "tools" / "get_vrm4u.ps1"
ENGINE_INI = ROOT / "UnrealProject" / "Config" / "DefaultEngine.ini"

# VRM4U v1.2026.10.17, VRM4U_5_8_20261017.zip: 68,577,272 bytes. Hash computed from the download and
# equal to the "digest" field of the GitHub release asset.
VRM4U_SHA256 = "4ab9d363c006a00c6bf10712b6b5fb79e4aad3ee859927f4ae0216e96f677f3f"


def ps1_value(name: str) -> str:
    match = re.search(rf'^\${name}\s*=\s*"([^"]+)"', PS1.read_text(encoding="utf-8"), re.M)
    assert match, name
    return match.group(1)


def engine() -> str:
    return json.loads(UPROJECT.read_text(encoding="utf-8"))["EngineAssociation"]


def test_vrm4u_matches_engine() -> None:
    # VRM4U ships one zip per engine minor version: VRM4U_<major>_<minor>_<date>.zip.
    assert get_vrm4u.ASSET.startswith(f"VRM4U_{engine().replace('.', '_')}_")
    assert get_vrm4u.SHA256 == VRM4U_SHA256
    assert get_vrm4u.TAG in get_vrm4u.URL and get_vrm4u.ASSET in get_vrm4u.URL


def test_vrm4u_scripts_agree() -> None:
    assert ps1_value("Tag") == get_vrm4u.TAG
    assert ps1_value("Asset") == get_vrm4u.ASSET
    assert ps1_value("Sha256") == get_vrm4u.SHA256


def test_substrate_explicit() -> None:
    lines = [line.strip() for line in ENGINE_INI.read_text(encoding="utf-8").splitlines()]
    section = lines[lines.index("[/Script/Engine.RendererSettings]") + 1:]
    section = section[:next((i for i, line in enumerate(section) if line.startswith("[")), len(section))]
    assert "r.Substrate=False" in section


def test_vrm4u_patch_is_idempotent(tmp_path):
    from tools import get_vrm4u as g

    src = tmp_path / g.PATCH_FILE
    src.parent.mkdir(parents=True)
    src.write_text("a\n\tif (VRMConverter::IsImportMode()){\n\t\tUI();\n\t}\n", encoding="utf-8")
    assert g.patch_plugin(tmp_path)
    once = src.read_text(encoding="utf-8")
    assert g.PATCH_NEW in once and once.count("IsImportMode") == 1
    assert g.patch_plugin(tmp_path)
    assert src.read_text(encoding="utf-8") == once


def test_vrm4u_patch_strings_match_ps1():
    from tools import get_vrm4u as g

    ps1 = (g.ROOT / "tools" / "get_vrm4u.ps1").read_text(encoding="utf-8")
    assert f'"{g.PATCH_OLD}"' in ps1 and f'"{g.PATCH_NEW}"' in ps1
