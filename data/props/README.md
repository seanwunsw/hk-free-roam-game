# Street props

The pipeline places Hong Kong traffic signals and safe islands from OpenStreetMap
(`tools/pipeline/props.py`), and the bake draws them with these two Sketchfab models.
Download them yourself (Sketchfab login, "Download 3D Model", choose **glTF Binary (.glb)**):

| Folder | Model | Link |
| --- | --- | --- |
| `data/props/hk_traffic_light/` | "Hong Kong Traffic Light" by businessyuen | https://sketchfab.com/3d-models/hong-kong-traffic-light-c5a8a5726a7c4cddb8b7060b475ac8cf |
| `data/props/hk_safe_island/` | "Hong Kong Safe Island" by businessyuen | https://sketchfab.com/3d-models/hong-kong-safe-island-0be42ccfa7f045d390be6cd09c1e8a63 |

Expected files (SHA-256 of the copies the defaults were measured on):

- `hk_traffic_light/hong_kong_traffic_light.glb` 17acf3a2a11b2b097ab605fff76d024ebd522d3d0bba8d1d2dd976186358d342 (35.3k triangles, 20 meshes, 8 materials, no textures)
- `hk_safe_island/hong_kong_safe_island.glb` d0507a1c5f6d6b5effedd67a7ff475a383e5838121d2caf44e550f72f29cce02 (13.7k triangles, 9 meshes, 5 materials, no textures)

`*.glb` is tracked by Git LFS (`.gitattributes`); CC BY 4.0 allows redistributing them
with the credit below. Put one `.glb` in each folder (any file name; the first one alphabetically is used), then
run `python tools/run_pipeline.py` and the bake again. Both are CC BY 4.0: keep
`CREDITS.md` and the in-game credit line (F1 help) when you share builds.

If a folder has no GLB the pipeline logs `props: no GLB in data/props/<slug>, skipped`,
still writes the placements, and the bake logs how many placements it skipped.

## What the pipeline does with a model

- Flattens all meshes into one, with vertex colours from the base colour factor, the
  base colour texture (sampled at each vertex, converted from sRGB) and `COLOR_0`.
  Fine texture detail is lost; the bake material is `M_Prop` (`VertColor`).
- Applies every node matrix (the Sketchfab files wrap the meshes in a Z-up to Y-up
  root, an FBX root and 10x part scales, so one part alone reads y 27.6-27.94),
  converts glTF axes to the tile layout (Y up; the bake turns that into UE Z up),
  puts the lowest point on the ground, centres it on its foot (pole or bollard, not the
  bounding box, since the signal arm sticks out), scales it to `height_m`, and turns its
  front to face east (yaw 0). Result: light 3.6 m (red lens 3.19 m, green 2.76 m),
  island 1.1 m with its blue keep-left sign facing traffic.
- Copies `asset.extras` (title, author, licence, source) into the manifest.
- Writes `<out>/props/<slug>.glb`; placements go to `<out>/tiles/p_<ix>_<iy>.json`.

## Tuning

`props.json` here overrides the defaults per model:

```json
{"assets": {"hk_traffic_light": {"height_m": 3.6, "front_yaw_deg": 0}}}
```

`front_yaw_deg` is the direction the model's lit face points after import (degrees,
counter-clockwise from east). If signals show their back to traffic, add or subtract
180; if they face across the road, try 0 or 180.

## Placement rules

- Signals: every `highway=traffic_signals` node on a drivable road, one head per
  approach (`traffic_signals:direction` / `direction` = forward or backward limits it,
  one-way roads have one), merged within 30°, at most 4. Each stands 2.5 m before the
  node on the left kerb (HK drives on the left), 0.6 m out from the carriageway edge,
  facing the oncoming traffic.
- Safe islands: `crossing:island=yes` and `traffic_calming=island` nodes snap to the
  nearest road centreline; `traffic_calming=island` / `area:highway=traffic_island` ways
  within 6 m of a road sit at their centre along their long axis.
- Not yet: junction direction signs, collision, poles on bridges or in tunnels checked.
