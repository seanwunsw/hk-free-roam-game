# 狀態

驗收要求：開專案、build、烘焙一次之後，每次運行都係同一個固定佈局，並且可以喺成個香港步行、揸車同飛行。下面分開寫 **已經做咗嘅嘢** 同 **呢部機未測到嘅嘢**。

## 里程碑

| 里程碑 | 內容 | 狀態 |
| --- | --- | --- |
| M0 | 目錄、可編譯結構嘅 UE C++ 專案、`AGENTS.md` | 源碼寫好。第一次 MSVC 編譯失敗（見「第一次 Windows 編譯」）。修正未再編譯 |
| M1 | Python pipeline、warp、真實 OSM + SRTM、預覽 | 跑完，檢查通過 |
| M2 | 烘焙 commandlet：Landscape、路、建築物、World Partition | 源碼寫好。未跑過 commandlet |
| M3 | 第三人稱步行、上落載具 | 源碼寫好。未玩過 |
| M4 | Chaos 車 | 源碼寫好。未玩過 |
| M5 | 直升機 | 源碼寫好。未玩過 |
| M6 | 小地圖、大地圖、傳送、畫質 | 源碼寫好。未玩過 |
| M7 | 文件同編譯向嘅自我檢查 | 文件寫好。第一次 MSVC 編譯失敗。修正未再編譯 |

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

呢個環境冇 Epic 帳號，亦裝唔到 Unreal Editor，所以以下全部 **未喺呢部機編譯、未烘焙、未進入 Play**。Sean 部 Windows 機跑過一次 `HKFreeRoamEditor` Win64 Development，失敗；修正未再編譯（見「第一次 Windows 編譯」）。

- Visual Studio 工程生成同 `HKFreeRoamEditor` 再編譯（第一次失敗咗）
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

C++ 原本係對住 UE 5.6 公開 API 寫，而家目標係 UE 5.8（見下面「UE 5.8 升級」）。第一次 MSVC 編譯失敗，修正未再編譯（見「第一次 Windows 編譯」）。文件上對到、但未編譯嘅包括：Chaos `bUseAutomaticGears`、`bAffectedByEngine`、`bAffectedByBrake`、`SpringRate`（單位 N/m）、`UEditorLoadingAndSavingUtils::NewBlankMap` / `SaveMap`（宣告喺 `FileHelpers.h`）、`UStaticMesh::Build(bool, TArray<FText>*)`。仍然要睇烘焙 log 先知係咪真係成功嘅包括：`FStaticToSkeletalMeshConverter` 喺安裝版引擎係咪連結到、Landscape `Import` 嘅 Guid 鍵、`UHLODLayer::SetLayerType`、World Partition `RuntimeHash` / `LoadingRange` 反射。對唔到嘅話先改嗰一行，唔好改 warp。

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

1. 懸掛 `SpringRate`：45000 改咗做 600（2026-11-03，疑似 spawn 反轉原因，**未驗證**，未喺 PIE 試過）
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
13. `bCanHaveLayersContent`：5.7 API 已經冇呢個成員，烘焙唔再賦值（見「第一次 Windows 編譯」）
14. `run_pipeline.py` 唔理參數（`--help` 會跑成條 pipeline）
15. Tile 例外被吞，報告仍然 `ok: true`
16. SRTM 令市區地面偏高
17. 可分離 warp 令新市鎮比例偏細（README `convert.py` 例子已改做 Unreal 厘米）

## 數據同刻意限制

- OSM：`https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf`（`asia/hong-kong-latest.osm.pbf` 會 404）。© OpenStreetMap contributors，ODbL。
- 地形：SRTM `N22E113`、`N22E114`，`https://elevation-tiles-prod.s3.amazonaws.com/skadi/N22/`。1.5 米以下當海，負值乘 0.35，再壓低 2 米（海床至少 −2 米，branch `fix/road-pipeline`）。密集市區會偏高（灣仔、尖沙咀一類可以有幾十米），呢個係 SRTM，唔係地政總署 DTM。DTM 冇下載：`https://data.gov.hk/en-data/dataset/hk-landsd-openmap-5-digital-terrain-model`。
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

目標 **UE 5.8.4**（`EngineAssociation` = `5.8`）。下面係升級時對文件嘅判斷。第一次真實 MSVC 編譯見最後一節：嗰次失敗，修正 **未再編譯**，未烘焙、未 Play。呢部機冇 Unreal。「已驗證」= 對過 Epic 5.8 API 文件／release notes，或者喺呢部機實際下載、計過；「推斷」= 要喺 Windows 上 build 同烘焙先作實。

| 項目 | 改動 | 狀態 |
| --- | --- | --- |
| 引擎版本 | `.uproject` `EngineAssociation` 5.6 → 5.8；plugin 清單冇改 | 改咗。Plugin 喺 5.8 仲存在：IKRig／IKRigEditor（API 文件路徑 `Plugins/Animation/IKRig`）、ChaosVehiclesPlugin（`Plugins/Experimental/ChaosVehiclesPlugin`）已驗證；EnhancedInput、PythonScriptPlugin、EditorScriptingUtilities、Interchange、InterchangeEditor 推斷（release notes 冇講刪） |
| 工具鏈 | README／AGENTS 寫明 VS 2022 17.14+ 或 VS 2026、MSVC 14.38+、Windows SDK 10.0.22621.0+ | 已驗證（5.8 release notes「Platform SDK Upgrades」）。Sean 部機：VS 2022 17.14.43、MSVC 14.44.35207、Windows SDK 10.0.22621/26100、UE 5.8.4 CL 58902052 |
| Target.cs | 保持 `BuildSettingsVersion.Latest`、`EngineIncludeOrderVersion.Latest` | 5.7 notes 要求安裝版引擎用 V6；`Latest` 已經 ≥ V6，5.8 notes 冇新版本 → 推斷唔使改 |
| Build.cs module 名 | 冇改 | `IKRig`、`IKRigEditor`、`ChaosVehicles`、`Landscape`、`UnrealEd`、`SkeletalMeshUtilitiesCommon`、`Engine`、`CoreUObject` 已驗證（5.8 API 文件嘅 module 路徑）；其餘推斷 |
| VRM4U | 5.8 zip，68,577,272 bytes，SHA-256 `4ab9d363c006a00c6bf10712b6b5fb79e4aad3ee859927f4ae0216e96f677f3f` | 已驗證（下載、hash = GitHub digest、解壓、uplugin `5.8.0`）。`ImportVRMFileWithOptions`、`FImportOptionData::bGenerateRigIK`、`UVrmAssetListObject` 喺 5.8 源碼仲喺度：已驗證。VRM4U 喺 5.8 編唔編到：推斷 |
| R1：動畫 retarget | `DuplicateAndRetarget` → `RunBatchRetarget(FIKRetargetBatchOperationInputs)`（`RetargetEditor/IKRetargetBatchOperation.h`）；欄位：`AssetsToRetarget`、`SourceMesh`、`TargetMesh`、`IKRetargetAsset`、`Suffix`、`bIncludeReferencedAssets`、`bOverwriteExistingFiles`、`bUseSourcePath`、`TargetPath` | API 已驗證（5.8 文件）。直接 call 嘅 `UIKRigController::GetController/SetSkeletalMesh`、`UIKRetargeterController::GetController/SetIKRig/AddDefaultOps/AutoAlignAllBones(ERetargetSourceOrTarget, ERetargetAutoAlignMethod)` 喺 5.8 有 export：已驗證（VRM4U 5.8 預編譯 DLL import 咗同一批 mangled symbol）。Struct 用 reflection 對名同大小先填；實際出到 `_HK` clip：推斷 |
| 硬錯誤 | 搵唔到 engine function、struct 形狀唔啱、batch 出唔到 `_HK` clip → `Error`，`Bake()` 回 `Failed`，`BakeWorld`／`-PlayerOnly` exit 1 | 寫好，未跑 |
| 5.8 腳 chain 拆開 | 5.8 biped 模板：Leg 去到腳眼，新 `LeftFoot`／`RightFoot`（ball／toe）。VRM4U `IK_*_Mannequin` 嘅 LeftLeg 去到腳趾、冇 Foot chain（已驗證：VRM4U 5.8 源碼）。得一邊有 Foot 就併返入 Leg；chain map 逐條 log | 改動已寫；UAL skeleton 喺 5.8 模板真係會出 Foot chain：推斷（release notes 話全部 17 個 biped 模板都拆咗）。腳掌角度／IK goal 位置要喺 PIE 睇 |
| Substrate | `DefaultEngine.ini` 加 `r.Substrate=False` | 5.8 Substrate 文件話「升級上嚟嘅舊專案預設繼續行非 Substrate，除非 project settings 明確開」：已驗證。`r.Substrate` 呢個 cvar 名：社區同 Epic 論壇一致，未喺 5.8 官方文件見到原文 → 推斷 |
| 點解唔開 Substrate | Figure 物料（Subsurface + rim emissive）、描邊（Unlit）、`MakeCustomMaterial` 起嘅 facade／road／water／terrain／pad，全部 C++ 直接接舊 pin。開 Substrate 會自動轉換，外觀會變；Substrate 轉換係單程；Toon 喺 Substrate 仲係 Experimental | 理由。開唔開 Substrate 嘅視覺比較要另開 branch 試 |
| Landscape | `ALandscapeProxy::Import` 喺 5.8 淨返 `TArrayView<const FLandscapeLayer>` 個 overload（5.6 嗰個 `TArray*` 冇咗），而家明確傳空 view | 已驗證（5.6／5.8 API 文件對比）；編譯推斷 |
| 其他 C++ API | `SetDeprecatedInputYawScale/PitchScale`、`FVehicleTransmissionConfig`（`bUseAutomaticGears` 等）、`UChaosVehicleWheel` 全部 setter 欄位、`FSavePackageArgs`、`UStaticMesh::Build(bool, TArray<FText>*)`、`FStaticToSkeletalMeshConverter`、`UEditorLoadingAndSavingUtils::NewBlankMap/SaveMap/SaveDirtyPackages`、`UHLODLayer::SetLayerType` | 已驗證仲喺 5.7／5.8 API 文件。`bCanHaveLayersContent` 嗰句作廢：5.7 `ALandscapeProxy` 成員表同 deprecated 表都冇呢個欄位（見最後一節）。World Partition `RuntimeHash`／`LoadingRange` 反射：推斷（反射，搵唔到會 warning） |
| 已知 5.8 bug | UE-364613（World Partition server streaming + Iris，5.8 受影響，target fix 6.0） | 單機版唔受影響；將來做多人先要理（見多人研究） |
| Python | `pytest tools/tests`（加 `test_engine.py`：VRM4U asset 跟 `EngineAssociation`、兩個 script 一致、`r.Substrate=False`）、`pyflakes tools` | 呢部機跑過：21 項通過，pyflakes 乾淨 |

Windows 上要做嘅：刪 `Binaries`／`Intermediate`／`DerivedDataCache`／`Saved`／`Plugins/VRM4U`，跑 `get_vrm4u.ps1`，generate project files，build `HKFreeRoamEditor`，`-PlayerOnly` 烘角色睇 log 入面 `chain X <- Y` 同 `retargeted N of M clips`，再烘世界、Play。

## 第一次 Windows 編譯（UE 5.8.4）

Sean 部機第一次 build `HKFreeRoamEditor` Win64 Development（`Build.bat ... -FromMsBuild`）失敗，exit 6，`OtherCompilationError`。引擎 UE 5.8.4 launcher CL 58902052，VS 2022 17.14.43，MSVC 14.44.35207，Windows SDK 10.0.22621/26100。下面嘅修正 **未再編譯**（Sean 聽日再 build）。未烘焙、未 Play。呢部機冇 Unreal，對過嘅係 Epic API 頁同已經成功編譯過嘅翻譯單元，唔係再跑一次 MSVC。

| 檔案 | Build log | 修正 | 證據 |
| --- | --- | --- | --- |
| `HKCar.cpp` / `HKCar.h` | C4458：`SetVehicleMesh` 嘅 `Mesh` 遮住 class member | 參數改名 `NewMesh` | 車係 `AWheeledVehiclePawn`，mesh 組件成員叫 `Mesh`。只改名 |
| `HKPlayerController.cpp` | C4458：`Character`（237、280、288、296、304、455、499、650）、`Pawn`（470、613）遮住 class member | 區域變數改名 `Walker`、`ControlledPawn` | `AController::Character` 喺 `GameFramework/Controller.h`（UE 5.5 起已經有，UE 當 C4458 做 error）。`AController::Pawn` 係原有成員 |
| `HKPlayerController.cpp` | C2664：`AController::Possess(APawn*)` 收唔到 `AActor*` | `FindRide()` 結果 `Cast<APawn>` 先 `Possess` | `Possess` 簽名係 `APawn*`。車同直升機都係 pawn；唔係 pawn 就唔上 |
| `HKBakeLibrary.cpp` | C1083：搵唔到 `Engine/SkyAtmosphere.h` | 刪咗呢行 include。`ASkyAtmosphere` 用已經 include 咗嘅 `Components/SkyAtmosphereComponent.h` | [UE 5.8 `ASkyAtmosphere`](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/ASkyAtmosphere)：header 係 `Components/SkyAtmosphereComponent.h`。`ASkyLight` 仍然係 `Engine/SkyLight.h`（5.8 文件），冇郁 |
| `HKBakePlayer.cpp` | C2665：`TMap::Add` 兩個 overload 都唔夾（122、134） | `FString(*Pair.Key)` 再 `Add` | [UE 5.8 `FJsonObject`](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Json/FJsonObject) 繼承 `FJsonObjectSharedStringStorage`。`Values` 鍵係 `FStringType`（`UE::FSharedString`），唔再係 `FString`，所以 `TMap<FString,…>::Add` 唔接受 `Pair.Key`。`*Key` 係字元指針，`FString` 可以由佢起。同一寫法喺別嘅 5.8 plugin 全量 build 過 |
| `HKBakePlayer.cpp` 754–755，同 `HKBakeLibrary.cpp` 未編譯到嘅同一呼叫 | C4996：`UMaterial::SetMaterialUsage` deprecated in 5.8，「Use the new (virtual) implementation」 | 改呼叫 `SetMaterialUsage(EMaterialUsage)`，唔再傳 `bool&` | [UE 5.8 `UMaterialInterface`](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/UMaterialInterface)：`virtual bool SetMaterialUsage(EMaterialUsage Usage)`。`bUsedWithNanite` 係同一批 `UE_DEPRECATED(5.8)`，改做 `SetMaterialUsage(MATUSAGE_Nanite)`。`HKBakeLibrary.cpp` 死喺 include，呢幾行上次 build 未跑到 |
| `HKBakeLibrary.cpp` `NaniteSettings` 直接讀寫 | 上次 build 未跑到（fatal include）。5.7 起直接讀寫欄位係 deprecated | 改 `GetNaniteSettings` / `SetNaniteSettings` | UE 5.7 `UStaticMesh` 文件已經有呢兩個函數（`Engine/StaticMesh.h`）。欄位本身 5.7 頁仲列住，所以舊寫法可能只係 C4996，唔係 error |
| `HKBakeLibrary.cpp` `bCanHaveLayersContent = false` | 上次 build 未跑到 | 刪咗賦值 | UE 5.7 `ALandscapeProxy` 公開成員表同 deprecated 表都冇 `bCanHaveLayersContent`，只剩 `CanHaveLayersContent()` getter 同 `bHasLayersContent_DEPRECATED`。5.8 嗰頁 403，讀唔到。5.8 唔會加返一個 5.7 已經刪咗嘅欄位。高度／layer map 仍然用同一個非空 `FGuid`（`AGENTS.md`） |
| `HKFreeRoam.h` `LogHK` | build log 未出現（編譯未去到 link） | `HKFREEROAM_API` export | Editor module 係另一個 DLL，`UE_LOG(LogHK)` 要用到 game module 嘅符號。冇 export 嘅話 link 會 LNK2019。呢個係預測，上次 log 冇呢個 error |

掃過其餘 C++：game module 其他翻譯單元上次冇 C4458（`HKFreeRoamHUD`／`HKDebugCommands` 嘅 `Pawn`、`HKPlayerAnimInstance` 嘅 `Character` 唔係 `AController` 嘅成員函數，而且嗰啲 TU 已經編譯完）。`HKBakePlayer.cpp` 入面其他 `TMap::Add` 用嘅係 `TMap<FString,…>`，編譯過。`REN_ForceNoResetLoaders` 喺 `HKBakePlayer.cpp` 163 行，編譯過，冇刪。IKRig header 已經 include 到，冇加 Slate。`TryGetStringField` 喺 game module 編譯過，冇改。

WIP 冇跟嘅 hunk：`HeightData`／`Layers` 改鍵做 `FGuid()`。呢個唔係編譯錯誤，而且同「兩個 map 用同一個非空 Guid」衝突。5.8 `Landscape.cpp` 嘅 `Import` 本體呢度讀唔到，所以唔知 runtime 係咪 `FindChecked(FGuid())`。如果烘焙 assert 話搵唔到高度，先至要改鍵，唔好而家估。

唔肯定聽日會唔會過嘅：
- `bCanHaveLayersContent` 如果 5.8 竟然仲喺度，而家唔再強制 false（編譯仍然會過）。
- `LogHK` export 係預測嘅 link 修正，log 未證明。
- `GetNaniteSettings`／`SetNaniteSettings` 5.7 文件有，5.8 頁 404，推斷仲喺。
- `HKBakeLibrary.cpp` 喺 include 之後嘅 API（`FStaticToSkeletalMeshConverter`、World Partition 反射、`Import` 嘅空 `TArrayView`）上次完全未編譯到。文件話 `Import` 要 `TArrayView<const FLandscapeLayer>`，現有呼叫已經係咁，但係未喺呢次 MSVC 證實。

## 第二次 Windows 編譯（UE 5.8.4，2026-10-28）

Sean 部機 pull `46cd1b5` 之後再 build `HKFreeRoamEditor` Win64 Development：**全部 compile 都過咗**，game module `UnrealEditor-HKFreeRoam.dll` link 成功，VRM4U 都編到。所以上一節嘅修正（包括 `HKBakeLibrary.cpp` include 之後嗰段、`LogHK` export、Nanite getter/setter、`Import` 嘅 `TArrayView`）喺 MSVC 已經證實編譯得到。只係 `UnrealEditor-HKFreeRoamEditor.dll` link 失敗：`HKBakePlayer.cpp.obj` 有 7 個 unresolved external（LNK2019／LNK1120），全部係 `FSlateAttributeDescriptor::FInitializer`、`SWidget`／`SCompoundWidget`／`SBorder::PrivateRegisterAttributes`，嚟自 `RetargetEditor` header 入面嘅 `STableRow<FRetargetChainElement>`。

修正：`HKFreeRoamEditor.Build.cs` 加 `Slate`、`SlateCore` private dependency。已驗證：`96eab13` 喺 Sean 部機再 build，link 成功，`Result: Succeeded`（2026-10-28 20:02 英國時間）。上一節話「冇加 Slate」嗰個判斷錯咗。未烘焙、未 Play。

呢部機只得 16 GB RAM，build 時 UBT 限制得 1 個 action 同時跑，成次 build 用咗大約 53 分鐘（UBA 3190 秒）。

## 第一次烘焙（2026-10-28，`e0c5ddc`）

`-run=HKBakeWorld` 喺 Sean 部機匯入 `data/characters/player.vrm` 時 crash（exit 3）。VRM4U `ConvertModel`、`ConvertRig`、`ConvertIKRig`、`ConvertMorphTarget` 都行完，`SK_player` build 成功；之後 `VRMConverter::ConvertPose()`（`VrmConvertPose.cpp:1424`）喺 `GWorld` spawn `ASkeletalMeshActor`，引擎 assert：`InMeshDesc.Scene && InMeshDesc.Scene->GetSkeletalMeshUpdater()`（`SkeletalRenderGPUSkin.cpp:673`，「Scene cannot be null when creating a SkeletalMeshObject」）。

修正：`ImportVrm` 設 `Options.bSkipRetargeter = true`。VRM4U 源碼入面呢個 flag 只喺 `ConvertPose` 開頭用嚟直接 return，唔影響 `ConvertIKRig`（`IK_*_Mannequin` 喺 `ConvertPose` 之前已經寫好）。烘焙自己整 `RTG_UAL_To_Player`，冇讀 VRM4U 嘅 `POSE_retarget_*`。**未再烘焙**。

## 第一次完整烘焙成功（2026-10-28，UE 5.8.4，Sean 部 PC）

- 用 commandlet（`-run=HKBakeWorld`）烘焙喺 UE 5.8.4 會 assert：commandlet 冇 FScene 同 Slate，VRM4U 同 Interchange 匯入 skeletal mesh 時要用到。
- 改用完整 editor 行同一個 script：`UnrealEditor.exe HKFreeRoam.uproject -ExecutePythonScript=<abs>\Content\Python\bake_hk_world.py -unattended`。
- 結果：Meshes 4402，failed 0，cars 26，helicopters 5；角色 11/11 動畫 clip retarget 成功；地形 3025x2773。
- 修正（73d88f2）：Landscape `Import()` 要用空 FGuid 做 key；UE 5.8 Interchange clip 名係 `<檔名><clip>` 冇分隔符。
- 未測：HLOD 未生成；未入 PIE 試玩；角色朝向同 spring bone 未睇；commandlet 烘焙仍然會 crash；成套 pytest 未喺 box 行（安裝被擋）。

## 畫質同量度（branch `perf/sm6-baseline`）

SM6 目標同路面非 Nanite 喺 `fix/road-collision`，呢個 branch 冇改嗰兩樣。呢度加咗 software Lumen 嘅 Global Distance Field 追蹤、distance field voxel density 鎖喺引擎預設 0.2、High 畫質嘅 VSM bias／Lumen probe／反射 downsample，同 F9 改行 scalability。**呢部機冇 Unreal，未編譯、未烘焙、未 Play。** 幀數仍然係未 profile 嘅 PIE 數：穩態大約 120+ FPS（當時最高 feature level 係 SM5），7 FPS 只出現喺第一次載入。量完先至填 after。步驟見 [PERFORMANCE.md](PERFORMANCE.md)。

## 道路 pipeline 重做（branch `fix/road-pipeline`，2026-10-29）

全部改動喺 `tools/pipeline`，**冇改 C++**。只喺呢部 box 跑過 Python pipeline 同量度；**未喺 Sean 部 PC 重新烘焙、未入 PIE**。數據用 OSM 261025 snapshot（同之前 commit 嗰份一樣）。

### 改咗乜

| 問題 | 改動 | 檔案 |
| --- | --- | --- |
| 平行／重疊嘅路疊埋一齊（雙程路、OSM 重複 way） | 全部路沿線 4 米取樣，按等級／闊度排先後；同 mode（橋再要同 `layer`）、方向差 30° 內、橫向重疊嘅點併入優先嗰條，嗰條加闊（每邊最多 16 米），被併嘅段刪走 | `roads.py` `merge_parallel` |
| 路面高度同地面唔夾、最近種子點跳來跳去 | 每條路先做平滑設計高度（坡度上限 30%，但永遠夾喺平滑地形 ±3 米內），一次過用加權平均挖入地形（冇「最近一條路贏」）；之後 ribbon 每個頂點都喺 **量化後嘅 r16** 用 Unreal 三角形分法重新取樣 | `roads.py` `set_design_profiles`、`carve_terrain`、`build_ribbon`；`surface.py` |
| Ribbon 邊唔跟橫向斜度、太粗 | 每段 4 米、橫向 2–4 米一格，每格頂點獨立取樣地面，所以邊跟住橫坡 | `roads.py` `ribbon_grid` |
| 18% 坡度上限 | 改做 30%，但設計高度唔可以離平滑地形多過 3 米；舊上限喺山路會令路面離地幾十米 | `roads.py` |
| 橋 | 橋面 = 兩頭地面高度按圖距離淡入（40 米）到淨空（最少 6 米），斜坡尾同地面接；同一 `layer` 嘅橋段先會連埋 | `roads.py` `set_bridge_decks` |
| 隧道 | 仍然係明挖（冇管道）。地面路橫過明挖坑時改做橋面跨過，唔會畀坑切斷 | `roads.py` `bridge_over_trenches` |
| 海床 | 海格喺平滑之後再壓到 ≤ −2 米；建築物「喺水入面」嘅門檻跟住移 2 米 | `build_world.py` |
| 建築物 | 底部用腳印最低一點（唔再浮喺斜坡），屋頂高度唔變 | `build_world.py` `assign_building_z` |
| 出生點 | 由 `world.json` `player_start` 起計：車同玩家都要企喺最高可行走面，頭頂 4 米內冇路面或建築物；揀唔到就喺附近另揾。屯門玩家喺 `TuenMun_0` 旁邊 3 米 | `spawns.py` |
| 量度 | `python -m pipeline.check_roads [processed]`（喺 `tools/` 行）：疊路面積、路面同地形高度差（Unreal 三角形）、出生點頭頂幾何 | `check_roads.py` |

### 前後對比（`check_roads.py`，同一份 OSM）

| 指標 | 之前（commit 咗嘅數據） | 之後 |
| --- | --- | --- |
| 有兩層或以上路面嘅面積 | 21.6% | 8.1%（差唔多全部係橋喺路上面） |
| 疊埋而高度差 0.45–4 米（會卡腳／浮） | 9.7% | 0.84% |
| 地面路同地面路疊埋高度差 > 0.45 米 | 14.0% | 0.0% |
| 路面離地形 −0.45～+0.45 米（全部路面，唔計離地 > 4 米） | 60.8% | 97.6% |
| 地面路離地形 ±0.45 米內 | 未分（舊數據冇 mode） | 99.94%（p99 +0.27 米） |
| 出生點頭頂 4 米內有幾何 | 27 個中 4 個（包括玩家） | 27 個中 0 個 |
| 出生點喺建築物入面 | 3 個（中環三架車） | 0 |
| 海格 ≤ −2 米 | 26.5% 嘅格（其餘海喺 −2～0） | 43.6%；−2～0 米剩返 0.09% 嘅格 |
| 陸上建築物 | 69113 | 69106 |
| 車 | 26 | 26 |
| Tile／三角形 | 2461／1.73M | 2462／3.02M（路 ribbon 1.74M） |

`pytest tools/tests`：34 項通過（新 `test_roads.py` 11 項）。`pyflakes tools` 乾淨。報告 `ok: false` 只係因為 box 冇 g++，native warp check 跳過咗；其他檢查都過。

### 未測／要 Sean 部 PC 做

- 要 pull 呢個 branch、`git lfs pull`，再用完整 editor 重新烘焙（同「第一次完整烘焙成功」一樣條命令），開 HKWorld 入 PIE 睇。
- Unreal Landscape 三角形對角線方向係憑引擎源碼記憶（NW–SE），**未喺 UE 證實**。如果錯咗，路面中間會有最多約一格高度差嘅一半浮起或陷落。
- 三角形多咗大約 75%（路 ribbon 細格），要睇 FPS。
- 建築物碰撞仍然係每棟一個凸包（C++，冇改），可能喺窄路變隱形牆。
- 明挖隧道坑仍然好深；跨坑嘅地面路改咗做橋（286 段）。
- 海岸線入面大約 0.3 平方公里（以前平滑後高過 1.5 米嘅岸邊格）而家變海；內陸水面由 929 變 868。
- 南丫島仍然冇車（450 米內冇地面路）。

## 落唔到地 + 小地圖唔似香港（branch `fix/road-pipeline`，2026-10-29）

**全部未喺 UE 測過**：冇編譯、冇烘焙、冇 PIE。下面數字全部嚟自呢部機嘅 Python pipeline 同檢查 script。

### 1. 三角形方向（落唔到地嘅根本原因）

- glTF → UE 個軸換算 `(X, −Z, Y)` 係鏡像，所以每個三角形嘅繞向反轉咗。UE 用 `Cross(P2−P0, P1−P0)` 計面法線，路面 collision 係 ComplexAsSimple 雙面，sweep 嘅 ImpactNormal 係原始面法線，所以路面法線 Z 係負數，低過可行走斜度（Z ≥ 0.643），角色企唔穩、成日喺「跌緊」狀態。
- `HKBakeLibrary.cpp` `AppendPrim`：而家用 UE 嘅公式計面法線，同 glTF 存落嘅法線對比，相反就調轉 I1/I2。
- 新加入 import 後檢查：每個 tile mesh 數「面法線 · glTF 法線 ≤ 0」嘅三角形，有就逐個 mesh 出 Warning；烘焙完出一行總數：`HK winding check: N of M tile triangles in K meshes face away from their glTF normals`。正確應該係 **0**。
- 只有 tile import（建築、路、水）行呢條路。Landscape 係 heightfield；車、直升機、玩家唔經 `AppendPrim`。注意：`BuildChassis` 手砌嘅車身面用 UE 公式計係向下，呢個係舊有，collision 係 None、車用 PhysicsAsset，所以今次冇改。

### 2. Warp v2（小地圖扭曲）

- 舊公式喺維港附近有隨 x 變化嘅 A（fade）同 origin pin，令遠方都有剪切（小地圖見到之字形）。新公式：`Y = H'(y) + A·tanh((y − yc_s(x)) / W)`，A 係常數，遠方只係平移 ±A，冇剪切。`H'` 已經包咗令原點唔郁嘅常數。
- `yc` 用新嘅 `harbour_yc_lonlat`（向西延長到汲水門／大嶼山東北，向東延長），再做 400 米高斯平滑。
- 參數：A 700（舊 1100），W 340，`harbour_yc_smooth_m` 400，刪咗 `harbour_fade_m`。比例 knots 冇改。
- LUT 版本升到 2，`hk_warp.h` 會拒絕舊 v1 檔，所以一定要 `git lfs pull`。
- 結果：長軸 23420 米，高 18855 米（舊 19655），最細 Jacobian 0.01044，冇摺疊。維港 26 個斷面：最窄 1129 米（鯉魚門），中位 1603，最闊 2614；中環↔尖沙咀 1271 米（舊 1918）。Native warp：正向最大誤差 2.52e-6 米，反向 6.09e-11 度。
- 代價：A 細咗，維港闊度細咗（但仍然 ≥ 1000 米）。tanh 帶喺穿過陸地嘅位置（大嶼山東北、清水灣）南北方向最多拉長大約 5 倍。

### 3. 自交建築腳印

- 新 warp 之後荃灣 `TsuenWan_0` 架車出現喺建築入面。原因：切路之後嘅腳印抽點會令多邊形自交，三角化後屋頂／牆漏出去路面，但 spawn 嘅點喺多邊形檢查（shapely）判斷唔到。
- `build_world.py` 加 `repair_rings`：自交嘅腳印用 `make_valid` 取最大嗰塊，再做保留拓撲嘅簡化。今次修咗 213 個，冇刪。

### 檢查（`check_roads.py`，舊數據 → 新數據）

| 指標 | 之前 | 之後 |
| --- | --- | --- |
| 路面面積 (m²) | 9,965,322 | 8,901,847 |
| 重疊 | 8.092% | 7.438% |
| 間隙 > 0.45 米 | 4.525% | 3.664% |
| 間隙 0.45–4 米 | 0.837% | 0.801% |
| 地面路重疊 | 0.0 | 0.0 |
| 排除 > 4 米，喺台階內 | 97.58% | 97.5% |
| 地面路喺台階內 | 99.94% | 99.98% |
| 橋喺台階內 | 3.52% | 3.45% |
| spawn 頭頂有嘢／喺建築入面／浮空 | 0 / 0 / 0 | 0 / 0 / 0 |

- 玩家 spawn 仍然喺屯門 `TuenMun_0` 旁邊（大約 3 米）。Tile 2386，三角形 2.82M（舊 3.02M）。`pytest tools/tests` 36 項通過。pipeline `ok=True`。

### 未處理／風險

- C++ 未編譯，可能有編譯錯。
- ~~SRTM 將大部分維港當成陸地~~：已經喺下一節「維港／海岸線」用 OSM 海岸線修正。
- 上次 PIE log 入面 21 個 NaN bounds tile、InverseFast 誤差同 distance field 問題未處理。
- 車身手砌面方向（見上面）。

## 維港／海岸線用 OSM 做準（branch `fix/road-pipeline`，2026-10-29）

**全部未喺 UE 編譯、未烘焙、未入 PIE 測試。** 以下數字只係 pipeline 同 Python 檢查嘅結果。

### 做法

- 海陸 mask 改用 OSM `natural=coastline`（1608 條 way），唔再靠 SRTM。新 `tools/pipeline/coast.py`：
  - 海岸線同 Geofabrik extract 邊界（新檔 `data/config/hong-kong.poly`）一齊 node，再 polygonize；每塊面用海岸線方向（陸地喺左邊）投票決定係陸定海。結果 911 塊（陸 910、海 1、判斷唔到 0），extract 內陸地 1114.0 km²（官方約 1114 km²）。
  - 海岸線喺 extract 邊（深圳河一帶）開口嘅兩條，靠同 extract 邊界 node 埋處理。
  - extract 以外（深圳）冇 OSM 海岸線，改用 SRTM > 1.5 米判斷。
  - 海平面高度嘅 OSM 水面（795 個，例如魚塘、潮汐河道）由陸地扣走，當海。高過海平面嘅水塘保留做內陸水面（881 個）。
  - 輸出 `data/processed/land_mask.png`（1-bit，北向上，0.0001°）同 `land_mask.json`。
- 地形：陸地 = max(SRTM × 高度比例, 0.6 米)；海 = min(SRTM 海床 × 0.35, 近岸斜坡)，斜坡由岸邊 −2 米跌到大約 −10 米（120 米衰減）。平滑之後再夾一次（陸 ≥ 0.6，海 ≤ −2）。
- 明挖隧道（紅隧、西隧、東隧、屯門至赤鱲角）以前會將海床挖高到隧道面，喺維港整咗條「陸橋」（紅磡↔銅鑼灣最高 18.4 米）。而家：
  - 新 `roads.deck_over_sea`：地面路同隧道經過離岸超過 2 格（約 16 米）嘅海，改成固定高度嘅低橋面（設計高度 + 路面抬高），今次 20 段。
  - 挖地形之後，離岸超過 2 格嘅海格唔准高過原本海床。
- 地面路取樣低過 0.6 米嘅抬到 0.6 米（1806 個）。
- 小地圖嘅海色跟 mask；內陸水面另外填色。
- Warp：`harbour_centerline_lonlat` 同 `harbour_yc_lonlat` 改用 OSM mask 量出嚟嘅航道中線（舊點喺中環／尖沙咀同鯉魚門偏咗大約 400 米）。A=700、W=340、平滑 400 冇改。

### 海陸吻合度（extract 內，`python -m tools.pipeline.check_coast`）

| 指標 | 之前（`9c84ded` 地形） | 之後 |
| --- | --- | --- |
| OSM 海嘅頂點低過 0 米 | 72.71% | 99.69% |
| OSM 海嘅頂點 ≤ −2 米 | 72.64% | 99.63% |
| OSM 陸嘅頂點高過 0 米 | 98.08% | 99.85% |
| 總吻合 | 83.38% | 99.76% |

- 上面係 raster 檢查（最近格）。pipeline 用多邊形逐點計：海 < 0 米 99.805%，≤ −2 米 99.743%，陸 > 0 米 100%，吻合 99.887%。
- 剩低嘅主要係岸邊 2 格內（路肩、海堤）同 mask 像素邊界。
- 新測試 `tools/tests/test_coast.py`：開口海岸線、反轉方向、extract 外用 DEM、吻合度計數、隧道過海變橋面；另外有一個對 processed 數據嘅整合測試（中環、尖沙咀、紅磡係陸，維港中間係海，九龍↔港島距離 ≥ 1000 米）。

### 維港闊度

- 九龍↔港島最近距離（新指標 `harbour_clearance`）：遊戲 1085 米（真實 427 米，鯉魚門）。最低要求 1000 米，只係多 85 米。
- 142 個斷面：最窄 1328 米，中位 2198 米，最闊 3543 米。（只用 SRTM 海岸嘅比較：最窄 1102 米。）

### 其他檢查

- pipeline exit 0，`ok=True`，長軸 23420 米，tile 2373，三角形 2.82M。spawn 冇一個喺海上；玩家仍然喺屯門 `TuenMun_0`。建築物喺陸上 71966，喺水入面刪咗 37。
- `check_roads.py`（上次 → 今次）：

| 指標 | 上次 | 今次 |
| --- | --- | --- |
| 路面面積 (m²) | 8,901,847 | 8,857,045 |
| 重疊 | 7.438% | 7.435% |
| 間隙 > 0.45 米 | 3.664% | 3.651% |
| 間隙 > 1 米 | 3.468% | 3.452% |
| 間隙 0.45–4 米 | 0.801% | 0.799% |
| 地面路重疊 | 0.0 | 0.0 |
| 排除 > 4 米，喺台階內 | 97.5% | 97.4% |
| 地面路喺台階內 | 99.98% | 99.98% |
| 橋喺台階內 | 3.45% | 3.28% |
| spawn 頭頂有嘢／喺建築入面／浮空 | 0 / 0 / 0 | 0 / 0 / 0 |

- 隧道面積少咗大約 15.3 萬 m²，橋面多咗大約 14.6 萬 m²（過海隧道變咗低橋面）。地面路少咗大約 4 萬 m²，相信係因為 warp 中線改咗。
- 海上嘅路頂點：橋 31647 個，低過 +0.3 米嘅只有 82 個（引橋尾）；地面 135 個、隧道 2 個仲貼住海床（岸邊）。青馬、昂船洲等橋面仍然喺水面以上（最高 41.6 米）。
- `check_map`：通過。`pytest tools/tests` 42 項通過。pyflakes 冇錯。

### 未處理／風險

- **未喺 UE 試過**：Landscape 海床、水面、低橋面碰撞、小地圖全部未睇過。
- 過海隧道而家係貼水面嘅低橋（揸車會喺海面上行），唔係真隧道。
- 近岸海床斜坡係人造，唔係真實水深。
- 魚塘、潮汐河道（例如元朗、南生圍）而家當海。
- 深圳一邊仍然靠 SRTM。
- 鯉魚門只係多 85 米先到 1000 米下限。
- 上次 PIE log 嘅 NaN bounds tile、InverseFast 誤差、distance field 問題仍然未處理。

## 路網坡度解法 + 短橋淨空 + 撳 F 上唔到車（branch `fix/road-pipeline`，2026-11-03）

### 改咗乜

- **路網坡度解法（`tools/pipeline/road_graph.py`）**：路口而家係共用頂點，所有接入嘅路喺路口用同一個高度。坡度用 A/B 兩邊 Dijkstra 限制。橋過冇相連嘅低路時有硬下限（低路 +5.5 米），隧道都有硬下限。±3 米貼地限制保留。舊嘅 `limit_grade`／`set_design_profiles` 同臨時 `HK_LEGACY_ROADS` 開關已經刪咗。
- **短橋淨空**：橋頭 fade 長度 = min(40 米, 橋長/3)。共用頂點取所有相連橋嘅最大值，所以短橋中間都有足夠淨空。
- **`merge_parallel` bug**：之前太短而冇輸出嘅段仍然當係「仲在」，之後嘅路被吸入一段唔存在嘅路，所以路中間有一格（3.5–4.8 米）綠色缺口。屯門 `TuenMun_0` 附近見到。已修正，並加咗測試。
- **車 spawn**：車貼最終路中線，泊喺左線（香港靠左行），車頭方向跟路。避開路口範圍（路口半闊 + 4.5 米內有 >20° 嘅路就唔用）。玩家喺第一架車旁邊 3 米（先試路邊／行人路一邊）。
- **`check_roads` 新指標 `spawn_lanes`**：每架車離中線距離、方向誤差、車身係咪全部喺路面。資料喺 `data/processed/spawn_roads.json`。
- **撳 F 上唔到車（C++，要重新 build）**：根本原因係 `APawn` 預設 `AutoPossessAI = PlacedInWorld`，`AIControllerClass = AAIController`。烘焙出嚟嘅車同直升機係「放喺地圖」，開波時自動被 AIController 附身，觸發 `PossessedBy`，`bOccupied = true`。`FindRide` 會跳過有人坐嘅車，所以撳 F 搵唔到車。同時因為 `bOccupied` 而冇 `Park()`，手掣冇拉，車可能自己溜走（可能就係車唔喺路上嘅原因）。修正：`HKCar`／`HKHelicopter` 建構時設 `AutoPossessAI = Disabled`、`AIControllerClass = nullptr`；`BeginPlay` 如果見到非玩家 controller 就 `UnPossess` 同刪走（舊地圖都有效）；`PossessedBy` 只對玩家 controller 設 `bOccupied`。

### 呢部機實際跑過

- pipeline exit 0，`ok=True`，tile 2371，三角形 2.83M。
- `check_roads`、`check_map`、`check_coast` 全部通過；`pytest tools/tests` 54 項通過；pyflakes 冇錯。
- 指標（`552e590` → 舊解法 → 今次）：

| 指標 | 552e590 | 舊解法 | 今次 |
| --- | --- | --- | --- |
| 設計高度路口差 最大 | – | 17.18 米 | 0 |
| 設計高度路口差 >50 厘米 | – | 57.5% | 0% |
| 路面路口差（地面）最大／>50 厘米 | – | – | 2.37 米／0.77% |
| 路面坡度超標（地面） | – | 4.21% | 3.07% |
| 橋淨空 最小 | – | −13.5 米 | 5.26 米 |
| 橋淨空 <4 米 | – | 19.2% | 0% |
| 間隙 0.45–4 米 | 0.799% | 0.808% | 0.517% |
| 排除 >4 米，喺台階內 | 97.4% | 97.4% | 98.49% |
| 地面路喺台階內 | 99.98% | 99.98% | 99.99% |
| 車方向誤差最大 | – | 89.8° | 0.24° |
| 車身出咗路面 | – | – | 0 |
| 玩家離第一架車 | – | – | 3.0 米 |

- 對比圖：`/workspace/hk-perf/tuenmun_compare.png`（真 OSM／遊戲 tile／`TuenMun_0` 90 米近鏡）。

### 屯門仲差乜（影響由大到細）

1. 路中間一格缺口 —— 已修正。
2. warp 將屯門壓到東西 ×0.30、南北 ×0.50，但路闊有固定下限（雙線 ≥8 米），所以路同路之間擠埋，雙程路併成 20 米闊嘅灰色一大片。要改路闊跟 warp 或者改 warp 比例（設計決定，未做）。
3. `M_Road` 材質：黃邊線太粗（闊度 8%）、每條路都有黃色中間虛線（單程路都有），而且穿過路口。建議改白色分線、邊線用米計、路口唔畫線（要改 C++／材質，未做）。
4. 路口冇填補，路尾方角留低三角形空位。建議做路口多邊形（中等工作量）。
5. 住宅路、服務路、行人路、樓梯全部冇，所以冇行人路同路邊石。建議喺路邊加行人路帶。
6. 建築物稀疏、對比低。
7. 冇讀 OSM `oneway`（呢區有 493 條單程主要路），影響分線同泊車邊。

### 未測試／風險

- **全部未喺 UE 試過**：C++ 改動未 build、未 PIE；撳 F 上車、車唔溜、玩家落地位置都要喺 Sean 部 PC 驗證。
- 保留 ±3 米限制，所以設計坡度超標比舊解法略高（1.82% vs 1.29%）。
- 路面路口差（全部，連橋）最大仍有 28.6 米，係橋同地面路嘅接觸位，未處理。
- 車泊喺左線係按「車頭方向嘅左邊」，冇讀 `oneway`，單程路可能泊錯邊。

## 上到車但係車唔郁（branch `fix/car-drive`，2026-11-03）

Sean 部 PC 用 `54535be` build 同烘焙成功，撳 F 上到車，但係 HUD 一直 `0 km/h`，車身好似斜咗、浮喺路邊。

### 根本原因

1. **車身冇開物理模擬**：`AWheeledVehiclePawn` 建構時設 `Mesh->BodyInstance.bSimulatePhysics = false`。UE 官方設定步驟要求喺 mesh 剔 Simulate Physics。`AHKCar` 由頭到尾冇 call `SetSimulatePhysics(true)`（成個 source 只有 `HKHelicopter` 有），所以車身係 kinematic，Chaos 加幾多扭力都推唔郁，車停喺烘焙位置（路面 +1 米，唔跟路斜），所以睇落斜咗、浮咗。
2. **四個轆都綁喺 `Root`，即係車身嗰塊 physics body**：Chaos `FixupSkeletalMesh` 會將每個「轆骨」嘅 physics body 設做唔碰撞（`ECR_Ignore`）同唔模擬（`SetInstanceSimulatePhysics(false)`）。轆骨同車身共用 `Root`，即係將車身本身關咗。
3. 附帶：`SM_HKChassis` 六塊面全部反轉（用返 `AppendPrim` 嗰條 UE 規則 `Cross(P2-P0, P1-P0)` 計，6/6 向入），所以由上面睇見到車廂入面，好似「反轉」。

之前寫「手掣冇拉所以車溜走」係估錯：車身根本冇模擬，唔會溜。

### 修正

- `AHKCar::EnableChassisPhysics()`（`BeginPlay`）：恢復每塊 body 嘅碰撞，然後 `SetSimulatePhysics(true)`。舊地圖都有效。
- 烘焙：骨架加 `Wheel_FL/FR/RL/RR`（`Root` 嘅子骨，喺原點，冇 physics body），轆改綁呢四條骨，位置照用 `AdditionalOffset`。舊地圖冇呢四條骨就退返 `Root`，log 會提你重新烘焙。
- 烘焙：車身六塊面改返正確方向。
- 泊住嘅車：`BeginPlay` 照 `Park()`（腳掣 + 手掣），而且立即做 `HoldIfGroundUnloaded()`，避免未載入地面就跌落去。

### 未測試

- **未 build、未 PIE**。呢部機冇 Unreal。要確認：揸得郁、轉彎、泊住嘅車唔溜、落車再上車。
- 轆彈簧 `SpringRate` 由 45000 改咗做 600，`SpringPreload` 50，`SuspensionMaxRaise` 10 cm（2026-11-03）。推斷：45000 太硬，開咗物理之後積分唔穩，令車 spawn 時反轉；「Chaos 內部 ×100」都係推論，**未驗證**，要等 Sean 喺 PIE 試過先算修好。另外加咗 `SelfRightIfFlipped`（冇 sweep，喺橋底或者隧道入面可能會卡入天花）。

## 路闊、標線、路口、小路、建築、單程路、泊車高度（branch `fix/car-drive`，2026-11-03）

詳細計劃同數字：`docs/ROAD_VISUALS_PLAN.md`。**全部未喺 UE 編譯、烘焙或者玩過**，以下只係 pipeline 同 Python 檢查嘅結果。

### 改咗乜
- 路闊跟 warp 垂直路方向嘅壓縮比，每線最少 3.0 m、最多真實線闊；無連接路面重疊 1.883%、灰板 1.946%。
- 路面標線改用米：UV0 = (沿路米, 離左邊米)，UV1 = (路闊, 分隔位 + 線數)，vertex colour R = 標線開關。黃邊線 0.12 m、白虛線分線、雙程先有雙白中線、路口冇線。單程路有中線 = 0。
- 路口補面 22,766 個（material 3，冇標線）。
- 新增 residential / living_street / service 車路，footway / pedestrian / steps 行人路（material 4），主路兩邊 1.5 m × 0.15 m 行人路帶。
- 建築：細建築門檻降低、新外牆色盤、天台淺灰同牆分開（M_Facade）。陸地上 72,873 棟（之前 71,955）。
- 單程路：讀 `oneway`、roundabout、motorway。車跟合法方向泊最左線，逆向 0。
- 車喺半空出世：原因係烘焙將車放喺 spawn + 100 cm，而 main 車身係 kinematic，所以一直吊住；開咗物理之後會跌 1 m。而家 spawn 計 4 轆路面高同 pitch，z = 接觸點 + 0.02 m，烘焙唔再加 100 cm，用 pitch；`HoldIfGroundUnloaded` trace 由車上 1 m 開始。最大轆離地 0.079 m。
- 三角形 2.83M → 4.51M（+59.6%）。

### 退步（要知）
- tunnel within step 97.18% → 93.49%；coast agree 99.758% → 99.644%（海邊 service 路）；橋淨空最低 5.26 → 5.03 m。

### 未測試
- M_Road / M_Facade HLSL 未 compile；UV1（TEXCOORD_1）讀取未試；Nanite 下 UV 精度未睇。
- 路邊石垂直面可能有 winding 警告。
- 車 spawn 高度、pitch 喺 Chaos 入面穩唔穩未試。
