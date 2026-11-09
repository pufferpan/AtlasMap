"""把 map-export.exe（地图导出器）包装成可被界面调用的东西。

设计要点：

* 所有配置都落到一个 json 里（导出器自己的 `--config`），界面只改这个 json；
* 所有命令都是子进程，stdout/stderr 合流按行回调出去，界面里直接滚日志；
* 不假设导出器的开关齐全 —— `merge` 的 `--help` 只列了 4 个，但 DLL 里支持更多
  （`--split/--deduplicate/--keep-base-with-hd/--max-tex/--visible-only` 等），
  界面按需拼，真不支持时子进程会把用法打回来。
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

APP_NAME = "AtlasMap"

# 工具链默认跟着程序目录走（见 _bundled_tool_dirs）
DEFAULT_TOOL_DIRS: tuple = ()          # 不再内置开发机路径：工具链只跟程序目录走


def _bundled_tool_dirs() -> list:
    """打包后导出器工具链跟着 exe 走：<exe 目录>/runtime、<exe 目录>/tools/runtime。"""
    out = []
    root = app_dir()
    for rel in ("runtime", os.path.join("tools", "runtime")):
        d = os.path.join(root, rel)
        if os.path.isdir(d):
            out.append(d)
    parent = os.path.dirname(root)
    for rel in ("runtime", os.path.join("tools", "runtime")):
        d = os.path.join(parent, rel)
        if os.path.isdir(d):
            out.append(d)
    return out

DEFAULT_PAKS = ""                      # 首选用户在设置里指定的目录
DEFAULT_KEYFILE = ""                   # 优先用程序自带或用户指定的密钥文件
_bundled_key = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(__file__))),
                            'assets', 'AESKey1.json')
if os.path.isfile(_bundled_key):
    DEFAULT_KEYFILE = _bundled_key


def app_dir() -> str:
    """配置/缓存目录：%LOCALAPPDATA%\\AtlasMap。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _src_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _meipass() -> Optional[str]:
    return getattr(sys, "_MEIPASS", None)


def runtime_root() -> str:
    """Locate export scripts in source, directory and single-file builds."""
    if getattr(sys, 'frozen', False):
        extracted = _meipass()
        if extracted and os.path.isdir(os.path.join(extracted, 'scripts', 'official')):
            return extracted
        return os.path.dirname(os.path.abspath(sys.executable))
    return _src_root()


def find_exe() -> Optional[str]:
    """找 map-export.exe：设置里指定的 → 程序目录旁的。"""
    roots = []
    base = _meipass()
    if base:
        roots.append(base)
    roots.append(_src_root())
    roots.append(os.path.dirname(_src_root()))
    for root in roots:
        for name in ("map-export.exe", os.path.join("runtime", "map-export.exe"),
                     os.path.join("tools", "map-export.exe")):
            path = os.path.join(root, name)
            if os.path.isfile(path) and exporter_is_required(path):
                return path
    for d in _bundled_tool_dirs():
        path = os.path.join(d, "map-export.exe")
        if os.path.isfile(path) and exporter_is_required(path):
            return path
    return None


def exporter_is_required(exe):
    """Never fall back to another exporter selected in an older profile."""
    try:
        library=os.path.join(os.path.dirname(exe),'dfmap.dll')
        with open(exe,'rb') as stream:
            if hashlib.sha256(stream.read()).hexdigest() != '32cfc2d98630eba7c8513027d8b5a72cc30da86c7fffb0283f45a6e4f18b548c':
                return False
        with open(library,'rb') as stream:
            return hashlib.sha256(stream.read()).hexdigest() == 'f5a909824c021b27ff5a76d94e1b5a3f01db85b09d84568e9b990d327cbc6ac7'
    except OSError:
        return False


# ---------------------------------------------------------------- 设置 ----
SETTINGS_NAME = "settings.json"


def settings_path() -> str:
    return os.path.join(app_dir(), SETTINGS_NAME)


def load_settings() -> Dict[str, object]:
    path = settings_path()
    data: Dict[str, object] = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:                                       # noqa: BLE001
            data = {}
    data.setdefault("exe", "")
    data.setdefault("paks", DEFAULT_PAKS)
    data.setdefault("keyfile", DEFAULT_KEYFILE)
    data.setdefault("outdir", os.path.join(os.path.expanduser("~"), "Documents", "atlasmap-exports"))
    data.setdefault("game", "GAME_DeltaForce")
    data.setdefault("blender", "")
    return data


def save_settings(data: Dict[str, object]) -> None:
    with open(settings_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def exporter_config_path() -> str:
    return os.path.join(app_dir(), "exporter.json")


def game_resource_root(paks: str) -> str:
    """Include WeGame's downloaded updates alongside its base Content/Paks."""
    path = Path(paks)
    if path.name.lower() == 'paks' and path.parent.name.lower() == 'content':
        game = path.parent.parent
        extra = [game / 'PackContent' / 'Paks']
        dolphin = game / 'Saved' / 'Dolphin'
        if dolphin.is_dir():
            extra.extend(dolphin.glob('*/Paks'))
        if any(folder.is_dir() and any(folder.glob('*.pak')) for folder in extra):
            return str(game)
    return str(paks)


def keyfile_candidates() -> list:
    """AES 密钥文件可能放的位置（按优先级）：程序目录、程序目录/assets、配置目录。"""
    roots = []
    meipass = _meipass()
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(_src_root())
    roots.append(app_dir())
    out = []
    for root in roots:
        for rel in ("AESKey1.json", os.path.join("assets", "AESKey1.json")):
            path = os.path.join(root, rel)
            if os.path.isfile(path) and path not in out:
                out.append(path)
    return out


def resolve_keyfile(settings: Optional[Dict[str, object]] = None) -> str:
    """返回真正可用的密钥文件路径；设置里的路径不存在时自动找随包/程序目录里的。"""
    s = settings or load_settings()
    chosen = str(s.get("keyfile") or "").strip()
    if chosen and os.path.isfile(chosen):
        return chosen
    hits = keyfile_candidates()
    return hits[0] if hits else ""


def write_exporter_config(settings: Optional[Dict[str, object]] = None, path: Optional[str] = None) -> str:
    """把界面里的设置写成导出器认识的 json，返回路径。"""
    s = settings or load_settings()
    data = {
        "PaksDirectory": game_resource_root(str(s.get("paks") or "")).replace("\\", "/"),
        "Recursive": True,
        "Game": s.get("game") or "GAME_DeltaForce",
        "MeshGame": "",
        "KeyFile": resolve_keyfile(s).replace("\\", "/"),
        "KeyUrl": "",
    }
    path = path or exporter_config_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- 运行 ----
LineFn = Callable[[str], None]
DoneFn = Callable[[int], None]


@dataclass
class Job:
    args: List[str]
    title: str = ""
    lines: List[str] = field(default_factory=list)
    code: Optional[int] = None
    started: float = field(default_factory=time.time)
    _proc: Optional[subprocess.Popen] = None
    _threads: List[threading.Thread] = field(default_factory=list)
    _cancelled: bool = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            from core.process_control import terminate_processes
            terminate_processes([proc])

    def command_line(self) -> str:
        return " ".join(f'"{a}"' if " " in a else a for a in self.args)


def _no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW


def start(arg_line: List[str], on_line: Optional[LineFn] = None,
          on_done: Optional[DoneFn] = None, cwd: Optional[str] = None,
          title: str = "") -> Job:
    """起一个导出器子进程，按行回调，结束时回调退出码。"""
    job = Job(args=list(arg_line), title=title)
    try:
        proc = subprocess.Popen(
            job.args, cwd=cwd or os.path.dirname(job.args[0]) or None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=_no_window())
    except Exception as exc:                                    # noqa: BLE001
        msg = f"[启动失败] {exc}"
        job.lines.append(msg)
        if on_line:
            on_line(msg)
        job.code = -1
        if on_done:
            on_done(-1)
        return job

    job._proc = proc

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            job.lines.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:                               # noqa: BLE001
                    pass
        code = proc.wait()
        proc.stdout.close()
        if code == 0 and not job._cancelled and 'merge' in job.args:
            try:
                from core.export_filter import filter_export
                filtered=filter_export(job.args[job.args.index('merge')+2])
                message=f"[filter] 爆破开局空气墙：移除 {filtered['removed_instances']} 个源实例"
                job.lines.append(message)
                if on_line:on_line(message)
                command=source_state_command(job.args)
                if command:
                    message='[source] 导出原始灯光、后处理和烘焙载荷…'
                    job.lines.append(message)
                    if on_line:on_line(message)
                    extra=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',creationflags=_no_window())
                    job._proc=extra
                    for raw in extra.stdout:
                        line=raw.rstrip('\r\n');job.lines.append(line)
                        if on_line:on_line(line)
                    extra.stdout.close()
                    code=extra.wait()
                    if code==0:
                        from core.scene_state import enrich
                        enrich(command[-2])
            except Exception as exc:
                code=-4
                message='[源渲染数据导出失败] '+str(exc)
                job.lines.append(message)
                if on_line:on_line(message)
        if job._cancelled:code=130
        job.code = code
        if on_done:
            try:
                on_done(code)
            except Exception:                                   # noqa: BLE001
                pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    job._threads.append(th)
    return job


def source_state_command(args):
    if 'merge' not in args:return None
    i=args.index('merge')
    if i+2>=len(args):raise ValueError('地图导出参数缺少输出目录')
    base=runtime_root()
    helper=os.path.join(base,'scripts','tools','scene-state','scene-state.exe')
    config=args[args.index('--config')+1] if '--config' in args else write_exporter_config()
    root=os.path.abspath(args[i+2])
    return [helper,os.path.dirname(os.path.abspath(args[0])),config,root,os.path.join(root,'source-render')]


def run_blocking(arg_line: List[str], timeout: float = 180.0,
                 cwd: Optional[str] = None) -> tuple[int, str]:
    """同步跑一条命令，返回 (退出码, 全部输出)。用于 doctor/keys/find 这种短命令。"""
    try:
        proc = subprocess.run(arg_line, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              cwd=cwd or (os.path.dirname(arg_line[0]) or None),
                              creationflags=_no_window())
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:                                    # noqa: BLE001
        return -1, f"{exc}"


# ---------------------------------------------------------------- 命令 ----
def _base_cmd(exe: str) -> List[str]:
    return [exe, "--config", write_exporter_config()]


def doctor(exe: str, mount: bool = False, out: Optional[str] = None) -> tuple[int, str]:
    cmd = _base_cmd(exe) + ["doctor"]
    if mount:
        cmd.append("--mount")
    if out:
        cmd += ["--out", out]
    return run_blocking(cmd, timeout=600)


def keys(exe: str) -> tuple[int, str]:
    return run_blocking(_base_cmd(exe) + ["keys"], timeout=120)


def parse_maps(text: str, prefix: Optional[str] = None) -> Dict[str, int]:
    """Read both authored levels and streamed map families; omit physics folders."""
    counts: Dict[str, int] = {}
    levels = set()
    family = re.escape(prefix) + '/' if prefix else r'(?:(?:BuildMaps_HD|BuildMaps)/)?'
    pat = re.compile(r'DeltaForce/Content/Maps/' + family + r'([^/\s]+)/', re.I)
    for line in text.splitlines():
        m = pat.search(line)
        if m:
            name = m.group(1)
            if name.lower().startswith("physxshared"):
                continue
            counts[name] = counts.get(name, 0) + 1
            if line.rstrip().lower().endswith(".umap"):
                levels.add(name)
    return {name: count for name, count in counts.items() if name in levels}


def list_maps(exe: str, prefix: Optional[str] = None, limit: int = 2147483647) -> Dict[str, int]:
    query = 'DeltaForce/Content/Maps/' + (prefix + '/' if prefix else '')
    code, text = run_blocking(_base_cmd(exe) + ["find", query, str(limit)], timeout=900)
    if code != 0:
        raise RuntimeError(f'游戏地图扫描失败（{code}）：{text[-1500:]}')
    inventory = re.search(r'== (\d+) files matching .*\(showing (\d+)\)', text)
    if inventory and int(inventory[1]) > int(inventory[2]):
        raise RuntimeError('地图文件清单被截断，请提高扫描上限后重试')
    try:
        from core.export_quality import cache_inventory
        cache_inventory(text,load_settings())
    except (OSError,ValueError):pass
    return parse_maps(text, prefix)


def merge_command(exe: str, map_name: str, out_dir: str, roots: List[str],
                  flags: Optional[List[str]] = None, extra: Optional[List[str]] = None) -> List[str]:
    """The exporter reads a comma-separated root list from the first --root option."""
    cmd = _base_cmd(exe) + ["merge", map_name, out_dir]
    selected = [root for root in roots if root]
    if selected:
        cmd += ["--root", ",".join(selected)]
    if flags:
        cmd += list(flags)
    if extra:
        cmd += [a for a in extra if a]
    return cmd


# ---------------------------------------------------------------- 预设 ----
def presets_dir(exe: Optional[str] = None) -> Optional[str]:
    base = os.path.dirname(exe) if exe else None
    if base:
        path = os.path.join(base, "presets")
        if os.path.isdir(path):
            return path
    for d in list(_bundled_tool_dirs()) + list(DEFAULT_TOOL_DIRS):
        path = os.path.join(d, "presets")
        if os.path.isdir(path):
            return path
    return None


def load_presets(exe: Optional[str] = None) -> List[Dict[str, object]]:
    """读 presets/*.json，返回 [{map, stages:[{id,label,roots,note}], date}]。"""
    root = presets_dir(exe)
    out: List[Dict[str, object]] = []
    if not root:
        return out
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:                                       # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("stages"):
            data["_file"] = name
            out.append(data)
    return out


def docs_dir(exe: Optional[str] = None) -> Optional[str]:
    base = os.path.dirname(exe) if exe else None
    for cand in ([os.path.join(base, "docs")] if base else []) + \
                [os.path.join(d, "docs") for d in DEFAULT_TOOL_DIRS]:
        if os.path.isdir(cand):
            return cand
    return None
