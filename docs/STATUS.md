# 狀態

驗收要求：開專案、build、烘焙一次之後，每次運行都係同一個固定佈局，並且可以喺成個香港步行、揸車同飛行。下面分開寫 **已經做咗嘅嘢** 同 **呢部機未測到嘅嘢**。

## 里程碑

| 里程碑 | 內容 | 狀態 |
| --- | --- | --- |
| M0 | 目錄、可編譯結構嘅 UE C++ 專案、`AGENTS.md` | 源碼寫好。未喺 Unreal 編譯 |
| M1 | Python pipeline、warp、真實 OSM + SRTM、預覽 | 跑完，檢查通過 |
| M2 | 烘焙 commandlet：Landscape、路、建築物、World Partition | 源碼寫好。未跑過 commandlet |
| M3 | 第三人稱步行、上落載具 | 源碼寫好。未玩過 |
| M4 | Chaos 車 | 源碼寫好。未玩過 |
| M5 | 直升機 | 源碼寫好。未玩過 |
| M6 | 小地圖、大地圖、傳送、畫質 | 源碼寫好。未玩過 |
| M7 | 文件同編譯向嘅自我檢查 | 文件寫好。C++ 未經過 MSVC |

## 呢部機實際跑過

- `python tools/run_pipeline.py` 用真實數據，exit 0，報告 `ok: true`，大約 138 秒（第二次，道路挖掘改成「同一格用較低嘅路」之後）。
- 長軸 23419.5 米，高度 21629 米。範圍大約 x −12193 至 11226 米，y −9815 至 11815 米（未計 350 米邊界；小地圖邊界有計）。
- 維港 26 個斷面：最窄 1520 米，中位 2186 米，最闊 3400 米。
- 水平比例（幾何平均）大約：中環 0.53，灣仔／銅鑼灣／油麻地／旺角／啟德／沙田／觀塘／將軍澳／荃灣／葵涌／香港仔／赤柱／太平山／西貢 0.50，尖沙咀 0.73（東西 0.50、南北 1.06），屯門 0.39，元朗 0.34，大埔 0.32，粉嶺 0.28，大帽山 0.48，大嶼山 0.31，機場 0.29，長洲 0.50，南丫 0.50。
- Native warp：68 個樣本，正向最大誤差 5.03e-6 米，反向 7.67e-11 度。`pytest tools/tests` 喺改幾何之後係 7 項通過（4 項 warp、3 項 mesh）。
- OSM：建築物面積 119432，保留道路 35961（橋 4030，明挖隧道 155）。過濾後陸地上建築物 69113，內陸水面 929。Tile 2461，三角形大約 1.73M。
- Landscape：3025×2773，間距 7.98×8.06 米，`(頂點-1)` 可以被 63 整除。`terrain.r16` 16,776,650 bytes。高度大約 −17.6 至 659 米。南北對調相關性約 0.008，唔係鏡像。
- 26 架車相對高度圖：最低仲高 0.11 米，冇一架埋喺地形下面。灣仔嗰架高過取樣點大約 6.9 米，係橋面／高架喺地形之上，車坐喺道路 mesh，唔係陷落地面。
- 五個停機坪都由水面或斜坡吸咗去 300 米內較平嘅陸地。南丫島標記 450 米內冇地面路，所以嗰度冇車；個點本身喺陸上（大約 21 米）。
- 預覽：`data/processed/previews/scale_field.png`、`harbour_width.png`、`relief.png`、`network.png`。輪廓對得上機場、維港、九龍同港島。

## 未測試（必須當未完成）

呢個環境冇 Epic 帳號，亦裝唔到 Unreal Editor，所以以下全部 **未編譯、未烘焙、未進入 Play**：

- Visual Studio 工程生成同 `HKFreeRoamEditor` 編譯
- `-run=HKBakeWorld` 同 Python `bake_world()`
- Landscape Import、Nanite、World Partition loading range 反射、HLOD layer 係咪真係生效
- 步行、跳躍、游水、上落車鏡頭
- Chaos 車嘅懸掛、加速、手煞、倒車手感
- 直升機總距、週期變距方向、懸停、落地
- 小地圖方向、大地圖點擊傳送、Ctrl 熱鍵、`HK.Go`
- RTX 3060、中畫質、大約 60 fps
- 串流同 HLOD。烘焙只指定 HLOD layer，**唔生成** HLOD mesh。遠景建築物會喺 loading range 外消失，直到你自己跑：

```bat
UnrealEditor-Cmd.exe HKFreeRoam.uproject -run=WorldPartitionBuilderCommandlet -Builder=WorldPartitionHLODsBuilder /Game/Maps/HKWorld -unattended
```

呢條命令亦未跑過。如果烘焙 log 話搵唔到 `LoadingRange`，要喺 World Partition 手動設 250000（厘米）。

C++ 原本係對住 UE 5.6 公開 API 寫，而家目標係 UE 5.8（見下面「UE 5.8 升級」），冇喺 MSVC 編譯。文件上對到、但未編譯嘅包括：Chaos `bUseAutomaticGears`、`bAffectedByEngine`、`bAffectedByBrake`、`SpringRate`（單位 N/m）、`UEditorLoadingAndSavingUtils::NewBlankMap` / `SaveMap`（宣告喺 `FileHelpers.h`）、`UStaticMesh::Build(bool, TArray<FText>*)`。仍然要睇烘焙 log 先知係咪真係成功嘅包括：`FStaticToSkeletalMeshConverter` 喺安裝版引擎係咪連結到、Landscape `Import` 嘅 Guid 鍵、`UHLODLayer::SetLayerType`、World Partition `RuntimeHash` / `LoadingRange` 反射。對唔到嘅話先改嗰一行，唔好改 warp。

## Review 修正（branch `fix/review-blockers-majors`）

全部改動都 **未喺 MSVC 編譯、未烘焙、未 Play**。「已驗證」即係對過 UE 5.6 官方 API 文件，或者喺呢部機用數據／數值腳本計過；「推斷」即係要喺 Windows 上試先作實。

| 項目 | 改動 | 檔案 | 狀態 |
| --- | --- | --- | --- |
| B1 | `Possess` 係 final，改 override `OnPossess`，call `Super::OnPossess` | `HKPlayerController.h/.cpp` | 已驗證（5.6 文件：`AController::OnPossess` 係 overridable） |
| B2 | `InputYawScale`／`InputPitchScale` 喺 UE5 係 `_DEPRECATED`，改用 `SetDeprecatedInputYawScale(1)`／`SetDeprecatedInputPitchScale(1)` | `HKPlayerController.cpp` | API 已驗證；滑鼠上下方向要喺 PIE 睇（推斷冇變） |
| B3 | 刪咗 `MATUSAGE_Landscape`（5.6 冇呢個 enum 值） | `HKBakeLibrary.cpp` | 已驗證 |
| B4 | `Build.cs` 刪咗唔存在嘅 `"WorldPartition"` module | `HKFreeRoamEditor.Build.cs` | 已驗證（module index 冇；`UWorldPartition` 喺 Engine） |
| M1 | Custom material 加 input 之前先 `Inputs.Reset()`，UV／VertColor／WorldPos 接返啱嘅 slot | `HKBakeLibrary.cpp` | 根因已驗證；material 編譯成功係推斷 |
| M2 | 東西鏡像：遊戲北對應 Unreal −Y。全部經新 header `HKAxes.h`：glTF `(x, −z, y)`、Landscape 倒轉行次序並放喺 `Y = −max_y`、tile origin、海面、水 volume、spawn、yaw 取負、傳送、HUD、`HK.ToLatLon`。Python 加 `game_m_to_unreal_cm`，`convert.py` 改用 Unreal 厘米 | `HKAxes.h`、`HKBakeLibrary.cpp`、`HKPlayerController.cpp`、`HKFreeRoamHUD.cpp`、`HKDebugCommands.cpp`、`tools/hkwarp/*` | 數學已驗證（行列式 −1、Landscape 頂點同 tile 頂點落喺同一個 Unreal 位置、yaw 對準路、小地圖北向上）；畫面要喺 PIE 對返小地圖 |
| M3 | 建築碰撞由每棟一個 AABB 改做每棟一個 `FKConvexElem`（用該棟頂點） | `HKBakeLibrary.cpp` | 已量度：中環 tile 46_31 道路被遮由 45% 降到 18.5%（真腳印本身 18.0%，係 OSM 路面同建築重疊），旺角 49_47 由 19% 降到 0.3%；cooking 成功係推斷 |
| M4 | 車同直升機改做 always loaded（`SetIsSpatiallyLoaded(false)`）；無人嘅車腳下 5 米內冇地面就關重力、清速度 | `HKBakeLibrary.cpp`、`HKCar.h/.cpp` | 推斷（要 PIE 揸遠啲再返嚟睇車仲喺唔喺度） |
| M5 | 懸停輔助關咗時總距範圍加大：最大 1.5 倍重量（大約 0.63 懸停）；推力 clamp 唔會變負 | `HKHelicopter.cpp` | 數值已驗證（舊 1.0 倍，即係永遠升唔到）；手感推斷 |
| M6 | Roll 取負：UE 繞本地 +X 正力矩會令右邊升起 | `HKHelicopter.cpp` | 數值已驗證（四元數積分：向右推 → 右翼向下）；pitch／yaw 本身啱 |
| M7 | 烘焙一個 `APhysicsVolume`（`bWaterVolume`），範圍成張地圖、由海平面到 KillZ；刪咗 `UpdateSwim` 強制游水 | `HKBakeLibrary.cpp`、`HKFreeRoamCharacter.h/.cpp` | API 已驗證（`UActorFactory::CreateBrushForVolumeActor`、`UCubeBuilder`）；游水推斷 |
| M8 | 重新烘焙前 GC 舊 world、`ResetLoaders`，刪 `HKWorld.umap` 同 `__ExternalActors__`／`__ExternalObjects__/Maps/HKWorld`；刪唔到就 fail | `HKBakeLibrary.cpp` | API 已驗證（`IFileManager::Delete/DeleteDirectory`、`ResetLoaders`）；烘兩次 actor 數目一樣係推斷 |

呢部機跑過：`pytest tools/tests` 9 項通過（多咗 2 項 Unreal 軸測試）、`pyflakes tools` 乾淨、`build_warp()` 重建嘅 `warp_lut.bin` 同 `golden_warp.csv` 同 commit 咗嗰份 byte 一樣。`warp_lut.bin`、`golden_warp.csv`、`spawns.json`、`landmarks.json`、`terrain.r16`、tile glb 冇改；`manifest.json` 只改咗兩句軸說明。冇 g++，`test_hk_warp.cpp` 未編譯。

### 仍然未處理（Minor）

1. 懸掛 `SpringRate` 45000 可能太硬
2. 傳送只 trace 到 Landscape，未等建築／路串流
3. 單一 Landscape actor（2112 components，冇 streaming proxy）
4. `GConfig` 寫 `DefaultEngine.ini` 可能寫唔入（startup map）
5. `-ExecutePythonScript` 烘焙路徑可能唔會退出
6. Constructor 入面 `NewObject` 起 input action
7. Look 冇 `Completed` binding
8. `ReplaceObject` 永遠 return nullptr
9. Packaged build 搵唔到 `data/processed`
10. 非 ASCII 路徑讀唔到 LUT（`fopen_s`）
11. HUD 中文字型 fallback 未確認
12. 小地圖 aspect fallback 寫死
13. `bCanHaveLayersContent` 之後版本會 deprecated
14. `run_pipeline.py` 唔理參數（`--help` 會跑成條 pipeline）
15. Tile 例外被吞，報告仍然 `ok: true`
16. SRTM 令市區地面偏高
17. 可分離 warp 令新市鎮比例偏細（README `convert.py` 例子已改做 Unreal 厘米）

## 數據同刻意限制

- OSM：`https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf`（`asia/hong-kong-latest.osm.pbf` 會 404）。© OpenStreetMap contributors，ODbL。
- 地形：SRTM `N22E113`、`N22E114`，`https://elevation-tiles-prod.s3.amazonaws.com/skadi/N22/`。1.5 米以下當海，負值乘 0.35。密集市區會偏高（灣仔、尖沙咀一類可以有幾十米），呢個係 SRTM，唔係地政總署 DTM。DTM 冇下載：`https://data.gov.hk/en-data/dataset/hk-landsd-openmap-5-digital-terrain-model`。
- 扭曲可分離，見 `ARCHITECTURE.md`。
- 隧道係明挖，過海變低堤，冇管狀隧道。
- OSM 內環（天井）填咗。`building:part` 如果更高，可能同主體重疊。
- 冇渡輪。長洲只靠 unclassified。南丫島標記附近冇路，要行或者飛。
- 道路最小寬度會從建築物脚印切走一條。
- 大世界座標大約到 2e6 厘米，float 精度大約 0.25 厘米，冇做 origin rebasing。

## 固定佈局點樣成立

烘焙把車、直升機、停機坪、路同建築物寫入關卡。Runtime 唔再生成佢哋。傳送同上下車只移動玩家。所以同一次烘焙出嚟嘅關卡，每次 Play 佈局相同。呢一句係程式結構，唔係玩過嘅結果。

## 玩家角色（branch `feat/chibi-player`）

全部改動 **未喺 MSVC 編譯、未烘焙、未 Play**。正式角色設計同 VRoid 步驟：[characters/VROID.md](characters/VROID.md)（設計已批，模型未整、未試）。換模型同刪暫代角色：[data/characters/README.md](../data/characters/README.md)。

| 項目 | 狀態 |
| --- | --- |
| VRM4U `v1.2026.10.17`（UE 5.8 zip `VRM4U_5_8_20261017.zip`）URL、大小 68,577,272 bytes、SHA-256 `4ab9d363…6f677f3f` | 已驗證：呢部機下載、計 hash（同 GitHub release `digest` 一樣）、`tools/get_vrm4u.py` 解壓成功，`VRM4U.uplugin` 寫 `EngineVersion 5.8.0`。`.ps1` 未喺 Windows 跑 |
| UAL 動畫（Quaternius，CC0）剪成 11 段、65 joints | 已驗證：gltf-validator 0 error；pytest 檢查 clip 名同 joint |
| 暫代角色 glb | **冇喺 repo**：Sketchfab 下載要登入（API 401），要手動下載。冇就用方塊 |
| `ImportVRMFileWithOptions`、`FImportOptionData::bGenerateRigIK`、`IK_<名>_Mannequin` 命名 | 已驗證（VRM4U 源碼） |
| `UIKRetargeterController::AddDefaultOps/SetIKRig/AutoAlignAllBones/AutoMapChains/GetSourceChain`、`UIKRigController::SetSkeletalMesh/ApplyAutoGeneratedRetargetDefinition/GetRetargetChains/GetRetargetChainEndBone/SetRetargetChainEndBone/RemoveRetargetChain`、`RunBatchRetarget` 同 `FIKRetargetBatchOperationInputs` 欄位名 | 已驗證（5.8 C++ API 文件；`DuplicateAndRetarget` 喺 5.8 已經冇） |
| `FAnimInstanceProxy::PreUpdate/Evaluate`、`UAnimSequence::GetAnimationPose`、`FAnimExtractContext`、`FAnimationRuntime::BlendTwoPosesTogether`、`SetOverlayMaterial`、`SetSkeletalMeshAsset`、`SetAnimInstanceClass` | 已驗證（5.6 API 文件） |
| Auto retarget definition 認唔認到 UAL 同 Interchange 匯入嘅 skeleton | 推斷。認唔到會 warning，角色企喺 reference pose（搵唔到 function 就係 error，烘焙停） |
| Interchange `UAssetImportTask` 匯入 skeletal glb 連動畫（同步、asset 命名） | 推斷。烘焙用「folder 入面第一個 skeletal mesh」同「名結尾 = clip 名」搵 |
| 冇 anim graph 時 proxy `Evaluate` 會被 call | 推斷（LiveLink 等 engine proxy 用同一做法） |
| Figure 物料嘅數值（SSS、rim、angel ring）、slot 分類 | 推斷，要喺 PIE 睇 |
| 動畫參考速度（walk 150、jog 340、sprint 560、swim 200 cm/s @180 cm）、`mesh_yaw_deg -90` | 推斷。滑腳就調 `anim_ref_speed_cm_s`，打側就調 `mesh_yaw_deg` |
| Capsule／鏡頭按身高、落車／傳送／PlayerStart 用 capsule 高度 | 數值自查；未 Play |
| VRM spring bone（頭髮、裙）| 唔會郁：冇用 VRM4U 嘅 anim node |
| `.uproject` `"Optional": true` | 推斷 JSON key 名（`FPluginReferenceDescriptor::bOptional`） |

已知風險：plugin folder 存在但喺 editor 停用咗，`HKFreeRoamEditor` 會 link 唔到 VRM4U；chibi 大頭細手，retarget 之後手可能穿過頭／身；500/900 速度對 120 cm 角色可能好快、腳步要靠 play rate 補（上限 1.6 倍）。

## UE 5.8 升級（branch `feat/chibi-player`）

目標 **UE 5.8.4**（`EngineAssociation` = `5.8`）。全部改動 **未喺 MSVC 編譯、未烘焙、未 Play**，呢部機冇 Unreal。「已驗證」= 對過 Epic 5.8 API 文件／release notes，或者喺呢部機實際下載、計過；「推斷」= 要喺 Windows 上 build 同烘焙先作實。

| 項目 | 改動 | 狀態 |
| --- | --- | --- |
| 引擎版本 | `.uproject` `EngineAssociation` 5.6 → 5.8；plugin 清單冇改 | 改咗。Plugin 喺 5.8 仲存在：IKRig／IKRigEditor（API 文件路徑 `Plugins/Animation/IKRig`）、ChaosVehiclesPlugin（`Plugins/Experimental/ChaosVehiclesPlugin`）已驗證；EnhancedInput、PythonScriptPlugin、EditorScriptingUtilities、Interchange、InterchangeEditor 推斷（release notes 冇講刪） |
| 工具鏈 | README／AGENTS 寫明 VS 2022 17.14+ 或 VS 2026、MSVC 14.38+、Windows SDK 10.0.22621.0+ | 已驗證（5.8 release notes「Platform SDK Upgrades」）。Sean 部機嘅 VS 版本未知 |
| Target.cs | 保持 `BuildSettingsVersion.Latest`、`EngineIncludeOrderVersion.Latest` | 5.7 notes 要求安裝版引擎用 V6；`Latest` 已經 ≥ V6，5.8 notes 冇新版本 → 推斷唔使改 |
| Build.cs module 名 | 冇改 | `IKRig`、`IKRigEditor`、`ChaosVehicles`、`Landscape`、`UnrealEd`、`SkeletalMeshUtilitiesCommon`、`Engine`、`CoreUObject` 已驗證（5.8 API 文件嘅 module 路徑）；其餘推斷 |
| VRM4U | 5.8 zip，68,577,272 bytes，SHA-256 `4ab9d363c006a00c6bf10712b6b5fb79e4aad3ee859927f4ae0216e96f677f3f` | 已驗證（下載、hash = GitHub digest、解壓、uplugin `5.8.0`）。`ImportVRMFileWithOptions`、`FImportOptionData::bGenerateRigIK`、`UVrmAssetListObject` 喺 5.8 源碼仲喺度：已驗證。VRM4U 喺 5.8 編唔編到：推斷 |
| R1：動畫 retarget | `DuplicateAndRetarget` → `RunBatchRetarget(FIKRetargetBatchOperationInputs)`（`RetargetEditor/IKRetargetBatchOperation.h`）；欄位：`AssetsToRetarget`、`SourceMesh`、`TargetMesh`、`IKRetargetAsset`、`Suffix`、`bIncludeReferencedAssets`、`bOverwriteExistingFiles`、`bUseSourcePath`、`TargetPath` | API 已驗證（5.8 文件）。直接 call 嘅 `UIKRigController::GetController/SetSkeletalMesh`、`UIKRetargeterController::GetController/SetIKRig/AddDefaultOps/AutoAlignAllBones(ERetargetSourceOrTarget, ERetargetAutoAlignMethod)` 喺 5.8 有 export：已驗證（VRM4U 5.8 預編譯 DLL import 咗同一批 mangled symbol）。Struct 用 reflection 對名同大小先填；實際出到 `_HK` clip：推斷 |
| 硬錯誤 | 搵唔到 engine function、struct 形狀唔啱、batch 出唔到 `_HK` clip → `Error`，`Bake()` 回 `Failed`，`BakeWorld`／`-PlayerOnly` exit 1 | 寫好，未跑 |
| 5.8 腳 chain 拆開 | 5.8 biped 模板：Leg 去到腳眼，新 `LeftFoot`／`RightFoot`（ball／toe）。VRM4U `IK_*_Mannequin` 嘅 LeftLeg 去到腳趾、冇 Foot chain（已驗證：VRM4U 5.8 源碼）。得一邊有 Foot 就併返入 Leg；chain map 逐條 log | 改動已寫；UAL skeleton 喺 5.8 模板真係會出 Foot chain：推斷（release notes 話全部 17 個 biped 模板都拆咗）。腳掌角度／IK goal 位置要喺 PIE 睇 |
| Substrate | `DefaultEngine.ini` 加 `r.Substrate=False` | 5.8 Substrate 文件話「升級上嚟嘅舊專案預設繼續行非 Substrate，除非 project settings 明確開」：已驗證。`r.Substrate` 呢個 cvar 名：社區同 Epic 論壇一致，未喺 5.8 官方文件見到原文 → 推斷 |
| 點解唔開 Substrate | Figure 物料（Subsurface + rim emissive）、描邊（Unlit）、`MakeCustomMaterial` 起嘅 facade／road／water／terrain／pad，全部 C++ 直接接舊 pin。開 Substrate 會自動轉換，外觀會變；Substrate 轉換係單程；Toon 喺 Substrate 仲係 Experimental | 理由。開唔開 Substrate 嘅視覺比較要另開 branch 試 |
| Landscape | `ALandscapeProxy::Import` 喺 5.8 淨返 `TArrayView<const FLandscapeLayer>` 個 overload（5.6 嗰個 `TArray*` 冇咗），而家明確傳空 view | 已驗證（5.6／5.8 API 文件對比）；編譯推斷 |
| 其他 C++ API | `SetDeprecatedInputYawScale/PitchScale`、`FVehicleTransmissionConfig`（`bUseAutomaticGears` 等）、`UChaosVehicleWheel` 全部 setter 欄位、`FSavePackageArgs`、`UStaticMesh::Build(bool, TArray<FText>*)`、`FStaticToSkeletalMeshConverter`、`UEditorLoadingAndSavingUtils::NewBlankMap/SaveMap/SaveDirtyPackages`、`UHLODLayer::SetLayerType`、`ALandscape::bCanHaveLayersContent` | 已驗證仲喺 5.8 API 文件。World Partition `RuntimeHash`／`LoadingRange` 反射：推斷（反射，搵唔到會 warning） |
| 已知 5.8 bug | UE-364613（World Partition server streaming + Iris，5.8 受影響，target fix 6.0） | 單機版唔受影響；將來做多人先要理（見多人研究） |
| Python | `pytest tools/tests`（加 `test_engine.py`：VRM4U asset 跟 `EngineAssociation`、兩個 script 一致、`r.Substrate=False`）、`pyflakes tools` | 呢部機跑過：21 項通過，pyflakes 乾淨 |

Windows 上要做嘅：刪 `Binaries`／`Intermediate`／`DerivedDataCache`／`Saved`／`Plugins/VRM4U`，跑 `get_vrm4u.ps1`，generate project files，build `HKFreeRoamEditor`，`-PlayerOnly` 烘角色睇 log 入面 `chain X <- Y` 同 `retargeted N of M clips`，再烘世界、Play。
