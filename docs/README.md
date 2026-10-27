# 點樣開、build、烘焙、玩

引擎版本淨係睇 `UnrealProject/HKFreeRoam.uproject` 嘅 `EngineAssociation`。而家寫住 **5.6**，安裝要同呢個欄位一樣。

## 環境

- Unreal Engine，版本 = `EngineAssociation`
- Visual Studio 2022，「Game development with C++」（MSVC、Windows SDK）
- Git LFS

`data/processed` 已經包含高度圖、道路、建築物 glTF、出生點同小地圖。`data/raw` 唔入 git。

## 步驟

1. 用 Git LFS clone 呢個 repo。
2. 右鍵 `UnrealProject/HKFreeRoam.uproject` → Generate Visual Studio project files。
3. 打開 solution，**Development Editor**，build **HKFreeRoamEditor**。
4. 烘焙一次。把 `<UE>` 換成你安裝 `EngineAssociation` 嗰個引擎目錄：

```bat
"<UE>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" UnrealProject\HKFreeRoam.uproject -run=HKBakeWorld -unattended -AllowCommandletRendering -nosplash
```

5. 烘焙會建立 `/Game/Maps/HKWorld`，並把 `DefaultEngine.ini` 嘅 `GameDefaultMap` 同 `EditorStartupMap` 改去呢張圖。之前嗰兩行指向引擎模板，係為咗地圖未存在時編輯器都開到。
6. 打開專案，Play。玩家由中環附近開始。

另一個入口係 `UnrealProject/Content/Python/bake_hk_world.py`，佢呼叫 `unreal.HKBakeLibrary.bake_world()`，同 commandlet 係同一段 C++。

烘焙要為大約 2461 個 tile 建 Nanite mesh，喺 RTX 3060 上可能要幾十分鐘到幾個鐘。

## 玩法

步行：WASD、Shift 跑、Space 跳、滑鼠望。水面冇碰撞；角色低過海平面會游（bake 咗一個 bWaterVolume 嘅 physics volume，由 CharacterMovement 處理入水出水）。

F：450 cm 內最近嘅車，或者 700 cm 內最近嘅直升機。再按 F 喺載具右邊落車。鏡頭大約 0.6 秒 blend。

車係 Chaos 四驅，自動波，慢速踩煞會倒車，Space 係手煞。無人揸嘅車會拉手煞。

直升機：滑鼠週期變距、A D 偏航、E Q 總距、H 懸停輔助（預設開）。停喺停機坪時關掉重力，所以唔會自己跌落海。飛緊先至有推力同力矩。

M 開大地圖，北向上，撳地圖會傳送。Ctrl+1 到 Ctrl+0 去中環、灣仔、銅鑼灣、尖沙咀、油麻地、旺角、啟德、沙田、屯門、大嶼山。其他地方用控制台 `HK.Go <id>`。

F9 切換低／中畫質。中畫質開 Nanite、Lumen software、virtual shadow，並強制 `r.Lumen.HardwareRayTracing 0`。

## 座標工具

```bat
python tools/hkwarp/convert.py --lat 22.2849 --lon 114.1583
python tools/hkwarp/convert.py --x-cm 0 --y-cm 0    # Unreal 厘米，北係 -Y
```

遊戲內 `HK.ToGame <lat> <lon>` 傳送，`HK.ToLatLon` 印出玩家經緯度。兩邊都讀 `data/processed/warp_lut.bin`。

## 重造中間檔

```bat
python -m venv .venv
.venv\Scripts\pip install -r tools\requirements.txt
python tools\run_pipeline.py
```

`--synthetic` 會直接失敗（exit 2），唔會當成功交付。

架構同未測試項目：`docs/ARCHITECTURE.md`、`docs/STATUS.md`。
