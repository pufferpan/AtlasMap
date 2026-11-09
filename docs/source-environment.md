# 原始环境反射、天空与玻璃

新版从游戏导出的 LocalReflectionGroupBake 载荷中恢复 HDR 反射立方体，按原组件 LocalReflectionGroupBakeBuildID 逐个绑定，保留组件位置及影响半径。不会按名称 `NewReflectionComponent` 匹配，因为多个探针重名。不同烘焙包中复用 GUID 的记录也按原组件引用的包区分。

CollectionRoom验证样本包含 21 条记录，全部与 21 个组件对应。已识别的载荷是 BC6H 六面颜色、完整 mip 链及独立 BC4 数据。直接调用指定工具链的 BC6H 块解码器取得半浮点颜色，绕过会把 HDR 截到 8 位的 PNG 路径；以 RGBA16F DDS 导入原生 TextureCube，保留原始六面及全部 8 级 mip，转换为 DDS 要求的逐面排列。样本解码值最大为 65.5625，透明度为 1，保存、重开 UE 关卡后 21 个反射组件及 21 个有边界的环境光组件均通过检查。

原始载荷保持不变。已验证载荷的 SHA-256：`9f586bd959e5376ce51ea66d7b8b2bd6bc69a4677852e4805ae9c534d82db007`。新的布局必须通过版本、维度、mip 字节数、有限值和文件结尾校验；不支持的记录写入 `reflection-cubemaps.json`，不会把任意二进制数据当成贴图。解码记录保留原始平均亮度、亮度和未解释的浮点系数。

游戏兼容模式使用源平均亮度与解码立方体球面积加权亮度之比映射原生强度，并对相交的环境光体做叠加补偿。局部环境光是标准 UE 的有边界 Ambient Cubemap 映射；源游戏的自定义 PRT、遮蔽算法以及 36 个原始浮点数的完整语义尚未重建。该映射不能声称与游戏逐像素一致。严格源模式仍恢复原始反射，不添加这部分兼容环境光。

天空导出沿关卡、天空/天气对象、材质和立方体引用追踪资源。原始 TextureCube 和能够确认投影的单个天空全景贴图可恢复为背景，天空光优先使用源立方体及原始参数。多个天气天空没有确定活动状态时会保留候选并报告，避免随意选图。RGBM 编码范围未知、布局未知的资源同样报告为不支持。

CollectionRoom资源目录 `SkyCube` 中的 `T_Miniworld_CollectionRoom_Scene01` 经检查是房间平面预览图，父材质为 `M_Billboard`，不是天空全景。它保留在资源目录中，但明确禁止作为天空或环境光；本次CollectionRoom数据没有唯一可确认的独立天空盒。

玻璃区分普通薄玻璃和磨砂玻璃。薄玻璃保留颜色透射、折射偏置，避免灰白漫反射覆盖；磨砂玻璃使用源 BlurRoughness、Distance、Opacity 构造原生 SceneColor 多点背景模糊，在景深前合成。源游戏的水滴、噪声和时域滤波完整着色程序仍属于兼容近似。AlphaComposite、Additive 不再一律改成普通透明混合。旧材质缓存版本已更新，旧导出需要用新版重新导入。

依据：[Epic 薄透明材质](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-transparency-in-unreal-engine-materials)、[UE 5.4 透明渲染通道](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialTranslucencyPass?application_version=5.4)、[CUE4Parse BC6H 解码接口](https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse-Conversion/Textures/BC/BC6H.cs)。原始二进制格式未被 REA 的 open_binary 支持，因此采用已保留载荷、字节边界校验、组件 GUID 全覆盖及原生 UE 导入检查互相验证，未对游戏运行进程做注入或修改。
