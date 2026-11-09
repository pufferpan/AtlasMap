"""HyperOS 那版的流动光斑背景（D:/HyperOS.html 里那段 WebGL 的 Qt 复刻）。

原版是一张全屏片元着色器：黑底 + 四个超大柔光球，球心按
`x += sin(t + y) * 0.1`、`y += cos(t + x) * 0.1` 缓慢游走，球体之间用
`smoothstep(rad, 0, d)` 混色，最后再用一层柏林噪声提亮去饱和。

这里不做噪声（Qt 里太贵），保留最出效果的「四个游走的柔光球」：

    from app.glow import paint_glow
    paint_glow(painter, rect, time_seconds, palette="dark", strength=1.0)

为了 60fps 下不卡，内部按 1/3 分辨率画到 QImage 再放大贴回去。
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

Vec3 = Tuple[float, float, float]

# 球心 (x, y, radius)，都是 0~1 的相对坐标，跟原版 params.points 一致
POINTS_DARK: Sequence[Tuple[float, float, float]] = (
    (0.63, 0.50, 0.88), (0.69, 0.75, 0.80), (0.17, 0.66, 0.81), (0.14, 0.24, 0.72))
COLORS_DARK: Sequence[Vec3] = (
    (0.00, 0.31, 0.58), (0.53, 0.29, 0.15), (0.46, 0.06, 0.27), (0.16, 0.12, 0.45))

POINTS_LIGHT: Sequence[Tuple[float, float, float]] = (
    (0.67, 0.42, 1.00), (0.69, 0.75, 1.00), (0.14, 0.71, 0.95), (0.14, 0.27, 0.80))
COLORS_LIGHT: Sequence[Vec3] = (
    (0.57, 0.76, 0.98), (0.98, 0.85, 0.68), (0.98, 0.75, 0.93), (0.73, 0.70, 0.98))

_BASE_DARK = QColor(4, 5, 9)
_BASE_LIGHT = QColor(10, 12, 20)


def _palette(name: str):
    if str(name).lower() == 'red':
        return POINTS_DARK, ((.65,.10,.13),(.45,.08,.16),(.70,.22,.15),(.38,.08,.15)), QColor('#24090d')
    if str(name).lower() == "office":
        return POINTS_DARK, ((0.24, 0.47, 0.76), (0.12, 0.29, 0.55),
                             (0.18, 0.37, 0.65), (0.30, 0.51, 0.78)), QColor("#2B579A")
    if str(name).lower() in ("light", "bright", "white"):
        return POINTS_LIGHT, COLORS_LIGHT, _BASE_LIGHT
    return POINTS_DARK, COLORS_DARK, _BASE_DARK


def render_glow(width: int, height: int, time_s: float, palette: str = "dark",
                strength: float = 1.0, divisor: int = 3) -> QImage:
    """把光斑画到一张低分辨率图上（调用方负责放大）。"""
    d = max(1, int(divisor))
    w = max(2, int(width) // d)
    h = max(2, int(height) // d)
    points, colors, base = _palette(palette)

    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(base)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    t = float(time_s)
    # 原版：point.x += sin(t + y) * 0.1;  point.y += cos(t + x) * 0.1
    # 半径是 UV 单位（0.8 左右），在屏幕上是一个椭圆：x 方向 rad*w，y 方向 rad*h
    for idx, (px, py, rad) in enumerate(points):
        cx = px + math.sin(t + py) * 0.10
        cy = py + math.cos(t + px) * 0.10
        rw = max(0.05, float(rad)) * w
        rh = max(0.05, float(rad)) * h
        col = colors[idx]
        alpha = int(max(0, min(255, 235 * float(strength))))
        rgb = [min(255, int((c ** 0.85) * 255)) for c in col]
        painter.save()
        painter.translate(cx * w, cy * h)
        painter.scale(rw, rh)
        grad = QRadialGradient(QPointF(0.0, 0.0), 1.0)
        grad.setColorAt(0.0, QColor(*rgb, alpha))
        grad.setColorAt(0.35, QColor(*rgb, int(alpha * 0.92)))
        grad.setColorAt(0.70, QColor(*rgb, int(alpha * 0.45)))
        grad.setColorAt(1.0, QColor(*rgb, 0))
        painter.fillRect(QRectF(-1.0, -1.0, 2.0, 2.0), grad)
        painter.restore()
    # 轻微暗角：原版黑底 + 光斑，四角要能回落到接近黑
    painter.setBrush(Qt.NoBrush)
    vig = QRadialGradient(QPointF(w * 0.5, h * 0.5), max(w, h) * 0.78)
    vig.setColorAt(0.45, QColor(0, 0, 0, 0))
    vig.setColorAt(1.0, QColor(0, 0, 0, 24 if palette == "office" else 120))
    painter.fillRect(QRectF(0, 0, w, h), vig)
    painter.end()
    return img


def paint_glow(painter: QPainter, rect, time_s: float, palette: str = "dark",
               strength: float = 1.0, opacity: float = 1.0) -> None:
    """在给定矩形里铺一层流动光斑（会自动缩放贴图）。"""
    w = int(rect.width())
    h = int(rect.height())
    if w < 8 or h < 8 or opacity <= 0.01:
        return
    img = render_glow(w, h, time_s, palette, strength)
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setOpacity(max(0.0, min(1.0, float(opacity))))
    painter.drawImage(QRectF(rect), img)
    painter.restore()


class GlowBackdrop(QWidget):
    """整屏光斑背景：自己维持 30fps 的时钟，随时序慢慢流动。"""

    def __init__(self, parent=None, palette: str = "dark", strength: float = 1.0,
                 interval: int = 33) -> None:
        super().__init__(parent)
        self._palette = palette
        self._strength = strength
        self._t = 0.0
        self._image: QImage | None = None
        self._image_key = (-1, -1)
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(interval)))
        self._timer.timeout.connect(self._tick)

    # ---- 生命周期 ------------------------------------------------------ #
    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_palette(self, name: str) -> None:
        self._palette = name
        self.update()

    def _tick(self) -> None:
        self._t += self._timer.interval() / 1000.0
        self.update()

    # ---- 绘制 ---------------------------------------------------------- #
    def paintEvent(self, _event) -> None:                       # noqa: N802
        p = QPainter(self)
        key = (self.width(), self.height())
        if self._image is None or self._image_key != key:
            self._image_key = key
            self._image = None
        img = render_glow(self.width(), self.height(), self._t, self._palette,
                          self._strength)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(self.rect(), img)

    def showEvent(self, event) -> None:                         # noqa: N802, D102
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:                         # noqa: N802, D102
        self.stop()
        super().hideEvent(event)
