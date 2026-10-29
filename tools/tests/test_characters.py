"""Player character data: config, CC0 clips, credits, placeholder isolation and removal."""

from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.characters import remove_placeholder  # noqa: E402
from tools.characters.trim_glb import read_glb, trim, write_glb  # noqa: E402

CONFIG = ROOT / "data" / "config" / "player.json"
CREDITS = ROOT / "data" / "characters" / "CREDITS.md"
BEGIN = "<!-- BEGIN placeholder-credit -->"
END = "<!-- END placeholder-credit -->"
# Files allowed to name the placeholder (see AGENTS.md).
ALLOWED = {
    "data/config/player.json",
    "data/characters/CREDITS.md",
    "data/characters/README.md",
    "tools/characters/remove_placeholder.py",
}
KEY_BONES = ["root", "pelvis", "spine_01", "head", "hand_l", "hand_r", "foot_l", "foot_r"]


def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def animations_glb() -> Path:
    path = ROOT / config()["animations"]
    if not path.exists():
        pytest.skip(f"{path} missing")
    if path.read_bytes()[:4] != b"glTF":
        pytest.skip(f"{path} is a Git LFS pointer; run git lfs pull")
    return path


def test_config_keys() -> None:
    cfg = config()
    for key in ("model", "animations", "clips", "anim_ref_speed_cm_s", "target_height_cm", "mesh_yaw_deg", "materials"):
        assert key in cfg, key
    assert cfg["model"].endswith(".vrm")
    assert cfg["materials"] in ("figure", "imported")
    assert 60 <= cfg["target_height_cm"] <= 200
    speeds = cfg["anim_ref_speed_cm_s"]
    assert 0 < speeds["walk"] < speeds["jog"] < speeds["sprint"]
    for key in ("idle", "walk", "jog", "sprint", "jump_start", "jump_loop", "swim_idle", "swim_fwd"):
        assert key in cfg["clips"], key


def test_placeholder_is_one_key_in_one_folder() -> None:
    cfg = config()
    placeholder = cfg.get("placeholder_model")
    if placeholder is None:
        return  # already removed
    assert placeholder.startswith("data/characters/placeholder/")
    assert Path(placeholder).suffix in (".glb", ".gltf", ".fbx")


def test_clips_exist_in_animation_glb() -> None:
    doc, _ = read_glb(animations_glb())
    names = {a["name"] for a in doc["animations"]}
    for key, clip in config()["clips"].items():
        assert clip in names, f"{key}: {clip}"


def test_animation_skeleton() -> None:
    doc, _ = read_glb(animations_glb())
    assert len(doc["skins"]) == 1
    joints = doc["skins"][0]["joints"]
    assert len(joints) == 65
    joint_names = {doc["nodes"][j]["name"].lower() for j in joints}  # UAL uses "Head"
    for bone in KEY_BONES:
        assert bone in joint_names, bone


def test_trim_round_trip(tmp_path: Path) -> None:
    src = animations_glb()
    doc, binary = read_glb(src)
    keep = ["Idle_Loop", "Walk_Loop"]
    new_doc, new_bin = trim(doc, binary, keep)
    out = tmp_path / "t.glb"
    write_glb(out, new_doc, new_bin)
    back, back_bin = read_glb(out)
    assert [a["name"] for a in back["animations"]] == keep
    assert len(back["skins"][0]["joints"]) == 65
    assert len(back_bin) < len(binary)
    # Every buffer view still fits inside the binary chunk.
    for view in back["bufferViews"]:
        assert view.get("byteOffset", 0) + view["byteLength"] <= len(back_bin)
    magic, version, length = struct.unpack_from("<III", out.read_bytes())
    assert magic == 0x46546C67 and version == 2 and length == out.stat().st_size


def test_credits() -> None:
    text = CREDITS.read_text(encoding="utf-8")
    assert "Quaternius" in text and "CC0" in text
    assert "VRM4U" in text
    if "placeholder_model" in config():
        assert text.count(BEGIN) == 1 and text.count(END) == 1
        assert text.index(BEGIN) < text.index(END)
        assert "CC BY 4.0" in text[text.index(BEGIN):text.index(END)]


def test_placeholder_isolation() -> None:
    remove_placeholder.set_root(ROOT)
    hits = []
    for path in remove_placeholder.tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or rel.startswith("data/characters/placeholder/") or not path.is_file():
            continue
        if any(p in rel.lower() for p in remove_placeholder.LEFTOVER_PATTERNS):
            hits.append(rel)
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        if any(p in text for p in remove_placeholder.LEFTOVER_PATTERNS):
            hits.append(rel)
    assert not hits, hits


def test_remove_placeholder_on_copy(tmp_path: Path) -> None:
    for rel in ("data/config/player.json", "data/characters", "docs/characters", "tools/characters/remove_placeholder.py"):
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    placeholder_dir = tmp_path / "data" / "characters" / "placeholder"
    placeholder_dir.mkdir(parents=True, exist_ok=True)
    (placeholder_dir / "model.glb").write_bytes(b"glTF")
    baked = tmp_path / "UnrealProject" / "Content" / "HK" / "Player"
    baked.mkdir(parents=True)
    (baked / "DA_PlayerAvatar.uasset").write_bytes(b"x")
    try:
        assert remove_placeholder.main(["--root", str(tmp_path), "--dry-run"]) == 0
        assert placeholder_dir.exists()
        assert remove_placeholder.main(["--root", str(tmp_path)]) == 0
        assert not placeholder_dir.exists()
        assert not baked.exists()
        cfg = json.loads((tmp_path / "data" / "config" / "player.json").read_text(encoding="utf-8"))
        assert "placeholder_model" not in cfg
        assert cfg["model"] == config()["model"]
        credits = (tmp_path / "data" / "characters" / "CREDITS.md").read_text(encoding="utf-8")
        assert BEGIN not in credits and END not in credits
        assert "Quaternius" in credits
        assert remove_placeholder.main(["--root", str(tmp_path), "--check"]) == 0
    finally:
        remove_placeholder.set_root(ROOT)


def test_vroid_guide_and_concept() -> None:
    image = ROOT / "docs" / "characters" / "player-concept.jpg"
    assert image.read_bytes()[:3] == b"\xff\xd8\xff"
    guide = (ROOT / "docs" / "characters" / "VROID.md").read_text(encoding="utf-8")
    assert "player-concept.jpg" in guide
    assert "data/characters/player.vrm" in guide
    for colour in ("#B8662A", "#C8282E", "#7A5236"):
        assert colour in guide
    swap = (ROOT / "data" / "characters" / "README.md").read_text(encoding="utf-8")
    assert "docs/characters/VROID.md" in swap
    assert "VROID.md" in (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
