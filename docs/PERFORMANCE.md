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

The branch is based on `fix/road-collision` (`4118cbf`). That branch already targets D3D12 Shader Model 6 (`-D3D12TargetedShaderFormats=PCD3D_SM5`, `+D3D12TargetedShaderFormats=PCD3D_SM6`), makes road tiles non-Nanite, and calls `ResetLoaders` before saving a tile. This branch does not edit those lines or that bake code.

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
