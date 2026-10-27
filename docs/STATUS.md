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

C++ 係對住 UE 5.6 公開 API 寫嘅，冇喺 MSVC 編譯。文件上對到、但未編譯嘅包括：Chaos `bUseAutomaticGears`、`bAffectedByEngine`、`bAffectedByBrake`、`SpringRate`（單位 N/m）、`UEditorLoadingAndSavingUtils::NewBlankMap` / `SaveMap`（宣告喺 `FileHelpers.h`）、`UStaticMesh::Build(bool, TArray<FText>*)`。仍然要睇烘焙 log 先知係咪真係成功嘅包括：`FStaticToSkeletalMeshConverter` 喺安裝版引擎係咪連結到、Landscape `Import` 嘅 Guid 鍵、`UHLODLayer::SetLayerType`、World Partition `RuntimeHash` / `LoadingRange` 反射。對唔到嘅話先改嗰一行，唔好改 warp。

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
