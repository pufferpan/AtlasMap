# AtlasMap
# 此代码仅供学习使用禁止用于非法用途，包括但不限于其导出的资产禁止违规使用

地图导出器，当前源码版本 `1.0+2026-11-05.export-quality`

新增五档导出质量与预计大小，支持 UE、Blender 和性能模式，简易模式也可直接使用。估算范围和使用方式见 [导出质量说明](docs/export-quality.md)。

支持一键导出 Blender 完整工程和导出过程中可旋转、缩放的分块 3D 预览（可能比较反人类）。使用方式和验证范围见 [更新说明](docs/blender-preview-wegame-fix.md)。

本版恢复指定天空 Cubemap、源曝光范围/曲线/测光图，修复已关闭的雾被启用，并按要求默认移除爆破模式开局空气墙。详见 [更新说明](docs/更新说明_20261103_天空光与空气墙.md)。虚幻引擎 **记得使用虚幻5.4.4版本，其他版本测试结果为,物体会乱**

以及地图导出、源渲染状态保存、Blender 转换、UE 导入与预览流程。

本版合并完整任务日志、FluentPy Form XddXmt 控件、首次使用图解教程、HDR 反射与材质源数据修复，并修复 Windows 长路径烘焙资源合并和超大天空边界的精度误判。验证范围见 [长路径修复说明](docs/NOTES-long-path-fix.md)。

本次同时保留原生 FluentPy 控件、最新网格拓扑修复，并修复 Retrowar 批量创建对象时的 NullRHI Hit Proxy 数组溢出，见 [无渲染导入修复](docs/nullrhi-import-fix.md)。

## 开发与构建

Windows x64，Python 3.12，.NET 10；编译辅助程序需要 .NET 10 SDK。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe run.py
```

```powershell
powershell -ExecutionPolicy Bypass -File .\build-source.ps1 -PythonExe .\.venv\Scripts\python.exe
```

构建产物为 `dist/AtlasMap/AtlasMap.exe`，发布时携带整个程序目录。UE 与 Blender 需另外安装并在界面中配置。

### 单文件版

只想拷一个 exe 就走，加一个环境变量即可：

```powershell
$env:ATLASMAP_BUILD_ONEFILE = '1'
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm AtlasMap.spec
```

产物是 `dist/AtlasMap-Standalone.exe`（约 103 MB）。它把 `runtime/` 与 `scripts/` 一起塞进
exe，运行时解压到系统临时目录：首次双击到界面出现约 10–15 秒，退出后临时目录自动清掉；
解压需要约 300 MB 临时空间。目录版启动更快（2–3 秒），功能完全一样。
两个版本都从 Release 页下载：`AtlasMap-win64.zip`（目录版）与 `AtlasMap-Standalone.exe`（单文件）。

完整目录、原导出核心源码和依赖说明见 [源码说明](README-source.md)。本版导出窗口动画与资源占用入口见 [界面更新说明](docs/NOTES-export-ui.md)，标准 UE 渲染的兼容边界见 [导出说明](docs/NOTES-export-rebuild.md)

游戏光照兼容模式、原始参数切换、地图调校和验证范围见 [光照说明](docs/NOTES-game-lighting.md)。

默认关闭的多进程加速、性能模式、桌面平铺进度窗口及 Blender / UE 分片导出见 [并行导出说明](docs/NOTES-parallel-export.md)。

`runtime/` 保留固定版本导出工具链的原始二进制；`exporter-source/` 保存导出核心的 C# 工程源码，`tools/scene_state/` 保存新增辅助程序源码。构建产物、导出地图、运行日志和旧 ZIP 不进入版本管理。
