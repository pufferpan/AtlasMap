"""一次性把官方 7 阶段（textures→meshes→masters→instances→bindings→actors→parents）跑完。

用法（UE 编辑器里，Output Log 的 Cmd 下拉切到 Python）：
    exec(compile(open(r'<仓库>\scripts\official\ue_stage_runner.py',
                      encoding='utf-8').read(), 'ue_stage_runner.py', 'exec'))

前置：
    1) 先按 `ue_preflight.py` 自检通过；
    2) 目标关卡已经新建并保存（本脚本不会 new_level，避免覆盖已有成果）；
    3) 环境变量 DEST/LEVEL 可覆盖 manifest 里的 ue_root / level。

它自己注册 slate post-tick 回调推进，脚本「立即返回」，不会卡住编辑器，
所以可以把这一行粘进 Python 控制台然后干别的事，进度看 Output Log 里的 [runner] 行，
或者 `import ue_iceland_bridge as b; b.status()`。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import unreal

SCRIPTS = Path(r"D:\AtlasMap-build\atlasmap\scripts\official")
ROOT = Path(os.environ.get("ATLASMAP_UE_ROOT") or r"D:\AtlasMap-build\atlasmap\work\ue_test\ue_transfer")
DEST = os.environ.get("ATLASMAP_UE_DEST")      # 比如 /Game/AtlasMaps/CollectionRoom54
LEVEL = os.environ.get("ATLASMAP_UE_LEVEL")    # 比如 /Game/AtlasMaps/CollectionRoom54/LV_Map

STAGES = ["textures", "meshes", "masters", "instances", "bindings", "actors", "parents"]

log = unreal.log
warn = unreal.log_warning


def _patch_manifest() -> None:
    """把 manifest 里的 ue_root / level 换成本次要用的，省得每次手改。"""
    mp = ROOT / "manifest.json"
    if not mp.exists():
        raise RuntimeError(f"找不到 {mp}：先把 Blender 的 transfer 包跑出来")
    data = json.loads(mp.read_text(encoding="utf-8-sig"))
    changed = False
    if DEST and data.get("ue_root") != DEST:
        data["ue_root"] = DEST
        changed = True
    if LEVEL and data.get("level") != LEVEL:
        data["level"] = LEVEL
        changed = True
    if changed:
        mp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[runner] manifest 已改写：ue_root={data.get('ue_root')} level={data.get('level')}")
    else:
        log(f"[runner] manifest 沿用：ue_root={data.get('ue_root')} level={data.get('level')}")


def main() -> None:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    _patch_manifest()

    import ue_iceland_bridge as bridge

    # 已经跑完的从下一段开始，方便失败后续跑
    done = os.environ.get("ATLASMAP_UE_SKIP", "").split(",")
    todo = [s for s in STAGES if s not in done and s != ""]
    if not todo:
        warn("[runner] 没有要跑的阶段（ATLASMAP_UE_SKIP 全吃掉了）")
        return

    state = {"i": 0, "started": 0.0, "handle": None, "stage": None}

    def tick(_dt: float) -> None:
        try:
            st = bridge.status()
            if state["stage"] is None:
                stage = todo[state["i"]]
                log(f"[runner] === 开始 {stage}（{state['i'] + 1}/{len(todo)}）===")
                bridge.start(stage)
                state["stage"] = stage
                state["started"] = time.time()
                return
            if st.get("running"):
                return
            if not st.get("complete"):
                warn(f"[runner] {state['stage']} 结束但 complete=False：{st}")
            log(f"[runner] === {state['stage']} 完成，用时 {time.time() - state['started']:.1f}s，cursor={st.get('cursor')}/{st.get('total')} ===")
            state["i"] += 1
            state["stage"] = None
            if state["i"] >= len(todo):
                log("[runner] 全部阶段完成 ✅")
                # 存盘：不存就把这次导入丢了
                try:
                    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
                    les.save_current_level()
                    log("[runner] 关卡已保存")
                except Exception as exc:                      # noqa: BLE001
                    warn(f"[runner] 存盘失败：{exc}")
                unreal.unregister_slate_post_tick_callback(state["handle"])
                state["handle"] = None
        except Exception as exc:                              # noqa: BLE001
            import traceback

            warn(f"[runner] 阶段 {state['stage']} 出错：{exc}")
            traceback.print_exc()
            if state["handle"]:
                unreal.unregister_slate_post_tick_callback(state["handle"])
                state["handle"] = None

    state["handle"] = unreal.register_slate_post_tick_callback(tick)
    log(f"[runner] 已启动，阶段队列：{todo}（进度看 Output Log）")


main()
