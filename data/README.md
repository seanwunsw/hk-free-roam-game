# 數據

`data/config/world.json` 係唯一一份比例設定。`data/processed` 係 pipeline 輸出，烘焙器讀呢度。`data/raw` 係下載嚟嘅原始檔，**唔入 git**。

## 已用來源

| 檔 | URL |
| --- | --- |
| OSM PBF | https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf |
| 說明頁 | https://download.geofabrik.de/asia/china/hong-kong.html |
| SRTM N22E113 | https://elevation-tiles-prod.s3.amazonaws.com/skadi/N22/N22E113.hgt.gz |
| SRTM N22E114 | https://elevation-tiles-prod.s3.amazonaws.com/skadi/N22/N22E114.hgt.gz |

放到：

```text
data/raw/hong-kong-latest.osm.pbf
data/raw/N22E113.hgt.gz
data/raw/N22E114.hgt.gz
```

地圖 © OpenStreetMap contributors，以 ODbL 授權。地形係 NASA/USGS SRTM，經 AWS elevation-tiles-prod 攞。地政總署數碼地形模型冇用：https://data.gov.hk/en-data/dataset/hk-landsd-openmap-5-digital-terrain-model

## 重跑

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r tools/requirements.txt
python tools/run_pipeline.py
```

成功時 `data/processed/logs/report.json` 嘅 `ok` 係 true，並且會重寫高度圖、glTF、`warp_lut.bin`、`golden_warp.csv`、`spawns.json`、`landmarks.json`、`manifest.json`、`minimap.png` 同 `previews/`。

`python tools/run_pipeline.py --synthetic` 會 exit 2。呢個原型唔用合成地圖交貨。

座標：

```bat
python tools/hkwarp/convert.py --lat 22.2849 --lon 114.1583
python tools/hkwarp/convert.py --x-cm 0 --y-cm 0
```

## 輸出點樣讀

- `manifest.json`：Landscape 尺寸、tile 列表、小地圖邊界。
- `terrain.r16`：小端 uint16，第 0 行係南，32768 = 海平面。
- `tiles/*.glb`：glTF 2.0，Y-up 米，另加 HKGM chunk 俾 Unreal 烘焙器。
- `spawns.json`：玩家、車、停機坪。Z 係表面，烘焙器再加膠囊／車輪／機身偏移。
- `landmarks.json`：地區 id、中文名、熱鍵、經緯度同已經算好嘅遊戲 XY。

Git LFS 追蹤 `*.glb`、`*.r16`、`*.png`。如果帳戶 LFS 配額唔夠，可以唔提交 `data/processed/tiles` 同 `terrain.r16`，用上面條命令喺本地重生。
