# 揸車手感計劃（GTA5 式「街機寫實」）

> 狀態：程式碼已寫好，**未喺 UE 編譯，亦未試玩過**（box 冇 UE）。所有數字要等 Sean 喺 PC 跑 `HK.DriveTest` 之後先算數。
> `tools/drive_model` 只係離線 sanity model，**唔可以代替 UE 測試**。

## 1. 目標

- 地圖、車、操控不變：W 油、S 剎／倒後、A/D 軚、Space 手掣、F 上落車。
- 手感：加速有層次、軚隨車速收窄、唔會「溜冰」、剎車有點頭、轉彎有側傾、手掣可以 drift 又救得返、唔會無啦啦自己自轉。
- 鏡頭：GTA5 式追尾鏡，順滑、加速拉遠、剎車推近、高速 FOV 變闊、輕微震、零 jitter。
- 暫時只有 **3 個車種**（Sean t98u）：**FR**、**FF**、**4WD（AWD）**。冇跑車／超跑／肌肉車／SUV／越野／電單車。

## 2. 架構

```
data/config/vehicles.json      ← 唯一真相：3 個 class、車 id → class、lot、targets
        │
        ├─ HKHandling.cpp       讀 JSON（Defaults 深層合併每個 class），寫 wheel CDO
        │     └─ UHKWheelFront_FR/FF/AWD、UHKWheelRear_FR/FF/AWD（HKWheelClasses.h）
        ├─ AHKCar::ApplyHandling   質量、重心、慣量、引擎扭力曲線、波箱、驅動輪、分扭、懸掛、輪
        ├─ AHKCar::DriveTick       每 tick：玩家輸入 → hkdrive::Step → Chaos 輸入 + 額外力矩
        │     └─ shared/hk_drive_assist.h   街機 assist（C++ 同 Python 共用同一份）
        ├─ UHKChaseCamera          追尾鏡（PostPhysics，1/120 s 內部 substep）
        └─ AHKDriveTestRunner      HK.DriveTest：喺 2 km 高空測試場自動跑，出 CSV

tools/drive_model/   離線模型（ctypes 載入同一個 hk_drive_assist.h）
tools/tests/test_drive_model.py   JSON ↔ C++ key、分配、header、模型 targets
```

### 2.1 點解係「Chaos + assist 層」

Chaos 負責真實嘅部分：懸掛、輪胎、引擎、波箱、差速器、驅動輪。Assist 只係喺上面加幾樣嘢：

| Assist 功能 | 做法 |
|---|---|
| 軚隨車速收窄 | `HighSpeedSteer`／`SteerSpeedRefKmh`；Chaos 本身嘅 steering curve 設成平（佢 X 軸係 MPH） |
| 輸入平滑 | `SteerRise/Return`、`ThrottleRise/Fall`、`BrakeRise/Fall`；Chaos input rate 設 60，交俾 assist 控制 |
| 唔溜冰 | `LateralGrip`：後軸側滑速度阻尼，上限 `LateralGripMaxG` |
| 唔亂轉 | `YawDamping`、`AntiSpin`（超過 `MaxSlipDeg` 先加力）、`SpinDamping` |
| 手掣 drift | `HandbrakeRearGrip`（後輪摩擦倍數）、`HandbrakeYawKick`（一下 yaw） |
| 油門甩尾（FR） | `PowerOversteer`：後驅＋大油，後輪抓地減少 |
| 救車 | `GripRecoverSeconds`、`CountersteerAssist`、`AutoCountersteer`、`DriftSteerOpen` |
| 側傾／點頭 | Chaos 懸掛做真實部分；`AllowedRollDeg`＋`AntiRoll`＋`RollDamping` 只限制過量 |
| 高速穩定 | `DownforceG`、`HighSpeedGripLoss`（預設 0） |
| 離地 | `AirControl`（只阻尼，唔畀飛天轉向） |
| 越野 | `OffroadGrip`（踩落 landscape 時嘅摩擦倍數，AWD 最高） |

Slip 用 **後軸側滑角**（VelLat 喺 actor 原點量度 = 軸距中心，所以 `RearAxleM = WheelbaseM / 2`），低速唔會誤判 drift。

### 2.2 方向同單位（易錯）

- Unreal：X 前、Y 右、Z 上，cm。繞 +Up 力矩 = 車頭向右（yaw+）；繞 −Fwd = 右邊沉（roll+）。
- 力矩／力用 `AddTorqueInRadians`／`AddForce`，`bAccelChange = true`（assist 輸出係角加速度／加速度）。
- `SpringRate`：Chaos 內部 ×100，所以填 `(2π·RideHz)²·角落質量 / 100`。`MaxRaise ≥ 靜態下沉 + 4 cm`。
- 重心：用 BodyInstance `COMNudge = (ComX, 0, ComZ − 55)`（車身 box 中心 Z = 55 cm）。冇用 `bEnableCenterOfMassOverride`，因為語義唔肯定。
- `FrontRearSplit`：Chaos 數值係「後輪份額」，0.6 = 前 40／後 60。

## 3. 三個車種

| | **FR**（前置後驅） | **FF**（前驅） | **AWD／4WD**（四驅） |
|---|---|---|---|
| 性格 | **三款入面加速最快**，扭力全落後輪，重量偏後（約 43/57）幫起步抓地，油門＋手掣可以甩尾／drift | 易轉、寬容，極限輕微推頭，但靈活，好難自轉 | 穩陣、抓地強、爛路好，分扭 40/60 |
| 驅動 | RWD，split 1.0 | FWD，split 0.0 | AWD，split 0.6（40/60） |
| 質量 | 1450 kg | 1250 kg | 1650 kg |
| 重量分佈（ComX） | −20 cm（約 43/57 後重） | +32 cm（約 62/38 前重） | +13 cm（約 55/45） |
| 重心高（ComZ） | 52 cm（加速時更多重量轉去後輪） | 45 cm | 55 cm |
| 慣量倍數 | 1.0 | 1.0 | 1.05 |
| 引擎 | 560 Nm，7200 rpm，尾牙 3.6，換波 0.12 s | 300 Nm，6800 rpm，尾牙 4.0，換波 0.18 s（三款最慢） | 390 Nm，6800 rpm，尾牙 3.8，換波 0.18 s |
| 輪 | 34 cm 半徑 ／ 22 cm 闊 | 34 ／ 22 | 36 ／ 24 |
| 懸掛頻率 前／後 | 1.9 ／ 2.0 Hz | 2.1 ／ 2.3 Hz | 1.6 ／ 1.7 Hz（軟，行程 14/15 cm） |
| 阻尼比 | 0.55 | 0.55 | 0.48 |
| 防傾桿 | 0.5 | 0.6 | 0.2（抓地低咗都保留側傾感） |
| 摩擦 前／後 | 2.15 ／ 2.35 | 1.95 ／ 2.1 | 1.6 ／ 1.65 |
| 剎車 前／後（Nm） | 2300 ／ 1300 | 1800 ／ 850 | 2500 ／ 1450 |
| 手掣（Nm） | 4000 | 3200 | 3600 |
| ABS ／ TC | ABS 開；TC 前關、後開 | ABS 開；TC 開 | ABS 開；TC 開 |
| 高速軚比例 ／ 參考車速 | 0.37 ／ 140 km/h | 0.38 ／ 150 km/h（80 km/h 時軚最多，最靈活） | 0.36 ／ 130 km/h |
| 轉軚速度 SteerRise | 3.8 | 4.5 | 3.2 |
| YawDamping | 3.8 | 5.0 | 4.5 |
| MaxSlipDeg ／ AntiSpin | 45 ／ 12 | 30 ／ 12 | 38 ／ 9 |
| PowerOversteer | 0.5 | 0 | 0.15 |
| 手掣後輪抓地 ／ yaw kick | 0.38 ／ 1.4 | 0.55 ／ 1.1 | 0.45 ／ 1.2 |
| 救車時間 GripRecover | 0.7 s | 0.45 s | 0.6 s |
| 容許側傾 | 4.5° | 4.0° | 6.0° |
| OffroadGrip | 0.75 | 0.75 | 0.92 |
| 極速限制 | 260 km/h | 220 km/h | 245 km/h |
| 鏡頭 臂長／高度 | 600 ／ 150 cm，加速拉 70 cm | 570 ／ 145 cm | 650 ／ 170 cm，bump shake 0.45 |

全部數值喺 `data/config/vehicles.json`；改 JSON 之後喺遊戲入面 `HK.ReloadHandling` 即刻生效，唔使 rebuild。

### 3.1 26 架車點分

| Class | 車 id |
|---|---|
| FR（9） | TuenMun_0、Central_0、CausewayBay_0、TST_0、MongKok_1、KaiTak_0、TseungKwanO_0、TaiPo_0、Stanley_0 |
| FF（9） | Central_1、WanChai_0、TST_1、YauMaTei_0、MongKok_0、KwunTong_0、TsuenWan_0、Aberdeen_0、CheungChau_0 |
| AWD（8） | Central_2、ShaTin_0、Lantau_0、KwaiChung_0、YuenLong_0、Fanling_0、SaiKung_0、Airport_0 |

屯門出生點：TuenMun_0 係 FR。為咗三款都喺附近，`lot` 會喺開波 1 秒後喺 TuenMun_0 前後 7.5 m／15 m 加一架 FF、一架 AWD（地面 trace + 重疊檢查，最多試 60 次）。預設關住（`HK.CarLot` 0），要喺 anchor 車載入之前設 `HK.CarLot 1`（例如用 -ExecCmds）先會擺。

## 4. 追尾鏡（UHKChaseCamera）

- Spring arm 用絕對旋轉，唔跟 pawn control rotation，tick 喺 PostPhysics（避免同物理錯開一 frame 而 jitter）。
- 內部 1/120 s substep：yaw 用臨界阻尼彈簧追「車頭方向」同「速度方向」嘅混合（`VelocityBlend`），彈簧硬度由 `YawStiffness` 漸變到 `YawStiffnessFast`（150 km/h）；最大落後 70°。
- 臂長 = `ArmCm` + 車速拉遠 + 加速拉遠（`AccelPullCm`）− 剎車推近（`BrakePushCm`）。
- 側向 G：鏡頭橫移（`LatShiftCm`）同少少 roll（`LatRollDeg`）。
- FOV：`BaseFov` + smoothstep(車速 / `FovSpeedKmh`) × `FovAdd`。
- 震：`ShakeStartKmh` 以上加 Perlin 震；爛路 vertical jolt 加 bump shake。
- Spring arm pivot 喺車頂上（`PivotCm` 110 cm，車 mesh root 喺路面）；高度用 `TargetOffset`（世界向上），`SocketOffset` 淨係橫移。以前 pivot 喺路面，collision probe 一開始就陷入路面 → 臂長縮到 0 → 鏡頭喺車底（drivefix3 修正）。
- 滑鼠 360° 環迴望（`AddLook`），pitch 限住鏡頭最少離地 45 cm；停手 `RecenterDelay`（1.75 s）之後順滑回到車後，車速快回得快（1×→4.5×，0→120 km/h）。`RecenterWhenParked`（預設 true）設 false 就停車時唔回正，>10 km/h 先回。
- 滾輪拉近／拉遠（`AddZoom`，臂長 × 0.5–2.2，平滑）；步行鏡頭都得（× 0.45–2.5）。
- 淨係揸緊（或者 DriveTest）嗰架車嘅鏡頭 rig tick 同做 arm collision sweep（`SetCameraRigActive`）；泊喺度嗰 26 架唔行。
- Jitter 指標：每 frame 鏡頭 yaw 二階差分 RMS（度），同鏡頭相對車位置二階差分 RMS（cm）。

## 5. 測試計劃

### 5.1 UE：`HK.DriveTest`

喺 Tuen Mun 上空 2 km 生成 6 km × 800 m 平地測試場，加一條爛路（120 m 長，6 cm 高，左右交替每 3 m 一條）。每個 class 生成一架測試車（冇 controller，autopilot 輸入），鏡頭會跟住測試車。

| 階段 | 做法 | 指標 |
|---|---|---|
| 加速 | 全油，lane 保持 | `Accel0To100S`、`AccelSquatDeg` |
| 剎車 | 100 → 0 全剎 | `Brake100To0M`（由剎車輸入到 0.99 起計）、`BrakeLockPct`、`BrakeDiveDeg` |
| 極速 | 全油直到 3 秒升 < 1 km/h | `TopSpeedKmh`、`TopSpeedLimited`（1 = 跑到場尾，未到平台） |
| 側 G | 60／120 km/h 定速，8 秒內軚由 0 加到盡 | `LatG60`、`LatG120`（1 秒平均，slip < 12°，速度 ±8%）、`MaxRollDeg` |
| Slalom | 80 km/h，軚 0.5·sin(0.5 Hz)，6 秒 | `SlalomYawGain`（最大 yaw rate ÷ 0.5）、`SlalomLagS` |
| Drift（有救） | 70 km/h，手掣 0.7 s＋軚 0.8＋油 0.6，之後反軚 | `DriftEntryS`（slip > 15°）、`DriftRecoverS`（slip < 5° 同 yaw < 15°/s 持續 0.3 s）、`DriftPeakSlipDeg` |
| Drift（甩手） | 同上但之後放手 | `HandsOffRecoverS` |
| 自轉 | 兩個 drift 測試入面 slip > 80° 或者轉咗 > 200° | `Spins` |
| 爛路 | 60 km/h 過 bump | `RoughMaxRollDeg`、`RoughMaxVertG` |
| 鏡頭 | 全部駕駛 frame | `CamJitterDeg`、`CamJitterPosCm` |

輸出：
- `UnrealProject/Saved/HKDriveTest/summary_<時間>.csv`（class, metric, value, min, max, PASS/FAIL）
- `UnrealProject/Saved/HKDriveTest/trace_<class>_<時間>.csv`（每 frame）
- log：`HKDriveTest <class> <metric> <value> [min, max] PASS/FAIL`，最後 `HKDriveTest DONE failures=N summary=...`

無人值守（PowerShell，Sean PC）：

```powershell
& "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "E:\thingstoworkon\hk-free-roam-game\UnrealProject\HKFreeRoam.uproject" /Game/Maps/HKWorld -game -windowed -ResX=1280 -ResY=720 -benchmark -fps=60 -log -unattended -nosplash -ExecCmds="HK.DriveTest all quit" -abslog="E:\thingstoworkon\hk-free-roam-game\UnrealProject\Saved\Logs\drivetest.log"
Select-String -Path "E:\thingstoworkon\hk-free-roam-game\UnrealProject\Saved\Logs\drivetest.log" -Pattern "HKDriveTest"
```

`-benchmark -fps=60` 令每 frame 固定 1/60 s，結果可以重覆。只測一款：`HK.DriveTest FR`。

### 5.2 目標範圍

`[min, max]`，`—` = 冇界限。

| 指標 | FR | FF | AWD |
|---|---|---|---|
| 0–100 km/h（s） | **3.8–4.6**（最快） | 6.0–8.5 | **4.8–5.8** |
| 極速（km/h） | 240–275 | 205–230 | 230–260 |
| 100–0 剎車距離（m） | 32–40 | 32–40 | 32–40 |
| 側 G @60 | 1.00–1.25 | 1.00–1.25 | 1.00–1.25 |
| 側 G @120 | 1.00–1.30 | 1.00–1.30 | 1.00–1.30 |
| 最大側傾（°） | ≤ 5.5 | ≤ 5.0 | 1.5–7.5 |
| Slalom yaw gain（°/s 每單位軚） | 40–110 | 40–100 | 35–95 |
| Slalom 延遲（s） | ≤ 0.25 | ≤ 0.20 | ≤ 0.20 |
| Drift 入彎（s） | ≤ 0.7 | ≤ 1.2 | ≤ 1.0 |
| Drift 救返（s） | ≤ 1.8 | ≤ 1.2 | ≤ 1.5 |
| Drift 最大 slip（°） | 20–60 | 8–40 | 15–50 |
| 甩手自己救返（s） | ≤ 2.0 | ≤ 1.5 | ≤ 1.8 |
| 自轉次數 | 0 | 0 | 0 |
| 鏡頭 jitter（°） | ≤ 0.08 | ≤ 0.08 | ≤ 0.08 |
| 爛路最大側傾（°） | ≤ 10 | ≤ 10 | ≤ 10 |
| 剎車鎖死（%） | ≤ 5 | ≤ 5 | ≤ 5 |

**第一次 UE 跑（drivetest1）之後改咗嘅目標**：
- 側 G 收窄到 1.0–1.25（@120 准到 1.30，因為有 downforce 同 assist 側向抓地）：GTA 式路車大約 1.0–1.2 g，舊上限 1.4 太闊，UE 跑出 1.55–1.77 都差唔多 pass。
- 剎車收窄到 32–40 m（約 1.2–1.0 g），三款一樣。
- AWD 最大側傾下限 2.0 → 1.5°：抓地降咗之後側 G 細咗，側傾自然少；AWD 仍然係三款入面側傾最多。
- Slalom gain 範圍唔改：UE 量到 36–41，校準後模型都喺呢個位，下限 40／40／35 啱用。

**加速次序**：Sean 規格要 FR 係「加速快」嗰架，所以 FR 0–100 上限（4.6 s）要細過 AWD 下限（4.8 s）同 FF 下限（6.0 s）；`test_fr_is_the_fast_accelerating_class` 會檢查。FR 嘅優勢嚟自重量偏後、後輪摩擦高過前輪（2.35／2.15）同快啲換波；AWD 扭力 390 Nm，保留四驅起步穩定同爛路抓地（OffroadGrip 0.92、軟懸掛）。FF 係最慢：規格係「易轉」車唔係快車，UE drivetest1 FF（4.85 s）快過 AWD（5.38 s），所以扭力 340 → 300 Nm，加上抓地降低後前驅起步受抓地限制。測試亦檢查 AWD 上限 ≤ FF 下限。

### 5.3 離線模型（`tools/drive_model`）

```bash
python -m tools.drive_model.run            # 3 個 class
python -m tools.drive_model.run FR --csv out/
pytest tools/tests/test_drive_model.py
```

平面車模型：載荷轉移、輪胎曲線、摩擦橢圓、輪空轉、ABS/TC、roll/pitch 彈簧阻尼、按 Drive／FrontRearSplit 分扭，物理 1/480 s、遊戲 1/60 s，用同一份 `hk_drive_assist.h`。輪胎常數已經用 UE drivetest1 校準（見 5.4）。用途：改 JSON 之前預估 UE 結果、睇 assist 有冇令車自轉。**最終以 UE `HK.DriveTest` 為準。**

目前模型結果（全部 PASS，vehicles.json drivefix4，模型已用 drivetest1＋2 校準，見 5.5）：

| | FR | FF | AWD |
|---|---|---|---|
| 0–100 | **4.50 s**（UE 4.58） | 6.83 s | 5.47 s |
| 極速 | 253 | 213 | 237 |
| 100–0 | 34.7 m（UE 33.8） | 34.0 m | 38.2 m |
| 側 G 60／120 | 1.12／1.20 | 1.14／1.19 | 1.09／1.11 |
| 側傾 | 1.2° | 0.8° | 2.1° |
| Slalom gain | 44 | **49**（最靈活） | 37 |
| Drift peak／救返 | 48°／0.90 s | 30°／0.68 s | 38°／0.87 s |
| 自轉 | 0 | 0 | 0 |

### 5.4 模型校準（UE drivetest1，2026-11-03 23:40）

用 `HK.DriveTest all` 第一次 UE 5.8 結果（`summary_20261103_234023.csv` 同三個 trace）校 `tools/drive_model/model.py` 頂嘅常數。睇 trace 得出：

| 觀察（UE trace） | 結論 | 常數 |
|---|---|---|
| 三款剎車都係 ~1.56–1.68 g，冇鎖死；扭力估計 Σ扭力／(r·m) 只有 ~1.47 g | 剎車受抓地限制，唔係扭力；Chaos 剎車實際強過扭力估計 | `MU_PER_FRICTION` 0.30 → **0.47**，`BRAKE_TORQUE_SCALE` 1.5 |
| 側 G 最高 1.55–1.8（摩擦 3.3–3.6），FF 前驅起步 ~0.78 g（受抓地限制） | 同一個 μ／摩擦倍數 ≈ 0.47 | 同上 |
| 側 G ramp：後輪 slip 對側 G 線性，~0.5 g／度 | 後輪胎曲線 | `REAR_ALPHA0` 3.2° |
| 前輪：要 10–20° slip 先去到 1–1.5 g；細軚角幾乎冇反應（凸曲線），高速硬啲 | 前輪好軟，係 UE slalom gain（36–41）得舊模型（76–91）一半嘅原因 | `FRONT_ALPHA0` 15°（@16.9 m/s，× 車速^−0.58），`FRONT_POWER` 2.5，`LAT_PEAK` 1.6 |
| 側傾大約係彈簧估計嘅一半 | Chaos 側傾硬啲 | `ROLL_STIFFNESS_SCALE` 2.0 |
| Slalom 延遲 0.08–0.10 s | Chaos 下一個 physics step 先用輸入 | `INPUT_DELAY_FRAMES` 1 |

假設：輪胎曲線（g／載荷）**唔跟**摩擦倍數變，摩擦淨係限制頂位。如果下一次 UE 跑顯示 slalom gain 跟摩擦一齊跌（即係曲線跟摩擦縮），將 `LAT_CURVE_SCALES_WITH_FRICTION` 設 True 再校；咁樣 FF／FR slalom 可能跌到 40 以下，要再加 `HighSpeedSteer`。

校準後模型對 drivetest1（舊 JSON）：

| 指標 | FR UE／模型 | FF UE／模型 | AWD UE／模型 |
|---|---|---|---|
| 0–100（s） | 3.52／3.42 | 4.85／5.38 | 5.38／5.72 |
| 100–0（m） | 23.4／25.1 | 22.7／25.5 | 21.9／28.2 |
| 側 G 60 | 1.55／1.68 | 1.77／1.43 | 1.69／1.15 |
| 側 G 120 | 1.70／1.92 | 1.77／1.78 | 1.72／1.67 |
| Slalom gain | 40.8／40.8 | 38.4／38.2 | 36.2／36.9 |
| Drift peak（°） | 45.5／58.0 | 30.0／36.3 | 37.2／45.9 |
| 甩手救返（s） | 0.97／1.25 | 0.72／0.80 | 1.03／1.17 |
| 側傾（°） | 1.93／2.15 | 1.71／1.18 | 3.38／2.94 |
| 極速 | 252／253 | 213／214 | 236／237 |

已知偏差：模型 FF／AWD 加速慢 0.3–0.5 s、剎車長 7–28%（AWD ABS 震盪）、drift slip 高 ~25%（偏保守）、LatG60 FF／AWD 低（模型定速控制喺大 slip 時跌速，出咗 ±8% 窗）。（5.5 用 drivetest2 再校咗，以 5.5 為準。）

每次 UE 跑完：

```bash
python -m tools.drive_model.calibrate path/to/summary_<時間>.csv   # UE vs 模型（目前 JSON）
```

### 5.5 模型校準（UE drivetest2，2026-11-03 23:54）

drivetest2 用 drivefix2 JSON（摩擦 ~2.2）。結果：FR 全 PASS；FF 剎車 30.3 m、側 G120 1.34；AWD 剎車 28.2 m、側 G 1.30／1.45（太黐地）。睇法：

| 觀察 | 結論 | 常數 |
|---|---|---|
| 摩擦跌咗 ~35%，slalom gain 冇變（AWD 兩次都 36.2） | 側向輪胎曲線唔跟摩擦變，假設成立 | `LAT_CURVE_SCALES_WITH_FRICTION` 維持 False |
| 剎車 1.11／1.20／1.29 g（FR／FF／AWD），摩擦差唔多 | 抓地限制；FF、AWD 每單位摩擦嘅抓地多過 FR（側 G 一樣） | `MU_SCALE_BY_DRIVE` RWD 0.94、FWD 1.06、AWD 1.15 |
| 剎車 g 高過起步／側向用嘅 μ | 剎車方向多啲抓地 | `LONG_MU_SCALE` 1.12（淨係剎車） |
| drivetest1（摩擦 3.4）剎 ~1.7 g，Σ扭力／(r·m) 只有 1.47 g | drivetest1 係**扭力**限制（5.4 嘅「抓地限制」結論錯咗），Chaos 剎車 ≈ 1.3 × 扭力 | `BRAKE_TORQUE_SCALE` 1.3 |
| 舊 ABS（放 / 再踩）喺模型震盪、鎖死，UE 從來冇鎖 | ABS 改為封頂扭力 = 抓地；< 3 m/s 關 ABS；鎖死計法同 UE 一樣要 > 3 m/s | model.py |

校準後模型 vs UE（剎車 m）：drivetest1 FR 22.8／23.4、FF 24.3／22.7、AWD 25.2／21.9；drivetest2 FR 34.7／33.8、FF 29.9／30.3、AWD 28.4／28.2。側 G120 drivetest2：1.20／1.18、1.32／1.34、1.44／1.45。已知偏差：AWD LatG60 模型偏低（定速控制假象）、drift slip 模型偏高。`test_model_reproduces_ue_runs` 鎖住兩次跑嘅加速、slalom、側 G120、極速、剎車。

drivefix3 retune（淨改 FF、AWD，FR 不變）：FF 摩擦 2.2／2.35 → 1.95／2.1，剎車 2100／1000 → 1800／850；AWD 摩擦 2.15／2.2 → 1.8／1.85，剎車 2700／1600 → 2200／1300。按 drivetest2 每單位摩擦線性推 UE：FF 剎車 ~35–37 m、側 G120 ~1.19；AWD 剎車 ~34–36 m、側 G120 ~1.2、LatG60 ~1.1；slalom 唔跟摩擦，AWD 應該仲係 ~36。

drivefix4 AWD 再檢查（GSE）：UE 兩次跑 AWD 側 G120 3.3 → 2.175 摩擦只跌 1.715 → 1.453（power-law 指數 0.40；FR 0.83、FF 0.63）。模型喺 2.175 以下突然變成 μ 限制（指數 ~1），但 UE 未有呢個區間嘅數據，所以唔可以單靠模型。按兩點 fit：

| AWD 摩擦 | power-law | soft-min（n=2／4／8） | 模型 | 目標 |
|---|---|---|---|---|
| 1.825（A，drivefix3） | 1.36 | 1.32／1.29／1.25 | 1.19 | ≤ 1.30 |
| 1.625（B，drivefix4） | 1.29 | 1.22／1.16／1.10 | 1.11 | ≥ 1.0 |

A 喺大部分外推會超標，B 全部過，所以 vehicles.json 用 B：摩擦 1.6／1.65、剎車 2500／1450、防傾桿 0.45 → 0.2（UE 側傾跟摩擦跌，指數 ~1.36，推到 1.6 只有 ~1.3°，低過下限 1.5°；防傾桿細咗 → 模型 2.1°）。剎車：模型 38.2 m（抓地限制，扭力冇影響），UE power-law 推 ~34 m，都喺 32–40。Slalom 兩次 UE 都係 36.2（唔跟摩擦）。注意：兩次 UE 跑剎車扭力一樣，扭力嘅影響未喺 UE 量過。

同一個 session 比較 A／B：
```
HK.ReloadHandling sweeps/awd_f180.json   （A：overlay 疊喺 vehicles.json 上面）
HK.DriveTest AWD
HK.ReloadHandling                        （冇參數 = 返去 vehicles.json，即 B）
HK.DriveTest AWD
```
Overlay 檔喺 `data/config/sweeps/`，只寫要改嘅欄位；`test_sweep_overlays_only_override_existing_keys` 檢查欄位名冇打錯。

```bash
python -m tools.drive_model.calibrate summary.csv --vehicles 嗰次用嘅vehicles.json
```

## 6. 指令

| 指令 | 用途 |
|---|---|
| `HK.CarClass` | 顯示你揸緊（或者 10 m 內最近）架車嘅 class |
| `HK.CarClass FR\|FF\|AWD\|4WD` | 即時轉 class（亦接受 RWD／FWD） |
| `HK.SpawnCar FF` | 喺你前面 6 m 生成一架 |
| `HK.ReloadHandling [overlay]` | 重新讀 `vehicles.json`（可選 overlay，相對 `data/config/`，例如 `sweeps/awd_f180.json`），套落全部車 |
| `HK.DriveTest [all\|FR\|FF\|AWD] [quit]` | 自動測試 |
| `HK.DriveAssist 0` | 關 assist，淨係 Chaos（對比用） |
| `HK.CarLot 1` | 生成屯門 lot 車（預設 0 = 關） |
| `HK.CarWheelSuspension -1` | 如果車輪視覺上下調轉咗就用呢個 |

## 7. Rebuild vs rebake

**drivefix4 要 rebuild C++**（唔使 rebake）：
- `HKCar.cpp`：ensure 修正。`SpawnActorDeferred` 已經喺 `PostSpawnInitialize` 註冊 component，Chaos movement component 註冊時就搵 wheel bone，所以 `FinishSpawning` 之前先 set mesh 太遲。而家 movement component `bAutoRegister = false`，`RegisterVehicleMovement()` 等 mesh 有 asset 先註冊：擺喺地圖嘅車喺 `PostRegisterAllComponents`，`SpawnCar` 喺 set mesh 之後、`FinishSpawning` 之前，未 bake 嘅 world 喺 `BeginPlay` 再試。冇寫 class default（drivefix3 嘅 CDO 做法已經拎走）。
- `HKChaseCamera`／`HKCar`／`HKFreeRoamCharacter`／`HKPlayerController`／`HKFreeRoamHUD`：鏡頭車底修正、360° 環迴望＋自動回正、滾輪 zoom（換 avatar 之後保留）、幫助文字、鏡頭 rig 淨係揸緊先 tick、HUD 數 actor 串流完之後 5 s 一次。
- `HKHandling`／`HKDebugCommands`：`RecenterWhenParked`、`HK.ReloadHandling [overlay]`。
- JSON（FF／AWD retune、`RecenterDelay` 1.75、`RecenterWhenParked`）`HK.ReloadHandling` 就生效。

原本：**只需要 rebuild C++**（新增 UCLASS：`UHKWheelFront_*`、`UHKWheelRear_*`、`UHKChaseCamera`、`AHKDriveTestRunner`）。唔使 rebake：地圖、tiles、spawns、車 mesh 全部冇改。Class 按 car id（`Tags[0]`）喺 runtime 由 JSON 決定。

## 8. 風險同未確認 API

- Assist 力矩喺 game thread PrePhysics 加；如果 Chaos async／substep，可能只作用喺第一個 substep → 效果偏弱。睇 trace 嘅 yaw 同 `Assist.YawAccel`。
- `RecreatePhysicsState()` 會唔會用新 wheel CDO 重建輪：唔肯定，所以亦用 runtime setter 補（`SetWheelFrictionMultiplier` 等）。
- `FVehicleInputRateConfig` 欄位名、`SetAffectedByEngine` 等 setter 簽名、`IsInAir`／`GetSuspensionOffset` const、`PhysicsVehicleOutput()` 係咪 public：要編譯先知。
- `GetRotationAngle` 單位同 150 km/h 以上 aliasing → 鎖死輪判斷可能誤報。
- 極速：6 km 場未必夠 FR 到平台；`TopSpeedLimited = 1` 時 `TopSpeedKmh` 偏低。
- `-ExecCmds` 喺 world partition 未 load 完就行：runner 會等 2 秒，TuenMun_0 搵唔到就用玩家位置。
- Lot 車係 runtime spawn，同 AGENTS.md「唔好 runtime 生成城市」有少少衝突（只係 2 架車，有 CVar 可以關）。
