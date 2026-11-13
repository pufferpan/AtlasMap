# AtlasMap

地图导出器，当前源码版本 `1.0+2026-11-05.export-quality`。

本版新增：**区域框选导出**（平面图上拖框，只导选中分块，见 [区域导出](docs/区域导出.md)）、**简单导出向导**（导出前问一句，四步走完直接开跑，见 [简单导出向导](docs/简单导出向导.md)）、**物理灯光换算**与**贴纸透明修复**（见 [灯光与透明](docs/灯光与透明.md)）。

新增五档导出质量与预计大小，支持 UE、Blender 和性能模式，简易模式也可直接使用。估算按「实测历史 → 源导出统计 → 包体积」三档给出，量出来过什么就按什么报，细节见 [导出质量说明](docs/export-quality.md) 与 [预计大小](docs/预估大小.md)。

不再需要激活码：程序启动即用，没有机器码、没有有效期、没有联网校验；旧版的激活码与签发网页已从代码中移除。

支持一键导出 Blender 完整工程和导出过程中可旋转、缩放的分块 3D 预览。本版修复 WeGame 更新资源漏读导致的Brakkesh、Collapse缺失，以及 MA1 分块分析缺少 ZstdSharp 依赖的问题。使用方式和验证范围见 [更新说明](docs/blender-preview-wegame-fix.md)。

本版恢复指定天空 Cubemap、源曝光范围/曲线/测光图，修复已关闭的雾被启用，并按要求默认移除爆破模式开局空气墙。详见 [更新说明](docs/更新说明_20261103_天空光与空气墙.md)。虚幻引擎 **5.4 特殊构建版，已适配 5.4 普通版**。

包含桌面界面、首次向导和渐变开屏，以及地图导出、源渲染状态保存、Blender 转换、UE 导入与预览流程。

本版合并完整任务日志、FluentPy 控件、首次使用图解教程、HDR 反射与材质源数据修复，并修复 Windows 长路径烘焙资源合并和超大天空边界的精度误判。验证范围见 [长路径修复说明](docs/NOTES-long-path-fix.md)。

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

完整目录、原导出核心源码和依赖说明见 [源码说明](README-source.md)。本版导出窗口动画与资源占用入口见 [界面更新说明](docs/NOTES-export-ui.md)，标准 UE 渲染的兼容边界见 [导出说明](docs/NOTES-export-rebuild.md)。

游戏光照兼容模式、原始参数切换、地图调校和验证范围见 [光照说明](docs/NOTES-game-lighting.md)。

默认关闭的多进程加速、红色界面、桌面平铺进度窗口及 Blender / UE 分片导出见 [并行导出说明](docs/NOTES-parallel-export.md)。

`dfmap/` 保留指定 Export3 工具链的原始二进制；`exporter-source/` 保存提供的原工程源码，`tools/scene_state/` 保存新增辅助程序源码。构建产物、导出地图、运行日志和旧 ZIP 不进入版本管理。
