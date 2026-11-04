# Credits

## 3D models

From each file's glTF `asset.extras` (generator Sketchfab-12.66.0), checked against the
Sketchfab API on 4 Nov 2026:

- **"Hong Kong Traffic Light"** by businessyuen (https://sketchfab.com/businessyuen)
  - Licence: CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)
  - Source: https://sketchfab.com/3d-models/hong-kong-traffic-light-c5a8a5726a7c4cddb8b7060b475ac8cf
  - File: `hk_traffic_light/hong_kong_traffic_light.glb`
- **"Hong Kong Safe Island"** by businessyuen (https://sketchfab.com/businessyuen)
  - Licence: CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)
  - Source: https://sketchfab.com/3d-models/hong-kong-safe-island-0be42ccfa7f045d390be6cd09c1e8a63
  - File: `hk_safe_island/hong_kong_safe_island.glb`

Changes: tools/pipeline/props.py merges each model into one mesh, bakes the material
colours into vertex colours, and rescales and rotates it.

## Map data

© OpenStreetMap contributors, available under the Open Database License (ODbL),
https://www.openstreetmap.org/copyright.
