"""Download the pinned VRM4U release for UE 5.6, check its SHA-256 and unzip it.

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
ASSET = "VRM4U_5_6_20261017.zip"
SHA256 = "bf13ca417daa22fcbbff7e16f4b8103c4dbba65091be94a0c0067f2f53e032db"
URL = f"https://github.com/ruyo/VRM4U/releases/download/{TAG}/{ASSET}"

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "UnrealProject"
PLUGIN = PROJECT / "Plugins" / "VRM4U"
ZIP = ROOT / "data" / "raw" / ASSET


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
    (PLUGIN / "HK_VRM4U_VERSION.txt").write_text(f"{TAG} {ASSET} {SHA256}\n")
    print(f"VRM4U {TAG} installed in {PLUGIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
