"""把 dfmap 导出的地图导入 Unreal Engine 5.3.2（编辑器内 Python）。

用法一（推荐，UE 编辑器里）：
    1. 打开你的 UE 5.3.2 工程（C++ 或蓝图工程都行，空工程即可）
    2. 菜单 Tools → Execute Python Script… → 选本文件
    3. 弹出输入框里填导出目录（含 split\\ 和 scene.json 的那层）

用法二（命令行，无界面）：
    "C:\\Program Files\\Epic Games\\UE_5.3\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "D:\\MyUE53\\MyProject.uproject" -run=pythonscript ^
      -script="D:\\...\\ue_import_dfmap.py" -- ^
      --split "F:\\新建文件夹 (5)\\Mogadishu_20261101_0736" --dest /Game/AtlasMaps/Mogadishu

参数：
    --split <目录>      dfmap 导出目录（里面要有 split\\ 或 scene.glb）
    --dest  <包路径>    资源导入到哪，默认 /Game/AtlasMaps/<目录名>
    --level <名字>      生成的关卡名，默认 LV_<目录名>
    --limit <N>         只导前 N 个分块（先小样试跑）
    --no-level          只导资源，不建关卡
    --scale <倍数>      真机坐标不对时的整体缩放，默认 1（glTF→UE 会自动 ×100）
    --check             只做输入自检（不开引擎也能跑）

坐标：dfmap 的 scene.json 是 UE 厘米 Z-up，GLB 是 glTF 米 Y-up；
      UE 的 glTF 导入器会自动 ×100 并转回 Z-up，所以默认 scale=1。
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import time

ARGS = {}


# ----------------------------------------------------------------- 参数解析 --
def _raw_args() -> list:
    """取我们自己的参数。

    UE 的 PythonScriptCommandlet 不会把 `-- xxx` 塞进 sys.argv，得从
    `unreal.SystemLibrary.get_command_line()` 里切；编辑器里 exec 时则看 sys.argv。
    """
    argv = list(sys.argv)
    if "--" in argv:
        return argv[argv.index("--") + 1:]

    text = ""
    try:
        import unreal  # noqa: F401  只在引擎里存在
        text = unreal.SystemLibrary.get_command_line() or ""
    except Exception:                                        # noqa: BLE001
        text = ""

    if "--" in text:
        tail = text.split("--", 1)[1]
        try:
            return shlex.split(tail, posix=False)
        except Exception:                                    # noqa: BLE001
            return tail.split()
    return argv[1:]


def _glb_sid_to_mesh(split_dir: str) -> dict:
    """GLB 里 node 名是 DFI_<sourceId>、mesh 名是原始资产路径。
    同一份网格常被多个实例复用、却只导出一个 DFI_ 资产，
    所以先用它建 <sid> -> <网格短名>，缺 sid 时按网格名兜底。"""
    import glob as _glob
    import json as _json
    import os as _os
    import struct as _struct
    out = {}
    for path in _glob.glob(_os.path.join(split_dir, "*.glb")):
        try:
            with open(path, "rb") as fh:
                fh.read(12)
                clen, _ctype = _struct.unpack("<II", fh.read(8))
                doc = _json.loads(fh.read(clen).decode("utf-8"))
        except Exception:                                     # noqa: BLE001
            continue
        meshes = doc.get("meshes") or []
        for node in doc.get("nodes") or []:
            name = str(node.get("name") or "")
            if not name.startswith("DFI_"):
                continue
            idx = node.get("mesh")
            if idx is None or idx >= len(meshes):
                continue
            ref = str(meshes[idx].get("name") or "")
            short = ref.split(".")[-1]
            if short:
                out[name[4:].lower()] = short.lower()
    return out


def parse_args() -> dict:
    argv = _raw_args()

    out = {"split": "", "dest": "", "level": "", "limit": 0,
           "no_level": False, "scale": 1.0, "check": False, "use_scene": False,
           "scene_glb": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--split" and i + 1 < len(argv):
            out["split"] = argv[i + 1]; i += 2; continue
        if a == "--dest" and i + 1 < len(argv):
            out["dest"] = argv[i + 1]; i += 2; continue
        if a == "--level" and i + 1 < len(argv):
            out["level"] = argv[i + 1]; i += 2; continue
        if a == "--limit" and i + 1 < len(argv):
            out["limit"] = int(argv[i + 1]); i += 2; continue
        if a == "--scale" and i + 1 < len(argv):
            out["scale"] = float(argv[i + 1]); i += 2; continue
        if a == "--no-level":
            out["no_level"] = True; i += 1; continue
        if a == "--check":
            out["check"] = True; i += 1; continue
        if a == "--use-scene-json":
            out["use_scene"] = True; i += 1; continue
        if a == "--with-scene-glb":
            out["scene_glb"] = True; i += 1; continue
        i += 1
    return out


# ------------------------------------------------------------------ 输入自检 --
def check_input(split_dir: str) -> dict:
    """不依赖引擎的自检：目录结构、manifest、glTF 版本、坐标范围。"""
    import struct

    info = {"ok": False, "glb": [], "manifest": None, "scene": None, "notes": []}
    if not split_dir or not os.path.isdir(split_dir):
        info["notes"].append(f"目录不存在：{split_dir!r}")
        return info

    sub = os.path.join(split_dir, "split")
    glb_dir = sub if os.path.isdir(sub) else split_dir
    glbs = sorted(f for f in os.listdir(glb_dir) if f.lower().endswith(".glb"))
    info["glb"] = [os.path.join(glb_dir, f) for f in glbs]
    if not glbs:
        info["notes"].append("没找到任何 .glb")

    man = os.path.join(sub, "manifest.json")
    if os.path.isfile(man):
        try:
            info["manifest"] = json.load(open(man, encoding="utf-8"))
        except Exception as exc:                              # noqa: BLE001
            info["notes"].append(f"manifest.json 读不动：{exc}")

    scn = os.path.join(split_dir, "scene.json")
    if os.path.isfile(scn):
        try:
            info["scene"] = json.load(open(scn, encoding="utf-8"))
            info["notes"].append(f"scene.json 实例数 {len(info['scene'].get('instances', []))}，"
                                 f"坐标系 {info['scene'].get('coordinateSystem')}")
        except Exception as exc:                              # noqa: BLE001
            info["notes"].append(f"scene.json 读不动：{exc}")

    if glbs:
        path = info["glb"][0]
        try:
            with open(path, "rb") as f:
                magic, ver, _size = struct.unpack("<III", f.read(12))
                clen, _ctype = struct.unpack("<II", f.read(8))
                js = json.loads(f.read(clen).decode("utf-8"))
            ok = magic == 0x46546C67 and ver == 2
            info["notes"].append(
                f"首个 GLB：{os.path.basename(path)} · glTF {js['asset']['version']} · "
                f"nodes {len(js.get('nodes', []))} meshes {len(js.get('meshes', []))} "
                f"materials {len(js.get('materials', []))} images {len(js.get('images', []))}")
            ext = js.get("extensionsRequired")
            if ext:
                info["notes"].append(f"⚠ 需要扩展 {ext}（UE 5.3 可能不支持）")
            info["ok"] = ok
        except Exception as exc:                              # noqa: BLE001
            info["notes"].append(f"GLB 头解析失败：{exc}")

    return info


# -------------------------------------------------------------------- 主流程 --
def _headless() -> bool:
    """-run=pythonscript（命令行）模式下没有编辑器世界，建关卡会崩。"""
    try:
        import unreal
        cmd = (unreal.SystemLibrary.get_command_line() or "").lower()
    except Exception:                                         # noqa: BLE001
        return True
    return "-run=pythonscript" in cmd or "-unattended" in cmd


def run_in_ue(args: dict, info: dict) -> int:
    import unreal                                # noqa: PLC0415

    split_dir = os.path.abspath(args["split"])
    name = os.path.basename(split_dir.rstrip("\\/")) or "AtlasMap"
    dest = args["dest"] or f"/Game/AtlasMaps/{name}"
    level_name = args["level"] or f"LV_{name}"
    scale = float(args["scale"])

    glb_dir = os.path.join(split_dir, "split")
    if not os.path.isdir(glb_dir):
        glb_dir = split_dir
    glbs = sorted(f for f in os.listdir(glb_dir) if f.lower().endswith(".glb"))
    if args.get("scene_glb"):
        # scene.glb 就在导出目录里；备份写法兼容「split 子目录传进来」
        cand = [os.path.join(split_dir, "scene.glb"),
                os.path.join(os.path.dirname(split_dir.rstrip("\/")), "scene.glb")]
        big = next((c for c in cand if os.path.isfile(c)), cand[0])
        if os.path.isfile(big):
            glbs.append(big)
            unreal.log(f"[atlas] 追加整图 scene.glb：{big}")
        else:
            unreal.log_warning(f"[atlas] 没找到 scene.glb：{big}")
    if args["limit"]:
        glbs = glbs[: int(args["limit"])]
    if not glbs:
        unreal.log_error(f"[atlas] {glb_dir} 里没有 .glb")
        return 1

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    t0 = time.time()
    imported = []
    for idx, fname in enumerate(glbs, 1):
        src = os.path.join(glb_dir, fname)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", src)
        task.set_editor_property("destination_path", dest)
        task.set_editor_property("destination_name", "")
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", True)
        try:
            tools.import_asset_tasks([task])
            got = list(task.get_editor_property("imported_object_paths") or [])
            imported.extend(got)
            unreal.log(f"[atlas] {idx}/{len(glbs)} {fname} -> {len(got)} 个资源")
        except Exception as exc:                              # noqa: BLE001
            unreal.log_error(f"[atlas] {fname} 导入失败：{exc}")

    unreal.log(f"[atlas] import done: {len(imported)} assets in {time.time() - t0:.1f}s")
    if args["no_level"]:
        return 0
    if _headless():
        unreal.log("[atlas] headless mode: assets only. Open the project in the editor "
                   "and run this script again (window fills the export dir) to build the level.")
        return 0

    # ---- 建关卡（已存在就直接打开，避免 “an asset already exists”）----
    level_path = f"{dest}/{level_name}"
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        exists = unreal.EditorAssetLibrary.does_asset_exist(level_path)
        if exists:
            les.load_level(level_path)
            unreal.log(f"[atlas] 复用已有关卡 {level_path}")
        else:
            les.new_level(level_path)
    except Exception as exc:                                  # noqa: BLE001
        unreal.log_warning(f"[atlas] 建关卡失败（继续用当前关卡）：{exc}")

    meshes = []
    by_name = {}
    by_sid = {}
    by_unreal = {}
    sid_mesh = _glb_sid_to_mesh(split_dir)
    for path in imported:
        asset = unreal.load_asset(path)
        if isinstance(asset, unreal.StaticMesh):
            meshes.append(asset)
            name = asset.get_name()
            by_name[name.lower()] = asset
            low = name.lower()
            if low.startswith("dfi_"):
                key = low[4:]
                by_sid[key] = asset
                # 同名重复导入时 UE 会自动加 _1/_2 后缀，取前 24 位做键兜底
                if len(key) > 24:
                    by_sid.setdefault(key[:24], asset)
                unreal_short = sid_mesh.get(low[4:])
                if unreal_short:
                    by_unreal.setdefault(unreal_short, asset)
    unreal.log(f"[atlas] StaticMesh {len(meshes)} 个，开始摆放到关卡")

    actors = []
    if args["use_scene"]:
        # 严格按 scene.json 的 matrixUE（UE 厘米、Z-up、列主序）摆放，
        # 这时 GLB 自带的节点矩阵会被忽略，坐标和游戏里一致
        scn = info.get("scene") or {}
        placed = missing = 0
        for inst in scn.get("instances", []):
            meta = inst.get("dfmap") or {}
            sid = str(meta.get("sourceId") or "").lower()
            if sid.startswith("dfi_"):          # scene.json 里带前缀，资产表里的键不带
                sid = sid[4:]
            mesh = by_sid.get(sid) if sid else None
            mesh_name = str(inst.get("mesh", "")).split(".")[-1]
            if mesh is None:
                mesh = by_unreal.get(mesh_name.lower())
            if mesh is None:
                mesh = by_name.get(mesh_name.lower())
            if mesh is None and mesh_name:
                # 长节点名被 UE 截断时，用「资产名里含网格名」兜底
                low_mesh = mesh_name.lower()
                for key, val in by_name.items():
                    if low_mesh in key:
                        mesh = val
                        break
            if mesh is None:
                if missing < 5:
                    unreal.log_warning(
                        f"[atlas] 缺网格 sid={sid or '-'} mesh={str(inst.get('mesh','')).split('.')[-1]}")
                missing += 1
                continue
            try:
                l = inst.get("loc") or [0, 0, 0]
                r = inst.get("rot") or [0, 0, 0]
                sc = inst.get("scale") or [1, 1, 1]
                loc = unreal.Vector(float(l[0]), float(l[1]), float(l[2]))
                rot = unreal.Rotator(float(r[0]), float(r[1]), float(r[2]))
                actor = unreal.EditorLevelLibrary.spawn_actor_from_object(mesh, loc, rot)
                actor.set_actor_scale3d(unreal.Vector(
                    float(sc[0]) * scale, float(sc[1]) * scale, float(sc[2]) * scale))
                actors.append(actor)
                placed += 1
            except Exception as exc:                          # noqa: BLE001
                if placed + missing < 20:
                    unreal.log_warning(f"[atlas] 摆放失败：{exc}")
                missing += 1
        unreal.log(f"[atlas] 按 scene.json 摆放：成功 {placed}，跳过 {missing}")
    else:
        for mesh in meshes:
            try:
                actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
                    mesh, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
                if scale != 1.0:
                    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
                actors.append(actor)
            except Exception as exc:                          # noqa: BLE001
                unreal.log_error(f"[atlas] 摆放 {mesh.get_name()} 失败：{exc}")

    # ---- 验收：算整体包围盒，看坐标是不是真的对 ----
    try:
        lo = [1e18, 1e18, 1e18]
        hi = [-1e18, -1e18, -1e18]
        for mesh in meshes:
            b = mesh.get_bounding_box()
            for corner in (b.min, b.max):
                vals = (corner.x * scale, corner.y * scale, corner.z * scale)
                for k, v in enumerate(vals):
                    lo[k] = min(lo[k], v)
                    hi[k] = max(hi[k], v)
        unreal.log(f"[atlas] 包围盒 min={lo} max={hi} "
                   f"尺寸=({hi[0]-lo[0]:.0f}, {hi[1]-lo[1]:.0f}, {hi[2]-lo[2]:.0f}) cm")
        if max(hi[0] - lo[0], hi[1] - lo[1]) < 500:
            unreal.log_warning("[atlas] 整张图不到 5 米 —— 说明没按世界坐标摆放，"
                               "加 --scale 100 再试，或者看文档里「用 scene.json 摆放」那一节")
    except Exception as exc:                                  # noqa: BLE001
        unreal.log_warning(f"[atlas] 包围盒算不出来：{exc}")

    try:
        les.save_current_level()
    except Exception:                                         # noqa: BLE001
        unreal.EditorLevelLibrary.save_current_level()

    unreal.log(f"[atlas] 完成：{len(actors)} 个 Actor，关卡 {dest}/{level_name}，"
               f"总用时 {time.time() - t0:.1f}s")
    return 0


def main() -> int:
    args = parse_args()

    # 没给 --split 时，弹个输入框（编辑器里跑的时候方便）
    if not args["split"]:
        try:
            import unreal                        # noqa: PLC0415
            text = unreal.EditorDialog.show_string_dialog(
                "dfmap 导入", "dfmap 导出目录（含 split\\ 与 scene.json）", "")
            args["split"] = str(text or "")
        except Exception:                                     # noqa: BLE001
            pass

    info = check_input(args["split"])
    ARGS.update(args)
    print("[atlas] 输入自检：")
    for note in info["notes"]:
        print("   ", note)

    if args["check"]:
        return 0 if info["ok"] else 2
    if not info["ok"]:
        print("[atlas] 自检没过，先修目录再来")
        return 2

    try:
        in_ue = True
        import unreal          # noqa: F401,PLC0415
    except Exception:                                         # noqa: BLE001
        in_ue = False
    if not in_ue:
        print("[atlas] 当前不在 UE 编辑器 Python 里，只做了自检。")
        print("        请按文件头注释里的两种方式之一，在 UE 5.3.2 里跑它。")
        return 0

    return run_in_ue(args, info)


if __name__ == "__main__":
    sys.exit(main())
