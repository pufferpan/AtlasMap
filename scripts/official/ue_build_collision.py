"""给导入进来的静态场景批量补碰撞（通用版，不依赖 Iceland 源数据）。

用法：
    UnrealEditor-Cmd.exe "<proj>" -ExecutePythonScript="<本文件>" -unattended -nosplash
环境变量：
    ATLASMAP_UE_LEVEL   要处理的关卡，默认当前关卡
    ATLASMAP_UE_DEST    资产目录（默认从关卡路径推）
"""
from __future__ import annotations

import os
import json
from pathlib import Path

import unreal

LEVEL = os.environ.get("ATLASMAP_UE_LEVEL", "")
PROFILE = os.environ.get("ATLASMAP_UE_COLLISION_PROFILE", "BlockAll")


def _log(msg: str) -> None:
    unreal.log("[collision] " + str(msg))


def _ensure_level() -> None:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if LEVEL:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if world.get_path_name().split('.')[0] != LEVEL and not les.load_level(LEVEL):
            raise RuntimeError("Cannot load collision level: " + LEVEL)


def _fix_mesh(mesh: unreal.StaticMesh) -> bool:
    """把碰撞体设成「复杂碰撞当简单用」，这样玩家/射线能站在模型表面。"""
    ok = False
    try:
        body = mesh.get_editor_property("body_setup")
        if body:
            body.set_editor_property(
                "collision_trace_flag",
                unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
            )
            ok = True
    except Exception as exc:                                  # noqa: BLE001
        _log(f"设置 body_setup 失败 {mesh.get_name()}：{exc}")
    if not ok:
        try:
            mesh.set_editor_property(
                "collision_trace_flag",
                unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
            )
            ok = True
        except Exception as exc:                              # noqa: BLE001
            _log(f"设置 collision_trace_flag 失败 {mesh.get_name()}：{exc}")
    try:
        mesh.set_editor_property("collision_complexity",
                                 unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    except Exception:                                         # noqa: BLE001
        pass
    return ok


def main(save_asset=None, flush=None):
    _ensure_level()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()
    meshes: dict[str, unreal.StaticMesh] = {}
    comps = 0
    for actor in actors:
        try:
            comp = actor.get_editor_property("static_mesh_component")
        except Exception:                                     # noqa: BLE001
            comp = None
        if comp is None:
            continue
        mesh = comp.get_editor_property("static_mesh")
        if mesh is None:
            continue
        comps += 1
        key = mesh.get_path_name()
        if key not in meshes:
            meshes[key] = mesh
        try:
            comp.set_collision_profile_name(PROFILE)
        except Exception as exc:                              # noqa: BLE001
            _log(f"设置 profile 失败：{exc}")

    fixed = 0
    pending = []
    for mesh in meshes.values():
        if _fix_mesh(mesh):
            fixed += 1
        if save_asset:save_asset(mesh)
        else:pending.append(mesh)
    if pending and not unreal.EditorAssetLibrary.save_loaded_assets(pending, only_if_is_dirty=True):
        raise RuntimeError("Cannot save collision meshes")
    if flush:flush()

    _log(f"关卡 {LEVEL or '(当前)'}：Actor {len(actors)} 个，带网格组件 {comps} 个，唯一网格 {len(meshes)} 个，改好 {fixed} 个")
    saved = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    report = {"complete": bool(saved) and fixed == len(meshes), "level": LEVEL,
              "meshes": len(meshes), "fixed": fixed, "components": comps}
    root = os.environ.get("ATLASMAP_SOURCE_ROOT", "")
    if root:
        (Path(root) / "collision_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log(f"关卡已保存：{saved}")
    if not report["complete"]:raise RuntimeError("Collision setup incomplete: " + str(report))
    return report


if __name__ == "__main__":
    main()
