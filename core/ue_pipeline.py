"""「一键进 UE」：把导出器导出 → Blender 三段 → UE 七阶段 → 补灯 → 补碰撞 串成一条流水线。

设计成纯后台线程 + 回调，GUI 只负责显示；每一步是一条独立子进程，日志按行回调。
"""
from __future__ import annotations

import os
import json
import re
import uuid
import queue
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _no_window() -> int:
    return _NO_WINDOW


@dataclass
class Step:
    name: str                     # 显示名
    cmd: List[str]                # 命令行
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    allow_fail: bool = False      # True 时失败也继续
    validate: Optional[Callable[[float], None]] = None
    log_path: Optional[str] = None
    parallel_factory: Optional[Callable[[], List['Step']]] = None
    action: Optional[Callable[['Pipeline'], None]] = None
    work: Dict[str, int] = field(default_factory=dict)
    parallel_limit: Optional[Callable[[], int]] = None
    storage_limits: Dict[str, int] = field(default_factory=dict)
    priority: float = 0


def map_roots(name: str) -> List[str]:
    """A map can have streamed geometry and authored lighting in separate trees."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
        raise ValueError("请选择地图代号，或输入有效的英文地图代号")
    if name.lower().startswith("physxshared"):
        original=re.sub(r"^PhysXShared_?", "", name, flags=re.I)
        raise ValueError(f"{name} 是物理共享资源目录，不是地图关卡；请选择 {original}")
    return [f"DeltaForce/Content/Maps/BuildMaps_HD/{name}/",
            f"DeltaForce/Content/Maps/{name}/",
            f"DeltaForce/Content/Maps/BuildMaps/{name}/"]


def export_command(p: Dict[str, str], max_tex: Optional[int] = None) -> List[str]:
    from core import exporter
    from core.export_quality import max_texture
    max_tex=max_texture(p,max_tex)
    if not exporter.exporter_is_required(p['exe']):
        raise ValueError('导出器不是指定版本，已阻止导出')
    # The exporter reads the FIRST --root; several roots must be comma-separated.
    excluded = ["PhysicsProxy", "Reflection", "_SQ", "_SSQ"]
    if "_without" not in p["map"].lower():
        excluded.append("_Without")
    return [p["exe"], "--config", p["config"], "merge", p["map"], p["root"],
            "--root", ",".join(map_roots(p["map"])), "--all",
            "--exclude", ",".join(excluded),
            "--split", "--no-scene", "--keep-base-with-hd", "--deduplicate",
            "--max-tex", str(max_tex)]


def validate_export(root: str, name: str, started: float = 0) -> None:
    """Stop before Blender if a merge found nothing or left an older map behind."""
    paths = [os.path.join(root, "scene.json"),
             os.path.join(root, "split", "manifest.json"), os.path.join(root, "lights.json")]
    for path in paths:
        if not os.path.isfile(path) or os.path.getmtime(path) < started - 2:
            raise ValueError(f"本次导出未生成有效数据：{path}；不会继续使用旧地图")
    with open(paths[0], encoding="utf-8-sig") as fh:
        scene = json.load(fh)
    if scene.get("mapRoot") != " + ".join(map_roots(name)) or not scene.get("instances"):
        raise ValueError(f"地图 {name} 没有可用实例或输出地图不匹配，请检查游戏包；不会导入旧地图")
    from core.export_filter import filter_export
    filter_export(root)
    with open(paths[1], encoding="utf-8-sig") as fh:
        levels = json.load(fh).get("levels", [])
    if not levels or not any(row.get("instances", 0) for row in levels):
        raise ValueError(f"地图 {name} 没有可用的 split 分块")


def validate_result(path: str, level: str, started: float, run_id: str = "") -> None:
    if not os.path.isfile(path) or os.path.getmtime(path) < started - 2:
        raise ValueError(f"步骤没有生成本次完成报告：{path}")
    with open(path, encoding="utf-8-sig") as fh:
        report = json.load(fh)
    if not report.get("complete") or report.get("level") != level or (run_id and report.get("run_id") != run_id):
        raise ValueError(report.get("error") or f"步骤未完成或目标关卡不匹配：{path}")


def build_steps(p: Dict[str, str], *, max_tex: Optional[int] = None,
                skip_textures: bool = False) -> List[Step]:
    """按路径表拼出完整流水线。p 的键见 app/ue_page.py::_paths()。"""
    root = p["root"]
    transfer = p["transfer"]
    scripts = p["scripts"]
    blender = p["blender"]
    engine = p["engine"]
    engine_cmd = p["cmd"]
    project = p["project"]
    dest = p["dest"]
    level = dest.rstrip("/") + "/LV_Map"
    run_id = uuid.uuid4().hex
    workers = max(1, min(16, int(p.get("workers", "8"))))
    from core.export_quality import max_texture,record_quality
    max_tex=max_texture(p,max_tex)

    def validate_source(started):
        validate_export(root,p['map'],started)
        record_quality(root,p.get('export_quality'),max_tex)
        # 框选区域：先按 manifest 的分块包围盒裁掉不相交的 glb，再修透明，
        # 这样 Blender 只导入选中的那一块，UE 那边也少搬一大半几何。
        try:
            from core.region import filter_map
            region = p.get('region')
            if region:
                report = filter_map(root, region)
                print('区域导出：保留 %d/%d 个分块，跳过 %.1f MB' % (
                    report['kept'], report['levels'], report['removed_bytes'] / 1048576), flush=True)
        except Exception as error:                       # noqa: BLE001
            print('区域裁剪失败（继续导出整张图）：',str(error)[:300],flush=True)
        # 贴花 / 树叶 / 纱网的 alpha 被导出器写成了 OPAQUE，按贴图重新判定。
        # 放在这里是因为 Blender 与 UE 两条链都从这一步分叉，改完两边都吃到。
        try:
            from core.split_materials import repair_split
            repair_split(root,log=print)
        except Exception as error:                       # noqa: BLE001 - 修不动也不能让整张图失败
            print('修正贴图透明通道失败（继续导出）：',str(error)[:300],flush=True)

    steps: List[Step] = []

    steps.append(Step(
        "1/7 指定导出器导出 split",
        export_command(p, max_tex),
        validate=validate_source,
        log_path=os.path.join(root, "pipeline.log"),
    ))

    from core.scene_state import enrich
    def validate_state(started):
        state_file=os.path.join(root,'source-render','state-index.json')
        if not os.path.isfile(state_file) or os.path.getmtime(state_file)<started-2:
            raise ValueError('本次导出没有生成源渲染状态')
        state=enrich(root)
        if state['mapRoot'] != ' + '.join(map_roots(p['map'])):
            raise ValueError('源渲染状态与所选地图不匹配')
    steps.append(Step('2/7 原始渲染数据：灯光 / 后处理 / 烘焙载荷',
        [os.path.join(os.path.dirname(scripts),'tools','scene-state','scene-state.exe'),
         os.path.dirname(p['exe']),p['config'],root,os.path.join(root,'source-render')],
        validate=validate_state))

    steps.append(Step(
        "3/7 Blender ①：split → .blend",
        [blender, "-b", "--python-exit-code", "1", "-P", os.path.join(scripts, "blender_iceland.py"), "--",
         root, "--no-render", "--materials", "--flat-split"],
    ))

    steps.append(Step(
        "4/7 Blender ②：.blend → FBX + manifest",
        [blender, "-b", os.path.join(root, "scene_no_terrain.blend"), "--python-exit-code", "1", "-P",
         os.path.join(scripts, "blender_iceland_to_ue.py")],
        env={"ATLASMAP_UE_ROOT": transfer},
    ))

    steps.append(Step(
        "5/7 Blender ③：材质编译",
        [blender, "-b", "--python-exit-code", "1", "-P", os.path.join(scripts, "compile_iceland_ue_materials.py")],
        env={"ATLASMAP_UE_ROOT": transfer},
    ))

    steps.append(Step(
        "6/7 Blender ③：材质分组",
        [blender, "-b", "--python-exit-code", "1", "-P", os.path.join(scripts, "group_iceland_ue_materials.py")],
        env={"ATLASMAP_UE_ROOT": transfer},
    ))

    ue_env = {
        "ATLASMAP_UE_ROOT": transfer,
        "ATLASMAP_UE_DEST": dest,
        "ATLASMAP_UE_LEVEL": level,
        "ATLASMAP_UE_SKIP": "",
        "ATLASMAP_UE_START": "0",
        "ATLASMAP_SOURCE_ROOT": root,
        "ATLASMAP_UE_FINISH": "1",
        "ATLASMAP_UE_NO_RENDER": "1",
        "ATLASMAP_UE_BATCH_IMPORT": "1",
        "ATLASMAP_UE_BATCH_SAVE": "1",
        "ATLASMAP_UE_WORKERS": str(workers),
        "ATLASMAP_UE_BATCH_SIZE": str(min(32, max(4, workers * 2))),
        "ATLASMAP_UE_RUN_ID": run_id,
        "ATLASMAP_LIGHTING_MODE": p.get("lighting_mode", "source"),
        "ATLASMAP_RENDER_PROFILE": p.get("render_profile", "game"),
    }
    if skip_textures:
        ue_env["ATLASMAP_UE_SKIP"] = "textures"

    def validate_ue(started: float) -> None:
        validate_result(os.path.join(transfer, "ue_import_result.json"), level, started, run_id)
        validate_result(os.path.join(root, "lighting_report.json"), level, started)
        validate_result(os.path.join(root, "collision_report.json"), level, started)

    from core.ue_render_config import headless_renderer_args
    steps.append(Step(
        "7/7 UE 批量导入 + 源渲染状态 + 碰撞",
        [engine_cmd, project,
         f"-ExecutePythonScript={os.path.join(scripts, 'ue_run_headless.py')}",
         "-nullrhi", "-unattended", "-nosplash", "-SCCProvider=None", "-nop4",
         "-stdout", "-FullStdOutLogOutput", "-UTF8Output", *headless_renderer_args()],
        env=ue_env,
        validate=validate_ue,
    ))

    del engine  # 打开编辑器由调用方决定
    if p.get('parallel_export') in (True, '1'):
        from core.full_parallel_export import full_parallel_steps
        return full_parallel_steps(p, steps, run_id)
    return [replace(step,storage_limits={root:512*1024**2,os.path.dirname(project):512*1024**2}) for step in steps]


def render_step(p):
    """A separate real-RHI render, scoped to the selected imported level."""
    level = p['dest'].rstrip('/')+'/LV_Map'
    run_id = uuid.uuid4().hex
    result = os.path.join(p['root'], 'render_report.json')
    return Step('UE 游戏光照渲染预览',
                [p['engine'], p['project'], '-RenderOffscreen',
                 "-ExecCmds=py import sys;import os;sys.path[:0]=[os.environ['ATLASMAP_SCRIPTS']];import ue_render_preview",
                 '-unattended', '-nosplash', '-nosound',
                 '-SCCProvider=None', '-nop4', '-stdout', '-FullStdOutLogOutput', '-UTF8Output'],
                env={'ATLASMAP_SOURCE_ROOT':p['root'], 'ATLASMAP_UE_LEVEL':level,
                     'ATLASMAP_SCRIPTS':p['scripts'],
                     'ATLASMAP_RENDER_RUN_ID':run_id,
                     'ATLASMAP_RENDER_VIEW':p.get('render_view','auto'),
                     'ATLASMAP_RENDER_EV':p.get('render_ev','0'),
                     'ATLASMAP_RENDER_PROFILE':p.get('render_profile','game'),
                     'ATLASMAP_LIGHTING_MODE':p.get('lighting_mode','source')},
                validate=lambda started: validate_result(result, level, started, run_id),
                log_path=os.path.join(p['root'], 'render.log'))


def prepare_dirs(root: str, target: str = 'ue') -> List[str]:
    """The generic import reads root/split directly; no junction is required."""
    notes: List[str] = []
    os.makedirs(root, exist_ok=True)
    transfer=root+('_blender_work' if target=='blender' else '_ue')
    os.makedirs(transfer,exist_ok=True)
    if target!='blender':
        with open(os.path.join(transfer,'ue_import_result.json'),'w',encoding='utf-8') as stream:
            json.dump({'complete':False,'reason':'A new export has started'},stream)
    diag = os.path.join(root, "diagnostics")
    os.makedirs(diag, exist_ok=True)
    notes.append("diagnostics 目录就绪")
    return notes


class Pipeline:
    """顺序跑一串 Step，日志/进度按回调送出。"""

    def __init__(self, steps: List[Step], on_line: Optional[Callable[[str], None]] = None,
                 on_progress: Optional[Callable[[int, int, str], None]] = None,
                 on_done: Optional[Callable[[int], None]] = None, residue=None) -> None:
        self.steps = steps
        self.on_line = on_line
        self.on_progress = on_progress
        self.on_done = on_done
        self.residue = residue
        self.code: Optional[int] = None
        self.failure = None
        from core.export_failure import FailureTracker
        self._failure_tracker = FailureTracker()
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._thread: Optional[threading.Thread] = None
        self._log_file = None
        self._emit_lock = threading.RLock()
        self._children_lock = threading.Lock()
        self._children = []

    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        processes=[]
        self._cancel_tree(processes)
        from core.process_control import terminate_processes
        terminate_processes(processes,self._emit)

    def _cancel_tree(self,processes):
        self._cancelled = True
        with self._children_lock:
            children = list(self._children)
        for child in children:
            child._cancel_tree(processes)
        proc = self._proc
        if proc is not None and proc.poll() is None:
            processes.append(proc)

    def command_line(self) -> str:
        return "\n".join(" ".join(s.cmd) for s in self.steps)

    # ------------------------------------------------------------------ #
    def start(self) -> "Pipeline":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _emit(self, text: str) -> None:
        with self._emit_lock:
            self._emit_locked(text)

    def _emit_locked(self, text: str) -> None:
        self._failure_tracker.observe(text)
        if self._log_file:
            try:
                self._log_file.write(text + "\n")
            except OSError:
                self._log_file.close()
                self._log_file = None
        if self.on_line:
            try:
                self.on_line(text)
            except Exception:                                   # noqa: BLE001
                pass

    def _parallel(self, step):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        children = []
        for index, job in enumerate(step.parallel_factory()):
            def emit(line, worker=index, stage=job.name):
                native=bool(re.match(r'^\[\d{4}\.\d{2}\.\d{2}',line))
                if native and not any(word in line.lower() for word in (
                    '@map_task ','[headless]','[light]','[collision]','error:','warning:','traceback','exception','磁盘空间不足')):
                    return
                if line.startswith('[dfmap]') and not any(word in line.lower() for word in ('error','fail','失败')):
                    return
                data = {'worker': worker, 'stage': stage, 'event': 'line', 'text': line}
                marker = line.find('@ATLASMAP_TASK ')
                if marker >= 0:
                    try:
                        data.update(json.loads(line[marker + len('@ATLASMAP_TASK '):]))
                    except (ValueError, TypeError):
                        pass
                elif line.startswith('[进程启动] PID='):
                    data.update(event='process', pid=int(line.rsplit('=', 1)[1]))
                else:
                    progress=re.search(r'(?:\[(?:state|scan)\] level|extracted)\s+(\d+)\s*/\s*(\d+)(.*)',line)
                    if progress:
                        data.update(event='progress',done=int(progress[1]),total=int(progress[2]),
                                    unit='源关卡',current=progress[3].strip(' :'))
                self._emit('@ATLASMAP_PARALLEL ' + json.dumps(data, ensure_ascii=False))
            if job.work:
                emit('@ATLASMAP_TASK '+json.dumps(dict(event='assigned',work=job.work,
                     text=f'分块 {index+1} 独立任务：'+json.dumps(job.work,ensure_ascii=False)),ensure_ascii=False))
            children.append(Pipeline([job], on_line=emit))
        if not children:
            raise ValueError('没有可运行的并行任务')
        with self._children_lock:
            self._children = children
        try:
            if self._cancelled:
                return -2
            limit=max(1,min(len(children),step.parallel_limit() if step.parallel_limit else len(children)))
            order=sorted(children,key=lambda child:-child.steps[0].priority)
            if limit<len(children):
                for child in order[limit:]:
                    worker=children.index(child)
                    self._emit('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=worker,stage=child.steps[0].name,
                        event='queued',text=f'分块 {worker+1} 已排队；按内存余量同时运行 {limit} 个进程，完成一个后继续下一块'),ensure_ascii=False))
            with ThreadPoolExecutor(max_workers=limit) as pool:
                futures = {pool.submit(child._run): child for child in order}
                failure = 0
                for future in as_completed(futures):
                    child = futures[future]
                    try:
                        future.result()
                        rc = child.code if child.code is not None else -1
                    except Exception as exc:
                        self._emit(f'[并行任务失败] {exc}')
                        self._emit(traceback.format_exc().rstrip())
                        rc = -1
                    worker = children.index(child)
                    self._emit('@ATLASMAP_PARALLEL ' + json.dumps({'worker': worker,
                        'stage': child.steps[0].name, 'event': 'finished', 'code': rc,
                        'text': f'分块 {worker + 1} 校验通过，已完成' if rc == 0 else f'分块 {worker + 1} 退出，状态 {rc}'}, ensure_ascii=False))
                    if rc and not failure:
                        failure = rc
                        if child.failure is not None:
                            self.failure=replace(child.failure,worker=worker+1,stage=child.steps[0].name)
                        for other in children:
                            if other is not child:
                                other.stop()
                if failure==-6 and not self._cancelled:
                    disk=next((child for child in children if child.code==-5),None)
                    if disk is not None:
                        if disk.failure is not None:self.failure=replace(disk.failure,worker=children.index(disk)+1,stage=disk.steps[0].name)
                        return -5
                    self._emit('[内存不足] 已结束本组进程，将未完成分块降为单进程重试一次。')
                    for worker,child in enumerate(children):
                        if self._cancelled:return -2
                        if child.code==0:continue
                        self._emit('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=worker,stage=child.steps[0].name,
                            event='queued',text=f'分块 {worker+1}：内存不足，自动单进程重试'),ensure_ascii=False))
                        child._cancelled=False;child.code=None
                        if self._cancelled:return -2
                        child._run()
                        rc=child.code if child.code is not None else -1
                        self._emit('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=worker,stage=child.steps[0].name,
                            event='finished',code=rc,text=f'分块 {worker+1} 重试'+('完成' if rc==0 else '失败')),ensure_ascii=False))
                        if rc:
                            if child.failure is not None:self.failure=replace(child.failure,worker=worker+1,stage=child.steps[0].name)
                            return rc
                    failure=0
                    self.failure=None
                return -2 if self._cancelled else failure
        finally:
            with self._children_lock:
                self._children = []

    def _run(self) -> None:
        if self.residue is not None:
            self._emit('[残留清理] 正在记录导出前的文件，已有文件将保留。')
            self.residue.capture()
        log_path = next((step.log_path for step in self.steps if step.log_path), None)
        if log_path:
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                self._log_file = open(log_path, "a", encoding="utf-8", buffering=1)
                self._emit("\n=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===")
            except OSError as exc:
                self._emit(f"[日志文件不可写] {exc}")
        total = len(self.steps)
        code = 0
        for index, step in enumerate(self.steps, start=1):
            if self._cancelled:
                code = -2
                break
            from core.export_failure import FailureTracker
            self._failure_tracker=FailureTracker(step.name)
            self.failure=None
            self._emit("")
            self._emit(f"═══ 步骤 {index}/{total}：{step.name} ═══")
            self._emit(" ".join(step.cmd))
            if self.on_progress:
                try:
                    self.on_progress(index - 1, total, step.name)
                except Exception:                               # noqa: BLE001
                    pass
            if step.parallel_factory or step.action:
                started = time.time()
                try:
                    rc = self._parallel(step) if step.parallel_factory else (step.action(self) or 0)
                    if self._cancelled:
                        rc = -2
                    if rc == 0 and step.validate:
                        step.validate(started)
                except Exception as exc:
                    self._emit('[已终止] 后续步骤已取消' if self._cancelled else f'[并行导出失败] {exc}')
                    self._emit(traceback.format_exc().rstrip())
                    rc = -2 if self._cancelled else -5 if isinstance(exc,OSError) and exc.errno==28 else -4
                if rc and not step.allow_fail:
                    code = rc
                    break
                continue
            scripts_dir = step.env.get("_SCRIPTS") or ""
            missing = ""
            for token in step.cmd:
                probe = token.split("=", 1)[1] if token.lower().startswith("-executepythonscript=")                     else token
                if probe.lower().endswith(".py") and not os.path.isfile(probe):
                    missing = probe
                    break
            if missing:
                self._emit(f"[缺少脚本] {missing}")
                if not step.allow_fail:
                    code = -3
                    break
                continue
            if ".blend" in " ".join(step.cmd).lower():
                for token in step.cmd:
                    if token.lower().endswith(".blend") and not os.path.isfile(token):
                        self._emit(f"[缺少输入] {token}")
                        if not step.allow_fail:
                            code = -3
                            break
                if code:
                    break
            del scripts_dir
            env = os.environ.copy()
            env.update({k: str(v) for k, v in step.env.items()})
            started = time.time()
            from core.export_storage import check_space,DiskGuard
            try:
                if (step.env.get('ATLASMAP_RENDER_PROFILE')=='game' and step.env.get('ATLASMAP_UE_LEVEL')
                        and len(step.cmd)>1 and step.cmd[1].lower().endswith('.uproject')):
                    from core.ue_render_config import ensure_game_renderer
                    settings=ensure_game_renderer(step.cmd[1])
                    self._emit('[室内光照] 已启用 Lumen 间接光、反射和网格距离场：'+str(settings))
                check_space(step.storage_limits)
                proc = subprocess.Popen(
                    step.cmd, cwd=step.cwd, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", bufsize=1, creationflags=_no_window(),
                )
            except Exception as exc:                            # noqa: BLE001
                self._emit(f"[启动失败] {exc}")
                self._emit(traceback.format_exc().rstrip())
                if not step.allow_fail:
                    code = -5 if isinstance(exc,OSError) and exc.errno==28 else -6 if getattr(exc,"winerror",None) in (8,14,1450,1455) else -1
                    break
                continue
            self._proc = proc
            self._emit(f'[进程启动] PID={proc.pid}')
            def disk_full(message):
                self._emit('[ATLASMAP_DISK_FULL] '+message)
                from core.process_control import terminate_processes
                terminate_processes([proc],self._emit)
            guard=DiskGuard(step.storage_limits,disk_full).start()
            if self._cancelled:
                self.stop()
            assert proc.stdout is not None
            disk_failure=False
            memory_failure=False
            stalled=False
            last_line=''
            last_seen=time.time()
            stall_seconds=float(os.environ.get('ATLASMAP_STALL_SECONDS','900') or 900)
            stall_seconds=max(2.0,stall_seconds)
            pending_lines: "queue.Queue[object]" = queue.Queue()
            def pump(stream=proc.stdout) -> None:
                try:
                    for chunk in stream:
                        pending_lines.put(chunk)
                except Exception:                            # noqa: BLE001
                    pass
                finally:
                    pending_lines.put(None)
            threading.Thread(target=pump,daemon=True).start()
            while True:
                try:
                    raw=pending_lines.get(timeout=2.0)
                except queue.Empty:
                    raw=''
                if raw is None:
                    break
                line=str(raw).rstrip(chr(13)+chr(10))
                if line:
                    last_line=line
                    last_seen=time.time()
                if any(token in line.lower() for token in ('no space left on device','磁盘空间不足','not enough space on the disk','map_disk_full','disk full','0x80070070')):
                    disk_failure=True
                from core.export_failure import classify
                problem=classify(line)
                if problem and problem[1]=='memory':
                    memory_failure=True
                if line.strip():
                    self._emit(line)
                if proc.poll() is None and time.time()-last_seen>stall_seconds:
                    stalled=True
                    self._emit(f'[进程卡住] {stall_seconds/60:.0f} 分钟没有任何新日志，已终止：{os.path.basename(step.cmd[0])}（PID={proc.pid}）')
                    if last_line:
                        self._emit(f'[进程卡住] 最后一行：{last_line[:400]}')
                    self._emit('[进程卡住] 已完成的资产会保留，重新导出会自动跳过它们继续；若每次都卡在同一处，请把上面这行日志发给开发者。')
                    from core.process_control import terminate_processes
                    terminate_processes([proc],self._emit)
                    break
            proc.stdout.close()
            rc = proc.wait()
            if stalled:
                rc=-7
            guard.stop()
            disk_failure=disk_failure or bool(guard.error)
            if disk_failure:
                self._emit('[磁盘空间不足] 当前分块无法保存文件，已停止后续步骤。请释放导出盘空间或换到空间充足的磁盘。')
                rc=-5
            elif rc!=0 and (memory_failure or (rc & 0xffffffff) in (0xc0000017,0xc000012d)):
                self._emit('[内存不足] 当前进程没有足够的可用内存或提交空间，后续并行任务将减少并发重试。')
                rc=-6
            self._proc = None
            if self._cancelled:
                code = -2
                break
            if rc == 0 and step.validate is not None:
                try:
                    step.validate(started)
                except Exception as exc:
                    self._emit(f"[输出校验失败] {exc}")
                    self._emit(traceback.format_exc().rstrip())
                    rc = -4
            self._emit(f"── 步骤 {index}/{total} 结束，退出码 {rc}")
            if rc != 0 and not step.allow_fail:
                code = rc
                break
        self.code = code
        if code not in (0,-2,130):
            self.failure=self.failure or self._failure_tracker.finish(code)
            if self.failure is not None:self._emit(self.failure.event())
        else:self.failure=None
        if code != 0 and self.residue is not None:
            self._emit('[残留清理] 导出进程已结束，正在整理本次新增文件清单。')
            self.residue.seal()
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        if self.on_progress:
            try:
                self.on_progress(total if code==0 else max(0,index-1), total, "完成" if code == 0 else f"失败：{step.name}")
            except Exception:                                   # noqa: BLE001
                pass
        if self.on_done:
            try:
                self.on_done(code)
            except Exception:                                   # noqa: BLE001
                pass
