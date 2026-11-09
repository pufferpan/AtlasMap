# AtlasMap 开发记录

## 1. 导出遮罩（2026-11-01，`1.0+2026-11-01.0830`）

点「开始导出」后不再只是把日志塞到「任务」页，而是整窗盖一层遮罩：

- `app/export_overlay.py::ExportOverlay`
  - 底：`paint_glow()`（和开屏同一套 HyperOS 光斑）+ 一层 `QColor(4,6,11,130)` 压暗
  - 卡片：`min(w*0.62,860) × min(h*0.44,420)` 圆角 22，标题 / 副标题「请勿操作，导出结束后会自动收起」/
    跑马灯进度条 / 「当前动作」一行 / 「已经跑了 N 秒」
  - 右下角：`btn_stop`（终止导出）→ `stop_requested` → `window.stop_job()`
  - 完成态：标题换「导出完成 / 导出失败」+ 用时 + 路径，右下角换「打开导出目录 / 关闭」
  - 最右下 40×40 圆钮：`logPull` 属性动画 260ms 把日志面板拉下来（▾↔▴），面板里是 导出器的实时输出
- 接线：`app/main_window.py::show_export_overlay()`、`run_job(..., on_line=)`；
  `app/pages.py::MapPage.export()` 先建遮罩再起任务，遮罩建不起来时降级成「任务」页（不会连导出都跑不了）
- 踩的两个坑：
  1. `QPropertyAnimation` 只能动画真正的 Qt `Property`，用 Python `property()` 会报 `non-existing property`
  2. 遮罩里的按钮忘了 `setParent(self)` → 变成独立顶层窗口，截图里根本看不到

## 2. 导出「完全不能用」的两个根因（2026-11-01）

| 现象 | 根因 | 修法 |
|---|---|---|
| 点导出没反应 / 导出 0 层 | 唯一带预设的 **Iceland 这套 pak 里没有**，`find "Maps/BuildMaps_HD/Iceland"` 返回 0，预设的 18 个 root 全匹配 0 层 | 无预设地图按 `BuildMaps_HD/<图>/Runtime/{BigMeshGroup,...}` 生成资源根勾选；预设图若 0 文件则置灰 + 橙字警告 + 禁用「开始导出」 |
| 命令和官方文档不一致 | 官方 CLI 示例带 `--no-scene`，UI 之前没有 | 加「不合并总场景 (--no-scene)」勾，`_flags()` 已接 |

验证：`SafeHouse` 实导 62 秒完成，日志 `levels found : 5` → `extracted 5/5 levels, 478 instances` →
`decoded 97/97 meshes, 799503 verts, 708947 tris` → `scene.glb 49 MB` + `split\ 5 个 glb` + `textures\ 620 PNG`，
`world bounds (UE cm) min=(-14570,-19589,-21714) max=(12785,12786,-12755)`、`size 274 m × 324 m × 90 m`。

`job.stop()` 单测：起导出器 → 4 秒后 `job.stop()` → `running=False`、系统里 `map-export` 进程数 0。

## 3. UE 5.3.2 导入（`scripts/ue_import_atlas.py`）

- 不装引擎也能跑 `--check`：校验目录、`split\manifest.json`、`scene.json`、首个 GLB 的 glTF 版本/节点/材质/贴图
- 装了引擎：`ue_import.bat` 调 `UnrealEditor-Cmd.exe -run=pythonscript`
  - 默认模式：`AssetImportTask` 批量导入 → 新建关卡 → 每个 StaticMesh 摆在原点
  - `--use-scene-json`：按 `scene.json` 的 `matrixUE`（UE 厘米 / Z-up / 列主序）逐实例精确摆放
  - 收尾算整体包围盒，`max(size) < 500 cm` 就 warning（说明节点矩阵没烘进网格）
- 坐标对照：GLB = 米 / Y-up（节点矩阵 = UE 坐标 ÷100）；`scene.json` = 厘米 / Z-up；UE 导入器自动 ×100
- 本机 `E:\UE_5.3` 只有 Launcher 的 `.egstore`，**没有真引擎**，所以引擎侧脚本未实跑；详见 `docs/UE5.3_导入说明.md`
