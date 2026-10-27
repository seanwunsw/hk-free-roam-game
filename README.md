# 香港自由漫遊

固定佈局嘅香港開放世界原型。開專案、build、烘焙一次之後，每次運行都係同一張地圖：可以喺成個香港步行、揸車同飛。人同車保持 1:1，地形同街道先至縮放。

引擎版本只寫喺 `UnrealProject/HKFreeRoam.uproject` 嘅 `EngineAssociation`。而家係 **5.6**。請安裝同一個版本，下面嘅路徑用你部機嘅安裝目錄代入。

## 你需要

- 上面個 Unreal Engine（DX12）
- Visual Studio 2022，workload「Game development with C++」，包括 MSVC 同 Windows SDK
- Git LFS（`*.glb`、`*.r16`、`*.png` 用 LFS）

`data/processed` 已經係用真實 OSM 同 SRTM 生成嘅烘焙輸入，平常唔使再跑 Python。想重造先至睇 `data/README.md`。

## 編譯同烘焙

喺 `UnrealProject/HKFreeRoam.uproject` 右鍵 **Generate Visual Studio project files**。

用 Visual Studio 打開生成嘅 solution，configuration 選 **Development Editor**，build target **HKFreeRoamEditor**。

烘焙（會開一個空白關卡，讀 `data/processed`，寫入 `/Game/Maps/HKWorld`，再把啟動地圖改去呢張圖）：

```bat
"<UE 安裝目錄>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" UnrealProject\HKFreeRoam.uproject -run=HKBakeWorld -unattended -AllowCommandletRendering -nosplash
```

同一件事亦可以用 Python：

```bat
"<UE 安裝目錄>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" UnrealProject\HKFreeRoam.uproject -ExecutePythonScript=UnrealProject/Content/Python/bake_hk_world.py -unattended -AllowCommandletRendering -nosplash
```

烘焙未完成之前，啟動地圖係引擎模板，方便專案開得返。烘焙成功之後 `Config/DefaultEngine.ini` 會改做 `/Game/Maps/HKWorld`。如果命令行冇改到，喺編輯器打開 `Content/Maps/HKWorld`，World Settings 確認 Game Mode 係 `HKFreeRoamGameMode`，然後 Play。

2461 個 Nanite mesh 會喺你部機 build。以 RTX 3060 計，烘焙可能係幾十分鐘到幾個鐘，唔係幾秒。

## 操作

| 動作 | 按鍵 |
| --- | --- |
| 行 / 跑 / 跳 | WASD、Shift、Space |
| 望 | 滑鼠 |
| 上落車、上落直升機 | 靠近之後按 F |
| 車 | W 油門，S 煞車（慢速自動倒車），A D 轉向，Space 手煞 |
| 直升機 | 滑鼠係週期變距，A D 偏航，E Q 總距，H 開關懸停輔助，方向鍵或 IJKL 後備 |
| 大地圖（撳地圖傳送） | M |
| 說明 | F1 |
| 畫質低 / 中 | F9 |
| 地區傳送 | Ctrl+1 至 Ctrl+0（中環到大嶼山） |

控制台：

```text
HK.Go Central
HK.ToGame 22.2849 114.1583
HK.ToLatLon
```

`HK.ToGame` 第一個數係緯度。如果第一個數絕對值大過 90，就會當佢係經度。其他地區可以用 `HK.Go <id>`，id 同 `data/config/world.json` 一樣，例如 `ShaTin`、`Airport`、`Lamma`。

預設畫質係中：Lumen（software，關掉 hardware ray tracing）、Nanite、virtual shadow。F9 切去低會關掉 Lumen、Nanite 同 virtual shadow。目標係 DX12、RTX 3060、中畫質大約 60 fps；呢個幀數未喺真機量過。

## 座標

遊戲資料（manifest、spawns、landmarks、warp）係米，+X 東、+Y 北、Z 向上。Unreal 係左手座標，所以喺 Unreal 入面北係 −Y：`ue_cm = (東, −北, 上) × 100`，只經 `HKAxes.h` 轉換。`convert.py` 同 `HK.ToLatLon` 用嘅係 Unreal 厘米（編輯器見到嘅座標）。Python 同 C++ 用同一份 `data/processed/warp_lut.bin`。

```bat
python tools/hkwarp/convert.py --lat 22.2849 --lon 114.1583
python tools/hkwarp/convert.py --x-cm -80011 --y-cm 225634
```

## 資料出處

地圖 © OpenStreetMap contributors，ODbL。地形係 NASA/USGS SRTM 1 arc-second（AWS elevation-tiles-prod），唔係地政總署 DTM。詳情同限制見 `docs/STATUS.md` 同 `docs/ARCHITECTURE.md`。

## 已知、未玩過

呢個 repo 係喺冇 Unreal Editor 嘅環境寫嘅。Pipeline、預覽圖同 warp 單元測試跑過；編輯器編譯、烘焙、步行、揸車、飛行、手感同幀數未跑過。未測嘅部分寫喺 `docs/STATUS.md`。
