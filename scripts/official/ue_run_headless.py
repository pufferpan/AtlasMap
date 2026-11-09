"""headless 版：一次 -ExecutePythonScript 就把 7 阶段同步跑完（不依赖 slate tick）。

用法（命令行，不用开 GUI）：
    UnrealEditor-Cmd.exe "<proj>" -ExecutePythonScript="<本文件>" -unattended -nosplash -nullrhi

环境变量：
    ATLASMAP_UE_ROOT   transfer 包目录（默认 work\\ue_test\\ue_transfer）
    ATLASMAP_UE_DEST   资产根（默认 /Game/AtlasMaps/Iceland54）
    ATLASMAP_UE_LEVEL  关卡（默认 <DEST>/LV_Map）
    ATLASMAP_UE_SKIP   逗号分隔，跳过已完成的阶段

为什么要自己调 _tick：bridge 靠 register_slate_post_tick_callback 推进，命令行模式下
没有 GUI 帧，回调永远不来；所以这里直接同步驱动它的状态机（每步 0.18s 预算）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

import unreal

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
from map_io import atomic_json
ROOT = Path(os.environ.get("ATLASMAP_UE_ROOT") or r"D:\AtlasMap-build\atlasmap\work\ue_test\ue_transfer")
def _asset_path(value: str) -> str:
    """Normalize shell-rewritten asset paths back to /Game/... ."""
    text = str(value or "").replace("\\", "/")
    index = text.find("/Game/")
    if index > 0:
        text = text[index:]
    return text.rstrip("/") or "/Game/AtlasMaps/Iceland54"


DEST = _asset_path(os.environ.get("ATLASMAP_UE_DEST") or "/Game/AtlasMaps/Iceland54")
LEVEL = _asset_path(os.environ.get("ATLASMAP_UE_LEVEL") or (DEST + "/LV_Map"))
SKIP = {s for s in os.environ.get("ATLASMAP_UE_SKIP", "").split(",") if s}

STAGES = ["textures", "meshes", "masters", "instances", "bindings", "actors", "parents"]
LOG = ROOT / "headless_run.log"
RUN_ID = os.environ.get("ATLASMAP_UE_RUN_ID", "")
RESULT = ROOT / "ue_import_result.json"

def _task_event(**data):
    if os.environ.get('ATLASMAP_UE_SHARD', ''):
        print('@ATLASMAP_TASK '+json.dumps(data,ensure_ascii=False),flush=True)


def _log(msg: str) -> None:
    unreal.log("[headless] " + msg)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def _patch_manifest() -> None:
    mp = ROOT / "manifest.json"
    data = json.loads(mp.read_text(encoding="utf-8-sig"))
    if data.get("ue_root") != DEST or data.get("level") != LEVEL:
        data["ue_root"] = DEST
        data["level"] = LEVEL
        atomic_json(mp,data)
    _log(f"manifest -> ue_root={data['ue_root']} level={data['level']}")


def _ensure_level() -> None:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    pkg = LEVEL.rsplit("/", 1)[0]
    name = LEVEL.rsplit("/", 1)[1]
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        if not les.load_level(LEVEL):raise RuntimeError("Cannot load level: " + LEVEL)
        _log(f"载入已有关卡 {LEVEL}")
        return
    ok = les.new_level(LEVEL)
    if not ok:raise RuntimeError("Cannot create level: " + LEVEL)
    _log(f"新建关卡 {LEVEL} -> {ok}")
    les.save_current_level()
    _log("空白关卡已保存")


def _drive(stage: str, bridge, start: int = 0) -> bool:
    t0 = time.time()
    counts_by_stage={name:len(rows) for name,(rows,_) in bridge.PHASES.items()}
    active=[name for name in STAGES if name not in SKIP]
    offset=sum(counts_by_stage[name] for name in active[:active.index(stage)])
    total_work=sum(counts_by_stage[name] for name in active)
    def task_progress(done,current=''):
        _task_event(event='progress',done=offset+done,total=total_work,unit='任务',
                    current=stage+' '+current,text=f'{stage} {done}/{counts_by_stage[stage]} · {current}')
    if stage in ("textures", "meshes") and os.environ.get("ATLASMAP_UE_BATCH_IMPORT", "1") == "1":
        def progress(done, total, stats):
            _log(f"{stage} {done}/{total} · 新增 {stats['imported']} · 复用 {stats['skipped']}")
            current=bridge.status().get('current','')
            task_progress(done,current)
        counts = bridge.run_import_batches(stage, start, progress)
        _log(f"{stage} 完成，用时 {time.time()-t0:.1f}s，{counts}")
        return True
    bridge.start(stage, start)
    last = 0.0
    last_task=0.0
    while True:
        st = bridge.status()
        if not st.get("running"):
            break
        bridge._tick(0.0)            # 同步推进一步（内部有 0.18s 预算）
        now = time.time()
        if now-last_task>.3:
            current=bridge.status()
            task_progress(current.get('cursor',0),current.get('current',''))
            last_task=now
        if now - last > 2.0:
            last = now
            _log(f"{stage} {st.get('cursor')}/{st.get('total')}")
    st = bridge.status()
    if st.get("error"):
        _log(f"{stage} 出错：{st['error'].splitlines()[-1]}")
        return False
    _log(f"{stage} 完成：{st.get('cursor')}/{st.get('total')}，用时 {time.time() - t0:.1f}s")
    task_progress(st.get('cursor',0),st.get('current',''))
    return True


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(RESULT,{"complete": False, "level": LEVEL, "run_id": RUN_ID})
    if LOG.exists():
        LOG.unlink()
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    _log(f"engine {unreal.SystemLibrary.get_engine_version()}")
    from ue_headless_renderer import check_headless_renderer
    renderer = check_headless_renderer(unreal)

    _patch_manifest()
    from map_lod import apply_manifest
    from map_io import io_path
    lod_source = io_path(os.environ.get('ATLASMAP_GLOBAL_SOURCE_ROOT') or os.environ['ATLASMAP_SOURCE_ROOT'])
    manifest_path = ROOT / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    lod_report = apply_manifest(manifest, json.loads((lod_source/'scene.json').read_text(encoding='utf-8-sig'))['instances'])
    atomic_json(manifest_path, manifest)
    atomic_json(ROOT/'lod_report.json', lod_report)
    _log(f"HLOD 显示规则：隐藏 {lod_report['suppressed']} 个已有精细模型的重复代理")
    if os.environ.get('ATLASMAP_UE_PARALLEL_MERGED') == '1':
        unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous([DEST], True)
        _log('已扫描并行进程合并的资源包')
    _ensure_level()

    # Defer native saves to bounded batches. UObject work stays on this thread.
    os.environ.setdefault("ATLASMAP_UE_BATCH_SAVE", "1")

    import importlib

    import ue_iceland_bridge as bridge

    importlib.reload(bridge)
    _task_event(event='assigned',work={'textures':len(bridge.MANIFEST['images']),'meshes':len(bridge.MANIFEST['meshes']),
                'objects':len(bridge.MANIFEST['objects']),'levels':len(bridge.MANIFEST.get('chunk',{}).get('source_levels',[]))},
                text=f"本 UE 地图块：{len(bridge.MANIFEST['objects'])} 对象 / {len(bridge.MANIFEST['images'])} 贴图 / {len(bridge.MANIFEST['meshes'])} 模型")
    import ue_asset_inputs
    workers = int(os.environ.get("ATLASMAP_UE_WORKERS", "8"))
    bridge.INPUT_HASHES, preparation = ue_asset_inputs.prepare(ROOT, bridge.MANIFEST['images'],
        bridge.MANIFEST['meshes'], workers,
        lambda done, total: _log(f"并行校验 {done}/{total}"))
    _log(f"文件准备：{preparation['workers']} 线程，{preparation['files']} 文件，{preparation['seconds']:.2f}s")
    _log(f"manifest 载入：images={len(bridge.MANIFEST['images'])} meshes={len(bridge.MANIFEST['meshes'])} "
         f"objects={len(bridge.MANIFEST['objects'])} materials={len(bridge.PLAN['materials'])}")

    todo = [s for s in STAGES if s not in SKIP]
    start_at = int(os.environ.get("ATLASMAP_UE_START") or 0)
    _log("阶段队列：" + ",".join(todo) + (f"（首段从 {start_at} 续跑）" if start_at else ""))
    timings = {}
    for i, stage in enumerate(todo):
        started = time.monotonic()
        if not _drive(stage, bridge, start_at if i == 0 else 0):
            raise RuntimeError(f"UE import stage failed: {stage}")
        timings[stage] = time.monotonic() - started
    bridge.flush_saves()

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.save_current_level():
        raise RuntimeError("Cannot save imported level: " + LEVEL)
    if os.environ.get("ATLASMAP_UE_FINISH", "0") == "1":
        import ue_ensure_lighting
        import ue_build_collision
        started = time.monotonic()
        _log("还原源灯光及环境光…")
        ue_ensure_lighting.main()
        _log("设置网格碰撞…")
        ue_build_collision.main(save_asset=bridge.save, flush=bridge.flush_saves)
        timings["lighting_collision"] = time.monotonic() - started
    _log("全部完成，关卡已保存 ✅")
    atomic_json(RESULT,{"complete": True, "level": LEVEL, "run_id": RUN_ID,
        "stages": todo, "preparation": preparation, "timings": timings,
        "headless_renderer": renderer, "lod_policy": lod_report})

    try:
        n = len(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors())
        _log(f"关卡里的 Actor 数：{n}")
    except Exception as exc:                                  # noqa: BLE001
        _log(f"数 Actor 失败：{exc}")


try:
    main()
except Exception:                                             # noqa: BLE001
    error = traceback.format_exc()
    atomic_json(RESULT,{"complete": False, "level": LEVEL, "run_id": RUN_ID,"error": error})
    _log("顶层异常：\n" + error)
    raise
