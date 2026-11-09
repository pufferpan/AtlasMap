# AtlasMap 完整源码包

归档日期：2026-11-07。对应版本：`1.0+2026-11-05.export-quality`。这是地图导出器本机当前源码快照，包含流动渐变开屏、首次向导及图解教程、FluentPy 控件、完整任务日志导出、缓存画面分裂动画、隐藏资源监控、固定导出链、完整源渲染状态、HDR 反射与材质源数据修复、游戏光照兼容模式及 Blender / UE 地图分块并行导出、独立分块场景与关卡、独立日志和进度，并合入 Windows 长路径和超大天空边界校验修复。当前也包含导出质量与预计大小、失败原因界面、工程管理、残留清理和机器码激活相关代码，包括尚未提交的本机修改。同系列的模型查看器是另一个项目，不在此包内。归档日期不改变程序版本，也不表示重新验证了全部地图。

## 目录

- `app/`、`core/`、`run.py`：当前桌面程序全部 Python 源码。
- `assets/`：字体、图标、首次向导截图及随程序使用的资源配置。
- `scripts/official/`：当前 Blender、UE 导入、材质、碰撞、灯光和预览脚本。
- `tools/scene_state/`：完整源渲染状态辅助程序的 C# 源码和项目文件。
- `scripts/tools/scene-state/`：已构建的辅助程序和必需的原生解码库。
- `tests/`、`tools/`、`docs/`、`site/`：回归测试、构建与验证工具、文档、现有说明页面。
- `AtlasMap.spec`、`build-source.ps1`、`requirements*.txt`：打包配置、构建脚本和依赖版本。
- `runtime/`：指定 Export3 目录的完整固定版本工具链，按原字节保留；包含第三方依赖 DLL、运行时、预设和文档。
- `exporter-source/source/`：本机 `mapviewer_src/固定工具链/source` 中的全部原工程源码，包括 CLI 导出器、旧 WinForms GUI、脚本和测试；相邻目录保留原工程文档、预设、脚本和辅助工具。
- `third_party/fluentpy-qt/`：当前安装的 FluentPy 0.7.3 Python 源码、资源和发行元数据，供核对与参考。
- `SOURCE-MANIFEST.json`：包内文件大小、SHA256 和来源记录。

构建缓存、Python 缓存、旧 ZIP、打包产物、运行日志、游戏包、已导出的地图及 UE/Blender 工程不在源码包内。机器上的授权文件、个人设置和签发私钥不在源码包内。游戏解包密钥 `AESKey1.json` 也不附带，请从自己保管的配置另行提供。第三方依赖 DLL 随固定工具链保留；除单独收录的 FluentPy 外，依赖库的上游源码不属于本项目源码。

## 运行当前桌面程序

使用 Windows x64、Python 3.12（当前验证环境为 3.12.10）和 .NET 10 x64 运行时。使用 UE/Blender 导出功能时，另行安装 Blender 和 Unreal Engine；本版在 UE 5.4.4 验证。

解压 ZIP，进入含 `run.py` 的目录，在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe run.py
```

首次运行使用对应机器码激活，在界面中设置本机游戏包、解包密钥文件、Blender 和 UE 路径。源码保留开发时的默认路径；如果本机没有原 Export3 路径，会自动查找此源码根目录下随附的 `runtime/`。设置与缓存仍写入 `%LOCALAPPDATA%\AtlasMap`。授权公钥随包保留，签发私钥由所有者单独保管。

## 构建当前版本

除上述环境外，安装 .NET 10 SDK：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-source.ps1 -PythonExe .\.venv\Scripts\python.exe
```

脚本校验随附 `map-export.exe` 与 `dfmap.dll`，重新编译 `scene-state`、运行回归测试，再调用 PyInstaller。结果为 `dist/AtlasMap/AtlasMap.exe`；发布时需要携带整个 `AtlasMap` 文件夹。

源码包附带现成的 `scene-state`，直接运行不必先安装 SDK。完整桌面构建使用随附固定版本导出器，不会重编译或替换它。

生成单文件前可设置 `$env:ATLASMAP_BUILD_ONEFILE='1'`，再执行同一构建命令；单文件产物为 `dist/AtlasMap.exe`。

## 原导出核心源码

`exporter-source/source/dfmap/dfmap.csproj` 是提供的原工程项目文件，其 NuGet 引用原样保留（CUE4Parse / CUE4Parse-Conversion `1.2.2.202609` 等）。独立编译原核心需要能取得这些指定版本的包；源码包同时保留当前程序实际使用的依赖二进制，但没有包含原工程 NuGet 缓存或第三方上游源码。

```powershell
dotnet build .\exporter-source\source\dfmap\dfmap.csproj -c Release
```

此命令仅说明原工程入口，未在此次源码归档任务中重新验证。重编译生成的二进制可能与固定版本哈希不同，当前桌面程序会拒绝不同哈希的工具链；如要开发核心，需要同时审查 `core/exporter.py`、`tools/scene_state/Program.cs` 中的固定版本校验并重新做完整导出验证。

## 光照边界

完整源灯光、雾、后处理和烘焙载荷会保留。标准 UE 预览仍存在游戏专用 PRT、预烘焙雾深度和自定义渲染字段的兼容差异，不表示画面已与游戏完全一致。详情见 `docs/NOTES-export-rebuild.md`。

## 归档校验

ZIP 同目录附带 `.sha256` 校验文件。`SOURCE-MANIFEST.json` 列出除清单自身外的全部文件及 SHA256；本次归档已逐项核对内容，并完成 ZIP CRC 检查。
