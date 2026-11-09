# 2026-11-03 NullRHI 批量导入修复

Retrowar 的 UE 对象放置阶段出现 `Trying to resize TArray to an invalid size of 2147719392`。崩溃记录未标记为 OOM；该数字是数组元素数量，并非字节数。

本机 UE 5.4.4 的游戏线程调用栈与二进制反汇编对应到视口 Hit Proxy 更新、`ReadSurfaceCommand` 和 `FNullDynamicRHI::RHIReadSurfaceData`。后者对输出颜色数组调用 `AddZeroed(Rect.Width() * Rect.Height())`。反复通过编辑器视口放置对象会让这条无渲染路径上的缓存不断追加颜色项，最终超过 TArray 的 int32 容量。单独关闭网格距离场后仍能复现，因此距离场不是这次崩溃的直接原因。

模型、相机、辅助对象、源灯光、后处理及源环境对象现在直接在编辑器世界中创建，不再经过 `EditorActorSubsystem.spawn_actor_from_class` 的视口放置与拾取流程。UE 5.4 没有为两个 Blueprint 内部生成函数提供普通 Python 方法，因此使用官方 `Object.call_method` 反射入口调用 `BeginDeferredActorSpawnFromClass` / `FinishSpawningActor`，保留完整源变换及后续标签、父子关系、材质与隐藏状态设置；创建失败不会退回有问题的视口流程。

同时通过进程启动参数 `-ini:Engine:` 在 NullRHI 导入时临时关闭距离场、动态 GI 和反射的渲染准备，避免无渲染导入阶段的额外构建开销。导入及主关卡组装脚本会检查这些启动参数是否生效。界面给出的手动命令使用相同参数。用户工程的 `DefaultEngine.ini` 及正常编辑器/Lumen 设置保持原值。

本修复针对 UE 批量导入。已经生成的模型和贴图可继续用于重跑验证；普通导出按钮仍会创建一次新任务。

Retrowar 原失败分块已在 UE 5.4.4 实际重跑：4,553 个对象全部放置完成，4,424 条父子关系阶段记录全部完成，灯光和碰撞报告均为 complete，关卡保存成功，进程正常退出；耗时约 126 秒。原工程配置文件的 SHA256 保持不变。验证复用了已导入的模型、贴图和材质，没有重新提取整张地图，也未据此宣称其余 5 个分块和最终主关卡已导出完成。

随后用独立 UE 进程重新打开已保存关卡，核对 4,553 个对象的覆盖、位置、旋转、缩放及父子关系，另核对 4,424 个网格对象、5,108 个材质槽和隐藏辅助物可见性：全部通过，最大位置误差 0 厘米。
