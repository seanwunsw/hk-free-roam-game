# 路面、標線、行人路、建築、單程路、泊車高度：計劃

Branch `fix/car-drive`。每項寫：原因、做法、改邊啲檔、點樣驗收。完成後喺「結果」補數字。

## 1. 路闊 vs 地圖壓扁
- 原因：`geometry.road_game_width` 用 `lanes×3.4×horizontal`，再加硬下限（1 線 3.2 m、2 線 8 m）。屯門東西壓到 ×0.30、南北 ×0.50，下限永遠贏，所以路比真實相對闊兩三倍，雙程分隔路撞埋變一大塊灰。
- 做法：用路嘅**垂直方向**壓縮比 `s⊥ = |S·n|`（n = 路法線，S = warp 嘅 dx/dy），每線闊 = clamp(真實線闊 × s⊥, 3.0 m, 真實線闊)。3.0 m 下限 > 車身 1.9 m / 輪距 1.6 m 加 0.55 m 兩邊。`merge_parallel` 記低每邊併入咗幾多線，畀標線用。
- 檔：`tools/pipeline/geometry.py`、`roads.py`、`build_world.py`。
- 驗收：無連接路面平面重疊面積 %、「灰板」%（合併闊 > 線數×線闊+1 m 嘅面積），對比圖。

## 2. 路面標線
- 原因：`M_Road` 用 UV.y 比例畫邊線（0–8% 同 92–100%，20 m 路就係 1.6 m 闊黃線），中線無理單程定雙程都畫，路口都畫。
- 做法：pipeline 寫第二套 UV（TEXCOORD_1 = 路闊 m、線數/分隔位置），UV0.y 改為離左邊緣嘅米數；vertex colour R = 標線開關（路口 = 0），G = 行人路物料。`M_Road` 用米畫：黃邊線 0.12 m、白色虛線分線、雙程路先有中線（雙白實線）、路口無線。
- 檔：`glbutil.py`、`build_world.py`、`roads.py`、`HKGlb.h/.cpp`、`HKBakeLibrary.cpp`（讀 UV1、M_Road、路 mesh 唔再自動生 lightmap UV、UV 全精度）。
- 驗收：單程路有中線嘅比例 = 0；路口範圍內有標線嘅頂點 = 0；測試。

## 3. 路口補面
- 原因：每條路係獨立帶狀 mesh，轉角位兩條帶之間留低三角形窿。
- 做法：每個有 ≥2 條路經過嘅路口節點，攞附近（半闊範圍內）每條帶嘅邊點做凸包，砌平面，高度 = 最終地面 + 0.06 m（比所有路帶低少少，避免 z-fighting），無標線。
- 檔：`roads.py`（`junction_fills`）、`build_world.py`。
- 驗收：補面數量、面積、窿面積（路口凸包內無路面覆蓋嘅面積）前後比較。

## 4. 小路同行人路
- 原因：`ROAD_CLASSES` 只到 tertiary + unclassified，residential / service / footway / steps 全部冇。
- 做法：車路加 `residential`、`living_street`、`service`（唔要 parking_aisle / drive-through / emergency_access）。行人路加 `footway`（唔要 sidewalk / crossing，因為由下面行人路帶代替）、`pedestrian`、`steps`，跟地形，唔落車路 graph、唔 carve 地，唔泊車；同車路、建築重疊嘅格剔走。主路（primary–tertiary、residential、unclassified）兩邊加 1.5 m 行人路帶，高 0.15 m（< 0.45 m 級高），有路邊石垂直面。
- 檔：`geometry.py`、`build_world.py`、`roads.py`、`spawns.py`。
- 驗收：新增各類數量；三角形總數目標 < +60%。

## 5. 建築
- 原因（要量）：遊戲面積 < 4 m² 就丟（壓扁區真實 27 m² 都會變 < 4）；路太闊 + 1.5 m 切走好多；細建築合併成方盒；顏色得 4–5 種近似米色，天台仲暗過牆。
- 做法：只用真實面積 ≥ 12 m² 過濾；路變窄後少切；切剩 ≥ 3 m² 都留；每棟用香港常見外牆色盤 + 隨機；天台淺灰同牆分開（M_Facade）。
- 檔：`build_world.py`、`HKBakeLibrary.cpp`（M_Facade）。
- 驗收：屯門、旺角範圍內 OSM 建築覆蓋率（面積）同數量前後。

## 6. 單程路
- 原因：`extract_osm` 冇讀 `oneway`。
- 做法：讀 `oneway=yes/true/1/-1/reverse`，`junction=roundabout/circular`、motorway / motorway_link 默認單程（除非 `oneway=no`）。`-1` 反轉點序，令點序 = 合法方向。標線用；泊車車頭跟合法方向，泊喺最左線（香港靠左）。
- 檔：`build_world.py`、`roads.py`、`spawns.py`。
- 驗收：單程路上車逆向數 = 0、車喺線內。

## 7. 車喺半空出世
- 原因：bake 將車放喺 spawn z + 100 cm（`HKBakeLibrary.cpp` `+ FVector(0,0,100)`），而家物理開咗，車跌 1 m；遠處路未 stream 入時 `HoldIfGroundUnloaded` 關重力，車就一直吊喺 1 m 高。
- 做法：spawn 計 4 個轆位置嘅路面高，加 pitch 跟斜；z = 轆底剛好掂到最高嗰點 + 0.02 m；bake 唔再加 100 cm，用 pitch。hold 嘅 trace 由車上面 1 m 開始。
- 檔：`spawns.py`、`HKBakeLibrary.cpp`、`HKCar.cpp`。
- 驗收：每架車 4 轆離路面最大距離（< 0.1 m），車高 = 路面 + 0.02 m。

## 結果

Pipeline run13（`/workspace/hk-perf/pipeline_run13.log`），對比 run8（main 7271a7c 嘅數據）。**全部未喺 UE 試過**：M_Road / M_Facade 新 HLSL、UV1 讀取、車嘅 spawn 高度都係源碼改咗、未編譯、未烘焙。

| 項 | 量度 | 結果 |
| --- | --- | --- |
| 1 路闊 | 無連接路面重疊 / 灰板 | 1.883% / 1.946%（新量度，main 冇同一量度，睇對比圖）；路闊 p50 3.0 m、p95 12.0 m、最大 30.8 m |
| 2 標線 | 單程路有中線嘅點 | 0 / 185,483；路口範圍內 101k / 701k 中線點關咗標線 |
| 3 路口補面 | 補面數、面積、補返嘅窿 | 22,766 個、1.475 km²、窿 136,317 m² |
| 4 小路、行人路 | 新增 | residential 5,923、service 23,979、living_street 48 段；footway 26,020、pedestrian 1,473、steps 5,450 條；行人路帶 1,099.7 km |
| 5 建築 | 陸地上建築數 | 72,873（run8 71,955，+1.3%）；屯門 roof/OSM 面積 0.71 → 0.72、旺角 0.88 → 0.87（覆蓋率差唔多，主要改善係顏色同天台對比）|
| 6 單程路 | 單程路段、逆向車 | 26,316 段；26 架車中 20 架喺單程路、逆向 0、雙程路靠右 0 |
| 7 半空 spawn | 4 轆最大離地、最大 pitch | 0.079 m（上限 0.08）、8.9°；車 z = 最高轆位路面 + 0.02 m |

- 三角形：4,511,765（run8 2,826,792，+59.6%，目標 < +60%）。建築 1.437M、路帶 2.020M、路口補面 0.135M、行人路帶 + 行人路 0.894M。
- check_roads：stacked 7.374% → 6.964%，stacked gap > 0.45 m 3.784% → 2.469%，ground within step 99.99% → 99.94%，excl > 4 m 98.49% → 98.73%，**tunnel within step 97.18% → 93.49%**（見風險）。
- 路口高差（ground）：max 2.37 → 2.53 m，p99 0.45 → 0.37 m。橋淨空最低 5.26 → 5.03 m。
- check_coast（inside extract）：agree 99.758% → 99.644%，海面 < 0 99.692% → 99.481%。主因係魚塘基圍、碼頭上嘅 service 路 carve 拉高咗海邊格。試過小路分開 carve（6 m 路肩、唔蓋主路），coast 好返少少（99.684%）但 ground within step 跌到 99.28%（地形穿過小路），所以放棄。
- 泊車：max heading err 0.24°、body off ribbon 0、max centreline 4.5 m（單程闊路最左線，係刻意）、floating 0、入咗建築 0。南丫 450 m 內冇地面路（run8 已經係咁）。
- 圖：`/workspace/hk-perf/visuals_compare.png`（OSM | main | 新，屯門同旺角）。

### 同計劃唔同嘅地方
- 路口補面高度 = 最低一條路帶 lift − 0.05 m（唔係地面 + 0.06 m），保證喺所有路帶下面。
- unclassified 冇行人路帶（三角形預算）。
- 建築過濾用遊戲面積 ≥ 1 m²、切剩 ≥ 3 m²（唔係真實 12 m²）。
- 行人路帶冇外側落地面，只有路邊石面同頂面；行人路取樣 10 m、strip 抽稀 0.15 m / 0.06 m。
