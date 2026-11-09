# 把 导出器导出的地图导入 UE 5.3.2

目标：导出的 `split\*.glb` + `scene.json` → UE 5.3.2 里一个能直接走进去看的关卡。

---

## 0. 先决条件

| 需要 | 说明 |
|---|---|
| UE **5.3.2** | 引擎目录里要有 `Engine\Binaries\Win64\UnrealEditor-Cmd.exe` |
| 一个工程 | 空 C++ 或蓝图工程都行（建议蓝图，省编译） |
| 导出产物 | 导出器导出目录，里面有 `split\*.glb`、`scene.json`、`textures\` |

> 本机检测结果：`E:\UE_5.3` 下只有 Epic Launcher 的 `.egstore`，**没有真正装引擎**（没有 `Engine\Binaries`）。
> 所以下面这套脚本是在没有引擎的机器上写完的，**引擎侧那几步需要你在装了 UE 5.3.2 的机器上跑一次**。
> 脚本里有 `--check` 自检，不装引擎也能验证输入是否合格。

---

## 1. 两条路子，先跑哪条

### 路子 A：纯资产导入（最快，先看形状对不对）

1. 打开工程 → 内容浏览器里新建文件夹 `AtlasMaps`
2. 把导出目录 `split\` 里的一两个 `.glb`（比如 `000_BigMeshGroup_0_-10.glb`）**直接拖进** `AtlasMaps\`
   - 导入选项里 **Import Uniform Scale 保持 1.0**（glTF 米 → UE 厘米由导入器自己 ×100）
   - 勾上 **Generate Lightmap UVs**（要静态光就勾），其余默认
3. 拖进关卡，看位置/大小对不对

### 路子 B：脚本一把梭（整张图 + 关卡）

```powershell
set UE_ROOT=E:\UE_5.3
set UE_PROJECT=D:\MyUE53\MyProject.uproject
scripts\ue_import.bat "F:\新建文件夹 (5)\Mogadishu_20261101_0736" --use-scene-json
```

会做这些事：

1. 逐个 `split\*.glb` 用 `AssetImportTask`（Interchange glTF 管线）导到 `/Game/AtlasMaps/<地图名>/`
2. 新建关卡 `/Game/AtlasMaps/<地图名>/LV_<地图名>`
3. 按 `scene.json` 的 `matrixUE`（**UE 厘米 / Z-up / 列主序**）逐个 `spawn_actor`，缩放也照着 `scale`
4. 算一遍整体包围盒并打日志：`min/max/尺寸`，尺寸应该是几百米级（Mogadishu ≈ 1.2 km）
5. 存关卡

`--use-scene-json` 和不加的区别：

| 模式 | 摆放依据 | 什么时候用 |
|---|---|---|
| 默认（不加） | 依赖导入器把 glTF 节点矩阵**烘进 StaticMesh**，Actor 全部摆在原点 | 只想快速看单个 chunk |
| `--use-scene-json` | 用 `scene.json` 里每个实例的 `matrixUE` 精确摆放 | **要还原整张地图、和游戏里一致** |

---

## 2. 编辑器内跑（不开命令行）

1. 打开工程
2. `Tools → Execute Python Script…` → 选 `scripts\ue_import_atlas.py`
3. 弹框里粘导出目录，回车

脚本自己会判断：不在 UE 里跑就只做自检，不会报错。

---

## 3. 坐标/单位对照（出问题先看这张表）

| 空间 | 单位 | 轴 | 出处 |
|---|---|---|---|
| 游戏 / `scene.json` | 厘米 | Z-up | `coordinateSystem: UE centimetres, Z-up` |
| GLB（`.glb`） | 米 | Y-up | glTF 规范；节点矩阵 = UE 坐标 ÷100 再转轴 |
| UE 关卡 | 厘米 | Z-up | 导入器自动 ×100 转回 Z-up |

- **图整体缩小 100 倍**（看起来像火柴盒）→ 导入时 scale 被设成 0.01 了，改回 1.0；或用脚本 `--scale 100`
- **图散在原点**（一堆东西叠一起）→ 说明导入器没烘节点矩阵，改用 `--use-scene-json`
- **图上下颠倒 / 躺倒** → glTF 的 Y-up 转 Z-up 没生效，检查导入选项里 `Convert Scene` / `Force Front XAxis`

---

## 4. 材质和贴图

- 导出的 GLB **自带贴图**（`images: 33`，PNG 内嵌），导入后会自动建 `MI_*` 材质实例
- UE 里可能会提示贴图过大（我们有 2048/4096 的），在导入选项勾 `Compress` 或加 `Texture Max Size` 限制
- dfmap 的材质只是 **PBR 兼容层**，不是游戏里的真材质；路面/水面那种要去文档里找专门步骤

---

## 5. 验收（别只看「导入成功」）

1. 关卡里按 `F` 聚焦一个 Actor，看尺度：一扇门应该 ~200 cm 高，不是 2 cm 也不是 20000 cm
2. `Window → World Settings → Enable World Bounds Checks` 关掉（地图 1.2 km，容易被裁）
3. 走两步：`Play` → `Possess` 一个 Pawn，能站上去说明 Z 对
4. 眼熟的地标（Mogadishu 的桥、Retrowar 的街区）位置对不对，对不上就回看第 3 节的对照表

---

## 6. 已知限制

- 导出的只有**静态几何 + PBR 材质**：没有光照图、没有游戏里的真 shader、没有碰撞体（`scene.json` 里 `collision` 只是源记录）
- `KHR_lights_punctual` 扩展（灯光）UE 5.3 的 glTF 导入器支持有限，灯光可能不导
- 750 MB 级的 `scene.glb`（不分块时）导入会很吃内存，**建议始终用 `--split` 导出**

## 实测踩过的坑（2026-11-01，UE 5.3.2）

1. **导出目录必须是纯 ASCII 路径**。UE 命令行会把中文参数转成 `?????`，
   `F:\新建文件夹 (5)\...` 这种路径传进去就变成 `F:\????? (5)`，脚本直接找不到目录。
   建议导出到 `G:\map_exports\<MapName>` 这类路径。

2. **UE 编辑器只能有一个实例**。上一个编辑器不关就再起，新进程会把命令行交给老实例，
   于是「改了脚本没效果」。重跑前先：
   ```powershell
   Get-Process | Where-Object { $_.ProcessName -like "*Unreal*" } | ForEach-Object { $_.Kill() }
   ```

3. **`-run=pythonscript`（命令行模式）里不要建关卡**：`LevelEditorSubsystem.new_level()`
   在 NullRHI 下会 `EXCEPTION_ACCESS_VIOLATION`。脚本已自动判断：命令行模式只导资源。

4. **`-- xxx` 不在 `sys.argv` 里**。UE 的 Python 命令行不把 `--` 后面的参数放进 `sys.argv`，
   脚本改用 `unreal.SystemLibrary.get_command_line()` 里 `split("--", 1)[1]` 再 `shlex.split(posix=False)`。

5. **`split\` 分块只包含部分网格**。`scene.json` 里有 424 个实例，但 4 个分块 GLB 只覆盖 141 个，
   其余 283 个（如 `SM_IceLand_Nature_Rock_Wall_03A`）不在分块里。两种补法：
   - 加 `--with-scene-glb`，把导出目录下的 `scene.glb` 一并导入（整图网格，最稳，但很慢）；
   - 或者导出时**不加 `--split`**，只出单个 `scene.glb` 再导。

6. **摆放失败别急着怪脚本**：看 `Saved/Logs/<项目>.log` 里的
   `[atlas] 缺网格 sid=... mesh=...`，那说明缺的是网格资产，不是坐标算错。
7. **别把 51 MB 的 `scene.glb` 直接塞给 UE 5.3 导入器**：实测导入到第 5 个文件时编辑器进程直接退出
   （无 Python 报错、日志停在 `4/5`）。全量想进引擎就走 Blender 中转：
   `scripts/blender_import_verified.py --split <导出目录>\split`，再在 UE 里导 FBX/GLB。
   在 UE 内继续用 `--split` 的 4 个分块（稳，能摆 141 个实例）。

## 推荐的完整路线：Blender 转 FBX 再进 UE（424 个实例全覆盖）

`runtime\scripts\blender_split_to_fbx.py` 是工具链自带的转换器：把每个分块 GLB 里**已摆好位置的实例**
转成一个 FBX（几何带世界坐标），UE 里只要 4 个 Actor 就能看到整张图，不用再做「实例 → 网格」匹配。

```powershell
# 1) 导出（散件 GLB 分块）
map-export.exe --config %LOCALAPPDATA%\AtlasMap\exporter.json merge CollectionRoom G:\map_exports\CollectionRoom `
  --root "DeltaForce/Content/Maps/BuildMaps_HD/CollectionRoom/Runtime/BigMeshGroup/" `
  --split --keep-base-with-hd --deduplicate --max-tex 512

# 2) Blender 转 FBX（4 个分块 → 4 个 FBX，424 个网格全在里面）
& "G:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup `
  --python "<runtime>\scripts\blender_split_to_fbx.py" -- `
  "G:\map_exports\CollectionRoom\split" "G:\map_exports\CollectionRoom\fbx"

# 3) UE 5.3.2 导 FBX 并摆进关卡（脚本会存盘并补灯）
UnrealEditor.exe "<你的工程>.uproject" -ExecutePythonScript="scripts\ue_import_fbx.py" `
  -- --fbx "G:\map_exports\CollectionRoom\fbx" --dest /Game/AtlasMaps/CollectionRoomFBX --level LV_CollectionRoom_FBX
```

实测（CollectionRoom，216 m × 153 m × 82 m）：

| 项目 | 结果 |
| --- | --- |
| Blender 转 FBX | 4 个分块 → 2 / 142 / 273 / 7 = **424 个网格**，0.1 / 6.3 / 28.4 / 0.6 MB |
| UE 导入 | 4 个 StaticMesh 资源（`transform_vertex_to_absolute=True`，世界坐标烘进顶点），39 秒 |
| 关卡 | 4 个 Actor，位置 (0,0,0)、缩放 (1,1,1)，几何落在正确世界位置 |
| 视口 | 切「无光照」能直接看到整张图（截图 `work/ue_level_visible.png`） |

**注意**（都是实测）：
- 默认**不导材质**：28 MB 那块带 `import_materials=True` 导入会让编辑器在 5.3 里直接崩。想要材质就分块跑，或在 Blender 里先烘一张底图。
- 关卡没灯 → 切「无光照」看几何；想用 LIT 还得补 `SkyAtmosphere`（脚本只补了 DirectionalLight + SkyLight，没有 Atmosphere 会报「需要至少一个 SkyAtmosphere」）。
- 地图整体在 X≈161000 cm，视口默认在原点 → 全选 Actor 按 **F** 框住，再滚轮拉近。

---

## 六、官方路线（zip 里 `docs/Iceland地图导出与还原说明书.md` §5）在本机的落地

官方把「进 UE」拆成 **Blender 侧出清单 → 材质图编译 → UE 里分 7 阶段导入 → 修复/光照/水/碰撞**，
脚本都在 `固定工具链\scripts\`（60 个 .py）。我按它的顺序在本机完整跑通了 **UE 之前的所有步骤**，
只有最后「UE 内导入」受版本差异（官方 5.4.4 / 本机 5.3.2）和缺失输入数据限制。

### 6.1 已在 CollectionRoom 上实测跑通的四步

```powershell
# 0) 导出器导出（路径必须纯 ASCII，UE 命令行会把中文变成 ?????）
& '.\map-export.exe' --config "$env:LOCALAPPDATA\AtlasMap\exporter.json" merge CollectionRoom `
    (Join-Path $root 'CollectionRoom') `
    --root 'DeltaForce/Content/Maps/BuildMaps_HD/CollectionRoom/Runtime/BigMeshGroup/' `
    --split --keep-base-with-hd --deduplicate --max-tex 512

# 1) 官方 blender_iceland.py 建 Blender 场景（它按 ROOT/<group>/split/manifest.json 找分块）
#    ROOT 布局：<root>\geometry\split\*.glb + manifest.json（用 mklink /J 把真 split 链过去即可）
& 'G:\SteamLibrary\steamapps\common\Blender\blender.exe' --background --factory-startup `
    --python scripts\official\blender_iceland.py -- (Join-Path $root 'blender_root')

# 2) 官方 blender_iceland_to_ue.py 出 transfer 包（manifest.json + 每网格 FBX + 材质节点图）
$env:ATLASMAP_UE_ROOT = (Join-Path $root 'ue_transfer')
& blender.exe --background (Join-Path $root 'blender_root\scene_no_terrain.blend') `
    --python scripts\official\blender_iceland_to_ue.py

# 3) 官方材质编译 + 分组（纯 Python，不用开 UE）
python scripts\official\compile_iceland_ue_materials.py
python scripts\official\group_iceland_ue_materials.py
```

实测结果（CollectionRoom 这张小图）：

| 步骤 | 产物 | 数量 |
| --- | --- | --- |
| `blender_iceland.py` | `.blend` 场景 | 4 个分块，唯一网格去重后共享 |
| `blender_iceland_to_ue.py` | `manifest.json` / `meshes\*.fbx` / `material_graphs\` | objects 428、mesh_objects 424、mesh_assets 109、materials 42 |
| `compile_iceland_ue_materials.py` | `material_plan.json` | 42 个变体、109 条网格绑定、424 条物件绑定 |
| `group_iceland_ue_materials.py` | `material_instance_plan.json` | 1 个母材质 + 42 个实例 |

> 官方脚本 ROOT 写死在 `D:/AtlasMap-tooling/...`，我改成读环境变量 `ATLASMAP_UE_ROOT`
> （`scripts\official\` 里是改过的副本，zip 原件没动）。`blender_iceland.py` 还硬性要求
> `ROOT/terrain.npz`（CDLOD 地形，由 `iceland_terrain.py` 从 `dump/raw` 的地形诊断数据解出），
> 没有就整段崩 —— 副本里加了「没有就跳过并存 `scene_no_terrain.blend`」的守卫。

### 6.2 UE 里那 7 个阶段（官方 §5.2）

进 UE 编辑器（打开 Python Editor Script Plugin），把脚本目录塞进 path，然后**逐阶段**跑，
每阶段等 `status()` 到 `running=false && complete=true` 再跑下一个：

```python
import sys, os
sys.path.insert(0, r'D:\AtlasMap-build\atlasmap\scripts\official')
os.environ['ATLASMAP_UE_ROOT'] = r'D:\AtlasMap-build\atlasmap\work\ue_test\ue_transfer'
import ue_iceland_bridge as bridge
bridge.start('textures')    # 等完成
bridge.start('meshes')
bridge.start('masters')
bridge.start('instances')
bridge.start('bindings')
bridge.start('actors')      # 按 manifest 的世界矩阵摆 Actor
bridge.start('parents')
```

要点（官方明确写的）：

* 靠 `unreal.register_slate_post_tick_callback` 分批推进，**不能把 7 行连着执行**；
* `_busy` 是防重入的，别删；执行中别 reload 模块；
* 失败先回读 `status()` 的 `cursor` 和实际资产，再决定从哪续；
* 材质槽用 `DF_SLOT_0000` 占位 + manifest 里的 slot 映射，不靠 FBX 导入顺序猜；
* 目标关卡用**新建的空关卡**（`MANIFEST['level']`），别在默认 ThirdPersonMap 上跑。

### 6.3 之后的修复/光照/水/碰撞（官方 §5.3–5.6）

| 目的 | 脚本 | 关键调用 |
| --- | --- | --- |
| 隐藏件可见性落地 | `ue_repair_iceland_visibility.py` | `exec(compile(open(...).read(), ..., 'exec'))` |
| 打包图 alpha 修复 | `ue_repair_iceland_packed_alpha.py` | 同上，配合 `binary_alpha_rgb_risk.json` |
| 容器细节/染色 | `ue_repair_iceland_container_detail.py` | 同上 |
| 源光照 | `ue_iceland_source_lighting.py` | `light.apply(ibl_coefficient=500, sky_energy_scale=500, manual_ev100=8.8, fog_energy_scale=500, static_gi_fill=2.0)`；先把 `SCb0_19_2_RGBA16F.dds` 当 TextureCube（sRGB=false）导入 |
| 水体 | `ue_rebuild_iceland_water.py` | `water.build()` → 新建 Coast/Deep 图 → `water.apply()` |
| 静态碰撞 | `ue_rebuild_iceland_collision.py` | `collision.start_meshes()` → 等完 → `collision.start_component_phase()` |

### 6.4 本机跑不通的部分（必须说清楚）

1. **这些脚本依赖他们那次 Iceland 的中间数据**（`out/Iceland/audit/...` 的天空 DDS、
   `water_rebuild/.../source_data`、`source_hidden_collision_policy.json`、`terrain.npz`），
   zip 里**只发了代码、没发这些数据** → 光照/水/碰撞三段无法原样复现，只能拿自己的导出数据重做等价步骤。
2. **版本**：官方 UE 5.4.4，本机 5.3.2。`ue_iceland_bridge.py` 里部分 5.4 才有的 API
   （`LevelEditorSubsystem` 的部分方法、材质编辑接口）在 5.3.2 上要按报错逐个替换。
3. 官方是**从最终修好的 `.blend` 出发**（地形/材质/水体都已修过），不是从 dfmap 的 split 直接出发；
   我们从 split 出发时，地形（CDLOD）、水体、碰撞这些源数据要按 §3.4/§5.5/§5.6 自己补。

---

## 七、换到 UE 5.4.4 的准备工作（已完成，等引擎装完即可跑）

### 7.1 现在的状态

| 项 | 状态 |
| --- | --- |
| 引擎 | `E:\UE_5.4` 目前只有 `.egstore`（Epic 还没下完）。装完后 `Engine\Binaries\Win64\UnrealEditor.exe` 出现即可 |
| 5.4 测试工程 | 已建 `work\ue_test\AtlasMapTest54\AtlasMapTest54.uproject`（`EngineAssociation` 5.4，启用 PythonScriptPlugin / EditorScriptingUtilities / GeometryScripting） |
| transfer 包 | 已用官方脚本重做，**带贴图和材质节点**：objects 428 / mesh_objects 424 / mesh_assets 109 / materials 163 / images 322 |
| 材质计划 | `material_plan.json`（163 变体、109 网格绑定、424 物件绑定）、`material_instance_plan.json`（11 母材质 + 163 实例） |
| 自检脚本 | `scripts\official\ue_preflight.py` —— 12 项通过、1 项提醒（提醒内容是"当前不是 UE 的 Python"） |
| 一键流程 | `tools\ue54_run.ps1`（找引擎 → 查工程 → 跑自检 → 清残留 Unreal → 起编辑器 → 打印要粘的两行） |
| 阶段执行器 | `scripts\official\ue_stage_runner.py` —— 粘一行就把 7 阶段按序跑完（自带 slate tick 推进，不卡编辑器） |

### 7.2 装好 5.4 之后就跑这两条

```powershell
# 1) 只做检查（引擎/工程/transfer 包/脚本齐不齐）
powershell -ExecutionPolicy Bypass -File D:\AtlasMap-build\atlasmap\tools\ue54_run.ps1 -JustCheck

# 2) 正式开跑：设好环境变量、起编辑器（默认资产根 /Game/AtlasMaps/CollectionRoom54，关卡 LV_Map）
powershell -ExecutionPolicy Bypass -File D:\AtlasMap-build\atlasmap\tools\ue54_run.ps1
```

编辑器起来后：

1. File → New Level → **Empty Level**，Save As 到 `…/CollectionRoom54/LV_Map`（先建空关卡，`actors`/`parents` 阶段才有地方摆）。
2. Output Log 左下 `Cmd` 切到 **Python**，粘自检那行（脚本会打印）。
3. 自检全 OK 后，粘 `ue_stage_runner.py` 那行 —— 它自己按 `textures → meshes → masters → instances → bindings → actors → parents` 推进，每段完成会打 `[runner] === xxx 完成 ===`，全部完成会存盘。

卡住了就用 `import ue_iceland_bridge as b; b.status()` 看 `phase/cursor/total/running/complete`；想从第 N 段续跑，设 `ATLASMAP_UE_SKIP=textures,meshes` 再粘一次。

### 7.3 为了让这条线在 5.4 上真的能跑，我改了什么

| 文件（`scripts\official\` 里的副本，zip 原件未动） | 改动 |
| --- | --- |
| `blender_iceland.py` | 没有 `terrain.npz` 时不再整段崩：打日志、存 `scene_no_terrain.blend` 后正常退出 |
| `blender_iceland_to_ue.py` | ROOT 改为读 `ATLASMAP_UE_ROOT`；节点属性里补导 `data_type`（Blender 5 的 Mix 节点必需） |
| `compile_iceland_ue_materials.py` | ROOT 读环境变量；**新增 `MIX` 节点支持**（按 socket identifier 取 A/B/Factor，支持 MIX/MULTIPLY/ADD/SUBTRACT/SCREEN），不支持的仍明确报错 |
| `group_iceland_ue_materials.py` | ROOT 读环境变量 |
| `ue_iceland_bridge.py` | ROOT 读环境变量（DEST/level 由 `ue_stage_runner.py` 先改写 `manifest.json`） |
| `ue_preflight.py`、`ue_stage_runner.py` | 新增（自检 / 7 阶段一次跑完） |

### 7.4 5.4 上仍需现场确认的三点

1. `ue_iceland_bridge.py` 里 5.4 的 API（材质编辑、`LevelEditorSubsystem`）在 5.4.4 上应该原样可用；若报 `AttributeError`，按报错把对应 `unreal.xxx` 换成 5.4 的名字即可。
2. 素材图片 322 张：导入时间会明显变长（首轮估计十几分钟），`textures` 阶段要等它 `complete`。
3. 官方那套「源光照 / 水 / 碰撞」仍缺他们工作区的中间数据（天空 DDS、water source_data、`source_hidden_collision_policy.json`），这三段只能按 §5.4–5.6 用我们的数据做等价实现。

---

## 八、UE 5.4.4 实测结果（2026-11-01，CollectionRoom 全流程跑通）

### 8.1 7 阶段结果

| 阶段 | 结果 | 用时 |
| --- | --- | --- |
| textures | **322/322** | 约 6 分钟（中途编辑器卡死一次，续跑 8 秒收尾） |
| meshes | **109/109** | 约 100 秒 |
| masters | **11/11** | 95 秒 |
| instances | **163/163** | 25 秒 |
| bindings | **109/109** | 23 秒 |
| actors | **428/428** | 4 秒 |
| parents | **424/424** | 1 秒 |

- 资产落地：`Content\AtlasMaps\Iceland54\` 下 **605 个 .uasset**（Textures 322 / Meshes 109 / Materials 174），关卡 `LV_Map.umap` 490 KB。
- 关卡层级：`LV_Map → Iceland → geometry → CollectionRoom_BigMeshGroup_12_0 → DFI_xxxx`（StaticMeshActor），共 **428 个 Actor**，`parents` 阶段把 424 个挂到对应父件上。
- 打开就能看：材质/贴图都绑上了（细节点开材质槽能看到 `M_80f9f32bcdd85…`）。

### 8.2 为了跑通又改/加了两个文件

| 文件 | 改动 |
| --- | --- |
| `scripts\official\ue_iceland_bridge.py` | `mesh_slot_map()` 不再对非 `DF_SLOT_` 槽抛异常（FBX 自带的 `WorldGridMaterial` 槽直接忽略并打 warning）；`bind_mesh()` 里只保留 `DF_SLOT_` 槽再重排，避免重复占位。原来这里会 `RuntimeError: Unrecognized FBX material slot WorldGridMaterial` 整批中断 |
| `scripts\official\ue_run_headless.py`（新） | 命令行一次跑完 7 阶段：`_ensure_level()` 建/载关卡 → 逐阶段 `bridge.start()` + 循环调 `bridge._tick(0)`（**命令行没有 GUI 帧，slate 回调永远不会来，必须自己推状态机**）→ 每 2 秒打进度到 `work\ue_test\headless_run.log` → 末尾 `save_current_level()`。支持 `ATLASMAP_UE_SKIP` 续跑、`ATLASMAP_UE_START` 从某条索引续跑 |
| `scripts\official\ue_ensure_lighting.py`（新） | 给导入好的关卡补 `SkyAtmosphere` + `DirectionalLight`（强度 12，暖白）+ `SkyLight`（实时捕获，2.5），否则 Lit 模式全黑 |

### 8.3 命令行配方（不用开 GUI）

```powershell
$env:ATLASMAP_UE_ROOT  = "D:\AtlasMap-build\atlasmap\work\ue_test\ue_transfer"
$env:ATLASMAP_UE_DEST  = "/Game/AtlasMaps/Iceland54"
$env:ATLASMAP_UE_LEVEL = "/Game/AtlasMaps/Iceland54/LV_Map"
# 第一次全跑
& "E:\UE_5.4\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" "<proj>" `
  "-ExecutePythonScript=D:\AtlasMap-build\atlasmap\scripts\official\ue_run_headless.py" `
  -unattended -nosplash -FullStdOutLogOutput
```

注意事项（都是实测踩出来的）：

1. **别加 `-nullrhi`** —— Slate 初始化会崩（`UnrealEditor-SlateRHIRenderer.dll` 访问违例，exit=3）。
2. **`-ExecutePythonScript` 能建关卡/导资源**，`-run=pythonscript`（NullRHI）不能。
3. 中途卡死（日志停在某条索引、CPU 不再动）就杀进程，用 `ATLASMAP_UE_SKIP=<已完成阶段>`、需要时再配 `ATLASMAP_UE_START=<索引>` 续跑；实测 302/322 卡住，重启后 8 秒跑完剩下的 20 张。
4. 关卡要**先存在并保存**再跑 `actors` 阶段（脚本里 `_ensure_level()` 已代劳）。

### 8.4 效果

`work\_ue54_open.png`（无光照，看层级和摆放）、`work\_ue54_lit.png`（加灯后 Lit，看材质）。

### 8.5 还没做的三段（官方 §5.4–5.6）

源光照（`ue_iceland_source_lighting.apply()`，需要作者的天空 DDS）、水体（`ue_rebuild_iceland_water` 需要 `water_rebuild` 中间数据）、碰撞（`ue_rebuild_iceland_collision` 需要 `source_hidden_collision_policy.json`）。
这三件的输入 zip 里没发，先用 `ue_ensure_lighting.py` 的通用三点光顶上；等我们能从 pak 里自己提天空 cubemap 再按那套参数（`ibl_coefficient=500 / sky_energy_scale=500 / manual_ev100=8.8 / static_gi_fill=2.0`）做等价实现。

## 九、真图实测：SafeHouse 全流程（UE 5.4.4，2026-11-01）

前面第八节是用 CollectionRoom 这种小屋验证流程；这一节是**完整真图**（SafeHouse，274 m × 324 m × 90 m）。

### 1. 导出（dfmap）

```powershell
map-export.exe --config "$env:LOCALAPPDATA\AtlasMap\exporter.json" merge SafeHouse `
  D:\AtlasMap-build\atlasmap\work\ue_test\SafeHouse_export `
  --root "DeltaForce/Content/Maps/BuildMaps_HD/SafeHouse/Runtime/BigMeshGroup/" `
  --split --keep-base-with-hd --deduplicate --max-tex 512
```

产出 5 个分块 glb + 620 张 PNG + `manifest.json`，`world bounds` 274 m × 324 m × 90 m。

### 2. Blender ①（split → .blend）

**两个前置目录**，缺一个就白跑：

```powershell
# (a) 脚本只扫 <ROOT>/<group>/split，dfmap 只输出 <ROOT>/split
New-Item -ItemType Directory -Force "$ROOT\geometry" | Out-Null
cmd /c mklink /J "$ROOT\geometry\split" "$ROOT\split"
# (b) 脚本会写 <ROOT>/diagnostics/blender_import.glb
New-Item -ItemType Directory -Force "$ROOT\diagnostics" | Out-Null
```

```powershell
blender -b -P scripts/official/blender_iceland.py -- $ROOT --no-render --materials
```

实测：`Imported geometry 1/5; unique meshes 49` → `Finished geometry`，`scene_no_terrain.blend` 29 MB。
（没有 `terrain.npz` 会跳过 CDLOD 地形 —— 地形要先用 `iceland_terrain.py` 解 Header/Heightmap。）

### 3. Blender ②（→ transfer 包）、③（材质计划）

```powershell
$env:ATLASMAP_UE_ROOT = "…\ue_transfer_safehouse"
blender -b "$ROOT\scene_no_terrain.blend" -P scripts/official/blender_iceland_to_ue.py
blender -b -P scripts/official/compile_iceland_ue_materials.py
blender -b -P scripts/official/group_iceland_ue_materials.py
```

实测：`objects 483 / mesh_objects 478 / mesh_assets 100 / materials 184 / images 389`；
`source_materials 184` → `{"parents": 11, "instances": 184}`。

### 4. UE 5.4.4 七阶段（headless）

```powershell
$env:ATLASMAP_UE_ROOT  = "…\ue_transfer_safehouse"
$env:ATLASMAP_UE_DEST  = "/Game/AtlasMaps/SafeHouse54"
$env:ATLASMAP_UE_LEVEL = "/Game/AtlasMaps/SafeHouse54/LV_Map"
UnrealEditor-Cmd.exe "<proj>" -ExecutePythonScript="scripts\official\ue_run_headless.py" -unattended -nosplash
```

实测（分两次跑，textures 那次被系统杀掉后从 `ATLASMAP_UE_SKIP=textures` 续）：
`textures 389/389（808 s）`、`meshes 100/100`、`masters 11/11`、`instances 184/184`、
`bindings 100/100（11 s）`、`actors 483/483（10.5 s）`、`parents 478/478（3.8 s）`，
关卡 `Content\AtlasMaps\SafeHouse54\LV_Map.umap`，**483 个 Actor**，资产 `Textures 389 / Meshes 100 / Materials 195`。

### 5. 补灯

```powershell
$env:ATLASMAP_UE_LEVEL = "/Game/AtlasMaps/SafeHouse54/LV_Map"
UnrealEditor-Cmd.exe "<proj>" -ExecutePythonScript="scripts\official\ue_ensure_lighting.py" -unattended
```

`现有关卡 Actor 483 个，灯光类型：[]` → 加 `SkyAtmosphere + DirectionalLight(12) + SkyLight(2.5)` → 486 个。

### 6. 打开看

`UnrealEditor.exe "<proj>" /Game/AtlasMaps/SafeHouse54/LV_Map` → 视口里点一下 → `Ctrl+A` → `F` 框住 → 滚轮拉近；
嫌全白就把太阳强度调到 3 左右，或切「无光照」看几何。

截图：`work/_sh_framed.png`（框住整图）、`work/_sh_unlit.png`（无光照，八边形主楼 + 长走廊）、`work/_sh_lit.png`（Lit）。

### 仍未做（要接官方的三段）

源光照 `ue_iceland_source_lighting.apply()`（要先把 `SCb0_19_2_RGBA16F.dds` 当 TextureCube 导入）、
水面 `water.build()/apply()`、碰撞 `collision.start_meshes()/start_component_phase()`，
以及 `ue_repair_iceland_{visibility,packed_alpha,container_detail}.py` 三个修补脚本。

---

## 十、一键全自动（2026-11-01）

「进 UE」页顶部现在有一个 **⚡ 一键全自动** 卡片：点一下就按顺序跑完八步，不用再一条条复制命令。

### 跑的是什么

| # | 步骤 | 实现 |
|---|------|------|
| 1 | 导出器导出 split | `dfmap merge <地图> <导出目录> --root ".../Runtime/BigMeshGroup/" --split --keep-base-with-hd --deduplicate --max-tex 512` |
| 2 | Blender ① | `blender -b -P scripts/official/blender_iceland.py -- <导出目录> --no-render --materials` |
| 3 | Blender ② | `blender -b <导出目录>/scene_no_terrain.blend -P scripts/official/blender_iceland_to_ue.py`（`ATLASMAP_UE_ROOT=<导出目录>_ue`） |
| 4 | 材质编译 | `compile_iceland_ue_materials.py` |
| 5 | 材质分组 | `group_iceland_ue_materials.py` |
| 6 | UE 七阶段 | `UnrealEditor-Cmd.exe <工程> -ExecutePythonScript=ue_run_headless.py -unattended -nosplash`（`ATLASMAP_UE_ROOT/DEST/LEVEL`） |
| 7 | 补灯 | `ue_ensure_lighting.py`（`ATLASMAP_UE_LEVEL`） |
| 8 | 补碰撞 | `ue_build_collision.py`（`ATLASMAP_UE_LEVEL`） |

跑之前会自动 `prepare_dirs()`：建 `<导出目录>\geometry`、把 `<导出目录>\split` 软链到 `geometry\split`、建 `diagnostics\`。

### 代码

- `core/ue_pipeline.py`：`build_steps(paths, max_tex, skip_textures)` 拼八步；`prepare_dirs(root)`；`class Pipeline` 后台线程顺序跑、`on_line/on_progress/on_done` 回调、`stop()` 用 `taskkill /F /T`，每步跑前会检查脚本/`.blend` 在不在，不在就直接报「缺少脚本」而不是让 Blender 静默失败。
- `app/main_window.py::run_pipeline()`：复用「任务」页 + 导出小窗，日志实时进小窗的圆形下拉按钮。
- `app/ue_page.py::_run_all()`：校验引擎/Cmd/Blender/工程存在、路径全 ASCII → `prepare_dirs` → `build_steps` → 主窗口缩成右下角小窗 → 跑完自动「打开导出目录 / 关闭」。
- 命令行等价物：`python tools/run_pipeline.py CollectionRoom --dest /Game/AtlasMaps/CollectionRoomAuto`。

### 实测

- CLI 全链（CollectionRoom）：**8 步全过，202 秒**；UE 侧 `textures 322 / meshes 109 / masters 11 / instances 163 / bindings 109 / actors 428 / parents 424`，`Content\AtlasMaps\CollectionRoomAuto` 落地 605 个 .uasset + `LV_Map.umap`。
- 打包版点「一键全自动」：第 1–5 步在 exe 里正常跑（导出的 `scene.glb`、`scene_no_terrain.blend`、`manifest.json` 时间戳都在更新）。

### 注意事项

- 导出目录和工程路径必须 **纯 ASCII**（UE 命令行会把中文转成 `?`）。
- 第一次跑一张新图会比较久（CollectionRoom 约 3 分钟，SafeHouse 那种 389 张贴图的要十几分钟），中途可以点小窗里的「终止导出」。
- 跑之前最好把 `Unreal*` 进程都关掉（编辑器单实例，旧实例会吞掉新命令行）。

## 十一、没有 .uproject 也能一键跑（2026-11-01）

以前「一键全自动」要求先手动选/建一个 `.uproject`，没工程时只在状态栏说「还差：UE 工程」就停。
现在改成**自动准备**：

* 引擎/Blender 输入框为空时，先自动探测（`E:/UE_5.4`、`D:/`、`C:/Program Files/Epic Games` 等候选路径）。
* 工程为空时调用 `_ensure_project()`：
  * 有可用工程 → 直接用；
  * 否则在 **`<导出目录的父目录>/AtlasMapUE/AtlasMapUE.uproject`** 自动生成（`.uproject` + `Config/DefaultEngine.ini`，
    启用 `PythonScriptPlugin` / `EditorScriptingUtilities` / `GeometryScripting`，`EngineAssociation` 从引擎路径推断）；
  * 导出目录父级含中文时，退到 `%LOCALAPPDATA%/AtlasMap/UEProject`；
  * 已有但 0 字节或 JSON 坏掉的 `.uproject` 会被重写（不会卡在「文件存在但不合法」）。
* 生成后自动写回输入框并保存到 `settings.json`。

实测（`1.0+2026-11-01.1710`，打包版）：把 `ue_project` 清空后点「一键全自动」，
自动生成 `Export3/AtlasMapUE/AtlasMapUE.uproject`，随后 1–5 步跑完、第 6 步 `UnrealEditor-Cmd` 起来，
资产落到该工程的 `Content/AtlasMaps/CollectionRoomAuto3/`（当时已写入 366 个 `.uasset` 并在继续）。

⚠️ 跑之前把已经开着的 `UnrealEditor` 关掉（UE 是单实例的，编辑器的最大化窗口还会盖住本软件、吃掉鼠标点击）。

### 十一补充：「打开」按钮指向工程（2026-11-01）

一键流程跑完后，导出小窗里的按钮不是「打开导出目录」了，而是 **「打开 UE 工程」**：
点它会在资源管理器里**选中刚生成的 `.uproject`**（`explorer /select,<路径>`）；
如果工程文件找不到，就退到工程目录。

实现：`ExportWindow.finish(code, out_dir, open_path=..., open_label=...)` —— `open_path` 决定按钮实际打开什么，
`out_dir` 仍然写在副标题里做记录；`app/ue_page.py::_run_all()` 把 `p["project"]` 传进去，
并顺手 `self.win.last_open_dir = os.path.dirname(project)`，
这样「任务」页的「打开导出目录」也会优先跳到工程目录（`app/pages.py::JobPage._open_out`）。

