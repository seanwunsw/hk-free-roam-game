# 暫代角色（placeholder）

呢個 folder 淨係放暫代角色。正式角色（VRoid 做嘅 `data/characters/player.vrm`）一放落去，烘焙就會用正式角色，呢度會被忽略。要成個刪走，睇 `data/characters/README.md` 「刪走暫代角色」。

## 下載（要手動）

模型冇入 repo：Sketchfab 嘅下載 API 要登入（未登入會 HTTP 401），所以要你自己下載。

1. 開 https://sketchfab.com/3d-models/cute-chibi-girl-free-game-ready-character-28e2f98ab4bf4313a3f258d45d987716 ，登入 Sketchfab（免費戶口得）。
2. 撳 **Download 3D Model**。
3. 揀 **glTF** 一欄嘅 **Autoconverted format (glb)**，即係單一個 `.glb` 檔。唔好揀 USDZ。如果只得 Original format 係 `.fbx`，都用得，見第 5 步。
4. 改名做 `cute_chibi_girl.glb`，放落：

   ```text
   data/characters/placeholder/cute_chibi_girl.glb
   ```

5. 如果你用 `.fbx`：檔名改 `cute_chibi_girl.fbx`，再把 `data/config/player.json` 嘅 `placeholder_model` 改做 `data/characters/placeholder/cute_chibi_girl.fbx`。
6. 重新烘焙（指令見 `docs/README.md`）。

`.glb` 同 `.fbx` 都由 `.gitattributes` 交俾 Git LFS。想入 git 就 `git add` 佢；唔入都得，烘焙淨係睇檔喺唔喺度。

## 授權

CC BY 4.0，作者 Tim0。署名文字喺 `data/characters/CREDITS.md` 嘅 placeholder 段。用呢個模型出街（包括截圖、片）就要帶埋署名。
