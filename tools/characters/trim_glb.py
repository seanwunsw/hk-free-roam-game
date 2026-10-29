"""Write a smaller copy of a skinned glTF binary (.glb) that keeps only some animations.

Used to cut the CC0 Quaternius "Universal Animation Library" (UAL1_Standard.glb,
43 clips) down to the clips the player needs, so the repo stays small.

    python tools/characters/trim_glb.py SRC.glb DST.glb --keep Idle_Loop Walk_Loop ...

Nodes, meshes, skins and materials are kept as they are. Only the animation
list shrinks, and any accessor or buffer view that nothing references any more
is dropped. Buffer views are copied byte for byte, so the kept data is
identical to the source.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError(f"{path} is not a glTF 2.0 binary")
    offset = 12
    doc: dict | None = None
    binary = b""
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + chunk_len]
        if chunk_type == CHUNK_JSON:
            doc = json.loads(chunk.decode("utf-8"))
        elif chunk_type == CHUNK_BIN:
            binary = chunk
        offset += 8 + chunk_len
    if doc is None:
        raise ValueError(f"{path} has no JSON chunk")
    return doc, binary


def write_glb(path: Path, doc: dict, binary: bytes) -> None:
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    out = struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(js), CHUNK_JSON) + js
    out += struct.pack("<II", len(binary), CHUNK_BIN) + binary
    path.write_bytes(out)


def used_accessors(doc: dict) -> set[int]:
    used: set[int] = set()
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            used.update(prim.get("attributes", {}).values())
            if "indices" in prim:
                used.add(prim["indices"])
            for target in prim.get("targets", []):
                used.update(target.values())
    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            used.add(skin["inverseBindMatrices"])
    for anim in doc.get("animations", []):
        for sampler in anim.get("samplers", []):
            used.add(sampler["input"])
            used.add(sampler["output"])
    return used


def trim(doc: dict, binary: bytes, keep: list[str]) -> tuple[dict, bytes]:
    names = [a.get("name", "") for a in doc.get("animations", [])]
    missing = [k for k in keep if k not in names]
    if missing:
        raise KeyError(f"animations not in source: {missing}")
    doc = json.loads(json.dumps(doc))
    doc["animations"] = [a for a in doc["animations"] if a.get("name") in keep]
    doc["animations"].sort(key=lambda a: keep.index(a["name"]))

    if any("uri" in b for b in doc.get("buffers", [])) or len(doc.get("buffers", [])) != 1:
        raise ValueError("only single-buffer .glb files are supported")
    for img in doc.get("images", []):
        if "bufferView" in img:
            raise ValueError("embedded images are not supported by this trimmer")
    for acc in doc["accessors"]:
        if "sparse" in acc:
            raise ValueError("sparse accessors are not supported by this trimmer")

    acc_keep = sorted(used_accessors(doc))
    acc_map = {old: new for new, old in enumerate(acc_keep)}
    view_keep = sorted({doc["accessors"][i]["bufferView"] for i in acc_keep if "bufferView" in doc["accessors"][i]})
    view_map: dict[int, int] = {}
    new_views = []
    new_bin = bytearray()
    for old in view_keep:
        view = dict(doc["bufferViews"][old])
        start = view.get("byteOffset", 0)
        chunk = binary[start : start + view["byteLength"]]
        new_bin += b"\0" * (-len(new_bin) % 4)
        view["buffer"] = 0
        view["byteOffset"] = len(new_bin)
        new_bin += chunk
        view_map[old] = len(new_views)
        new_views.append(view)

    new_accessors = []
    for old in acc_keep:
        acc = dict(doc["accessors"][old])
        if "bufferView" in acc:
            acc["bufferView"] = view_map[acc["bufferView"]]
        new_accessors.append(acc)

    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            prim["attributes"] = {k: acc_map[v] for k, v in prim.get("attributes", {}).items()}
            if "indices" in prim:
                prim["indices"] = acc_map[prim["indices"]]
            prim["targets"] = [{k: acc_map[v] for k, v in t.items()} for t in prim.get("targets", [])]
            if not prim["targets"]:
                del prim["targets"]
    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            skin["inverseBindMatrices"] = acc_map[skin["inverseBindMatrices"]]
    for anim in doc["animations"]:
        for sampler in anim["samplers"]:
            sampler["input"] = acc_map[sampler["input"]]
            sampler["output"] = acc_map[sampler["output"]]

    doc["accessors"] = new_accessors
    doc["bufferViews"] = new_views
    doc["buffers"] = [{"byteLength": len(new_bin) + (-len(new_bin) % 4)}]
    doc.setdefault("asset", {})["extras"] = {
        "hk_trimmed_by": "tools/characters/trim_glb.py",
        "hk_kept_animations": keep,
    }
    return doc, bytes(new_bin)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    parser.add_argument("--keep", nargs="+", required=True, help="animation names to keep, in order")
    args = parser.parse_args(argv)
    doc, binary = read_glb(args.src)
    doc, binary = trim(doc, binary, args.keep)
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    write_glb(args.dst, doc, binary)
    print(f"wrote {args.dst} ({args.dst.stat().st_size} bytes, {len(doc['animations'])} animations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
