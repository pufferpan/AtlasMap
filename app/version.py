"""版本号与构建时间（打包脚本会改写 BUILD）。"""
from __future__ import annotations

VERSION = "1.0"
BUILD = "2026-11-05.export-quality"
TITLE = "AtlasMap · 地图导出器"


def stamp() -> str:
    return f"{VERSION}+{BUILD}"
