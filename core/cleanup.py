"""导出后的临时文件清理。

一次完整导出会在几个地方留下中间产物：

* ``<导出目录>/preview/<run_id>/*.npz``  视口预览缓存，导完就没用了
* ``<导出目录>/source-render/raw``        分块原始 glb；合并成 split 之后只剩「再生成一次
  Blender 工程」时有用，体积最大（按实例数可达数 GB）
* ``<导出目录>/_blender/*/tasks``         分块任务清单
* ``%LOCALAPPDATA%\\AtlasMap\\job-config``  每次导出一份导出器配置
* ``%LOCALAPPDATA%\\AtlasMap\\logs``        每次导出一份日志
* 系统临时目录里的 ``atlasmap-probe-*``    逐包探测密钥时留下的目录

这里只删上面这些明确路径，且必须在导出目录之内；不碰用户自己放进去的东西。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

KEEP_JOB_CONFIGS = 20
KEEP_LOGS = 30
LOG_BUDGET = 300 * 1024 * 1024   # 日志总量上限；超了从最旧的开始删


def _app_dir() -> Path:
    from core import exporter

    return Path(exporter.app_dir())


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
    return total


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _preview_dirs(root: Path, run_id: str = "") -> List[Path]:
    preview = root / "preview"
    if not preview.is_dir():
        return []
    if run_id:
        target = preview / run_id
        return [target] if target.is_dir() else []
    return [p for p in preview.iterdir() if p.is_dir()]


def _blender_tasks(root: Path) -> List[Path]:
    found: List[Path] = []
    for base in root.glob("*_blender"):
        if not base.is_dir():
            continue
        for tasks in base.glob("*/tasks"):
            if tasks.is_dir():
                found.append(tasks)
    return found


def _newest_kept(files: Iterable[Path], keep: int) -> List[Path]:
    items = [p for p in files if p.is_file()]
    items.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return items[keep:]


def _temp_probes() -> List[Path]:
    import tempfile

    base = Path(tempfile.gettempdir())
    return [p for p in base.glob("atlasmap-probe-*") if p.is_dir()]


def plan(root: str, *, run_id: str = "", include_raw: bool = True,
         app_dir: Optional[Path] = None) -> Dict[str, object]:
    """列出可清理项：``{"items": [...], "size": 总字节}``。"""
    root_path = Path(root)
    app = Path(app_dir) if app_dir else _app_dir()
    items: List[Dict[str, object]] = []

    def add(kind: str, path: Path) -> None:
        if not path.exists():
            return
        if kind == "probe":
            pass
        elif kind in ("preview", "raw", "tasks"):
            if not _inside(path, root_path):
                return
        elif not _inside(path, app):
            return
        size = _size(path)
        if size <= 0 and kind != "tasks":
            return
        items.append({"kind": kind, "path": str(path), "size": size})

    for directory in _preview_dirs(root_path, run_id):
        add("preview", directory)
    if include_raw:
        add("raw", root_path / "source-render" / "raw")
    for tasks in _blender_tasks(root_path):
        add("tasks", tasks)

    jobs = app / "job-config"
    if jobs.is_dir():
        for stale in _newest_kept(jobs.glob("*.json"), KEEP_JOB_CONFIGS):
            add("job-config", stale)

    logs = app / "logs"
    if logs.is_dir():
        stale = _newest_kept(logs.glob("*.txt"), KEEP_LOGS)
        kept = [p for p in logs.glob("*.txt") if p not in stale]
        total = sum(_size(p) for p in kept)
        for path in sorted(kept, key=lambda p: p.stat().st_mtime):
            if total <= LOG_BUDGET:
                break
            total -= _size(path)
            stale.append(path)
        for path in stale:
            add("log", path)

    for probe in _temp_probes():
        size = _size(probe)
        if size >= 0:
            items.append({"kind": "probe", "path": str(probe), "size": size})

    return {"items": items, "size": sum(int(item["size"]) for item in items)}


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=False)


def clean(root: str, *, run_id: str = "", include_raw: bool = True,
          app_dir: Optional[Path] = None, log=None) -> Dict[str, object]:
    """按 :func:`plan` 的清单删除，返回实际删掉的数量与字节数。"""
    out = plan(root, run_id=run_id, include_raw=include_raw, app_dir=app_dir)
    removed = 0
    freed = 0
    errors: List[str] = []
    for item in out["items"]:
        path = Path(str(item["path"]))
        kind = item["kind"]
        if kind == "probe":
            pass
        elif kind in ("preview", "raw", "tasks"):
            if not _inside(path, Path(root)):
                continue
        elif not _inside(path, Path(app_dir) if app_dir else _app_dir()):
            continue
        try:
            _remove(path)
        except OSError as error:
            errors.append(f"{path}: {error}")
            if log:
                log(f"清理失败：{path}（{error}）")
            continue
        removed += 1
        freed += int(item["size"])
        if log:
            log(f"已删除 {path}")
    preview = Path(root) / "preview"
    try:
        if preview.is_dir() and not any(preview.iterdir()):
            preview.rmdir()
    except OSError:
        pass
    return {"removed": removed, "freed": freed, "errors": errors}


def describe(result: Dict[str, object]) -> str:
    freed = int(result.get("freed", 0)) / (1024 ** 3)
    removed = int(result.get("removed", 0))
    errors = result.get("errors") or []
    text = f"已清理 {removed} 项，释放 {freed:.2f} GB"
    if errors:
        text += f"；{len(errors)} 项没删掉（被占用或无权限）"
    return text
