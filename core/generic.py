"""其他游戏（通用 UE 工程）的支持：找包目录、探密钥、列 .umap、导出单张地图。

Delta Force 那一套有固定目录约定（DeltaForce/Content/Maps/…），别的游戏没有；
这里把「游戏根目录 → 找到 Content/Paks → 用哪套 profile → 缺哪些包的密钥」这些
通用步骤单独放一份，GUI 只负责问密钥和点按钮。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 常见 profile；默认按 UE5.3 起猜，用户也可以在界面上改
PROFILES = ("GAME_UE5_6", "GAME_UE5_5", "GAME_UE5_4", "GAME_UE5_3", "GAME_UE5_2",
            "GAME_UE5_1", "GAME_UE5_0", "GAME_UE4_27", "GAME_UE4_26", "GAME_UE4_25",
            "GAME_DeltaForce")

_FIND_LINE = re.compile(r"^\s*([\d,]+)\s+(.+\.umap)\s*$", re.IGNORECASE)
_HEX_KEY = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------- 目录与配置 --
def skip_names() -> Tuple[str, ...]:
    return ("windows", "program files", "program files (x86)", "programdata",
            "$recycle.bin", "system volume information")


def paks_dirs(root: str, max_depth: int = 3) -> List[str]:
    """在游戏根目录里找所有 `Content/Paks`（大写 Paks 也认），最多往下三层。"""
    base = Path(root)
    if not base.is_dir():
        return []
    found: List[str] = []
    try:
        for entry in base.iterdir():
            if entry.is_dir() and entry.name.lower() in skip_names():
                continue
            if entry.is_dir():
                _walk_paks(entry, 1, max_depth, found)
    except OSError:
        return []
    if (base / "Content" / "Paks").is_dir():
        found.append(str(base / "Content" / "Paks"))
    return found


def _walk_paks(folder: Path, depth: int, max_depth: int, found: List[str]) -> None:
    if depth > max_depth:
        return
    try:
        children = list(folder.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        if child.name.lower() == "paks" and child.parent.name.lower() == "content":
            found.append(str(child))
            continue
        _walk_paks(child, depth + 1, max_depth, found)


def write_config(path: str, game_root: str, profile: str = "GAME_UE5_3", *,
                 keyfile: str = "", oodle: str = "", recursive: bool = True,
                 mappings: str = "") -> str:
    """给导出器写一份最小配置；没有密钥文件也允许（未加密的包照样能挂）。"""
    data = {
        "PaksDirectory": str(game_root).replace("\\", "/"),
        "Recursive": bool(recursive),
        "KeyFile": str(keyfile or "").replace("\\", "/"),
        "OodlePath": str(oodle or "").replace("\\", "/"),
        "MappingsFile": str(mappings or "").replace("\\", "/"),
        "Game": profile or "GAME_UE5_3",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


# ------------------------------------------------------------------- 探密钥 --
def probe(exe: str, config: str, timeout: int = 300) -> Tuple[int, Optional[dict], str]:
    """跑 `probe`，返回 (退出码, 解析后的 JSON, stderr 末尾几行)。"""
    # 探测目录用完就删：以前每次「检测 / 填密钥」都会在 %TEMP% 留一个空壳目录。
    with tempfile.TemporaryDirectory(prefix="atlasmap-probe-") as folder:
        out = Path(folder) / "probe.json"
        command = [exe, "--config", config, "probe", str(out)]
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                 encoding="utf-8", errors="replace")
        except OSError as exc:
            return 2, None, str(exc)
        data = None
        if out.is_file():
            try:
                data = json.loads(out.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                data = None
    if data is None:
        start = run.stdout.find("{")
        if start >= 0:
            try:
                data = json.loads(run.stdout[start:])
            except ValueError:
                data = None
    return run.returncode, data, (run.stderr or "").strip()


def pending(probe_data: Optional[dict]) -> List[dict]:
    """还需要密钥的归档：加密、且没挂上。GUID 全零表示用主密钥。"""
    if not probe_data:
        return []
    result = []
    for row in probe_data.get("archives") or []:
        if not row.get("encrypted") or row.get("mounted"):
            continue
        guid = str(row.get("guid") or "").strip().lower()
        if set(guid) == {"0"}:
            guid = ""
        result.append({"file": row.get("file") or "?", "guid": guid})
    return result


def hex_key(value: str) -> str:
    """把用户输入整理成 32 字节小写 hex；`0x` 前缀、空格、短横线都接受。"""
    text = (value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    text = re.sub(r"[\s\-_:]", "", text)
    if not _HEX_KEY.match(text):
        raise ValueError("密钥需要 64 个十六进制字符（32 字节）")
    return text


def write_keys(path: str, main_key: str, guid_keys: Optional[Dict[str, str]] = None) -> str:
    """写一份导出器认识的 AesKeySet；主密钥为空时只用 GUID 密钥。"""
    entries = []
    for guid, key in (guid_keys or {}).items():
        g = (guid or "").strip().lower()
        if not g or set(g) == {"0"}:
            continue
        entries.append({"key": hex_key(key), "guid": g})
    data = {"Version": "custom", "MainKey": hex_key(main_key) if main_key else "",
            "Keys": entries}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
    return str(target)


# ------------------------------------------------------------------ 列地图 --
def parse_find(output: str) -> List[str]:
    """解析 `find .umap` 的输出：每行 `大小 路径`，去重保留顺序。"""
    seen, result = set(), []
    for line in (output or "").splitlines():
        match = _FIND_LINE.match(line)
        if not match:
            continue
        path = match.group(2).strip()
        if path.lower() in seen:
            continue
        seen.add(path.lower())
        result.append(path)
    return result


def list_maps(exe: str, config: str, limit: int = 0, timeout: int = 600) -> Tuple[int, List[str], str]:
    command = [exe, "--config", config, "find", ".umap"]
    if limit:
        command.append(str(limit))
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace")
    except OSError as exc:
        return 2, [], str(exc)
    return run.returncode, parse_find(run.stdout), (run.stderr or "").strip()


# ------------------------------------------------------------------ 导出 --
def _instances(out_dir: str) -> tuple:
    """返回 (levels, instances)，manifest 不存在时当 0。"""
    path = os.path.join(out_dir, "split", "manifest.json")
    try:
        with open(path, encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return 0, 0
    levels = data.get("levels") or []
    return len(levels), sum(int(row.get("instances") or 0) for row in levels)


def export_map(exe: str, config: str, vpath: str, out_dir: str, *,
               timeout: int = 3600) -> subprocess.CompletedProcess:
    """导出一个 .umap。

    UE 的关卡常常把真正的东西放在同目录的子关卡里，只按这个文件当 root 会导出空场景；
    所以第一次结果里一个实例都没有时，自动退回「整个目录」再导一次。
    """
    first = subprocess.run([exe, "--config", config, "umap", vpath, out_dir],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    if first.returncode != 0:
        return first
    levels, instances = _instances(out_dir)
    if instances > 0:
        return first
    folder = vpath.rsplit("/", 1)[0] + "/"
    if not folder or folder == vpath:
        return first
    second = subprocess.run([exe, "--config", config, "merge", folder, out_dir,
                             "--root", folder, "--all", "--split"],
                            capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
    if second.returncode != 0:
        return first
    merged = subprocess.CompletedProcess(
        first.args, 0,
        (first.stdout or "") + "\n[generic] 单文件没有实例，已改用上级目录重新导出：\n"
        + (second.stdout or ""),
        (first.stderr or "") + (second.stderr or ""))
    return merged
