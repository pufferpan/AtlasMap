"""把视口对准关卡里的所有 StaticMeshActor，并高分辨率截图。仅编辑器 GUI 可用。"""
import glob
import os

import unreal

LEVEL = "/Game/AtlasMaps/CollectionRoomFBX/LV_CollectionRoom_FBX"
FILE = "map_preview.png"


def main() -> int:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
        unreal.log(f"[preview] 打开 {LEVEL}")

    ue = unreal.EditorLevelLibrary
    actors = [a for a in ue.get_all_level_actors() if isinstance(a, unreal.StaticMeshActor)]
    # 地图离原点十几万厘米（导出报告里的 world bounds），直接用已知中心框住，
    # 比在 Python 里算包围盒（`get_actor_bounds` 的返回类型在 5.3 里不好解包）稳。
    cx, cy, cz, span = 161188.0, 2207.0, -57.0, 16744.0
    unreal.log(f"[preview] {len(actors)} 个 Actor，相机对准 ({cx:.0f},{cy:.0f},{cz:.0f}) 跨度={span:.0f}cm")
    ue.set_level_viewport_camera_info(
        unreal.Vector(cx - span * 0.95, cy - span * 0.95, cz + span * 0.75),
        unreal.Rotator(-30, 45, 0))
    try:
        unreal.AutomationLibrary.take_high_res_screenshot(1600, 900, FILE)
        unreal.log(f"[preview] 截图 {FILE} -> {unreal.Paths.project_saved_dir()}Screenshots/Windows/")
    except Exception as exc:                                 # noqa: BLE001
        unreal.log_warning(f"[preview] 截图失败：{exc}")
    return 0


if __name__ == "__main__":
    main()
