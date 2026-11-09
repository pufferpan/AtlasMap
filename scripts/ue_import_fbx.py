"""把 Blender 转好的分块 FBX 导进 UE 5.3 并摆进一个关卡。

用法（编辑器 GUI 或命令行都行，命令行模式只导资源）：

    UnrealEditor.exe "<proj>" -ExecutePythonScript="<本脚本>" -- \
        --fbx "G:\...\fbx" --dest /Game/AtlasMaps/CollectionRoom/FBX \
        --level LV_CollectionRoom_FBX

几何在 FBX 里是「世界坐标烘焙」的（dfmap 侧用 transform_vertex_to_absolute 打开），
所以每个分块只要在原点放一个 Actor 就能落在正确位置。
"""
import glob
import os
import shlex
import time

import unreal


def _raw_args() -> list:
    line = ""
    try:
        line = unreal.SystemLibrary.get_command_line()
    except Exception:                                        # noqa: BLE001
        pass
    if "--" not in line:
        return []
    tail = line.split("--", 1)[1]
    try:
        return shlex.split(tail, posix=False)
    except Exception:                                        # noqa: BLE001
        return tail.split()


def parse_args() -> dict:
    argv = _raw_args()
    out = {"fbx": "", "dest": "/Game/AtlasMaps/FBX", "level": "", "materials": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--fbx" and i + 1 < len(argv):
            out["fbx"] = argv[i + 1].strip('"'); i += 2; continue
        if a == "--dest" and i + 1 < len(argv):
            out["dest"] = argv[i + 1].strip('"'); i += 2; continue
        if a == "--level" and i + 1 < len(argv):
            out["level"] = argv[i + 1].strip('"'); i += 2; continue
        if a == "--materials":
            out["materials"] = True; i += 1; continue
        i += 1
    return out


def fbx_options(with_materials: bool = False) -> "unreal.FbxImportUI":
    opt = unreal.FbxImportUI()
    opt.automated_import_should_detect_type = False
    opt.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    opt.import_as_skeletal = False
    # 默认只导几何：28 MB 那块带材质/贴图导入会让编辑器在 5.3 里崩掉，
    # 想要材质就加 --materials（小块图表没问题，大块图建议分多次跑）。
    opt.import_materials = with_materials
    opt.import_textures = with_materials
    data = opt.static_mesh_import_data
    for key, val in {
        "combine_meshes": True,
        "auto_generate_collision": False,
        "generate_lightmap_u_vs": False,
        "remove_degenerates": False,
        "convert_scene": False,
        "convert_scene_unit": False,
        "force_front_x_axis": False,
        # 关键：把节点变换烘进顶点，Actor 放原点就落在世界正确位置
        "transform_vertex_to_absolute": True,
        "reorder_material_to_fbx_order": True,
        "normal_import_method": unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS,
    }.items():
        try:
            data.set_editor_property(key, val)
        except Exception:                                    # noqa: BLE001
            pass
    return opt


def main() -> int:
    args = parse_args()
    src = args["fbx"]
    if not src or not os.path.isdir(src):
        unreal.log_error(f"[fbx] 找不到 FBX 目录：{src!r}")
        return 1
    files = sorted(glob.glob(os.path.join(src, "*.fbx")))
    if not files:
        unreal.log_error(f"[fbx] {src} 里没有 .fbx")
        return 1

    dest = args["dest"]
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    t0 = time.time()
    imported = []
    for idx, path in enumerate(files, 1):
        stem = os.path.splitext(os.path.basename(path))[0]
        task = unreal.AssetImportTask()
        task.filename = path
        task.destination_path = dest
        task.destination_name = stem
        task.automated = True
        task.replace_existing = True
        task.save = True
        task.options = fbx_options(bool(args.get("materials")))
        tools.import_asset_tasks([task])
        paths = list(task.imported_object_paths)
        imported.append((stem, paths))
        unreal.log(f"[fbx] {idx}/{len(files)} {stem} -> {len(paths)} 个资源")
    unreal.log(f"[fbx] import done: {sum(len(p) for _, p in imported)} assets in {time.time()-t0:.1f}s")

    level_name = args["level"] or "LV_FBX"
    level_path = f"{dest}/{level_name}"
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if unreal.EditorAssetLibrary.does_asset_exist(level_path):
            les.load_level(level_path)
        else:
            les.new_level(level_path)
    except Exception as exc:                                 # noqa: BLE001
        unreal.log_warning(f"[fbx] 建关卡失败：{exc}")

    ue = unreal.EditorLevelLibrary
    placed = 0
    for stem, paths in imported:
        for p in paths:
            asset = unreal.load_asset(p)
            if not isinstance(asset, unreal.StaticMesh):
                continue
            ue.spawn_actor_from_object(asset, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            placed += 1
    unreal.log(f"[fbx] 摆了 {placed} 个 Actor（世界坐标已烘进几何，位置=0）")

    # 关卡里本来没有灯，补一盏方向和天光，Lit 模式下才看得见
    try:
        sun = ue.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 20000),
                                       unreal.Rotator(-38, 35, 0))
        comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
        comp.set_intensity(6.0)
        sky = ue.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 20000),
                                        unreal.Rotator(0, 0, 0))
        sky_comp = sky.get_component_by_class(unreal.SkyLightComponent)
        sky_comp.set_intensity(1.2)
        sky_comp.set_editor_property("real_time_capture", True)
        unreal.log("[fbx] 补了 DirectionalLight + SkyLight")
    except Exception as exc:                                 # noqa: BLE001
        unreal.log_warning(f"[fbx] 加灯失败：{exc}")
    # 一定要存盘：new_level() 建的是内存里的关卡，不 save 退出编辑器就白摆了
    try:
        saved = unreal.EditorLevelLibrary.save_current_level()
        if not saved:
            les2 = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
            les2.save_current_level()
        unreal.log(f"[fbx] 关卡已保存：{level_path}")
    except Exception as exc:                                 # noqa: BLE001
        unreal.log_warning(f"[fbx] 保存关卡失败：{exc}")

    unreal.log(f"[fbx] 完成：{placed} 个 Actor，关卡 {level_path}，总用时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    main()
