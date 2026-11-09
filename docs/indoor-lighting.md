# 室内光照修复

游戏兼容模式在 UE 启动前为目标工程启用 Lumen 全局光照、反射以及 Generate Mesh Distance Fields。此前导入命令强制关闭距离场，缺少屏幕外几何的遮蔽数据会破坏室内间接光和天空遮挡。现在普通导出、各个分块工程、主工程和渲染预览使用相同依赖。修改既有工程配置时保留无关字段，并在首次修改前保存 DefaultEngine.ini.atlasmap-backup。

兼容后处理体显式启用 Lumen，优先级低于游戏原有后处理区域；游戏原有曝光和局部色彩设置仍然优先。局部后处理组件显式绑定其 Box 边界，保留原始位移、旋转、缩放、模型边界中心、混合半径和权重。天空光恢复原有下半球遮蔽标记；源数据缺省时采用 UE 默认遮蔽，不再强制从下半球补光。

距离场的构建需要时间和额外缓存空间。已有工程须关闭并重新打开编辑器，使依赖生效；旧导出建议用新版重新导入。

游戏的自定义 PRT、烘焙光照和 DarknessCorrection 等专用着色逻辑无法直接加载到标准 UE。此修复恢复室内间接光所需的渲染依赖及局部设置，不代表已经与游戏截图逐像素匹配。

依赖说明：[Epic：Lumen 全局光照与反射](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine?application_version=5.4)。软件光线追踪依赖网格距离场；室内间接光和天空遮蔽需要正确的几何表示。
