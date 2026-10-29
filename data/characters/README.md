# 玩家角色：換 VRoid 模型、刪走暫代角色

玩家角色由 `data/config/player.json` 決定，烘焙（bake）時匯入，唔使改 code。

| 檔／folder | 用途 |
| --- | --- |
| `data/config/player.json` | 角色設定。`model` 係正式角色；`placeholder_model` 係暫代角色（唯一一個指向佢嘅 key） |
| `data/characters/player.vrm` | 正式角色（VRoid export）。入 Git LFS |
| `data/characters/placeholder/` | 暫代角色嘅 folder（唯一一個放佢嘅地方） |
| `data/characters/animations/UAL1_HK.glb` | CC0 動畫（Quaternius UAL），所有角色共用 |
| `data/characters/CREDITS.md` | 授權同署名。暫代角色只佔 `BEGIN/END placeholder-credit` 之間一段 |
| [`docs/characters/VROID.md`](../../docs/characters/VROID.md) | 正式角色嘅設計圖同 VRoid 製作步驟 |

## 烘焙點揀模型

1. `model` 指住嘅檔存在 → 用佢。`.vrm` 經 VRM4U 匯入（要先跑 `tools\get_vrm4u.ps1`）；`.glb`、`.gltf`、`.fbx` 經 Interchange 匯入。
2. 否則，如果有 `placeholder_model` 而且檔存在 → 用暫代角色。
3. 兩個都冇 → 玩家用返方塊（cube），log 會寫 `LogHK: Warning: Player: no model found`，其他嘢照烘。

匯入之後烘焙會：換上 figure 物料（`materials: "figure"`；想保留模型原本物料就改 `"imported"`）、建 IK Rig 同 IK Retargeter、將 UAL 動畫 retarget 落個角色度，再寫 `/Game/HK/Player/DA_PlayerAvatar`。遊戲開波時角色讀呢個 data asset。

其他 key：

| key | 意思 |
| --- | --- |
| `target_height_cm` | 角色縮放到幾高（cm），capsule 同鏡頭跟住呢個高度。`0` = 唔縮放 |
| `mesh_yaw_deg` | 模型轉幾多度先面向前。UE 慣例係 `-90`；PIE 見到角色打側就改 `0`、`90` 或 `180` |
| `outline` | `true` 開描邊（overlay material，inverted hull） |
| `clips` | 每個動作用 UAL 邊段 clip |
| `anim_ref_speed_cm_s` | 每段 clip 原本嘅移動速度（180 cm mannequin 計），用嚟調 play rate，減少滑腳 |

## 換自己嘅 VRoid 模型

1. 跟 [docs/characters/VROID.md](../../docs/characters/VROID.md) 整角色，export VRM（0.0 或 1.0）。
2. 放落 `data/characters/player.vrm`。
3. 第一次用 VRM 先要裝 VRM4U：

   ```bat
   powershell -ExecutionPolicy Bypass -File tools\get_vrm4u.ps1
   ```

   然後右鍵 `UnrealProject\HKFreeRoam.uproject` → Generate Visual Studio project files，build **HKFreeRoamEditor**（Development Editor）。`HKFreeRoamEditor.Build.cs` 見到 `Plugins/VRM4U` 先會 link VRM4U。
4. 重新烘焙。淨係換角色就加 `-PlayerOnly`，只重做 `/Game/HK/Player`，唔使重烘成個世界：

   ```bat
   "<UE>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" UnrealProject\HKFreeRoam.uproject -run=HKBakeWorld -PlayerOnly -unattended -AllowCommandletRendering -nosplash
   ```

   唔加 `-PlayerOnly` 就係成個世界連角色一齊烘（同平時一樣）。喺 editor 入面亦可以用 Python：`unreal.HKBakeLibrary.bake_player()`。

5. Log 應該見到 `Player: importing VRM data/characters/player.vrm`，跟住 `Player: retargeted N clips`。
6. 入 git：

   ```bat
   git lfs track "*.vrm"
   git add data/characters/player.vrm
   ```

   （`.gitattributes` 已經有 `*.vrm`，`git lfs track` 只係確認。）

有 `player.vrm` 時暫代角色已經唔會用；要清走佢就做下面。

## 刪走暫代角色

正式角色點整：[docs/characters/VROID.md](../../docs/characters/VROID.md)（設計圖、顏色、VRoid 步驟）。整好放落 `data/characters/player.vrm`，再刪暫代角色。

### 一行做晒

```bat
python tools\characters\remove_placeholder.py --dry-run
python tools\characters\remove_placeholder.py
```

第一行只係印出會做咩。第二行會：

1. 刪 `data/characters/placeholder/`（模型檔同佢個 README）。
2. 喺 `data/config/player.json` 刪 `placeholder_model` 呢個 key。
3. 喺 `data/characters/CREDITS.md` 刪 `<!-- BEGIN placeholder-credit -->` 到 `<!-- END placeholder-credit -->` 成段。
4. 刪 `UnrealProject/Content/HK/Player/`（烘焙出嚟嘅角色 asset，下次烘焙會重建）。唔想刪就加 `--keep-baked`。
5. 搵 tracked files 仲有冇提到暫代角色，有就印出嚟並 exit 1。

佢唔會 commit，亦唔會改 git history。

### 手動做

如果唔想用 script：

1. 刪 folder：

   ```bat
   git rm -r data/characters/placeholder
   ```

   如果模型檔從來冇 `git add` 過，直接喺 Explorer 刪個 folder 就得。
2. `data/config/player.json`：刪 `"placeholder_model": ...` 嗰行（記得睇吓上一行嘅逗號）。`model` 保持 `data/characters/player.vrm`。
3. `data/characters/CREDITS.md`：刪 `BEGIN placeholder-credit` 到 `END placeholder-credit` 之間（連兩行 marker）。
4. LFS：`.gitattributes` 冇暫代角色專用嘅 rule（`*.glb`、`*.fbx` 係通用），唔使改。檢查：

   ```bat
   git lfs ls-files | findstr /i placeholder
   ```

   應該冇輸出。舊 commit 入面嘅 LFS object 唔會自動消失；CC BY 4.0 冇要求你刪 history，只要求有用到嘅版本帶署名。
5. 刪 `UnrealProject\Content\HK\Player\`，然後重新烘焙（指令同上面「換自己嘅 VRoid 模型」第 4 步，可以加 `-PlayerOnly`）。

### 檢查冇殘留

```bat
python tools\characters\remove_placeholder.py --check
```

或者自己 grep（排除呢份 README 同個 script，因為佢哋要寫個名出嚟）：

```bat
git grep -n -i -e "cute_chibi" -e "cute chibi" -e "tim0" -e "28e2f98ab4bf4313a3f258d45d987716" -- . ":!data/characters/README.md" ":!tools/characters/remove_placeholder.py"
```

冇輸出 = 清晒。之後 commit：

```bat
git add -A data tools
git commit -m "Remove placeholder player model"
```

最後喺 PIE 確認：log 冇 `placeholder` 字眼，角色係你嘅 VRoid 模型。

## 動畫

`animations/UAL1_HK.glb` 由 `tools/characters/trim_glb.py` 從 Quaternius UAL Standard 剪出嚟，淨係留 `player.json` `clips` 用到嘅 11 段。想加 clip：

```bat
python tools\characters\trim_glb.py "<UAL zip 解壓>\Unreal-Godot\UAL1_Standard.glb" data\characters\animations\UAL1_HK.glb --keep Idle_Loop Walk_Loop Jog_Fwd_Loop Sprint_Loop Jump_Start Jump_Loop Jump_Land Swim_Idle_Loop Swim_Fwd_Loop Sitting_Idle_Loop Driving_Loop <新 clip>
```

再更新 `CREDITS.md` 嘅 clip 列表同 `tools/tests/test_characters.py`。
