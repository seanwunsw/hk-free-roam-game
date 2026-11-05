# Performance

This machine has no Unreal Editor and no MSVC. Nothing below was compiled, baked, or played here. The "before" numbers are the ones reported from PIE on the Windows machine. The "after" column stays empty until that machine measures a standalone run.

## Before

| | |
| --- | --- |
| Steady PIE | about 120 FPS or higher, average, unprofiled |
| First load only | about 7 FPS, while meshes built and the DDC filled |
| Feature level in that log | `Highest Feature Level of D3D12: SM5` |
| Where | Tuen Mun. `player_start` is on `TuenMun` |

That steady figure is the SM5 fallback. Nanite and virtual shadow maps do not run at SM5, so it is not a measurement of the settings below. PIE also includes the editor. Prefer the standalone `-game` launch in the protocol.

## After

TODO. Fill this in from the median of three standalone runs after the first launch has been discarded. Report the numbers in the checklist at the bottom.

## What this branch changes

The branch is based on `fix/road-collision` (`6fd9bbe`). That branch already targets D3D12 Shader Model 6 (`-D3D12TargetedShaderFormats=PCD3D_SM5`, `+D3D12TargetedShaderFormats=PCD3D_SM6`), makes road tiles non-Nanite, and fully loads an existing package in `ReplaceObject` before saving a re-baked tile. This branch does not edit those lines or that bake code.

`HardwareTargeting` stays `Maximum`. `AppliedDefaultGraphicsPerformance` already matches, so the editor does not stamp Epic again. Gameplay quality is applied in `BeginPlay`.

### Software Lumen and mesh distance fields

`Config/DefaultEngine.ini`, `[/Script/Engine.RendererSettings]`:

| Key | Value | Why |
| --- | --- | --- |
| `r.Lumen.HardwareRayTracing` | `False` (already set) | Software Lumen. Hardware ray tracing stays off. |
| `r.Lumen.TraceMeshSDFs` | `0` | Global Distance Field traces. `1` is detail tracing against each mesh distance field. [Lumen Technical Details](https://dev.epicgames.com/documentation/unreal-engine/lumen-technical-details-in-unreal-engine) says detail tracing is very expensive on large merged meshes, and these tiles are 250 m merges. A project setting outranks a scalability group. The console can still set `r.Lumen.TraceMeshSDFs 1`. |
| `r.GenerateMeshDistanceFields` | `True` (already set) | Software Lumen needs mesh distance fields. |
| `r.DistanceFields.DefaultVoxelDensity` | `0.200000` | The engine default through 5.8. Raising it rebuilds every distance field and the memory cost climbs quickly. The bake already sets each tile's `DistanceFieldResolutionScale` to 0.25. |

No rebake is required for `r.Lumen.TraceMeshSDFs`. If the editor offers to rebuild distance fields because the density key is now explicit, let that one rebuild finish and discard the run.

### Scalability

`Config/DefaultScalability.ini` overrides individual keys. Everything else stays on `Engine/Config/BaseScalability.ini`.

| Section | Key | Value | Why |
| --- | --- | --- | --- |
| `ShadowQuality@0` | `r.Shadow.Virtual.ResolutionLodBiasDirectional` | `2` | Coarsest step used by F9 Low. |
| `ShadowQuality@1` | same | `1` | |
| `ShadowQuality@2` | same | `1` | Playable default. `0` matches the camera. Subtracting 1 doubles virtual-shadow resolution and cost ([Virtual Shadow Maps](https://dev.epicgames.com/documentation/unreal-engine/virtual-shadow-maps-in-unreal-engine)). `+1` is one step coarser. Roads are non-Nanite and the landscape is non-Nanite, and that is the expensive part of a virtual shadow map. Epic and Cinematic are left on the engine curve. |
| `GlobalIlluminationQuality@2` | `r.Lumen.ScreenProbeGather.DownsampleFactor` | `32` | Fewer screen probes as the factor rises ([Lumen Performance Guide](https://dev.epicgames.com/documentation/unreal-engine/lumen-performance-guide-for-unreal-engine)). 32 is the engine High spacing. |
| `ReflectionQuality@2` | `r.Lumen.Reflections.DownsampleFactor` | `2` | One reflection ray per 2×2 quad on the default quality. The guide allows 1 or 2. |

`Config/DefaultGameUserSettings.ini` selects level 2 for every `sg.*` group. `sg.ResolutionQuality=87` is the screen percentage, not a quality index. The engine string `PerfIndexValues_ResolutionQuality` is `50 71 87 100 100` (Low, Medium, High, Epic, Cinematic).

`AHKPlayerController::ApplyQuality` runs from `BeginPlay` and from F9:

| HUD | `QualityIndex` | `SetFromSingleQualityLevel` |
| --- | --- | --- |
| 中 (default) | 1 | 2 (High) |
| 低 | 0 | 0 (Low) |

F9 leaves `r.Nanite` alone. Setting it to 0 draws the Nanite fallback meshes. Both steps still exec `r.Lumen.HardwareRayTracing 0`. High is the level on the key because that is the engine preset that keeps software Lumen. In the 5.1–5.4 `BaseScalability.ini`, `GlobalIlluminationQuality@1` sets `r.Lumen.DiffuseIndirect.Allow=0`. Confirm that line in `E:\UE_5.8\Engine\Config\BaseScalability.ini` before treating Medium as equivalent.

`SetFromSingleQualityLevel` maps level 2 through `PerfIndexValues_ResolutionQuality`, so a 5.8 change to that string wins over the `87` written in `DefaultGameUserSettings.ini` once `BeginPlay` runs.

On an existing checkout, `Saved/Config/Windows/GameUserSettings.ini` and `Saved/Config/WindowsEditor/EditorPerProjectUserSettings.ini` can still hold Epic. `BeginPlay` replaces that for the play session. The editor viewport toolbar is separate and can stay on Epic until you set it to High.

## Left for a later measurement

These are still in the project. This branch does not change them.

- HLODs are declared by the bake and not built. Buildings drop out past the 2.5 km loading range.
- The landscape is one always-loaded, non-Nanite actor (2112 components).
- Materials are two-sided. The sea is one map-sized translucent plane, plus the water tiles.
- The sky light is baked with real-time capture. `r.SkyLight.RealTimeReflectionCapture` defaults to 6 and cannot be changed at runtime, so it is not in an ini here.
- Physics substepping stays at 8 steps of 8 ms. 26 cars and 5 helicopters still tick while parked.
- The HUD still walks every actor once a second to count `HKSpatial` tags.
- PSO precaching stays at the engine default (`r.PSOPrecaching`, on). There is no recorded pipeline cache.
- Virtual shadow map cache stays at the engine default (`r.Shadow.Virtual.Cache`, on).

## Measurement protocol

Run this on the Windows machine. Close the editor, the browser, and anything else you can. With the editor open, free RAM has been about 1.9 GB of 16 GB, and a standalone launch on top of that will page.

Captures go in `E:\thingstoworkon\hk-perf\`, outside the repo.

### Fixed conditions

- Build `HKFreeRoamEditor` Win64 Development, then launch standalone `-game` on `UnrealEditor.exe`. There is no packaged build.
- Map `/Game/Maps/HKWorld`, 1920×1080, windowed, vsync off, frame rate uncapped.
- Quality for the baseline is the default 中 (High). Repeat the still route once with F9 (低, Low).
- Discard the first launch after pulling. Shader Model 6 recompiles the shader library, and an offered distance-field rebuild belongs to that same discarded run.
- Then three runs per quality. Record the median.
- `BeginPlay` applies scalability. Set A/B cvars after the HUD is up. If `stat unit` shows vsync locking the frame, run `r.VSync 0` again.

Confirm the base branch is active before any timed run:

- The log line is `Highest Feature Level of D3D12: SM6`.
- PIE does not show `Missing Project Settings: Shader Model 6`.
- `stat gpu` has Nanite and Virtual Shadow Map passes.

If the feature level is still SM5, stop. The numbers would be the fallback path again.

### Launch A, frame time

```bat
"E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "E:\thingstoworkon\hk-free-roam-game\UnrealProject\HKFreeRoam.uproject" /Game/Maps/HKWorld -game -windowed -ResX=1920 -ResY=1080 -log -trace=default,gpu,loadtime,counters -statnamedevents -tracefile="E:\thingstoworkon\hk-perf\A_high_1080p_run1.utrace" -ExecCmds="r.VSync 0, t.MaxFPS 0"
```

Change `run1` and `high` for Low (`low`) and for runs 2 and 3. `-trace=default` records the cpu, frame, log, and bookmark channels. `gpu`, `loadtime`, and `counters` are added on top. `-statnamedevents` and `-tracefile` are engine command-line arguments. `-windowed -ResX -ResY` and `-ExecCmds` are too.

Open the `.utrace` in `E:\UE_5.8\Engine\Binaries\Win64\UnrealInsights.exe`.

### Launch B, memory

Do this on its own. The memory channel is heavy, so it is not part of launch A.

```bat
"E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "E:\thingstoworkon\hk-free-roam-game\UnrealProject\HKFreeRoam.uproject" /Game/Maps/HKWorld -game -windowed -ResX=1920 -ResY=1080 -log -llm -trace=default,memory,loadtime -tracefile="E:\thingstoworkon\hk-perf\B_memory_run1.utrace" -ExecCmds="r.VSync 0, t.MaxFPS 0"
```

### Route

The player starts at Tuen Mun, beside the Tuen Mun car. At each stop, wait until the HUD says 串流完成, then hold still for 15 seconds. Bookmark first, then teleport.

```text
trace.bookmark TuenMun        (spawn, no teleport)
trace.bookmark Central        HK.Go Central
trace.bookmark MongKok        HK.Go MongKok
trace.bookmark TST            HK.Go TST
trace.bookmark VictoriaPeak   HK.Go VictoriaPeak
trace.bookmark TaiMoShan      HK.Go TaiMoShan
trace.bookmark Airport        HK.Go Airport
```

`HK.Go` moves the pawn immediately. The HUD line is the signal that streaming caught up.

Two motion segments, same path each time, after the stills:

- Drive the Tuen Mun car along the same road for 60 seconds. `trace.bookmark DriveStart` and `DriveEnd`.
- From `HK.Go CentralHelipad`, climb to about 300 m and fly toward Kai Tak for 60 seconds. `trace.bookmark HeliStart` and `HeliEnd`.

### Reading a frame

`stat unit` prints Game, Draw, GPU, and RHIT in milliseconds. The largest one is the bound:

| Largest | Bound | Next look |
| --- | --- | --- |
| Game | Game thread | `stat game`, `stat physics`, `dumpticks` |
| Draw | Render thread | `stat scenerendering`, `stat initviews`, `stat rhi` |
| GPU | GPU | `stat gpu`, then `ProfileGPU` |
| RHIT | RHI thread | `stat rhi` |

`stat unitgraph` shows the same split over time. `stat gpu` lists the Lumen passes. `ProfileGPU` (console, or Ctrl+Shift+comma) dumps one frame's GPU passes into the log. Copy that dump out of `Saved\Logs`. Lumen can overlap other work on async compute; `r.Lumen.AsyncCompute 0` turns that overlap off so a `ProfileGPU` of the Lumen passes is easier to read. Put it back to 1 afterwards. The default stays on.

Memory pressure is a different shape: frame time climbs while the disk works, and Task Manager commit is near 16 GB. Launch B's `stat llm` / `stat llmfull` and `memreport -full` (writes `Saved\Profiling\MemReports\`) split CPU memory. `r.DistanceFields.LogAtlasStats 1` prints distance-field atlas use. `r.Shadow.Virtual.Stats 1` prints virtual shadow page counts. Cached pages are cheap. Uncached non-Nanite pages are the landscape and the roads.

PIE frame times include the editor. A standalone number that is higher than the old 120 FPS PIE figure can still be the real SM6 cost. Compare standalone to standalone.

### A/B toggles

One change at a time, at Tuen Mun, Mong Kok, and Victoria Peak, on 中 (High), after the HUD is up. Put the cvar back before the next one. Screenshot `stat unit` and `stat gpu` for each.

| Toggle | What it isolates |
| --- | --- |
| `r.Lumen.TraceMeshSDFs 1` then `0` | Detail tracing against mesh distance fields |
| `r.Lumen.DiffuseIndirect.Allow 0` then `1` | Lumen GI |
| `r.Lumen.Reflections.Allow 0` then `1` | Lumen reflections |
| `r.Lumen.Reflections.DownsampleFactor 1` then `2` | Reflection resolution |
| `r.Lumen.ScreenProbeGather.DownsampleFactor 16` then `32` | Screen-probe spacing |
| `r.Shadow.Virtual.Enable 0` then `1` | Virtual shadow maps |
| `r.Shadow.Virtual.ResolutionLodBiasDirectional 0` then `1` | Directional virtual-shadow resolution |
| `r.ScreenPercentage 100` then `67` | Resolution |
| `ShowFlag.Landscape 0` then `1` | The always-loaded landscape |
| `ShowFlag.Translucency 0` then `1` | The sea plane and water tiles |
| `r.Nanite 0` then `1` | Fallback meshes. This is a test only. F9 does not do it |
| `r.Shadow.Virtual.MarkCoarsePagesDirectional 0` then `1` | Non-Nanite coarse pages. The virtual shadow map page says turning these off often helps non-Nanite casters |
| `pause`, then unpause, in an empty spot | Game-thread cost of the parked cars and helicopters |

`r.Shadow.Virtual.Visualize cache` shows which shadow pages were reused. Green is cached.

## Checklist to report

Paste these back. Median of three standalone runs, 1920×1080, vsync off, first launch discarded.

1. The log line `Highest Feature Level of D3D12`, and whether the Shader Model 6 project-settings warning is gone.
2. `stat unit` Game / Draw / GPU / RHIT milliseconds and the FPS readout at Tuen Mun, Central, Mong Kok, and Victoria Peak, for 中 and for 低.
3. The top passes from `ProfileGPU` at Tuen Mun and Victoria Peak (中).
4. `memreport -full` committed memory at Tuen Mun, and whether Task Manager was paging.
5. Which single A/B toggle moved GPU milliseconds the most, and by how much.
6. The first-load time, listed separately from the steady FPS.
7. If `E:\UE_5.8\Engine\Config\BaseScalability.ini` already sets `r.Lumen.ScreenProbeGather.DownsampleFactor` above 32 at `GlobalIlluminationQuality@2`, or a directional virtual-shadow bias above 1 at `ShadowQuality@2`, quote those two lines. The overrides in this branch would then be the more expensive of the two.

## Bounded warp (2026-11-04)

Warp-only. `tools/pipeline/roads.py`, `road_graph.py` and `check_roads.py` were not edited, and no road-height parameter was added. Measure this table again after the bridge-height fix. This machine did not compile, bake or play the project. [not verified in UE]

### What changed

`scale_x_knots_m` and `scale_y_knots_m` in `data/config/world.json`. Each axis is 0.40 from the origin out to 14 km east and 11 km north, then falls to 0.30 by 25 km east and 19 km north, and stays 0.30. The previous knots were 0.50 in that core, 0.1666667 on the shoulder, and 0.10 outside. Harbour widening is the same: amplitude 700 m, tanh width 340 m.

`MIN_LANE_M` stays 3.0. A 3.5 m real lane times 0.40 is 1.4 m, which is under the 1.90 m chassis (`AHKCar`, `ChassisWidth = 190`) and under the 2.0 m spawn envelope (`CAR_HALF_WIDTH_M`). The 3.0 m floor is that drivable minimum: 0.55 m each side of the 1.90 m body. Of drivable centreline length, 98.35% was already on the floor and 98.50% still is, so a lower floor would narrow roads the car needs. The narrowest ribbon is 3.0 m (Haiphong Road). A merged ribbon divided by its lane count can read 1.0 m (three counted lanes on a 3.0 m ribbon). The car sits in the 3.0 m ribbon.

### Why

Separable east and north scales differed by up to 5.00 on land (0.50 against the 0.10 floor), and by 3.06 to 3.37 at the airport, Fanling and Sheung Shui. Tuen Mun was 0.297 east by 0.500 north. That stretch is what pulls roads, ramps and junctions out of shape. Height scale is the square root of the geometric-mean horizontal scale, so the same knots change grades. The new pair caps the separable ratio at 0.40/0.30 = 1.333. The long axis stays under `target_long_axis_max_m` (25000 m) and a little under today's map. Harbour clearance, including Lei Yue Mun, stays above `min_harbour_width_m` (1000 m).

### How this was measured

Both columns are one full `python3 tools/run_pipeline.py` on this machine. Before is `HEAD`'s `world.json` written to `/tmp/hk-before` (422.8 s, `ok: true`). After is this branch written to `/tmp/hk-after` (394.6 s, `ok: true`). Map size, harbour section width, place scales, overlap, grade, tiles and triangles are `logs/report.json`. The same run stores `road_heights.warp_probe` (lane floor, bridge-end steps, Tuen Mun Road gap). `python3 -m tools.hkwarp.check_map` on this branch exited 0. `python3 -m tools.pipeline.check_roads` ran on both output directories.

Separable distortion is `max(G', H') / min(G', H')` on a 240×180 lon/lat grid over `bounds`, on cells the committed OSM land mask marks as land. `G'` and `H'` are the knot integrals, without the harbour `sech²` term. The full-axis ratio is `WarpModel.axis_scales`, which includes that term. Place scales are `axis_scales` at the place. Sheung Shui is 114.128° E, 22.501° N. Tung Chung is the `Lantau` place, 113.948° E, 22.289° N.

Grade is the share of ground centreline steeper than 0.30 (`GRADE` in `road_graph.py`) by more than 0.005, once for the design profile and once for the built ribbon. Bridge-end steps: a non-`deck_fixed` bridge sample at most 1 m, along that bridge, from a ground terminal, matched to the nearest ground or tunnel sample within 3 m; the step threshold is 0.45 m. The Tuen Mun Road ratio is the bridge sample of that name nearest the probe 113.98084° E, 22.38273° N that also lies within 25 m of a Castle Peak Road sample, divided by that sample's centreline Z.

`data/processed` in git is still the previous bake. Run the pipeline into `data/processed` before the next Unreal bake, or the baker will keep the old warp. [not verified in UE]

### Before / after

| | Before (0.50 / 0.10) | After (0.40 / 0.30) |
| --- | --- | --- |
| Map size | 23419.5 × 18855.2 m | 23221.3 × 18510.1 m |
| Long axis | 23419.5 m | 23221.3 m |
| Max separable distortion on land | 5.00 | 1.333 |
| Full-axis ratio on land, max / p99 | 12.51 / 4.97 | 6.77 / 1.333 |
| Central scale E, N (ratio) | 0.500, 0.563 (1.12) | 0.400, 0.463 (1.16) |
| Tuen Mun | 0.297, 0.500 (1.69) | 0.339, 0.400 (1.18) |
| Yuen Long | 0.479, 0.241 (1.99) | 0.394, 0.322 (1.22) |
| Tai Po | 0.500, 0.207 (2.42) | 0.400, 0.312 (1.28) |
| Tung Chung (`Lantau`) | 0.188, 0.500 (2.65) | 0.307, 0.400 (1.30) |
| Sheung Shui | 0.500, 0.148 (3.37) | 0.400, 0.300 (1.33) |
| Fanling | 0.500, 0.156 (3.21) | 0.400, 0.300 (1.33) |
| Airport | 0.163, 0.500 (3.06) | 0.300, 0.400 (1.33) |
| Tiles | 3168 | 2778 (−12.3%) |
| Triangles | 4,463,978 | 4,018,637 (−10.0%) |
| glTF / heightmap / PNG | 502.3 / 14.9 / 9.5 MB | 467.8 / 14.2 / 9.1 MB |
| Landscape grid | 3025 × 2458, ~7.98 m | 2962 × 2395, ~8.05 m |
| Harbour section min | 1327.5 m | 1263.4 m |
| Lei Yue Mun clearance | 1084.7 m | 1044.6 m |
| Building–road overlaps | 2 buildings, 13.0 m², carriageway 0 | 5 buildings, 7.5 m², carriageway 0 |
| Ground length over grade 0.30, design | 1.294% | 1.103% |
| Same, built ribbon | 3.071% | 2.926% |
| Bridge-end steps ≥ 0.45 m | 748 / 2006 matched (37.29%), max 26.42 m | 703 / 1865 matched (37.69%), max 29.00 m |
| Tuen Mun Road / Castle Peak Road | Z 11.683 / 8.446, gap 3.238 m, ratio 1.383 | Z 11.812 / 8.756, gap 3.057 m, ratio 1.349 |
| Narrowest drivable ribbon | 3.0 m (floor 3.0; car 1.90 m) | 3.0 m (floor 3.0; car 1.90 m) |

The full-axis maximum is the harbour widening, a thin band: after the change, 99% of land cells have a full-axis ratio of 1.333 or less. Tuen Mun in 1:N form goes from 1:3.4 east–west by 1:2.0 north–south to 1:2.9 by 1:2.5. Tile and triangle counts are the bake-time proxy. Unreal bake time and committed LFS size were not measured; the pipeline's glTF is 34.5 MB smaller (−6.9%) and the heightmap 0.7 MB smaller. [not verified in UE]

The bridge-end count is the current deck solver seen through game-space distances. Deck code did not change. A 3 m horizontal match can still pick up a parallel road, which is why the max step is tens of metres. Re-measure after the bridge fix.

### Spawn and HK.DriveTest

`TuenMun` is still `player_start`. The pipeline puts the player `PLAYER_GAP_M` (3.0 m) beside car `TuenMun_0` on a ground road. After the warp both are on the ribbon, 3.0 m apart, same yaw (−77.3°). The car's heading error against that centreline is 0.01° (was 0.24°). Its body fits: lateral offset 6.05 m on a ribbon whose left half is 7.26 m, chassis half-width 1.0 m. `check_roads` reports no spawn inside a building, none floating by more than 0.3 m, and the player on the surface under it. The same was true before.

`HK.DriveTest` anchors the pad on actor `TuenMun_0` and builds it at Z = 200000 cm, 2 km up (`PadZCm` in `HKDriveTest.cpp`). The pad is 6 km along world +X and does not follow city roads. Terrain from `terrain.r16` peaks at 658 m before and 595 m after, so the pad stays clear of the landscape. [not verified in UE]

Two other cars are on a ribbon but no longer aligned with the nearest centreline segment in `spawn_roads.json`: `Fanling_0` at 36.0° and `KwunTong_0` at 21.6°. Neither is wrong-way. `TuenMun_0` is not one of them.

### Checks on this machine

- `python3 -m tools.hkwarp.check_map`: exit 0. Extent 23221 × 18510 m. Harbour sections min 1263 m. Lei Yue Mun clearance 1045 m.
- `python3 -m tools.pipeline.check_roads` on both outputs: ground ribbons within 0.45 m of the terrain on 99.94% of their area. Stacked road area with a gap over 0.45 m went from 2.47% to 2.65%.
- `python3 -m pytest tools/tests -q`: 102 passed, 4 skipped, 1 failed. `test_real_traffic_light_stands_on_its_pole_with_the_lenses_facing_east` raises `KeyError: 'hk_traffic_light'` because `data/props/hk_traffic_light/hong_kong_traffic_light.glb` in this checkout is a Git LFS pointer, not a mesh. That test does not read the warp.
