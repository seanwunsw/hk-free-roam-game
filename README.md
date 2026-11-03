# 香港自由漫遊

固定佈局嘅香港開放世界原型。開專案、build、烘焙一次之後，每次運行都係同一張地圖：可以喺成個香港步行、揸車同飛。人同車保持 1:1，地形同街道先至縮放。

引擎版本只寫喺 `UnrealProject/HKFreeRoam.uproject` 嘅 `EngineAssociation`。而家係 **5.8**（用最新 hotfix，寫呢段時係 5.8.4）。請安裝同一個版本，下面嘅路徑用你部機嘅安裝目錄代入。由 5.6 升上嚟要點做，見下面「由 5.6 升級」。

## 你需要

- 上面個 Unreal Engine（DX12）
- Visual Studio：**2022 要 17.14 或以上**（Epic 自己 build 安裝版用 17.14 + MSVC 14.44），或者 Visual Studio 2026（5.8 建議）。Workload「Game development with C++」
- MSVC 最低 14.38（建議 14.44 至 14.50）；Windows SDK 最低 10.0.22621.0（預設 10.0.26100.0）。舊過呢啲，UBT 會一開始就報錯
- Git LFS（`*.glb`、`*.r16`、`*.png`、`*.vrm`、`*.fbx` 用 LFS）

`data/processed` 已經係用真實 OSM 同 SRTM 生成嘅烘焙輸入，平常唔使再跑 Python。想重造先至睇 `data/README.md`。

## 編譯同烘焙

喺 `UnrealProject/HKFreeRoam.uproject` 右鍵 **Generate Visual Studio project files**。

用 Visual Studio 打開生成嘅 solution，configuration 選 **Development Editor**，build target **HKFreeRoamEditor**。

### 由 5.6 升級（已經 build 過 5.6 先要睇）

1. 安裝 UE 5.8（Launcher），同埋上面嘅 Visual Studio 版本。
2. 刪 `UnrealProject` 入面嘅 `Binaries`、`Intermediate`、`DerivedDataCache`、`Saved`，同 `Plugins/VRM4U`（如果有）。
3. 有用 VRoid 角色先要：再跑 `tools\get_vrm4u.ps1`，佢而家攞 VRM4U 嘅 5.8 zip。
4. 右鍵 `.uproject` → **Generate Visual Studio project files**，再 build **HKFreeRoamEditor**。
5. 重新烘焙（世界同角色都要）。5.6 烘出嚟嘅 `/Game/HK/Player` 唔好留，5.8 嘅 IK rig 模板唔同（腳分咗 Leg 同 Foot 兩條 chain）。

物料刻意行舊（非 Substrate）路線：`Config/DefaultEngine.ini` 寫明 `r.Substrate=False`。原因見 `docs/STATUS.md`。

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

## 玩家角色

玩家係大約 120 cm 高嘅 chibi 公仔。模型由 `data/config/player.json` 揀，烘焙時匯入，換模型唔使改 code：

- 正式角色：自己用 VRoid 整，export 去 `data/characters/player.vrm`。設計圖同步驟：[docs/characters/VROID.md](docs/characters/VROID.md)。`.vrm` 要 VRM4U plugin：`powershell -ExecutionPolicy Bypass -File tools\get_vrm4u.ps1`，然後重新 generate project files 同 build。
- 暫代角色：一個 CC BY 4.0 嘅 glb，要自己下載（見 `data/characters/placeholder/README.md`）；冇就用方塊。
- 動畫：Quaternius Universal Animation Library（CC0），已經喺 repo。
- 只重烘角色：喺上面個烘焙命令加 `-PlayerOnly`。

換模型、刪暫代角色：[data/characters/README.md](data/characters/README.md)。

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

預設畫質係中，對應引擎 scalability High（level 2）：software Lumen 用 Global Distance Field（`r.Lumen.HardwareRayTracing=0`、`r.Lumen.TraceMeshSDFs=0`）、Nanite、virtual shadow。F9 去低係引擎 Low，Nanite 保持開。量度方法同而家嘅幀數見 `docs/PERFORMANCE.md`。

## 座標

遊戲資料（manifest、spawns、landmarks、warp）係米，+X 東、+Y 北、Z 向上。Unreal 係左手座標，所以喺 Unreal 入面北係 −Y：`ue_cm = (東, −北, 上) × 100`，只經 `HKAxes.h` 轉換。`convert.py` 同 `HK.ToLatLon` 用嘅係 Unreal 厘米（編輯器見到嘅座標）。Python 同 C++ 用同一份 `data/processed/warp_lut.bin`。

```bat
python tools/hkwarp/convert.py --lat 22.2849 --lon 114.1583
python tools/hkwarp/convert.py --x-cm -80011 --y-cm 225634
```

## 資料出處

地圖 © OpenStreetMap contributors，ODbL。角色、動畫同 VRM4U 嘅授權同署名見 [data/characters/CREDITS.md](data/characters/CREDITS.md)。地形係 NASA/USGS SRTM 1 arc-second（AWS elevation-tiles-prod），唔係地政總署 DTM。詳情同限制見 `docs/STATUS.md` 同 `docs/ARCHITECTURE.md`。

## 已知、未玩過

呢個 repo 係喺冇 Unreal Editor 嘅環境寫嘅。Pipeline、預覽圖同 warp 單元測試跑過；編輯器編譯、烘焙、步行、揸車、飛行、手感同幀數未跑過。未測嘅部分寫喺 `docs/STATUS.md`。
