# 单文件与完整目录构建

同一 AtlasMap.spec 支持两种输出。默认生成完整目录；设置环境变量 ATLASMAP_BUILD_ONEFILE=1 后生成 AtlasMap-Standalone.exe。

单文件内包含 Qt/Python 运行时、FluentPy、固定版本导出器、材质/环境辅助程序、Blender/UE 脚本、截图和文档。启动时由 PyInstaller 解包到临时目录，运行期间从该目录调用工具；配置及日志继续保存在用户目录。

单文件无需相邻文件，但导出仍使用本机安装的 Blender、UE、.NET 10 和用户游戏资源。首次启动需要解包时间。完整目录版可直接启动，无需每次解包。

构建示例（PowerShell）：

```powershell
python -m PyInstaller --noconfirm AtlasMap.spec
$env:ATLASMAP_BUILD_ONEFILE='1'
python -m PyInstaller --noconfirm --workpath build/singlefile --distpath dist/singlefile AtlasMap.spec
```
