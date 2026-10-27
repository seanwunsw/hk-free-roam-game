# AGENTS.md

This repository is a fixed-layout Hong Kong free-roam prototype for Unreal Engine. The engine version is the `EngineAssociation` field in `UnrealProject/HKFreeRoam.uproject`. Do not hardcode that version anywhere else.

## Layout

- `tools/` — Python pipeline. `python tools/run_pipeline.py` from the repo root rebuilds `data/processed`.
- `data/config/world.json` — the only gameplay-scale config (warp knots, harbour, landscape, places).
- `data/processed/` — committed bake inputs: heightmap, glTF tiles, spawns, warp LUT, minimap, previews.
- `data/raw/` — downloaded OSM and SRTM. Gitignored. URLs are in `data/README.md`.
- `shared/hk_warp.h` — header-only LUT evaluator. Python writes the LUT; C++ does not duplicate the scale curves.
- `UnrealProject/` — runtime gameplay and the editor bake commandlet. Runtime code must not generate the map.

## Rules that are easy to break

- The map is baked once. Cars, helicopters, helipads, roads and buildings are placed actors. Do not spawn the city at runtime.
- The warp is separable and monotone. Do not "fix" island scale with a folding 2D field. TST's north-south scale above 1 is the harbour constraint.
- Tunnels are open cuts clamped above the water plane. Do not pretend they are bored tunnels.
- Building meshes are one glTF primitive per building. Collision boxes are per primitive, after the final static-mesh build.
- glTF is Y-up metres (X east, Y up, Z north). Unreal is centimetres, X east, Y north, Z up. Fix winding per triangle; a global flip is wrong.
- Chaos `SpringRate` is N/m. The car uses 45000, not a unitless 150.
- Landscape `Import` keys both height and layer maps with the same non-empty `FGuid`. Subsection size is 63 quads and there is 1 section per component. `bCanHaveLayersContent` stays false.
- Committed `DefaultEngine.ini` points at the engine template map so the editor opens before the bake. The bake rewrites the startup map to `/Game/Maps/HKWorld`.
- Do not `ConstructorHelpers`-load `/Game/HK/Vehicles/SK_HKCar`. The baker assigns it; `BeginPlay` has a `LoadObject` fallback.
- Parked helicopters disable gravity. Parked cars hold the handbrake. Neither should be simulated in a constructor.
- `data/raw` stays untracked. Pipeline outputs are Git LFS (`*.glb`, `*.r16`, `*.png`).

## What this environment cannot verify

There is no Unreal Editor or MSVC here. Do not claim the project was compiled or played. Say so in `docs/STATUS.md`. Python tests and the pipeline can be run:

```bash
python -m pytest tools/tests -q
python tools/run_pipeline.py
g++ -std=c++20 -O2 -Wall -Wextra -I shared -o /tmp/test_hk_warp tools/tests/test_hk_warp.cpp
/tmp/test_hk_warp data/processed/warp_lut.bin data/processed/golden_warp.csv
```
