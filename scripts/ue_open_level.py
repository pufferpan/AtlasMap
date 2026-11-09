"""打开已导入的关卡、把视口对准整关、存一张截图。仅编辑器 GUI 可用。"""
import unreal

LEVEL = "/Game/AtlasMaps/CollectionRoom/LV_CollectionRoom"
OUT = "D:/AtlasMap-build/atlasmap/work/ue_level.png"


def main() -> int:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
        unreal.log(f"[ue-open] 打开 {LEVEL}")
    else:
        unreal.log_warning(f"[ue-open] 找不到 {LEVEL}")

    actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
              if isinstance(a, unreal.StaticMeshActor)]
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for a in actors:
        org = a.get_actor_location()
        vals = (org.x, org.y, org.z)
        for k, v in enumerate(vals):
            lo[k] = min(lo[k], v)
            hi[k] = max(hi[k], v)
    if actors:
        cx, cy, cz = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2)
        span = max(hi[0] - lo[0], hi[1] - lo[1], 1000.0)
        unreal.log(f"[ue-open] {len(actors)} 个 StaticMeshActor，中心=({cx:.0f},{cy:.0f},{cz:.0f}) 跨度={span:.0f}cm")
        ue = unreal.EditorLevelLibrary
        ue.editor_set_game_view(False)
        ue.set_level_viewport_camera_info(
            unreal.Vector(cx - span * 1.1, cy - span * 1.1, cz + span * 0.9),
            unreal.Rotator(-32, 45, 0))
    else:
        unreal.log_warning("[ue-open] 关卡里没有 StaticMeshActor")

    unreal.AutomationLibrary.take_high_res_screenshot(1600, 900, OUT, comparison_tolerance=-1)
    unreal.log(f"[ue-open] 截图 -> {OUT}")
    return 0


if __name__ == "__main__":
    main()
