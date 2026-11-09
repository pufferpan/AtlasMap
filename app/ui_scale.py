"""界面缩放适配：不同机器（100% / 125% / 150% / 4K）上别把界面挤爆。

Qt6 自己会把「逻辑像素」乘上系统缩放，所以我们的固定 px 在视觉上是跟着放大的；
真正会出问题的是**可用逻辑尺寸变小**了（1366×768 @125% 只剩 ~1093×614），
窗口按 1500×940 开、卡片按 140px 排，就会挤出屏幕 / 溢出布局。

这里的约定：
* `avail()`   当前屏幕可用区域（逻辑像素）
* `fit(w, h)` 把期望尺寸收进屏幕的 92%，并给一个跟着 DPI 走的最小值
* `ui_scale()` 字号/卡片这类"跟着文字走"的尺寸用这个系数
* `set_ui_scale(x)` 允许用 `ATLASMAP_UI_SCALE` 手动覆盖（排查用）
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

_OVERRIDE: Optional[float] = None


def _app():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:                                     # noqa: BLE001
        return None
    return QApplication.instance()


def avail() -> Tuple[int, int]:
    """当前屏幕可用宽高（逻辑像素，已排除任务栏）。"""
    app = _app()
    if app is None:
        return (1500, 940)
    try:
        screen = app.primaryScreen()
        if screen is None:
            return (1500, 940)
        r = screen.availableGeometry()
        return (max(640, r.width()), max(480, r.height()))
    except Exception:                                     # noqa: BLE001
        return (1500, 940)


def dpi_ratio() -> float:
    app = _app()
    if app is None:
        return 1.0
    try:
        screen = app.primaryScreen()
        dpi = float(screen.logicalDotsPerInch()) if screen is not None else 96.0
    except Exception:                                     # noqa: BLE001
        return 1.0
    return max(0.75, min(2.0, dpi / 96.0))


def ui_scale() -> float:
    """文字/卡片用的缩放系数（1.0 = 100%）。"""
    if _OVERRIDE is not None:
        return _OVERRIDE
    env = (os.environ.get("ATLASMAP_UI_SCALE") or "").strip()
    if env:
        try:
            return max(0.7, min(2.0, float(env)))
        except ValueError:
            pass
    return max(1.0, min(1.4, dpi_ratio()))


def set_ui_scale(value: Optional[float]) -> None:
    global _OVERRIDE
    _OVERRIDE = None if value is None else max(0.7, min(2.0, float(value)))


def px(value: float) -> int:
    """把设计稿像素换算成当前缩放下的逻辑像素。"""
    return int(round(float(value) * ui_scale()))


def fit(width: int, height: int, margin: float = 0.92) -> Tuple[int, int]:
    """把窗口期望尺寸收进屏幕可用区域的 `margin`。"""
    aw, ah = avail()
    return (max(640, min(int(width), int(aw * margin))),
            max(440, min(int(height), int(ah * margin))))


def min_size(width: int, height: int, margin: float = 0.62) -> Tuple[int, int]:
    """最小尺寸：既不超过屏幕，也不小于可用区域的一半左右。"""
    aw, ah = avail()
    return (max(640, min(int(width), int(aw * margin))),
            max(420, min(int(height), int(ah * margin))))
