"""ctypes binding for shared/hk_drive_assist.h. Struct layouts are parsed from the header."""

from __future__ import annotations

import ctypes
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "shared" / "hk_drive_assist.h"
SOURCE = Path(__file__).with_name("assist_capi.cpp")
BUILD = ROOT / "tools" / "drive_model" / "_build"

STRUCTS = ("Params", "State", "Input", "Output", "Memory")


def parse_header(text: str | None = None) -> dict[str, list[tuple[str, str]]]:
    """Return {struct: [(type, field), ...]} for the plain structs in the header."""
    text = text if text is not None else HEADER.read_text(encoding="utf-8")
    out: dict[str, list[tuple[str, str]]] = {}
    for name in STRUCTS:
        match = re.search(r"struct\s+" + name + r"\s*\{(.*?)\n\};", text, re.S)
        if not match:
            raise RuntimeError(f"struct {name} not found in {HEADER}")
        fields = re.findall(r"^\s*(float|bool)\s+(\w+)\s*=", match.group(1), re.M)
        out[name] = fields
    return out


def _ctype(kind: str):
    return ctypes.c_float if kind == "float" else ctypes.c_bool


def _make(name: str, fields):
    return type(name, (ctypes.Structure,), {"_fields_": [(f, _ctype(k)) for k, f in fields]})


LAYOUT = parse_header()
Params = _make("Params", LAYOUT["Params"])
State = _make("State", LAYOUT["State"])
Input = _make("Input", LAYOUT["Input"])
Output = _make("Output", LAYOUT["Output"])
Memory = _make("Memory", LAYOUT["Memory"])


def build(compiler: str = "g++") -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    lib = BUILD / "libhkassist.so"
    if not lib.exists() or lib.stat().st_mtime < max(HEADER.stat().st_mtime, SOURCE.stat().st_mtime):
        subprocess.run(
            [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
             "-I", str(ROOT / "shared"), str(SOURCE), "-o", str(lib)],
            check=True,
        )
    return lib


class Assist:
    def __init__(self, params: dict[str, float] | None = None):
        self.lib = ctypes.CDLL(str(build()))
        sizes = (ctypes.c_int * 5)()
        self.lib.hk_sizes(sizes)
        for index, struct in enumerate((Params, State, Input, Output, Memory)):
            if ctypes.sizeof(struct) != sizes[index]:
                raise RuntimeError(f"{struct.__name__} layout mismatch: python {ctypes.sizeof(struct)} vs C++ {sizes[index]}")
        self.params = Params()
        self.memory = Memory()
        self.lib.hk_defaults(ctypes.byref(self.params), ctypes.byref(self.memory))
        for key, value in (params or {}).items():
            if not hasattr(self.params, key):
                raise KeyError(f"unknown assist parameter {key}")
            setattr(self.params, key, value)

    def step(self, state: State, inp: Input, dt: float) -> Output:
        out = Output()
        self.lib.hk_step(ctypes.byref(self.params), ctypes.byref(state), ctypes.byref(inp),
                         ctypes.byref(self.memory), ctypes.c_float(dt), ctypes.byref(out))
        return out
