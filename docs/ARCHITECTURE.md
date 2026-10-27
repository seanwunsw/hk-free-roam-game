# 架構

三步，中間冇第四步。

1. **Python**（`tools/run_pipeline.py`）讀 OSM 同 SRTM，用 `data/config/world.json` 做座標扭曲，寫 `data/processed`。
2. **編輯器烘焙**（`UHKBakeWorldCommandlet`，`-run=HKBakeWorld`，或者 `UHKBakeLibrary::BakeWorld`）讀中間檔，一次過放 Landscape、道路、建築物、水、車、直升機同停機坪入 World Partition 關卡。
3. **Runtime** 只做玩法：行、上車、Chaos 車、直升機、HUD、傳送。唔會再生成地圖。

每次 Play 都載入同一張烘焙關卡，所以佈局固定。傳送只搬玩家，唔改關卡。

## 座標

原點經緯度 114.174、22.295。先轉本地東、北米，再做可分離扭曲：

- X 只經 G(x)
- Y = H(y) + A(x) * tanh((y - yc(x)) / W) − 常數

G、H 係正數 smoothstep 比例嘅積分，Jacobian 保持正數，所以唔會折疊或者打結。遊戲 +X 東、+Y 北，米；Unreal 係厘米，Z 向上。

Python 係比例曲線嘅唯一來源，寫出 `warp_lut.bin`（magic `HKWARP01`）。`shared/hk_warp.h` 只查表，C++ 冇再抄一套 knot。

可分離係刻意嘅妥協。同核心同一條經線或者緯線嘅島嶼，唔可以兩軸都係 1:10，否則核心會被壓扁或者折疊。尖沙咀南北比例大於 1，係為咗維港窄處都有大約 1 公里，唔係 bug。

`world.json` 嘅目標：核心同密集市區大約 1:2（比例 0.5），郊區新界大約 1:6，郊野公園同離島大約 1:10。實測長軸大約 23.4 公里，喺 15–25 公里之內。維港 26 個斷面，最窄大約 1.52 公里。

高度縮放比平面溫和：`height_scale = clip(sqrt(兩軸幾何平均), 0.20, 1.25)`。單線道路至少 3.2 米，雙線至少 8 米（遊戲空間）。人同車唔縮放。

## 地圖內容

保留 motorway、trunk、primary、secondary、tertiary、unclassified 同佢哋嘅 link。residential、service、footway、path、steps 丟掉。

橋係抬高嘅橋面，兩端貼地形，唔會把地形挖上橋面。隧道，包括過海隧道，係明挖：路面係兩個洞口之間嘅弦，並且夾喺水面之上，所以過海段變成低矮嘅堤道，獅子山一類係路塹，冇隧道頂。短隧道當地面路。

地面路會把高度圖挖到路面；同一格有多條路時，低嗰條贏，避免高架把下面條街埋咗。建築物同道路重疊嘅部分會切走。

每個 250 米 tile：

- `b_*.glb` 建築物，一個 primitive 一棟，簡單 box 碰撞
- `r_*.glb` 道路條帶，UV.x 沿米數，UV.y 橫向 0–1，複雜碰撞、雙面
- `w_*.glb` 內陸水面

glTF 係 Y-up 米（X 東、Y 上、Z 北）。檔尾 HKGM chunk 寫住 BIN 入面每個 primitive 嘅 byte offset，烘焙器唔靠 Interchange 嚟猜軸。轉去 Unreal 厘米時 X 同 Z 對調，再按每個三角形嘅幾何法線決定要唔要交換索引。

Landscape：3025×2773 頂點，每 section 63 quad、每 component 1 section，即 48×44 components。`terrain.r16` 小端 uint16，第 0 行係南。中間值 32768 係海平面，Z scale 512 厘米，即每單位 4 厘米。Landscape 同海平面唔空間卸載；建築、路、車、直升機先至卸載。Loading range 目標 250000 厘米（2.5 公里）。HLOD layer 係 Instancing，但 proxy mesh 要另外跑 World Partition HLOD builder，呢份烘焙唔生成。

## 玩法物件

全部由烘焙器放進行關，唔係開波先 spawn。

- 玩家：第三人稱膠囊加方塊，行 500、跑 900、跳大約 520（厘米／秒）。中環 PlayerStart。
- 車：`AWheeledVehiclePawn`，一個 Root bone 嘅盒形 skeletal mesh，四個輪用 `AdditionalOffset`。視覺輪係圓柱，跟前進速度轉。質量 1450 kg，彈簧 45000 N/m，四驅，自動波。
- 直升機：自訂力同一力矩。總距同懸停輔助決定沿機身向上嘅推力；週期變距同偏航係角加速度（`AddTorqueInRadians` 嘅 accel change），唔再乘質量。無人操時關重力，鎖喺停機坪上。停機坪：中環、啟德、尖沙咀、沙田、大嶼山。
- HUD：Canvas，唔係 UMG。速度 km/h、高度米、經緯度、小地圖、大地圖、FPS、串流狀態。

小地圖北向上：`u = (x - minx) / 寬`，`v = (maxy - y) / 高`。像素比例跟地圖，唔係正方形。

## 模組

- `HKFreeRoam`：runtime。Enhanced Input、Chaos Vehicles、JSON、ImageWrapper。
- `HKFreeRoamEditor`：commandlet、glTF 讀取、材質、Landscape、Nanite、World Partition。
- 插件：Enhanced Input、Chaos Vehicles、Python、Editor Scripting、Interchange。Interchange 開住，但烘焙主路徑係 HKGM，唔依賴 Interchange 嘅軸轉換。
