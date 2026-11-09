# 首启向导与教程图的来源

`assets/` 下这几张图都是**本程序自己的界面截图**，不含游戏美术、不含游戏地图名：

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `tutorial_maps.png` | 地图库页与导出设置面板 | `tools/capture_wizard_tutorial.py` |
| `tutorial_ue.png` | UE 导出页 | 同上 |
| `tutorial_performance.png` | 性能/并行设置卡片 | 同上 |
| `tutorial_progress.png` | 导出进度窗口 | 同上 |
| `wizard_base.png` | 渐变底 + 左侧压暗 | `tools/make_wizard_bg.py` |
| `wizard_row1..3.png` | 三条 45° 斜置的截图带子 | 同上（卡片取自上面四张教程图） |
| `wizard_rows.json` | 三条带子的画布坐标 | 同上 |
| `wizard_bg.png` | 上面几层合成好的静态兜底图 | 同上 |

两张脚本都只读本地界面、不触发导出、不改用户设置：

```bash
python tools/capture_wizard_tutorial.py     # 重新截四张教程图
python tools/make_wizard_bg.py              # 重新拼向导背景（默认 2560x1600）
```

截图里的路径都是占位（`D:/AtlasMaps/Export` 之类），不指向任何真实安装；地图行显示的是
pak 里的关卡代号，中文显示名由 `core/mapnames.json` 决定，本仓库给的是中性名称。

换主题/改文案后重跑上面两条命令即可，`app/wizard.py` 会按 `wizard_rows.json` 自动摆放。
如果只想换底图不换截图，单独跑 `make_wizard_bg.py` 就行。
