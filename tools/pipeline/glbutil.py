"""Minimal glTF 2.0 writer.

Vertices are metres, right-handed and Y-up: X east, Y up, Z north.
A trailing HKGM chunk stores primitive byte offsets so the Unreal baker reads
the same BIN chunk with an explicit axis conversion.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np


def _pad(blob: bytes, pad: bytes) -> bytes:
    extra = (-len(blob)) % 4
    return blob + pad * extra if extra else blob


def write_glb(path: Path, primitives: list[dict]) -> None:
    """Each primitive needs positions, normals, uvs, colors, indices and material."""
    blob = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    mesh_prims: list[dict] = []
    hkgm = bytearray(struct.pack("<I", 0))
    written = 0

    def align() -> None:
        extra = (-len(blob)) % 4
        if extra:
            blob.extend(b"\x00" * extra)

    for prim in primitives:
        pos = np.ascontiguousarray(prim["positions"], dtype=np.float32)
        nrm = np.ascontiguousarray(prim["normals"], dtype=np.float32)
        uv = np.ascontiguousarray(prim["uvs"], dtype=np.float32)
        col = np.ascontiguousarray(prim["colors"], dtype=np.float32)
        idx = np.ascontiguousarray(prim["indices"], dtype=np.uint32)
        if pos.shape[0] == 0 or idx.shape[0] == 0:
            continue
        align()
        vert_off = len(blob)
        vert_count = int(pos.shape[0])
        blob.extend(pos.tobytes())
        nrm_off = len(blob)
        blob.extend(nrm.tobytes())
        uv_off = len(blob)
        blob.extend(uv.tobytes())
        col_off = len(blob)
        blob.extend(col.tobytes())
        align()
        idx_off = len(blob)
        index_count = int(idx.shape[0])
        blob.extend(idx.tobytes())

        def add_view(offset: int, length: int, target: int) -> int:
            buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": length, "target": target})
            return len(buffer_views) - 1

        def add_acc(view: int, gl_type: str, component: int, count: int, mins=None, maxs=None) -> int:
            item = {"bufferView": view, "byteOffset": 0, "componentType": component, "count": count, "type": gl_type}
            if mins is not None:
                item["min"] = [float(v) for v in mins]
                item["max"] = [float(v) for v in maxs]
            accessors.append(item)
            return len(accessors) - 1

        v_pos = add_view(vert_off, vert_count * 12, 34962)
        v_nrm = add_view(nrm_off, vert_count * 12, 34962)
        v_uv = add_view(uv_off, vert_count * 8, 34962)
        v_col = add_view(col_off, vert_count * 16, 34962)
        v_idx = add_view(idx_off, index_count * 4, 34963)
        a_pos = add_acc(v_pos, "VEC3", 5126, vert_count, pos.min(axis=0), pos.max(axis=0))
        a_nrm = add_acc(v_nrm, "VEC3", 5126, vert_count)
        a_uv = add_acc(v_uv, "VEC2", 5126, vert_count)
        a_col = add_acc(v_col, "VEC4", 5126, vert_count)
        a_idx = add_acc(v_idx, "SCALAR", 5125, index_count)
        mesh_prims.append(
            {
                "attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv, "COLOR_0": a_col},
                "indices": a_idx,
                "material": int(prim.get("material", 0)),
                "mode": 4,
            }
        )
        hkgm.extend(struct.pack("<6I", vert_off, vert_count, idx_off, index_count, 1, int(prim.get("material", 0))))
        written += 1

    struct.pack_into("<I", hkgm, 0, written)
    document = {
        "asset": {"version": "2.0", "generator": "hk-free-roam-pipeline"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": path.stem}],
        "materials": [
            {"name": "Facade", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.68, 0.64, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85}},
            {"name": "Road", "pbrMetallicRoughness": {"baseColorFactor": [0.12, 0.12, 0.13, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.92}},
            {"name": "Water", "pbrMetallicRoughness": {"baseColorFactor": [0.05, 0.25, 0.35, 0.75], "metallicFactor": 0.0, "roughnessFactor": 0.15}, "alphaMode": "BLEND"},
        ],
        "meshes": [{"name": path.stem, "primitives": mesh_prims}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(blob)}],
        "extras": {"hk_x": "east", "hk_y": "up", "hk_z": "north", "hk_unit": "metre"},
    }
    json_bytes = _pad(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    bin_bytes = _pad(bytes(blob), b"\x00")
    hkgm_bytes = _pad(bytes(hkgm), b"\x00")
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes) + 8 + len(hkgm_bytes)
    out = bytearray()
    out.extend(struct.pack("<4sII", b"glTF", 2, total))
    out.extend(struct.pack("<I4s", len(json_bytes), b"JSON"))
    out.extend(json_bytes)
    out.extend(struct.pack("<I4s", len(bin_bytes), b"BIN\x00"))
    out.extend(bin_bytes)
    out.extend(struct.pack("<I4s", len(hkgm_bytes), b"HKGM"))
    out.extend(hkgm_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)


def read_hkgm_primitives(path: Path) -> list[dict]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not a glb")
    length = struct.unpack_from("<I", data, 8)[0]
    offset = 12
    json_bytes = b""
    bin_bytes = b""
    hkgm = b""
    while offset + 8 <= len(data) and offset < length:
        chunk_len, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        payload = data[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == b"JSON":
            json_bytes = payload
        elif chunk_type == b"BIN\x00":
            bin_bytes = payload
        elif chunk_type == b"HKGM":
            hkgm = payload
    json.loads(json_bytes.decode("utf-8").rstrip())
    if not hkgm:
        raise ValueError("missing HKGM chunk")
    (count,) = struct.unpack_from("<I", hkgm, 0)
    prims = []
    cursor = 4
    for _ in range(count):
        vert_off, vert_count, idx_off, index_count, flags, material = struct.unpack_from("<6I", hkgm, cursor)
        cursor += 24
        pos = np.frombuffer(bin_bytes, dtype=np.float32, count=vert_count * 3, offset=vert_off).reshape(-1, 3).copy()
        nrm = np.frombuffer(bin_bytes, dtype=np.float32, count=vert_count * 3, offset=vert_off + vert_count * 12).reshape(-1, 3).copy()
        uv = np.frombuffer(bin_bytes, dtype=np.float32, count=vert_count * 2, offset=vert_off + vert_count * 24).reshape(-1, 2).copy()
        col = np.frombuffer(bin_bytes, dtype=np.float32, count=vert_count * 4, offset=vert_off + vert_count * 32).reshape(-1, 4).copy()
        indices = np.frombuffer(bin_bytes, dtype=np.uint32, count=index_count, offset=idx_off).copy()
        prims.append(
            {
                "positions": pos,
                "normals": nrm,
                "uvs": uv,
                "colors": col,
                "indices": indices,
                "material": int(material),
                "flags": int(flags),
            }
        )
    return prims
