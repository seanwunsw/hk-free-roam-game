"""Download the pinned VRM4U release for UE 5.8, check its SHA-256 and unzip it.

Same job as tools/get_vrm4u.ps1, for people who prefer Python (or run it on
macOS/Linux to stage the files). The output goes to UnrealProject/Plugins/VRM4U,
which is gitignored.

    python tools/get_vrm4u.py

VRM4U is MIT licensed (c) Haruyoshi Yamamoto, https://github.com/ruyo/VRM4U
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

TAG = "v1.2026.10.17"
ASSET = "VRM4U_5_8_20261017.zip"
SHA256 = "4ab9d363c006a00c6bf10712b6b5fb79e4aad3ee859927f4ae0216e96f677f3f"
URL = f"https://github.com/ruyo/VRM4U/releases/download/{TAG}/{ASSET}"

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "UnrealProject"
PLUGIN = PROJECT / "Plugins" / "VRM4U"
ZIP = ROOT / "data" / "raw" / ASSET

# VRM4U refreshes the Content Browser at the end of every import. Under
# UnrealEditor-Cmd (-run=HKBakeWorld) there is no Slate application and UE 5.8.4
# asserts CurrentApplication.IsValid(). The assets are already saved by then, so
# skip that UI step when running as a commandlet. tools/get_vrm4u.ps1 applies the
# same edit; keep the two strings identical.
PATCH_FILE = Path("Source/VRM4ULoader/Private/LoaderBPFunctionLibrary.cpp")
PATCH_OLD = "if (VRMConverter::IsImportMode()){"
PATCH_NEW = "if (VRMConverter::IsImportMode() && !IsRunningCommandlet()){ // HK patch: no Content Browser in commandlets"


def patch_plugin(plugin: Path) -> bool:
    """Apply the HK commandlet patch to an extracted VRM4U. Idempotent."""
    path = plugin / PATCH_FILE
    text = path.read_text(encoding="utf-8-sig")
    if PATCH_NEW in text:
        return True
    if text.count(PATCH_OLD) != 1:
        print(f"VRM4U patch target not found exactly once in {path}", file=sys.stderr)
        return False
    path.write_text(text.replace(PATCH_OLD, PATCH_NEW), encoding="utf-8")
    return True


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ZIP.parent.mkdir(parents=True, exist_ok=True)
    if not ZIP.exists():
        print(f"Downloading {URL}")
        part = ZIP.with_suffix(".part")
        with urllib.request.urlopen(URL) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f)
        part.replace(ZIP)
    actual = sha256(ZIP)
    if actual != SHA256:
        ZIP.unlink()
        print(f"SHA-256 mismatch: expected {SHA256}, got {actual}. Deleted; run again.", file=sys.stderr)
        return 1
    print(f"SHA-256 OK: {actual}")
    if PLUGIN.exists():
        shutil.rmtree(PLUGIN)
    with zipfile.ZipFile(ZIP) as z:
        for info in z.infolist():
            # The release zip uses Windows separators (Plugins\VRM4U\...).
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            target = (PROJECT / name).resolve()
            if PROJECT.resolve() not in target.parents:
                print(f"Refusing unsafe path in zip: {name}", file=sys.stderr)
                return 1
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    if not (PLUGIN / "VRM4U.uplugin").exists():
        print(f"VRM4U.uplugin not found under {PLUGIN}", file=sys.stderr)
        return 1
    if not patch_plugin(PLUGIN):
        return 1
    (PLUGIN / "HK_VRM4U_VERSION.txt").write_text(f"{TAG} {ASSET} {SHA256}\n")
    print(f"VRM4U {TAG} installed in {PLUGIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
