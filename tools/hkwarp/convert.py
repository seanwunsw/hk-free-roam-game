"""Convert between WGS84 and Unreal centimetres (the coordinates shown in the editor).

Examples (from the repository root, after the pipeline has been run):

    python tools/hkwarp/convert.py --lat 22.2849 --lon 114.1583
    python tools/hkwarp/convert.py --x-cm 0 --y-cm 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hkwarp.warp import default_lut_path, load_warp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Hong Kong lat/lon <-> Unreal centimetres")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--x-cm", type=float)
    parser.add_argument("--y-cm", type=float)
    parser.add_argument("--lut", type=Path, default=None)
    args = parser.parse_args()
    warp = load_warp(args.lut) if args.lut else load_warp()
    lut = args.lut or default_lut_path()
    source = str(lut) if lut.exists() else "data/config/world.json (lut not built yet)"
    print(f"source: {source}")
    print("axes: Unreal centimetres, +X east, +Y south (north is -Y); Z is up and is not part of the warp")
    if args.lat is not None or args.lon is not None:
        if args.lat is None or args.lon is None:
            parser.error("--lat and --lon are required together")
        x_cm, y_cm = warp.lonlat_to_unreal_cm(args.lon, args.lat)
        print(f"lat {args.lat:.8f} lon {args.lon:.8f} -> x_cm {x_cm:.3f} y_cm {y_cm:.3f}")
        return 0
    if args.x_cm is not None or args.y_cm is not None:
        if args.x_cm is None or args.y_cm is None:
            parser.error("--x-cm and --y-cm are required together")
        lon, lat = warp.unreal_cm_to_lonlat(args.x_cm, args.y_cm)
        print(f"x_cm {args.x_cm:.3f} y_cm {args.y_cm:.3f} -> lat {float(lat):.8f} lon {float(lon):.8f}")
        return 0
    parser.error("pass --lat/--lon or --x-cm/--y-cm")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
