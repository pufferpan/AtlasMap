# dfmap 地图导出工具（2026-10-31 修正版）

当前 CLI 与 GUI 共享 CUE4Parse 解码、组件仿射变换和源元数据处理。完整教程已重写到 [docs](../docs/README.md)，不再以旧研究说明中互相冲突的坐标、SVT 或材质结论作为当前操作依据。

## 快速使用

```powershell
dotnet build .\dfmap-gui\dfmap-gui.csproj -c Release
& .\dfmap\bin\Release\net10.0\map-export.exe --config .\exporter.local.json doctor
& .\dfmap\bin\Release\net10.0\map-export.exe --config .\exporter.local.json doctor --mount
```

GUI 通过“资源与配置”设置游戏根目录和本地密钥文件，不按旧固定包数量判断挂载成功。CLI 所有命令支持全局 `--config`。便携修正版使用随附启动脚本；使用说明见 [软件修正版说明](../docs/软件修正版使用说明.md)。

## 当前数据约定

- UE 厘米 `(x,y,z)` → glTF 米 `(x,z,y)/100` → Blender 米 `(x,-y,z)/100`。
- 保留原组件仿射矩阵；不额外翻转三角形绕序。
- 多 UV、原顶点色和 section 材质槽按源数据导出；组件 OverrideMaterials 不得覆盖共享 mesh 的默认绑定。
- GLB 纹理以 bufferView 嵌入；仍应保存 scene.json、split/manifest.json 和验证报告。
- 默认 merge 保留源隐藏物件并写入 `node.extras.dfmap`；`--visible-only` 才过滤。源碰撞字段是元数据，原生碰撞仍需在目标引擎生成并验证。
- split 按完整源关卡路径分组，保留 node transforms，不是全部顶点已经烘焙。使用 `scripts/blender_import_verified.py` 导入与验证。
- 已支持 DeltaForce SVT chunk 修复。VolumeTexture、G16、RGBM、BC6H 及复杂源材质不能当普通 sRGB 颜色图统一处理；地图专用恢复参阅教程。

## 命令

`doctor`、`paks`、`maps`、`find`、`dump`、`level`、`mesh`、`raw`、`scan`、`merge`、`tex`。执行不带参数的 CLI 可查看基本帮助。常用 merge 开关包括 `--root`、`--split --no-scene`、`--keep-base-with-hd`、`--deduplicate`、`--visible-only`、`--max-tex`、`--mesh-filter` 和 `--instance-bbox`。

原始水体交互、完整 cooked shader 算法、GI2D/PRT、天气和目标引擎碰撞不是基础 GLB 导出自动完成的内容。Iceland 四阶段 preset 也不是“一键完整还原”承诺。

## 验证

```powershell
dotnet run --project .\tests\ConfigDoctor.Tests -c Release
dotnet run --project .\tests\ExportIntegrity.Tests -c Release -- .\out\integrity-tests
```

实际 Iceland 水面、隐藏辅助体导出和 Blender 后台导入的验证记录见 `out/software_upgrade/20261031`，软件交付目录随附汇总。当前基础库的已知 NuGet 审计限制见 [软件说明](../docs/软件修正版使用说明.md)。
