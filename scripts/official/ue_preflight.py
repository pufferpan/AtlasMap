"""UE 侧自检：引擎版本 / 工程 / 插件 / transfer 包 / 关卡 一次性核对。

两种跑法：
  A) 编辑器里（Output Log → Cmd → Python）粘：
     exec(compile(open(r'<仓库>\scripts\official\ue_preflight.py',
                       encoding='utf-8').read(), 'ue_preflight.py', 'exec'))
  B) 纯 Python（不 import unreal 也能跑完文件检查）：
     set ATLASMAP_UE_ROOT=...\\ue_transfer
     python scripts\\official\\ue_preflight.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ATLASMAP_UE_ROOT") or r"D:\AtlasMap-build\atlasmap\work\ue_test\ue_transfer")
SCRIPTS = Path(os.environ.get("ATLASMAP_UE_SCRIPTS") or r"D:\AtlasMap-build\atlasmap\scripts\official")
NEED = ["manifest.json", "material_plan.json", "material_instance_plan.json"]

ok: list[str] = []
bad: list[str] = []
warn: list[str] = []


def chk(cond: bool, good: str, badmsg: str) -> bool:
    (ok if cond else bad).append(good if cond else badmsg)
    return cond


# ---------- 文件侧 ----------
chk(ROOT.is_dir(), f"transfer 根目录存在：{ROOT}", f"缺 transfer 根目录：{ROOT}")
for name in NEED:
    p = ROOT / name
    chk(p.is_file(), f"{name}（{p.stat().st_size // 1024} KB）" if p.is_file() else "", f"缺 {name}")
if (ROOT / "manifest.json").is_file():
    m = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8-sig"))
    meshes = m.get("meshes") or []
    mats = m.get("materials") or []
    imgs = m.get("images") or []
    ok.append(f"manifest：网格资产 {len(meshes)}、材质 {len(mats)}、图像 {len(imgs)}")
    ok.append(f"目标资产根 ue_root={m.get('ue_root')}  level={m.get('level')}")
    if not imgs:
        warn.append("manifest 里 images=0：说明 Blender 场景没带贴图节点（导出时没加 --materials），UE 里只会是灰模")
    fbx = list((ROOT / "meshes").glob("*.fbx")) if (ROOT / "meshes").is_dir() else []
    chk(bool(fbx), f"meshes/*.fbx 共 {len(fbx)} 个", "meshes/ 下没有 fbx")

chk(SCRIPTS.is_dir(), f"官方脚本目录存在：{SCRIPTS}", f"缺脚本目录：{SCRIPTS}")
for s in ("ue_iceland_bridge.py", "ue_iceland_source_lighting.py", "ue_rebuild_iceland_water.py",
          "ue_rebuild_iceland_collision.py"):
    chk((SCRIPTS / s).is_file(), f"脚本 {s}", f"缺脚本 {s}")

# ---------- 引擎侧（只有在 UE 里跑才检查） ----------
try:
    import unreal  # noqa: F401
except Exception:                                            # noqa: BLE001
    warn.append("当前不是 UE 的 Python（没 import 到 unreal），引擎/插件/关卡检查已跳过；"
                "进编辑器后再跑一次这个脚本")
else:
    ver = unreal.SystemLibrary.get_engine_version()
    ok.append(f"引擎版本：{ver}")
    if not ver.startswith("5.4"):
        warn.append(f"官方脚本按 5.4 写（5.4.4 实测），当前 {ver}：bridge 里部分 API 可能要对不上")

    # Python 插件
    plugins = unreal.PythonScriptLibrary  # 存在即插件已启用
    ok.append(f"PythonScriptPlugin 可用：{plugins.__name__ if hasattr(plugins, '__name__') else 'ok'}")

    # 当前关卡
    world = unreal.EditorLevelLibrary.get_editor_world()
    cur = world.get_path_name().split(".")[0]
    ok.append(f"当前关卡：{cur}")
    manifest_level = ""
    if (ROOT / "manifest.json").is_file():
        manifest_level = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8-sig")).get("level", "")
    if manifest_level and cur != manifest_level:
        warn.append(f"当前关卡 {cur} ≠ manifest 里的 {manifest_level}：bridge 的 actors/parents 阶段会写错地方")

    # bridge 能不能 import
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import ue_iceland_bridge as bridge
        ok.append(f"ue_iceland_bridge 可导入，DEST={bridge.DEST}")
    except Exception as exc:                                 # noqa: BLE001
        bad.append(f"ue_iceland_bridge 导入失败：{exc}")

# ---------- 输出 ----------
print("\n=== UE 准备情况 ===")
for line in ok:
    print("  [OK]  " + line)
for line in warn:
    print("  [!!]  " + line)
for line in bad:
    print("  [NO]  " + line)
print(f"\n结论：{len(ok)} 项通过，{len(warn)} 项提醒，{len(bad)} 项阻塞\n")
if bad:
    print("先把 [NO] 的补上再跑 ue_stage_runner.py。")
