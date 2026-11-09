# Iceland 地图完整导出与复现教程

更新于 2026-10-31。本教程记录当前这份 Iceland 成品的实际制作路线：游戏资源 → 分块/地形导出 → Blender 场景与材质修复 → UE 迁移 → 光照、水体、碰撞。它不是“导出成功便等于原游戏渲染完全恢复”的说明。

相关文档：[AI 操作说明](AI地图处理操作说明.md)、[踩坑与排查](踩坑与排查手册.md)。软件本轮新增的入口、配置方式和发行包以项目入口文档及软件帮助为准；下文对旧研究脚本的调用均按本机实际代码核对。

## 1. 先选路线，避免把成品重做一遍

| 你现在有什么 | 推荐路线 | 不要做什么 |
| --- | --- | --- |
| 只想继续编辑当前 UE 地图 | 路线 C：打开现有关卡，按问题维护 | 不要重跑整套初次导入，覆盖已修复的材质、光照、水和碰撞 |
| 有最终修复 `.blend`，要另建 UE 项目/关卡 | 路线 B：从最终 Blender 场景迁移 | 不要先执行旧白模导入脚本、重置场景 |
| 只有同版本游戏包，要从零复现 | 路线 A：完整源导出，再建立 Blender 场景和修复包 | 不要把一条 `merge` 命令声称为当前成品的全部流程 |

当前成品的身份：

| 项目 | 位置/口径 |
| --- | --- |
| 工具工作区 | `D:/AtlasMap-tooling` |
| 最终 Blender 文件 | `out/Iceland/revised/Iceland_ground_detail_helpers_fixed.blend` |
| UE 项目 | `D:/xuhuan/UE_5.4/Projects/我的项目/我的项目.uproject` |
| UE 关卡 | `/Game/Maps/Iceland_Blender_20261031` |
| UE 导入资产根 | `/Game/Imported/Iceland_Blender_20261031` |
| 首次 UE 迁移中间包 | `out/Iceland/ue_transfer/20261031/` |
| 水体与光照恢复记录 | `out/Iceland/water_rebuild/20261031/` |
| 碰撞记录 | `out/Iceland/collision_rebuild/20261031/` |

最终 Blender 源场景保留 16,792 个对象，其中网格对象 16,789 个；UE 首次迁移产生 2,134 个静态网格资产、639 个材质 UV 绑定变体、1,520 个图像资产。后续又增加了水体、天空和兼容材质资产，不能把首次导入数量当作当前资产总数。源对象计数与额外光照/PlayerStart 也要分开。

## 2. 环境、版本和目录

本次使用游戏体验服，与用户对照的是同一体验服版本；解析 profile 为 `GAME_DeltaForce`。本机 Blender 为 `D:/blender/Blender 5.2/blender.exe`，UE 为 5.4.4，CLI/研究工具基于 .NET 10 与仓库引用的 CUE4Parse。换游戏更新、换 usmap、换解析器后必须重新验证，旧包数量、文件数量不是跨版本的固定验收值。

游戏根目录要递归扫描；资源不只在一处 `Content/Paks`。配置中的 `PaksDirectory`、密钥文件路径和游戏版本必须与 FModel 当前使用的一致。密钥值、完整密钥文件不得写入教程、日志附件或发行包。

配置示意（路径是占位值）：

```json
{
  "PaksDirectory": "E:\\WeGameApps\\rail_apps\\DeltaForceExper(2002097)",
  "Recursive": true,
  "Game": "GAME_DeltaForce",
  "MeshGame": "",
  "KeyFile": "E:\\LocalSecrets\\AESKey.json"
}
```

JSON 中 Windows 路径反斜杠必须写成 `\\`，也可以用 `/`。本次发现过 GUI 输出目录中的旧 `dfmap.json` 含非法转义和不可见方向字符，导致程序在挂载前即失败。先确认程序实际读取哪个配置，而不是只改工作区里一份同名文件。

旧 CLI 的配置优先查可执行文件旁边，再查工作目录；本次研究命令通常以 `out/Iceland/audit/environment_query` 为工作目录，里面是已验证的体验服配置。软件优化后的显式配置入口应优先使用；不要把“刚好在某工作目录能运行”当成可移植设计。

## 3. 路线 A：从原始游戏资源开始

### 3.1 构建与只读检查

在工作区运行：

```powershell
dotnet build .\dfmap\exporter.csproj -c Release
dotnet build .\scripts\IcelandAudit\IcelandAudit.csproj -c Release
```

有配置的工作目录里调用实际生成的 `map-export.exe`。先用 `paks`、`find`、`scan`、`level`、`dump` 检查，再开始大型写出。例如：

```powershell
& 'D:/AtlasMap-tooling/dfmap/bin/Release/net10.0/map-export.exe' paks
& 'D:/AtlasMap-tooling/dfmap/bin/Release/net10.0/map-export.exe' find 'Maps/Iceland/' 100000
& 'D:/AtlasMap-tooling/dfmap/bin/Release/net10.0/map-export.exe' scan 'Maps/Iceland' 'E:/work/Iceland/scan.json'
```

不要把 `keys` 的输出当成共享诊断材料，它会显示密钥。需要挂载诊断时只记录资源根、profile、挂载数量、失败原因与版本，不记录密钥内容。

### 3.2 建立关卡取舍清单

本次 Iceland 的资源分散在多类关卡。不能套用 SafeHouse 的 root 策略，也不能见到普通关卡和 `_HD` 就一律只保留 HD。Iceland 普通层中有厂房外墙等真实几何，而同名 HD 有时只附加灯光/效果。

当前初始五组导出采用的根目录可从以下文件的 `MapRoot` 字段精确读取：

```text
out/Iceland/revised/geometry/merge_report.json
out/Iceland/revised/interiors/merge_report.json
out/Iceland/revised/decorations/merge_report.json
out/Iceland/revised/supplement/merge_report.json
out/Iceland/revised/structures/merge_report.json
```

它们分别覆盖：

| 分组 | 已使用内容 |
| --- | --- |
| geometry | `BuildMaps_HD/Iceland/Runtime` 下 Big/Mid/SmallMeshGroup、Default、POIResident |
| interiors | S3/S4 等室内烘焙几何层及其附加 HD 层 |
| decorations | Decorations、Decorations_HQ、Landmark |
| supplement | Iceland InterActors、InterActors_HD、水体关卡 |
| structures | S2/S3/S4 等经核对的 LA_Mesh 结构层 |

随后还核对 Iceland_Tower 附加层、雷达支撑、中央尖塔、GenericConfig/通用静态层及组件模板中漏出的网格。只导这五组仍不足以证明当前成品完整。互斥的攻防、占领、活动等模式层不得全部混进“通用静态场景”；用户本次要求先处理通用静态场景。

复现同一资源版本时，可以用现有报告恢复初始分组命令，写到新的输出目录：

```powershell
$toolRoot = 'D:/AtlasMap-tooling'
$exportRoot = 'E:/work/Iceland_fresh'
$cli = Join-Path $toolRoot 'dfmap/bin/Release/net10.0/map-export.exe'
foreach ($group in @('geometry','interiors','decorations','supplement','structures')) {
    $report = Get-Content -LiteralPath (Join-Path $toolRoot "out/Iceland/revised/$group/merge_report.json") -Raw | ConvertFrom-Json
    $roots = ($report.MapRoot -split ' \+ ') -join ','
    & $cli merge Iceland (Join-Path $exportRoot $group) --split --no-scene --keep-base-with-hd --root $roots
    if ($LASTEXITCODE -ne 0) { throw "Export failed: $group" }
}
```

以上是“恢复本次已记录的初始 roots”，不是新版本游戏的通用选层算法；也不替代后面的补层和修复阶段。`--no-scene` 避免同时再构建一个巨大单 GLB；`--split` 保留逐关卡文件与 manifest。不得添加 `--no-textures` 后又期待导出完整贴图。

### 3.3 保留正确的源变换和实例语义

用完整组件链读取真实世界仿射矩阵，展开 ISM/HISM 的逐实例变换；在实例自身没有 StaticMesh 时继续读取组件模板。需要注册/处理本游戏的 `DFMDesStaticMeshComponent`、`DestructibleStaticMesh`、`MeshDecalComponent` 等类型。

当前正确约定：

```text
UE → Blender：位置 (x, -y, z) / 100，单位米，Z 向上
UE → glTF：位置 (x, z, y) / 100；变换矩阵使用相同基变换
Blender → UE：100 × (Bx, -By, Bz)，单位厘米
```

`GlbWriter.ConvertNativeMatrix` 同时置换矩阵行和列，仅对平移缩放单位。优先保留原矩阵，不能无端经过 Euler 往返；负缩放、非均匀缩放和微小剪切残差需要单独处理。当前 UE 迁移有一个仅用于保留仿射残差的网格变体。

三角形绕序按当前 `Glb.cs` 与独立 `winding_test.py` 的验证保持，不根据旧 README 中互相冲突的文字再次翻转。验证必须比较源矩阵下顶点，而非只比较物件原点或导出器自己生成的包围盒。

### 3.4 单独恢复 CDLOD 地形

地形不是一张默认平面。先用 `dump/raw` 提取 CDLOD 组件描述、Header、CoarseHeightmap 和各 Heightmap patch 的原始字节，放入同一 `diagnostics` 文件夹。现有输入示例见 `out/Iceland/diagnostics/`。

`scripts/iceland_terrain.py` 读取真实存储的高度样本与可见性位：

```powershell
python .\scripts\iceland_terrain.py 'E:/work/Iceland_fresh/diagnostics' --lod 2
```

该命令把 `terrain.npz` 写入 diagnostics 的上一级；LOD=2 对应 4 米样本间距。脚本检查 patch 边界、接缝误差、样本缺失，未找到样本时不能用平地悄悄补齐。`terrain_validation.json` 必须通过。

### 3.5 建立 Blender 基础场景

`scripts/blender_iceland.py` 会清空当前场景、读取多个分组的 split manifest、保留按完整源路径共享的网格、导入原始变换并创建源 CDLOD。必须在新的 Blender 进程或副本里运行：

```powershell
& 'D:/blender/Blender 5.2/blender.exe' --background --python 'D:/AtlasMap-tooling/scripts/blender_iceland.py' -- 'E:/work/Iceland_fresh' --materials --no-render
```

`--materials` 不可省略，否则该脚本主动移除材质显示输入。脚本可读取 `geometry/interiors/decorations/supplement/structures/common_towers/common_static`，缺某组 manifest 会跳过，因此“脚本没报错”不能证明全部组都已导出。检查实际组清单、objects/meshes 数量与 `diagnostics/blender_validation.json`。

该阶段允许按完整源资产路径和世界矩阵删除完全重复摆放，不能按同名网格或距离近就删除；不同组件材质覆盖、隐藏状态也应纳入审计。早期等效海面合并仅用于显示，并不代表水体渲染逻辑已经恢复。

## 4. Blender 修复与材质重建阶段

本次最终成品不是初次导入 GLB 的直接结果。研究脚本依赖预先生成的 source bundle、属性缓冲和输入清单；大多数仍写死本机路径。新机器或新输出目录上，必须先整理这些依赖、替换共享根目录，并使用新的工作副本。不要假装这些旧脚本已经是一条通用命令。

按以下依赖顺序处理；每一步保存独立检查记录与备份：

| 顺序 | 输入/研究命令 | Blender 应用与验证 |
| --- | --- | --- |
| 1. 补层与 section | `IcelandAudit --inventory`、原生矩阵审计；`--repair-bundle` 使用场景拓扑快照和已确认 missing placements | `apply_iceland_common_repair.py`；`verify_common_saved.py` |
| 2. 真实基础色与 VT | `--material-refresh` 读取完整源材质路径；修正 `VirtualTextureCompat` 的 DeltaForce codec 偏移；`--ground-export` 提取 DTA/权重 | `apply_iceland_texture_refresh.py`，检查材质族和失败清单 |
| 3. 多 UV 与贴花 | `--attributes` 提取原始 UV0…UVn、section、顶点色；隐藏组件源核对 | `apply_iceland_floor_repair.py`；`verify_iceland_floor_saved.py` |
| 4. 红厂房 | 根据 source master/两层材质、17 个源 slot、4 套 UV 恢复遮罩与分层响应 | `apply_iceland_factory_repair.py`；`verify_iceland_factory_saved.py` |
| 5. 道路、布、油罐 | 读取 source road/cloth/tank 参数与 RGBA8 顶点色；`--rvt-layers` 解开真实 RVT 各层，使用第 0 层颜色 | `apply_iceland_road_cloth_tank_repair.py`；`verify_iceland_road_cloth_tank_saved.py` |
| 6. 近景地面、道路细节 | `prepare_iceland_ground_detail.py`、`prepare_ground_weights.py`、`prepare_iceland_road_detail.py` 使用源细节纹理生成高频比例/权重数据 | `apply_iceland_ground_detail.py`；`verify_iceland_ground_detail_saved.py` |

`IcelandAudit` 的实际通用调用形状如下，参数顺序来自程序，不是 GUI 菜单名：

```powershell
# 所有命令均使用本地配置文件；不要在命令中放密钥值。
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --inventory $commaSeparatedRoots
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --repair-bundle $sceneTopologySnapshot $confirmedMissingPlacements
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --material-refresh $activeMaterialPathObjectJson
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --attributes $assetListJson
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --rvt-layers $runtimeVTAssetPath $mipIndex
dotnet run --project .\scripts\IcelandAudit -c Release -- $config $output --texture-files $maxSize $texturePath1 $texturePath2
```

变量是各阶段实际输入清单，不能把这些占位名称原样当文件名运行。现成 Iceland 输入与结果保存在 `out/Iceland/audit/`、`revised/common_static_repair/`、`revised/material_refresh/`、`revised/ground_material/`、`revised/ground_detail/`、`revised/road_detail/`；研究结果和这些文件的 schema 是当前可复现链的一部分。完全重新采集同一地图时也要重新生成 live topology snapshot 和完整材质路径清单。

关键原则：

- 颜色、法线、MRA/MAC、遮罩、数据图按源参数名分类，不能将 MAC 当颜色；图像按 bytes+色彩空间区分。
- 贴图存在不等于接法正确。道路 01a/02a 的混合遮罩使用 UV2，油罐使用 UV1，厂房又有独立分层；不能全图套用一个 UV 修复。
- 地面 8192² RVT 覆盖约 4033 米，只有约 2 像素/米；宏观颜色必须与原始 2048² 平铺细节合成，不能只放大低频图。
- Blender 图像打包、保存并重开，验证 UV/顶点色、面材质索引和世界矩阵未变。最后得到 `Iceland_ground_detail_helpers_fixed.blend`。

具体源链与数值证据见[材质修复说明](../out/Iceland/revised/材质修复说明.md)。其中早期统计是阶段快照，不等于最终 UE 资产总数。

## 5. 路线 B：从最终 Blender 文件迁移到新 UE 关卡

### 5.1 导出明确清单，而不是只导一个 FBX

先复制最终 `.blend`，运行 `blender_iceland_to_ue.py`。该脚本输出目录、目标 level 与资产根当前写死在脚本中；另建关卡时先统一修改相关脚本的 ROOT/DEST/level，不能只改一个文件。下面是本机复现路径示例：

```powershell
& 'D:/blender/Blender 5.2/blender.exe' --background 'D:/AtlasMap-tooling/out/Iceland/revised/Iceland_ground_detail_helpers_fixed.blend' --python 'D:/AtlasMap-tooling/scripts/blender_iceland_to_ue.py'
python .\scripts\compile_iceland_ue_materials.py
python .\scripts\group_iceland_ue_materials.py
```

该步骤建立 `manifest.json`、每个唯一网格的 FBX、图像、完整 Blender 节点图、物件材质覆盖和 source ID。FBX 临时副本换成 `DF_SLOT_0000` 等占位材料前，必须保存并恢复 polygon.material_index；文件先写 `.partial.fbx`，成功后原子替换。微小仿射残差烘焙到单独变体。

`compile_iceland_ue_materials.py` 只接受有支持的实际参与输出节点；遇到未支持节点就明确报错，不能默默用白色替代。`group_iceland_ue_materials.py` 将等结构 DAG 因式分为 36 个共享母材质和 639 个实例，并做替换可逆/数值等价检查。标识符替换必须按完整 token，避免 `Img_5` 改坏 `Img_50`。

### 5.2 在 UE 中按阶段导入

先创建新的空关卡并保存，确认 world 包路径正确；不要在原 ThirdPersonMap 上运行导入。启用 Python Editor Script Plugin，连接可执行 UE Python 的接口。把工作区 scripts 加入 Python path：

```python
import sys
sys.path.insert(0, 'D:/AtlasMap-tooling/scripts')
import ue_iceland_bridge as bridge
```

以下每一步单独调用；观察 `bridge.status()` 和 `ue_pipeline_status.json`，只有 `running=false`、`complete=true` 且无 error 后再启动下一阶段：

```python
bridge.start('textures')
# 等待完成后：
bridge.start('meshes')
bridge.start('masters')
bridge.start('instances')
bridge.start('bindings')
bridge.start('actors')
bridge.start('parents')
```

不能把这些行不等完成连续执行。它们使用 Slate post-tick 分批运行；`_busy` 防重入不可删除，执行中不可 reload 模块。失败后回读 current/cursor、实际资产和 source ID，再决定从何处恢复。不得因 RPC 超时就重复执行写入。

旧 `'materials'` 阶段代表未分组的单材质图路径，本次最终走的是 masters+instances，不要两条混用。材质槽使用 `DF_SLOT` 对应源面 slot，不能靠 FBX 导入顺序或 basename 猜。

### 5.3 首次迁移之后，应用最终兼容修复

1. 执行 `ue_repair_iceland_visibility.py`，将源隐藏网格的组件可见性保存为 false；图层成员关系不能代替实际隐藏持久化。
2. 对 `binary_alpha_rgb_risk.json` 中的打包数据图执行 `ue_repair_iceland_packed_alpha.py`；用 TGA 绕过 PNG 透明像素 RGB 填色，UE 导出回读做 RGBA 比对。
3. 执行 `ue_repair_iceland_container_detail.py`。它保留源浅米色/绿色等染色参数，以明确的兼容混合恢复底图锈迹和细节；原母材质保留。不能称为原染色公式已完整解出。
4. 使用下节的源光照、水体和碰撞处理。不要再调用旧 `ue_iceland_finish_scene.py` 把已恢复的原天空换回 forest.exr 预览灯光。

单个 UE 应用脚本的通用运行方式：

```python
exec(compile(open('D:/AtlasMap-tooling/scripts/ue_repair_iceland_visibility.py', encoding='utf-8').read(), 'ue_repair_iceland_visibility.py', 'exec'))
```

### 5.4 源光照重建

源配置位于 `IceLand_TODLight`、PC 序列 `Iceland_HD`，天气 ID 8001。已恢复的太阳世界旋转为 `(-28.244196, 16.426135, -4.159392)`，源强度 2000。真实 HDR 天光是 `SCb0_19_2` 六面 Half 数据；源天空全景是 RGBM，不能按普通 sRGB PNG 使用。

光照文件准备与参数来源见[源光照报告](../out/Iceland/audit/environment_query/lighting/源光照核对.md)。`prepare_iceland_source_sky.py` 处理已解码的原始天空数据；它不是直接挂载游戏包的入口，先要有对应 raw faces 和 RGBM 像素。

在新目标项目导入 `SCb0_19_2_RGBA16F.dds`，确认类型是 TextureCube、sRGB=false、HDR，命名为脚本期待的 `T_Iceland_SCb0_19_2_Source`，然后：

```python
import ue_iceland_source_lighting as light
light.apply(ibl_coefficient=500.0, sky_energy_scale=500.0,
            manual_ev100=8.8, fog_energy_scale=500.0, static_gi_fill=2.0)
```

这些是当前 UE 兼容换算，不是原游戏 NZSkyBox/GI2D/PRT 的完整算法。不要把项目旧曝光亮度字段直接填成 EV100 8.8–15；当前采用明确的手动物理相机曝光。天空网格必须 Unlit、is_sky、不投影、不参与光线追踪。仅保留一盏有效天光；用户自行新增灯光需要尊重其修改，本次经用户明确选择才停用额外 SkyLight 并恢复源配置。

### 5.5 水体兼容重建

现有可编辑原 shader 图不完整：水母材质 323 个表达式引用中 236 个为空，17 个直接函数没有可用的最终输出。不能要求用户重复提供已经存在的同版 cooked 文件就宣称可以完美复刻。

已有源数据：Data1/Data2 4096×1024，波浪 Volume 256×256×64，水高程 G16 4036²，细波、泡沫和波形资源。无损提取工具及所有 mip/哈希位于 `water_rebuild/20261031/source_data`，其独立 decoder 是研究工具，不是旧 `dfmap tex` 的通用 3D 支持。

UE 调用：

```python
import ue_rebuild_iceland_water as water
water.build()
# 在新建 Coast/Deep 图上按 material_get_graph 的真实 GUID：
# root.OutWPO → Material.WorldPositionOffset
# Python 隐藏了这个枚举，使用材质图接口连接，不猜整数枚举。
water.apply()
```

当前现有资产已连好，不应删除重建。本版用统一的原生 Single Layer Water 路径避免海岸/深水接缝；源 deep/far 中关闭 SLW 的专用分支未完整恢复，必须注明这一偏离。海面代理按源 HISM 构造可见标记保持隐藏，真正显示三个 In 水面及 Out 远海。不能误把水高程当海床深度，也不能将所有水面开成行走碰撞。

源三维波浪参与高度/法线和时间动画，但采样通道解释、12 秒周期与泡沫构造仍是兼容公式；角色/船尾流、浮力、原生 Gerstner 生成器和水下体积效果未完整实现。详细范围见[水体说明](../out/Iceland/water_rebuild/20261031/水体重建与验证.md)。

### 5.6 静态碰撞补全

仅有组件 BlockAll 而网格没有简单碰撞，角色仍会穿透。当前为 1,759 个实体网格建立静态三角面碰撞；将明确有源证据的隐藏阻挡恢复，而不对所有隐藏物件一概启用。

```python
import ue_rebuild_iceland_collision as collision
collision.start_meshes()
# 等待 meshes complete 后：
collision.start_component_phase()
# 再等 actors complete，保存后才能切关卡。
```

`source_hidden_collision_policy.json` 必须先由源审计生成。此文件不是可有可无的默认规则。当前审计 363 个隐藏 Cube：253 个 Pawn-only、28 个 BlockAll、79 个 disable、3 个未知不启用。关闭类别必须设 `NoCollision` profile，仅改 enabled 标记会在重开时被旧 BlockAll profile 覆盖。

验证应同时包含普通射线/胶囊与真实 PIE CharacterMovement。当前 9 类表面查询通过，5 类真实角色落地通过，道路实际行走约 2 米，运行无错误。它不是每个物件的动态刚体、Chaos 载具或可破坏逻辑制作。见[碰撞说明](../out/Iceland/collision_rebuild/20261031/碰撞补全说明.md)。

## 6. 验收与断点

先验证当前所处阶段，再看对应记录。后续兼容修复有意更换了容器父材质、天空与水面材质，原初次导入验证器会将这些识别为“与原计划不同”；不能为了让旧验证器通过而撤销正确的新修复。

| 阶段 | 验证入口/记录 |
| --- | --- |
| 初次 Blender→UE 的几何、图像、原图迁移 | `ue_validate_iceland_transfer.start('textures'/'meshes'/'materials'/'actors')`，每阶段分别等完成 |
| 隐藏、容器、源光照修复后 | `ue_validate_iceland_followup.py`，仅针对其声明的阶段；当前水面又有后续更改 |
| 水体与全部非水对象保持 | `ue_validate_iceland_water.py`、`water_final_validation.json` |
| 当前碰撞及场景保持 | `ue_validate_iceland_collision.py`、`final_collision_validation.json` |
| 灯光恢复 | `lighting_restore/saved_lighting_validation.json` |
| 数据图真实像素 | `packed_rgba_pixel_validation.json`、水体 `ue_texture_pixel_validation.json` |

最终验收至少包括：

1. 目标关卡正确、原 ThirdPersonMap 未被改写；源 ID 集合与本次基线一致。
2. 原物件名称、世界矩阵、父级、网格/面材质/物件覆盖、UV/顶点色、可见性保持；意图修改另列清单。
3. 当前母材质实际输出和参数回读正确，实际渲染平台的日志无当前编译错误，不只看工具一条“编译通过”。
4. 贴图尺寸、色彩空间、alpha、打包通道与 mip 正确；关键图 UE 导出回读对照。
5. 地形、道路、厂房、集装箱、布、油罐、水体等代表性画面检查；等待 pending assets/shaders/streaming 均为 0。
6. 保存，再切到其他安全关卡并打开目标关卡，重复状态检查。碰撞还要真实运行落地/行走。
7. 临时 QA 相机/目标点/角色已删除；全部修改已保存，报告无未解释错误。

存在一个已确认的零面积厂房三角面被 FBX SDK 滤除，不属于可见物件丢失；不能用统一“数量一切相等”掩盖或错误修补。大型海面跨约 24 km，顶点采样中约 0.055 cm 的 float32 误差有单独容差证据。

## 7. 路线 C：维护当前成品

打开现有 UE 项目与 `/Game/Maps/Iceland_Blender_20261031` 即可。先读本次当前关卡，再读最新验证 JSON，不能把老报告里的“正在导入”当成现在仍在运行。`CURRENT_CONTINUATION.md` 是历史和近期状态混合的工作日志，顶部最新更新优先，旧段只用于诊断。

定位一个问题时，优先收集：对象 source ID、完整资产路径、源组件、当前物件覆盖、slot/section、UV、节点贡献图和源参数。先形成最小诊断，再改一组共享规则并复查同类对象。新关卡/新版本先建新的输出 run，不覆盖这份已认可的场景。

当前明确保留的近似范围：复杂游戏材质数学、RVT 的全部动态合成、GI2D/PRT、天气、原生水体交互/水下及完整游戏逻辑。用户只有 FModel 游戏资源，不是原开发工程；贴图、参数和 compiled shader 的存在不等于可编辑原实现完整存在。
