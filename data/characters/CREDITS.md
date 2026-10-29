# 角色素材 credits

呢個檔列出 `data/characters/` 入面每一個第三方檔嘅來源同授權。加新檔就加一段；刪檔就刪返嗰段。

## 動畫：Quaternius Universal Animation Library

- 檔：`data/characters/animations/UAL1_HK.glb`
- 來源：Quaternius，「Universal Animation Library」Standard 版，`Unreal-Godot/UAL1_Standard.glb`
  - https://quaternius.com/packs/universalanimationlibrary.html
  - 下載：https://quaternius.itch.io/universal-animation-library （免費下載，冇登入）
  - 原 zip：`Universal Animation Library[Standard].zip`，15,904,933 bytes，SHA-256 `cc73fc4e495b82958207316596317a3f40b9fa38065bde1027937452da537724`
- 授權：CC0 1.0 Universal（Public Domain Dedication），https://creativecommons.org/publicdomain/zero/1.0/ 。zip 入面 `License.txt` 寫明。CC0 唔要求署名，呢度寫出嚟只係方便追來源。
- 改動：用 `tools/characters/trim_glb.py` 淨係留低 11 段 clip（Idle_Loop、Walk_Loop、Jog_Fwd_Loop、Sprint_Loop、Jump_Start、Jump_Loop、Jump_Land、Swim_Idle_Loop、Swim_Fwd_Loop、Sitting_Idle_Loop、Driving_Loop），mesh、skin（65 bones，UE mannequin 命名）同動畫數據 byte-for-byte 冇改。

## 正式玩家角色：`player.vrm`（底：いつつ用ちび素体）

- 檔：`data/characters/player.vrm`（Git LFS；VRoid Studio 2.14.0 export，VRM 0.0，16,812,424 bytes，SHA-256 `bd177301670593e490188cda5d9a7296f97857264972c1eab8fe66cdf8a55811`）
- 素體：「いつつ用ちび素体女性」（ちび素体・女性）by ichiei，VRoid Hub：https://hub.vroid.com/en/characters/4546129584464005032/models/7883792065184134379 （BOOTH 嗰份 `.vroid`，`chibi-vroid20231011.zip`，做底）
- 授權（2026-10-28 喺 VRoid Hub 頁面核對）：作者描述寫「無料かつCC0」；Hub 嘅使用條件：Avatar use、Violent、Sexual、Corporate use、Individual commercial use、Redistribution、Alterations 全部 Allow，Attribution: Not required。即係 CC0 噉用，唔使署名，呢度寫出嚟只係方便追來源。
- 改動（Sean，VRoid Studio 2.14）：面型、頭髮（長直、側髮）、眼重新調過；VRoid 內置衫（上衣 37 blazer、裙 25、襪 18、loafers 41）重新上色：blazer `#7A5236` 金鈕 `#D4A23A`、煲呔 `#8E1F2A`、格仔裙 `#6B4A33`／`#A07E5C`、襪 `#3B2A22`；頭髮 `#C8282E`；眼 `#B8662A`。金色髮夾未做。
- 呢個 export 本身嘅 VRM meta：title `shanachibi`、author `Se`、`licenseName: Other`（`otherLicenseUrl`／`otherPermissionUrl` 寫 `CC0`）、allowedUser `Everyone`、commercial／violent／sexual 寫 `Disallow`。呢啲係 Sean 對自己衍生模型定嘅條件，唔影響素體嘅 CC0；遊戲係 Sean 自己用，冇衝突。

## 工具：VRM4U（唔入 git）

- `tools/get_vrm4u.ps1` 下載去 `UnrealProject/Plugins/VRM4U/`。MIT License，© Haruyoshi Yamamoto，https://github.com/ruyo/VRM4U 。佢入面帶 assimp（BSD-3-Clause）同 nlohmann/json（MIT），授權檔喺 plugin 目錄入面。

<!-- BEGIN placeholder-credit -->
## 暫代角色（placeholder）

- 檔：`data/characters/placeholder/cute_chibi_girl.glb`（要自己下載，見 `data/characters/placeholder/README.md`）
- 作品：「Cute Chibi Girl (Free Game-Ready Character)」by Tim0
- 來源：https://sketchfab.com/3d-models/cute-chibi-girl-free-game-ready-character-28e2f98ab4bf4313a3f258d45d987716
- 授權：CC Attribution 4.0（CC BY 4.0），https://creativecommons.org/licenses/by/4.0/
- 署名文字（遊戲 credits 畫面照用）：
  "Cute Chibi Girl (Free Game-Ready Character)" by Tim0 (https://sketchfab.com/3d-models/cute-chibi-girl-free-game-ready-character-28e2f98ab4bf4313a3f258d45d987716), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Modified: re-materialed and retargeted at bake time.
<!-- END placeholder-credit -->
