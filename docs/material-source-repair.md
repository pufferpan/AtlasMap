# 材质引用兼容修复

版本：2026-11-02.material-source-fix

庄园（BombDefusal_Mansion）的两次失败日志均包含：
`KeyNotFoundException: There is no game file with the path "lambert1"`。
这是源渲染信息读取阶段把 glTF 中的默认材质名称当成游戏包路径读取造成的。

共用修复覆盖普通导出和多进程导出：

- 默认材质名称不访问游戏资源提供器，保留 glTF 材质与原网格材质槽。
- 缺失源材质时保留 glTF 着色；缺失父材质时保留已读取的子材质参数。
- 检测循环、过长继承链和无效父引用，记录明确的兼容状态。
- `materials.json` 中保留每个材质的 `source_status` 和 `issues`，
  `material-report.json` 汇总降级信息，实时日志也显示对应引用。
- 只把缺失的可选原生材质引用视为兼容降级。磁盘错误、内存不足、损坏 JSON
  和必需关卡读取错误继续向上传递。

原始固定版本 导出器保持不变。缺失游戏资源的真实贴图或着色逻辑无法凭空恢复；
兼容处理用于保留已有模型与材质并完成导出。

原生回归检查：
`dotnet run --project tools/material_source_tests/material-source-tests.csproj -c Release`

验证结果：

- 117 项 Python 测试、19 项原生材质回归检查通过。
- 最终发布辅助程序通过占位名称、缺失游戏材质、空 extras、空材质路径检查。
- 庄园整图六分块的全部 17 个步骤通过，包括 Blender、UE 导入、灯光、碰撞、
  主关卡组装和保存后的覆盖校验。共 4,809 个对象、7,477 个材质槽、141 个源灯光。
- 这次的 1,040 条分块材质记录中，1,039 条正常解析，1 条 `lambert1` 明确记录为占位兼容。
- 验证报告：`E:/AtlasMap-validation/material-source-repair/validation.json`，
  运行编号 `59bffee785d048c69229b06afae188b0`。

完整导出验证不代表游戏专用渲染算法全部还原。庄园仍按既有兼容策略记录了
23 个尚未支持映射的盒形反射捕获；原始资源保留在导出数据中。
