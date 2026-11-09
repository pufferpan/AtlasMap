# 2026-11-01.source-lighting

首次向导采用模型查看器同款的 #2B579A 蓝色、三行软件截图、逐行动画及固定画布展开。配置写入地图导出器自己的 settings.json，支持设置页重看。

地图导出使用 程序目录 runtime/ 下的 map-export.exe、dfmap.dll 及运行库，发布目录 runtime/reference-exporter.json 记录逐文件 SHA256。导出同时读取 BuildMaps_HD 与 Maps 对应地图目录，保留 Lighting 层。

UE 灯光以 lights.json 为准：原始 UE 厘米坐标、Roll/Pitch/Yaw、线性 RGB、原始亮度、衰减、锥角、矩形尺寸、阴影。零亮度和同位置的多个灯实例均保留，重复导入会更新原灯而非叠加。默认仅恢复源灯；预览补光须在界面单独勾选。

「进 UE」完成地图导入后，点击「游戏光照渲染预览」。该步骤启动 UE 编辑器的真实 GPU 渲染，以原生材质、局部光、阴影、GI 和色调映射输出 render_preview.png；不会使用导入时的 -nullrhi。可选择自动视角、全图俯视、光照区域，结果与日志放在所选地图导出目录。失败或地图身份不匹配会阻止显示旧结果。

验证：21 项回归通过；UE 5.4.4 测试工程验证七个实例，覆盖 Point、Spot、Rect、Directional、Sky、Fog 六类，核对线性颜色、零值及原位更新，完成 1600×900 原生渲染。SkyLight 使用其独立的线性颜色 API，避免与普通灯的 sRGB 开关签名混用。真实 CollectionRoom 恢复 Point 1、Rect 68、Spot 60、Fog 1，130 条源记录全部通过，没有新增补光，完成室内预览。

精度边界：参考版 lights.json 不包含原游戏烘焙 lightmap、天空纹理、自定义天空着色器及 PRT/GI 数据；这些部分不能据此逐像素重建。Sky 使用场景捕获，参考导出器的缺省 5000 天光占位值转换为原生默认 1，Fog 使用原生默认参数，均写入 lighting_report.json 的 compatibility。渲染是 UE 原生还原预览，不能宣称与游戏画面完全一致。
