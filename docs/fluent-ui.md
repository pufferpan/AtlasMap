# FluentPy 界面与完整日志

界面按 FluentPy 的 dialogs、inputs、selection、buttons、menus、themes、code-editor 和 feedback 示例迁移，当前使用 FluentPy 0.7.3。

- 路径框、多行资源根、勾选框、数字框和下拉地图选择使用 Fluent 控件；路径仍为实际输入值。
- 开启性能模式、清理残留、日志提示、截图及渲染预览使用 Fluent 弹窗。清理默认保留，回车或 Esc 都不会直接删除。
- 资源占用和导出范围警告使用布局内的 InfoBar，tone="warning"。
- 说明文档、步骤命令和任务日志使用只读 CodeEdit，可选择、复制、显示行号。
- 文本框与编辑器的右键菜单使用 ActionMenu；任务日志菜单还可导出整次任务的完整日志。
- 普通按钮与主按钮按 Button / AccentButton 区分。普通模式强调色为 #2B579A，性能模式为 #D13438；保留渐变开屏、导出窗口及灵动岛动画。
- 首次向导右侧截图由实际新版界面重新生成。

完整日志操作见「full-task-log.md」。本次验证覆盖控件交互、完整日志与打包启动；未重新执行完整地图导出。

参考：https://fluentpy.mcxmcl.cn/#/dialogs

## 原生控件约束

删除自绘回退和所有控件兼容子类。应用配置函数只创建 FluentPy 提供的原生实例，`type(widget)` 与库内类型相同；不会继承后重画按钮、卡片、输入框、数字框、弹窗或进度条。
地图选择使用 ToggleButton，说明目录使用 TableWidget；导出窗口和顶部进度条使用 CardWidget 与 ProgressBar。原有窗口缩放、分裂、截图过渡和图片背景作为窗口动画保留。
Qt 仅用于 FluentPy 没有对应组件的布局、容器、标签、图片、文件选择对话框以及事件和数据类型；滚动容器配套 FluentScrollBar。自动测试检查这些约束，禁止重新创建原版 Qt 替代控件。
