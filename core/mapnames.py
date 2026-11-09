"""地图代号 ↔ 游戏内中文名。

数据来自 pak 里的两张表（见 core/mapnames.json 的 _source）：
  * `DataTables/MapInfo.uasset`            代号（行名）→ MapConfigMapID
  * `R13N/Common/Base/DataTables/MapThumbnailTable.uasset`  MapID → 中文名
表里查不到的（比如 Mogadishu 只在文案表里出现）单独标注来源。

对外只有两个函数：
  cn_of(name) -> (中文名, 说明)      # 说明可能为空
  label(name) -> "Dam Iris Long3（代号 Dam_Iris_Long3）"
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Tuple

def _json_path() -> str:
    """打包后 mapnames.json 在 `_MEIPASS/core/`（或 exe 旁的 core/），源码态就在本文件旁边。"""
    import sys
    cands = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(os.path.join(meipass, "core", "mapnames.json"))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "executable", "") else ""
    if exe_dir:
        cands.append(os.path.join(exe_dir, "core", "mapnames.json"))
        cands.append(os.path.join(exe_dir, "_internal", "core", "mapnames.json"))
    try:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapnames.json"))
    except NameError:
        pass
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[-1] if cands else "mapnames.json"


_JSON = _json_path()

_cache: Dict[str, dict] = {}
_rules = []


def _load() -> None:
    global _cache, _rules
    if _cache:
        return
    try:
        import io
        with io.open(_JSON, encoding="utf-8") as source:
            data = json.load(source)
    except Exception:                       # noqa: BLE001
        data = {}
    _cache = {k: v for k, v in (data.get("maps") or {}).items()}
    _rules = list(data.get("prefix_rules") or [])


def _strip_physx(name: str) -> Tuple[str, str]:
    """PhysXShared_X → (X, '（物理共享层）')。"""
    for rule in _rules:
        p = str(rule.get("prefix") or "")
        if p and name.startswith(p):
            return name[len(p):].lstrip("_") or name, str(rule.get("suffix") or "")
    return name, ""


def _lookup(name: str) -> dict:
    _load()
    hit = _cache.get(name)
    if hit:
        return hit
    # 逐段剥掉尾部（Dam_Iris_Long3 → Dam_Iris_Long → Dam_Iris）
    parts = name.split("_")
    while len(parts) > 1:
        parts.pop()
        key = "_".join(parts)
        hit = _cache.get(key)
        if hit:
            return hit
    return {}


def cn_of(name: str) -> Tuple[str, str]:
    """返回 (中文名, 说明)；查不到时中文名回退成代号本身、说明写「未收录」。"""
    base, suffix = _strip_physx(str(name or ""))
    hit = _lookup(base)
    if not hit:
        return str(name), "未收录中文名"
    cn = str(hit.get("cn") or base)
    note = str(hit.get("note") or "")
    extra = " ".join(x for x in (note, suffix.strip("（）")) if x)
    if suffix and base != name:
        cn = f"{cn}{suffix}" if suffix.startswith("（") else f"{cn} {suffix}"
    return cn, extra


def label(name: str, *, fallback: str = "") -> str:
    """给界面用的一行标题：`中文名`（代号放副标题里，这里只给中文）。"""
    cn, _note = cn_of(name)
    return cn or fallback or str(name)


def subtitle(name: str) -> str:
    cn, note = cn_of(name)
    bits = [f"代号 {name}"]
    if note:
        bits.append(note)
    return " · ".join(bits)


def search_text(name: str) -> str:
    """搜索框匹配用：中文 + 代号拼一起。"""
    cn, note = cn_of(name)
    return f"{cn} {name} {note}".lower()


def known() -> Dict[str, dict]:
    _load()
    return {name:row for name,row in _cache.items() if row.get('selectable', True)}
