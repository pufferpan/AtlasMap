# 2026-11-02.game-lighting

「进 UE」增加默认开启的「游戏光照兼容」选项。它作用于导入后保存的关卡和原生渲染预览；关闭后使用原有源参数恢复路径。原始灯光、烘焙载荷与 `render_state.json` 不因兼容预设而更改。

补回源 `MaxDrawDistance`、`MaxDistanceFadeRange`，保持厘米单位与合法的 0；写入后独立读回，失败时不能生成成功报告。导入 27 个CollectionRoom源相机，保留位置、朝向、FOV 与实际提供的相机后处理覆盖；预览直接使用这些相机。

兼容模式限制游戏雾灯在原生 UE 中的散射贡献，并通过低优先级、无范围限制的后处理保留高光与阴影细节。默认预设让源后处理和源相机的显式设置优先；用户提供的 `game-lighting.json` 则优先于普通场景后处理。CollectionRoom的曝光预设是视觉兼容参数，不是从游戏自定义渲染器反推出的官方参数；其他地图不沿用CollectionRoom曝光。实际参数与原生读回值记录在 `lighting_report.json` 的 `game_profile`、`fog_compatibility` 和 `distance_fields` 中。

高级调校：在某张地图的导出目录放置 `game-lighting.json`，重新恢复灯光或预览后生效。例如：

```json
{"exposure_bias_ev": -1.0, "fog_only_scattering_cap": 0.02, "local_highlight_contrast": 0.8, "local_shadow_contrast": 0.9}
```

曝光范围为 -10 至 10，其余参数为 0 至 1；错误字段、非有限数值和越界值会报错。界面的「预览曝光补偿 EV」在兼容预设上追加偏移，只影响截图，不改写已保存关卡。

边界：游戏专用 PRT、预烘焙雾深度和 DarknessCorrection 等字段仍不能直接在标准 UE 执行。本模式用于减少泛白和亮斑、方便按游戏参考调校；没有同视角游戏截图的逐项比较时，不能据此宣称已与游戏画面基本匹配。

依据：[Epic 自动曝光与局部曝光说明](https://dev.epicgames.com/documentation/unreal-engine/auto-exposure-in-unreal-engine)、[Epic 体积雾说明](https://dev.epicgames.com/documentation/en-us/unreal-engine/volumetric-fog-in-unreal-engine)。
