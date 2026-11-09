"""开屏加载窗 —— 版式照 Office 启动卡（用户给的 Word 2019 图）来做。

    左上角   logo + "PufferPan"
    正中间   大号软件名 "AtlasMap"，下面一行小字副标题
    左下角   "正在启动…"（随后换成真实进度文字）
    最底部   一条细进度条（原图没有，这里要显示真实加载量）

使用固定的透明窗口作为画布，只在画布内展开卡片，减少系统合成与布局抖动。
恢复地图导出器原有的流动渐变，加载完成后平滑展开并交给主窗口。
"""
from __future__ import annotations

import os
import sys
import time as _time
from typing import Optional

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, QTimer)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontDatabase,
                           QFontMetricsF, QLinearGradient, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from app import fluent_api as F
from app.transitions import SurfaceWindow
from app.glow import render_glow

_DBG = bool(os.environ.get("ATLASMAP_SPLASH_DEBUG"))


def _mark(label: str) -> None:
    if _DBG:
        print(f"[splash] {_time.monotonic():.3f} {label}", flush=True)


# 仿 Office 启动卡的比例（原图 553×342）
SMALL_W = 560
SMALL_H = 346
EXPAND_MS = 760
APPEAR_MS = 200
LOGO_H = 30            # 地图导出器原始 logo 高度
BAR_H = 3              # 贴底滚动进度条的高度
TICK_MS = 16

CARD_TOP = QColor("#1f4e9c")
CARD_BOTTOM = QColor("#173f80")
ACCENT = QColor("#4cc2ff")


def logo_path() -> Optional[str]:
    """优先用横排 wordmark（左上角 logo，用户给的 LOGO2.png）。
    原图是深色字形 + 透明底，画在蓝色卡片上会看不见，所以另存了一份
    「保留 alpha、颜色刷白」的 logo_wordmark_light.png 排在前面。"""
    base = getattr(sys, "_MEIPASS", None)
    roots = []
    if base:
        roots.append(os.path.join(base, "assets"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(here, "assets"))
    for name in ("maplogo.png", "logo_wordmark_light.png", "logo_wordmark.png",
                 "logo_nobg.png", "logo.png"):
        for root in roots:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
    return None


# 标题用的粗体字（随包带一份 Noto Sans SC 的子集，只留拉丁字母/数字/标点）
_TITLE_FAMILY = {"tried": False, "family": None}


def title_font_path() -> Optional[str]:
    base = getattr(sys, "_MEIPASS", None)
    roots = []
    if base:
        roots.append(os.path.join(base, "assets", "fonts"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(here, "assets", "fonts"))
    # MiSans 优先（用户指定），没有就退回原来那份 Noto 子集
    for name in ("AtlasMap-MiSans-Bold.ttf", "AtlasMap-Bold.ttf"):
        for root in roots:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
    return None


def _title_family() -> Optional[str]:
    """注册随包字体；失败就返回 None（QFont 用默认家族 + Bold 凑合）。"""
    if _TITLE_FAMILY["tried"]:
        return _TITLE_FAMILY["family"]      # type: ignore[return-value]
    _TITLE_FAMILY["tried"] = True
    path = title_font_path()
    if path:
        try:
            fid = QFontDatabase.addApplicationFont(path)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
            if fams:
                _TITLE_FAMILY["family"] = fams[0]
                _mark(f"title font -> {fams[0]} ({os.path.basename(path)})")
        except Exception:                                    # noqa: BLE001
            pass
    return _TITLE_FAMILY["family"]      # type: ignore[return-value]


def _title_font(px: int, bold: bool = True) -> QFont:
    fam = _title_family()
    font = QFont(fam) if fam else QFont()
    font.setPixelSize(px)
    if bold:
        font.setWeight(QFont.Weight.Bold)
    return font


DARK_TOP = QColor("#1b1c20")
DARK_BOTTOM = QColor("#131417")


def _lerp(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def _mix_colors(t: float):
    return _lerp(CARD_TOP, DARK_TOP, t), _lerp(CARD_BOTTOM, DARK_BOTTOM, t)


def _logo_pixmap() -> Optional[QPixmap]:
    path = logo_path()
    if not path:
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    return pm.scaledToHeight(LOGO_H, Qt.SmoothTransformation)


class _Card(QWidget):
    """Decorative animated background with native Fluent progress and close controls."""

    def __init__(self, title: str, subtitle: str, brand: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._brand = brand
        self._status = "正在启动…"
        self._fraction = None
        self._content_opacity = 1.0
        self._bg_mix = 0.0      # 0 = Office 蓝卡, 1 = 主窗口深色（长大时渐变过去）
        self._reveal = 0.0      # 软件名滑入/擦除的进度（0 → 1）
        self._phase = 0.0       # 底部滚动亮块的相位（0 → 1 循环）
        self._glow_time = 0.0
        self._glow_frame = None
        self._glow_key = None
        self._logo = _logo_pixmap()
        self._close_hover = False
        self._close_rect = QRect()
        self.progress_bar=F.ProgressBar(self)
        self.progress_bar.setTextVisible(False)
        self.close_button=F.TransparentToolButton('✕',self)
        self.close_button.clicked.connect(lambda:self.window().close())

    # bg_mix 必须是 Qt Property，QPropertyAnimation 才认
    def _get_bg_mix(self) -> float:
        return self._bg_mix

    def _set_bg_mix(self, value: float) -> None:
        self._bg_mix = max(0.0, min(1.0, float(value)))
        self.update()

    bgMix = Property(float, _get_bg_mix, _set_bg_mix)

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = max(0.0, min(1.0, float(value)))
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)

    def _get_content_opacity(self):
        return self._content_opacity

    def _set_content_opacity(self, value):
        self._content_opacity = float(value)
        self.update()

    contentOpacity = Property(float, _get_content_opacity, _set_content_opacity)

    def set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.update()

    def set_fraction(self, value) -> None:
        self._fraction = None if value is None else max(0.0, min(1.0, float(value)))
        self.progress_bar.setRange(0,0 if self._fraction is None else 1000)
        if self._fraction is not None:self.progress_bar.setValue(round(self._fraction*1000))
        self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.progress_bar.setGeometry(12,self.height()-7,max(1,self.width()-24),6)
        self.close_button.setGeometry(self.width()-47,14,32,32)

    # ---- 绘制 ---------------------------------------------------------- #
    def paintEvent(self, _event) -> None:                       # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        pad = max(20, int(h * 0.085))

        top, bottom = _mix_colors(self._bg_mix)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.fillRect(0, 0, w, h, grad)

        # Preserve the original multicolour fog, cached at reduced resolution.
        # Its clock is independent of the progress bar's looping phase.
        p.fillRect(0, 0, w, h, QColor(5, 6, 10, 168))
        glow_key = (w, h, int(self._glow_time * 30))
        if glow_key != self._glow_key:
            self._glow_frame = render_glow(w, h, self._glow_time, 'dark', .95)
            self._glow_key = glow_key
        p.save()
        p.setOpacity(.95 * (1.0 - self._bg_mix))
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(self.rect()), self._glow_frame)
        p.restore()

        if self._content_opacity <= 0.001:
            return
        p.setOpacity(self._content_opacity)

        # 左上角：只画横排 logo（LOGO2.png），不再画 PufferPan 文字
        if self._logo is not None and not self._logo.isNull():
            p.drawPixmap(pad, pad - 4, self._logo)

        # 右上角关闭按钮
        size = 26
        # 中间：软件名（整串从右侧滑到正中，非线性）+ 从右往左的渐变擦除 + 副标题
        big = _title_font(max(34, int(h * 0.17)))
        p.setFont(big)
        fm = QFontMetricsF(big)
        total = fm.horizontalAdvance(self._title)
        # 滑入用强 ease-out（三次方），从卡片右半边滑到正中：位移量与 reveal 非线性相关
        e = 1.0 - (1.0 - self._reveal) ** 3.4
        off = (1.0 - e) * (w * 0.34)                         # 从右侧 1/3 屏宽处滑进来
        baseline = int(h * 0.28) + int(h * 0.20)
        if self._reveal > 0.002:
            x0 = (w - total) / 2.0 + off
            box = QRectF(x0, baseline - fm.ascent(), total + 4, fm.height())
            p.save()
            p.setOpacity(self._content_opacity * min(1.0, 0.25 + 0.75 * e))
            if self._reveal >= 0.985:
                # 收尾：整串已经是实心的了，别再让渐变把左边拖成半透明
                p.setPen(QColor(255, 255, 255, 246))
            else:
                # 渐变擦除：右边先显、左边后显（用带 alpha 的渐变画笔填字形）
                # 擦除在 reveal 走到 0.85 时就结束了，剩下 15% 只是把实心度补满。
                plan = min(1.0, self._reveal / 0.85)
                front = 1.0 - plan * 1.30                 # 1 → -0.3，从左往右推
                brush = QLinearGradient(box.left(), 0.0, box.left() + total, 0.0)
                lo = max(0.0, min(1.0, front - 0.02))
                hi = max(lo, min(1.0, front + 0.22))
                brush.setColorAt(0.0, QColor(255, 255, 255, 0))
                brush.setColorAt(lo, QColor(255, 255, 255, 0))
                brush.setColorAt(hi, QColor(255, 255, 255, 246))
                brush.setColorAt(1.0, QColor(255, 255, 255, 246))
                p.setPen(QPen(brush, 1))
            p.drawText(box, Qt.AlignLeft | Qt.AlignTop, self._title)
            p.restore()

        sub = QFont(self.font())
        sub.setPixelSize(max(12, int(h * 0.05)))
        p.setFont(sub)
        p.setPen(QColor(255, 255, 255, 190))
        p.drawText(QRect(0, int(h * 0.50), w, int(h * 0.10)),
                   Qt.AlignHCenter | Qt.AlignTop, self._subtitle)

        # 左下角：状态
        st = QFont(self.font())
        st.setPixelSize(max(12, int(h * 0.045)))
        p.setFont(st)
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(QRect(pad, h - pad - 24, w - pad * 2, 22),
                   Qt.AlignLeft | Qt.AlignVCenter, self._status)



class SplashWindow(SurfaceWindow):
    def __init__(self, title="AtlasMap", subtitle="地图导出器",
                 brand="PufferPan", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._status = "正在启动…"
        self._target = None
        self._shown_fraction = 0.0
        self._expanding = False
        self._card = _Card(title, subtitle, brand, self)
        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.PreciseTimer)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._last_tick = _time.monotonic()
        self._elapsed = 0.0
        self.resize(SMALL_W, SMALL_H)
        self.surfaceRect = self.rect()

    def _layout_surface(self):
        self._card.setGeometry(self.surfaceRect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._expanding:
            self.surfaceRect = self.rect()

    def center_on_screen(self):
        area = self.screen().availableGeometry()
        w, h = min(SMALL_W, area.width()), min(SMALL_H, area.height())
        self.setGeometry(QRect(area.center().x() - w // 2,
                               area.center().y() - h // 2, w, h))
        self.show()
        self.raise_()
        self.activateWindow()
        anim = QPropertyAnimation(self._card, b"contentOpacity", self)
        anim.setDuration(APPEAR_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._enter = anim
        reveal = QPropertyAnimation(self._card, b"reveal", self)
        reveal.setDuration(720)
        reveal.setStartValue(0.0)
        reveal.setEndValue(1.0)
        reveal.start()
        self._reveal_anim = reveal

    def set_status(self, text):
        self._status = text
        self._card.set_status(text)

    def set_fraction(self, value):
        self._target = None if value is None else max(0.0, min(1.0, float(value)))

    def expand_to(self, target, done=None, duration=EXPAND_MS):
        if self._expanding:
            return
        self._expanding = True
        self._enter.stop()
        self._reveal_anim.stop()
        start = QRect(self.mapToGlobal(self._card.pos()), self._card.size())
        # 原生窗口只改一次；动画只改变内部卡片，避免每帧触发 DWM 和窗口布局。
        self.setGeometry(target)
        self.surfaceRect = start.translated(-target.topLeft())
        fade = QPropertyAnimation(self._card, b"contentOpacity", self)
        fade.setDuration(180)
        fade.setStartValue(self._card.contentOpacity)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.start()
        self._inner_out = fade
        bg = QPropertyAnimation(self._card, b"bgMix", self)
        bg.setDuration(duration)
        bg.setStartValue(self._card.bgMix)
        bg.setEndValue(1.0)
        bg.setEasingCurve(QEasingCurve.InOutCubic)
        bg.start()
        self._bg_anim = bg

        def finish():
            if done is not None:
                done()
            self._tick.stop()
            self.hide()

        self.animate_surface(self.rect(), duration, finish)

    def _on_tick(self):
        import math
        now = _time.monotonic()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        self._elapsed += dt
        self._card._phase = (self._elapsed / 1.15) % 1.0
        self._card._glow_time = self._elapsed
        if self._target is None:
            self._card.set_fraction(None)
        else:
            self._shown_fraction += (self._target - self._shown_fraction) * (1.0 - math.exp(-dt / 0.10))
            if abs(self._target - self._shown_fraction) < 0.002:
                self._shown_fraction = self._target
            self._card.set_fraction(self._shown_fraction)

    def showEvent(self, event):
        super().showEvent(event)
        self._last_tick = _time.monotonic()
        self._tick.start()

    def hideEvent(self, event):
        self._tick.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._tick.stop()
        for anim in (self._surface_anim, getattr(self, "_enter", None),
                     getattr(self, "_reveal_anim", None)):
            if anim is not None:
                anim.stop()
        super().closeEvent(event)

