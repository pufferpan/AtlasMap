"""Verify that NullRHI imports cannot build renderer-only distance fields."""


def check_headless_renderer(unreal):
    system = unreal.SystemLibrary
    null_rhi = '-nullrhi' in system.get_command_line().lower().split()
    values = {name: system.get_console_variable_int_value(name) for name in (
        'r.GenerateMeshDistanceFields', 'r.DynamicGlobalIlluminationMethod', 'r.ReflectionMethod')}
    if null_rhi and any(values.values()):
        raise RuntimeError('NullRHI 导入的渲染启动参数未生效；请使用本版生成的 -ini:Engine 参数启动，'
                           '避免在无渲染导入阶段构建距离场等渲染资源。当前值：'+str(values))
    unreal.log('[headless] renderer startup: null_rhi='+str(null_rhi)+' '+str(values))
    return dict(null_rhi=null_rhi, settings=values)
