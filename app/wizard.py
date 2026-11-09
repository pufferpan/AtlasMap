"""首次向导：欢迎、游戏目录、四步图文教程、完成。

保留三行截图入场；教程页右侧使用软件自身界面的配套截图。

配置与地图导出器共用 `%LOCALAPPDATA%\\AtlasMap\\settings.json`。
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QSequentialAnimationGroup, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from app import fluent_api as F
from app.glow import render_glow
from app.transitions import SurfaceWindow

from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from core import exporter
from app.wizard_tutorial import TUTORIALS, TutorialPreview


class _GamePaths:
    @staticmethod
    def _paks_under(root):
        root = str(root).replace(chr(92), "/").rstrip("/")
        for path in (root, root+"/Content/Paks", root+"/DeltaForce/Content/Paks", root+"/Game/DeltaForce/Content/Paks"):
            if os.path.isdir(path) and any(n.lower().endswith(".pak") for n in os.listdir(path)):
                return path
        return ""

    @staticmethod
    def set_game_root(root):
        cfg = exporter.load_settings()
        cfg["paks"] = _GamePaths._paks_under(root)
        exporter.save_settings(cfg)
        exporter.write_exporter_config(cfg)

    @staticmethod
    def find_game_root():
        cfg = exporter.load_settings()
        for path in [cfg.get("paks", ""), exporter.DEFAULT_PAKS]:
            if path and _GamePaths._paks_under(path):
                return str(path)
        return ""


L = _GamePaths

CONFIG = exporter.settings_path()


def _asset(name: str) -> str:
    """资源路径：打包版在 `_MEIPASS/assets`，源码态在 `项目根/assets`。"""
    base = getattr(sys, "_MEIPASS", None)
    roots = []
    if base:
        roots.append(os.path.join(base, "assets"))
    roots.append(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"))
    for root in roots:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return os.path.join(roots[-1], name)


BG = _asset("wizard_bg.png")
ROWS_JSON = _asset("wizard_rows.json")
LOGO = _asset("maplogo.png")

PRIMARY = "#2B579A"
PRIMARY_HOVER = "#376BB5"
INK = "#EAF4FF"
SUB = "#A9C4DE"
BAD = "#FF8A8A"
GOOD = "#7BE0A8"

TITLE_FONT = 34
BODY_FONT = 16


# ---------------------------------------------------------------- 配置 ----
def _read_cfg() -> dict:
    try:
        with open(CONFIG, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:                                        # noqa: BLE001
        return {}


def _write_cfg(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:                                        # noqa: BLE001
        pass


def needs_wizard() -> bool:
    """要不要跑首次向导（环境变量可强制开关）。"""
    env = (os.environ.get("ATLASMAP_WIZARD") or "").strip().lower()
    if env in ("0", "off", "no"):
        return False
    if env in ("1", "on", "yes"):
        return True
    if not L.find_game_root():
        return True
    return not bool(_read_cfg().get("wizard_done"))


def mark_done() -> None:
    cfg = _read_cfg()
    cfg["wizard_done"] = True
    _write_cfg(cfg)


# ------------------------------------------------------------- 背景控件 ----
class _Backdrop(QWidget):
    """底图铺满整屏 + 三条 45° 截图带子（可各自平移/淡入，用来做「从屏幕外飞进来」）。

    带子的位置和角度来自 `assets/wizard_rows.json`（`make_wizard_bg.py` 生成），
    所以「三行一起摆好」的静态图和「逐行飞入」的动画是同一套坐标，对得上。
    """

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._pix = QPixmap(path) if os.path.exists(path) else QPixmap()
        self._fallback = QPixmap(self._pix)
        if self._pix.isNull():
            self._pix = QPixmap(16, 9)
            self._pix.fill(QColor(11, 30, 51))
        self._canvas = (float(self._pix.width()), float(self._pix.height()))
        self._rows = []
        self._rows_animating = False
        self._wall_cache = None
        self._scaled = {}             # (id, w, h) -> 缩放过的 QPixmap 缓存
        self._base_scaled = None
        self._growing = False
        self._small = QPixmap()
        # HyperOS 那种流动光斑背景（替代原来的深蓝底图）
        self._glow_t = 0.0
        self._glow_start = time.monotonic()
        self._glow_image = None
        self._glow = QTimer(self)
        self._glow.setTimerType(Qt.PreciseTimer)
        self._glow.setInterval(16)
        self._glow.timeout.connect(self._tick_glow)
        self.load_rows(ROWS_JSON, os.path.dirname(path) or ".")

    def _tick_glow(self) -> None:
        self._glow_t = time.monotonic() - self._glow_start
        if self._glow_image is None or not self._growing:
            # 与原生窗口同尺寸的缓存；长大/收起时复用它，不逐帧分配大图。
            win = self.window()
            self._glow_image = render_glow(win.width(), win.height(), self._glow_t,
                                           "office", 0.22, divisor=4)
        self.update()

    def showEvent(self, event) -> None:                     # noqa: N802, D102
        super().showEvent(event)
        self._tick_glow()
        if not self._glow.isActive():
            self._glow.start()

    def hideEvent(self, event) -> None:                     # noqa: N802, D102
        self._glow.stop()
        super().hideEvent(event)

    # -- 素材 ---------------------------------------------------------- #
    def load_rows(self, meta_path: str, folder: str) -> bool:
        """按清单加载三条带子；没有清单就退回「整张静态图」，功能不受影响。"""
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:                                    # noqa: BLE001
            return False
        # Only replace the composed fallback after all three layers loaded.
        base = meta.get("base")
        base_pix = QPixmap()
        if base:
            path = os.path.join(folder, base)
            if os.path.exists(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    base_pix = pix
        canvas = meta.get("canvas") or []
        if len(canvas) == 2 and all(canvas):
            self._canvas = (float(canvas[0]), float(canvas[1]))
        rows = []
        for item in meta.get("rows") or []:
            path = os.path.join(folder, item.get("file") or "")
            if not os.path.exists(path):
                continue
            pix = QPixmap(path)
            if pix.isNull():
                continue
            rows.append({"pix": pix,
                         "x": float(item.get("x") or 0),
                         "y": float(item.get("y") or 0),
                         "dx": 0.0, "dy": 0.0, "alpha": 1.0})
        if len(rows) != 3:
            return False
        if not base_pix.isNull():
            self._pix = base_pix
        self._rows = rows
        self._wall_cache = None
        self._scaled.clear()
        self._base_scaled = None
        # 入场期拉伸用的低分辨率底图：基于「干净底图」生成，且别带卡片
        self._small = self._pix.scaled(760, 470, Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
        self.update()
        return bool(rows)

    # -- 动画面板要用的三个口子 ---------------------------------------- #
    def set_row(self, index: int, dx=None, dy=None, alpha=None) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        if dx is not None:
            row["dx"] = float(dx)
        if dy is not None:
            row["dy"] = float(dy)
        if alpha is not None:
            row["alpha"] = max(0.0, min(1.0, float(alpha)))
        self.update()

    def row_count(self) -> int:
        return len(self._rows)

    def reset_rows(self) -> None:
        self._rows_animating = False
        for i in range(len(self._rows)):
            self.set_row(i, dx=0.0, dy=0.0, alpha=1.0)

    def animate_rows(self) -> None:
        self._rows_animating = True
        self.update()

    def _wall(self):
        """Cache the original three-row composition independently of animation state."""
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if self._wall_cache is not None and self._wall_cache[0] == key:
            return self._wall_cache[1]
        dpr = key[2]
        wall = QPixmap(QSize(max(1, round(key[0] * dpr)), max(1, round(key[1] * dpr))))
        wall.setDevicePixelRatio(dpr)
        wall.fill(Qt.transparent)
        p = QPainter(wall)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s, ox, oy = self._cover()
        for row in self._rows:
            pix = row["pix"]
            p.drawPixmap(QRectF(ox + row["x"] * s, oy + row["y"] * s,
                                pix.width() * s, pix.height() * s), pix, QRectF(pix.rect()))
        p.end()
        self._wall_cache = (key, wall)
        return wall

    # -- 绘制 ---------------------------------------------------------- #
    def _cover(self):
        """底图按 cover 铺满，返回 (缩放比例, 左上角偏移)。"""
        cw, ch = self._canvas
        if cw <= 0 or ch <= 0 or not self.width() or not self.height():
            return 1.0, 0.0, 0.0
        s = max(self.width() / cw, self.height() / ch)
        return s, (self.width() - cw * s) / 2.0, (self.height() - ch * s) / 2.0

    def _scaled_base(self):
        key = ("base", self.width(), self.height())
        if self._base_scaled is not None and self._base_scaled[0] == key:
            return self._base_scaled[1]
        cw, ch = self._canvas
        s, _, _ = self._cover()
        target = QSize(max(1, int(round(cw * s))), max(1, int(round(ch * s))))
        pix = self._pix.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._base_scaled = (key, pix)
        return pix

    def _scaled_row(self, index: int, s: float):
        row = self._rows[index]
        pix = row["pix"]
        key = (index, int(round(pix.width() * s)), int(round(pix.height() * s)))
        hit = self._scaled.get(key)
        if hit is not None:
            return hit
        scaled = pix.scaled(QSize(max(1, key[1]), max(1, key[2])),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if len(self._scaled) > 6:
            self._scaled.clear()
        self._scaled[key] = scaled
        return scaled

    def set_growing(self, on: bool) -> None:
        """窗口「长大」期间用低分辨率底图拉伸，别每帧重采样 2560×1600（那是卡顿主因）。"""
        self._growing = bool(on)
        self.update()

    def paintEvent(self, event) -> None:                    # noqa: N802, D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, not self._growing)
        s, ox, oy = self._cover()
        # 背景：HyperOS 风的流动光斑（原版是 WebGL 片元着色器，这里用 Qt 复刻）
        painter.fillRect(self.rect(), QColor(PRIMARY))
        if self._glow_image is not None:
            painter.drawImage(QRectF(self.rect()), self._glow_image)
        if not self._rows:
            # The old code discarded wizard_bg.png when its layer manifest failed.
            # Keep the original screenshot wall visible in that case as well.
            if not self._fallback.isNull() and not self._rows_animating:
                painter.drawPixmap(QRectF(ox, oy, self._canvas[0] * s, self._canvas[1] * s),
                                   self._fallback, QRectF(self._fallback.rect()))
            painter.end()
            return
        if not self._rows_animating:
            if self._growing:
                # Resize the source layers directly during the short transition;
                # rebuilding the full-resolution wall every frame would stutter.
                for row in self._rows:
                    pix = row["pix"]
                    painter.drawPixmap(QRectF(ox + row["x"] * s, oy + row["y"] * s,
                                               pix.width() * s, pix.height() * s),
                                       pix, QRectF(pix.rect()))
            else:
                painter.drawPixmap(QPointF(0, 0), self._wall())
            painter.end()
            return
        for i, row in enumerate(self._rows):
            if row["alpha"] <= 0.004:                        # 入场前整条是透明的，直接跳过
                continue
            painter.save()
            painter.setOpacity(row["alpha"])
            x = ox + (row["x"] + row["dx"]) * s
            y = oy + (row["y"] + row["dy"]) * s
            if self._growing:
                pix = row["pix"]
                painter.drawPixmap(QRectF(x, y, pix.width() * s, pix.height() * s),
                                   pix, QRectF(pix.rect()))
            else:
                pix = self._scaled_row(i, s)
                painter.drawPixmap(QPointF(x, y), pix)
            painter.restore()
        painter.end()


# --------------------------------------------------------------- 面板 ----
def _Panel(parent=None):
    panel=F.SimpleCardWidget(parent)
    panel.setMaximumWidth(620)
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(46, 40, 46, 34)
    lay.setSpacing(0)

    if os.path.exists(LOGO):
        logo = QLabel("AtlasMap")
        logo.setStyleSheet(
            "color: #FFFFFF; border: 0; background: transparent;"
            " font-size: 27px; font-weight: 800; letter-spacing: 1px;")
        lay.addWidget(logo)
        lay.addSpacing(24)

    panel.title = QLabel()
    panel.title.setWordWrap(True)
    panel.title.setStyleSheet(
        f"color: {INK}; border: 0; background: transparent;"
        f" font-size: {TITLE_FONT}px; font-weight: 700;")
    lay.addWidget(panel.title)
    lay.addSpacing(14)

    panel.body = QLabel()
    panel.body.setWordWrap(True)
    panel.body.setStyleSheet(
        f"color: {SUB}; border: 0; background: transparent;"
        f" font-size: {BODY_FONT}px; line-height: 165%;")
    lay.addWidget(panel.body)

    lay.addSpacing(20)
    panel.bullets = QLabel("")
    panel.bullets.setWordWrap(True)
    panel.bullets.setStyleSheet(
        "color: #BBD5EA; border: 0; background: transparent;"
        " font-size: 14px;")
    lay.addWidget(panel.bullets)

    lay.addSpacing(18)
    panel.extra = QWidget()
    panel.extra.setStyleSheet("background: transparent; border: 0;")
    ex = QHBoxLayout(panel.extra)
    ex.setContentsMargins(0, 0, 0, 0)
    ex.setSpacing(12)
    lay.addWidget(panel.extra)
    lay.addSpacing(12)

    panel.status = QLabel("")
    panel.status.setWordWrap(True)
    panel.status.setStyleSheet(
        f"color: {SUB}; border: 0; background: transparent; font-size: 14px;")
    lay.addWidget(panel.status)
    lay.addStretch(1)

    panel.dots = QLabel("")
    panel.dots.setStyleSheet(
        "color: #6E93B5; border: 0; background: transparent; font-size: 18px;"
        " letter-spacing: 6px;")
    lay.addWidget(panel.dots)
    lay.addSpacing(10)
    return panel


def _panel_button(panel,text,primary=False):
    button=F.PrimaryPushButton(text) if primary else F.PushButton(text)
    button.setMinimumHeight(42)
    return button


# --------------------------------------------------------------- 向导 ----
class WizardWindow(SurfaceWindow):
    finished = Signal(bool)                                  # True=完成, False=跳过

    STEPS = 3 + len(TUTORIALS)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("AtlasMap · 首次设置")
        self.setWindowFlag(Qt.FramelessWindowHint, True)


        self._step = 0
        self._game_root = ""
        self._paks = ""
        self._closing = False
        self._intro = False            # 入场阶段：小窗 + 提示语，三条带子还没进来
        self._panel_intro_size = None  # 入场期面板固定尺寸（避免每帧重排中文）
        self._full_rect = QRect()
        self._intro_delay = QTimer(self)
        self._intro_delay.setSingleShot(True)
        self._intro_delay.timeout.connect(self._grow)

        self.bg = _Backdrop(BG, self)

        self.panel = _Panel(self)
        self.tutorial = TutorialPreview(_asset, self)
        self.next_btn = _panel_button(self.panel,"下一步", primary=True)
        self.next_btn.clicked.connect(self._on_next)
        self.back_btn = _panel_button(self.panel,"上一步")
        self.back_btn.clicked.connect(lambda: self._show_step(max(0, self._step-1)))

        self.skip_btn = F.TransparentToolButton("跳过设置", self.panel)
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(lambda: self._finish(False))
        self.panel.layout().insertWidget(self.panel.layout().count() - 1, self.skip_btn)
        self.panel.layout().setAlignment(self.skip_btn, Qt.AlignLeft)
        self.panel.layout().insertSpacing(self.panel.layout().count() - 1, 8)

        # 第二步才出现的两个按钮
        self.auto_btn = _panel_button(self.panel,"自动检测")
        self.auto_btn.clicked.connect(self._auto_detect)
        self.pick_btn = _panel_button(self.panel,"手动选择…", primary=False)
        self.pick_btn.clicked.connect(self._pick_dir)

        self._show_step(0)

    def _set_buttons(self, buttons) -> None:
        """按给定顺序重排按钮行（其余按钮隐藏）。"""
        row = self.panel.extra.layout()
        for btn in (self.auto_btn, self.pick_btn, self.next_btn, self.back_btn):
            btn.hide()
            row.removeWidget(btn)
        while row.count():                       # 清掉上一轮留下的弹簧
            item = row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
        for btn in buttons:
            btn.show()
            row.addWidget(btn)
        row.addStretch(1)
        row.invalidate()
        row.activate()
        self.panel.extra.updateGeometry()
        self.panel.extra.show()

    # -- 文字入场动画 ---------------------------------------------------- #
    def _stop_lines(self, slot):
        for group, widget, base in getattr(self, "_anims", {}).pop(slot, []):
            group.stop()
            widget.move(base)
            widget.graphicsEffect().setOpacity(1.0)
            group.deleteLater()

    def _animate_lines(self, targets, *, duration=420, stagger=55,
                       dist=14, slot="step"):
        if self._closing:
            return
        if not hasattr(self, "_anims"):
            self._anims = {}
        self._stop_lines(slot)
        self._anims[slot] = []
        self.panel.layout().activate()
        shown = 0
        for widget in targets:
            if widget is None or not widget.isVisible():
                continue
            if isinstance(widget, QLabel) and not widget.text():
                continue
            base = QPoint(widget.pos())
            eff = widget.graphicsEffect()
            if not isinstance(eff, QGraphicsOpacityEffect):
                eff = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(eff)
            eff.setOpacity(0.0)
            widget.move(base + QPoint(0, dist))
            sequence = QSequentialAnimationGroup(self)
            sequence.addPause(shown * stagger)
            group = QParallelAnimationGroup(sequence)
            for target, prop, start, end in (
                (eff, b"opacity", 0.0, 1.0),
                (widget, b"pos", base + QPoint(0, dist), base),
            ):
                anim = QPropertyAnimation(target, prop, group)
                anim.setDuration(duration)
                anim.setStartValue(start)
                anim.setEndValue(end)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                group.addAnimation(anim)
            sequence.addAnimation(group)
            sequence.finished.connect(lambda w=widget, b=base: w.move(b))
            self._anims[slot].append((sequence, widget, base))
            sequence.start()
            shown += 1

    # -- 布局 ---------------------------------------------------------- #
    def _layout_panel(self) -> None:
        """入场阶段面板**尺寸固定**、只跟着窗口居中 —— 每帧重排中文会重折行，
        那才是「长大过程卡顿」的真凶；等入场结束再按大窗口重排一次。"""
        rect = self.surfaceRect
        wid, hei = rect.width(), rect.height()
        if self._intro:
            if self._panel_intro_size is None:
                self._panel_intro_size = (max(320, int(wid * 0.86)),
                                          max(220, hei - 48))
            pw, ph = self._panel_intro_size
            pw = min(pw, max(320, wid - 40))
            ph = min(ph, max(220, hei - 40))
            self.panel.setGeometry(rect.x() + (wid - pw) // 2, rect.y() + (hei - ph) // 2, pw, ph)
        else:
            pw = min(max(360, int(wid * 0.44)), 620, max(1, wid - 40))
            ph = min(max(500, int(hei * 0.70)), 620, max(1, hei - 40))
            if 2 <= self._step < 2+len(TUTORIALS):
                ph = min(760,max(1,hei-60))
            self.panel.setGeometry(rect.x() + int(wid * 0.05), rect.y() + (hei - ph) // 2, pw, ph)
        if not self._intro:
            left = self.panel.geometry().right()+24
            self.tutorial.setGeometry(left, rect.y()+(hei-ph)//2,
                                      max(1,rect.right()-left-int(wid*.04)),ph)

    def _layout_surface(self):
        self.bg.setGeometry(self.surfaceRect)
        self._layout_panel()
        self.bg.lower()
        self.panel.raise_()
        self.tutorial.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._intro and not self._closing:
            self.surfaceRect = self.rect()

    # -- 开场：提示语 → 慢慢变大 → 三行截图飞进来 ----------------------- #
    def _row_starts(self):
        """三条带子各自的「屏幕外起点」（按当前窗口大小算，飞之前/飞都用这一份）。"""
        scale, _, _ = self.bg._cover()
        wid = (self.bg.width() or 760) / scale
        hei = (self.bg.height() or 470) / scale
        return [(wid * 1.10, -hei * 0.10),
                (wid * 1.18, hei * 0.42),
                (wid * 1.26, -hei * 0.55)]

    def _park_rows(self) -> None:
        """入场阶段先把三条带子停在屏幕外（不然小窗里就已经能看见背景图了）。"""
        self.bg.animate_rows()
        for i, (dx, dy) in enumerate(self._row_starts()):
            self.bg.set_row(i, dx=dx, dy=dy, alpha=0.0)

    def _intro_text(self) -> None:
        """小窗里先只说一句话，别急着上第一步。"""
        self._intro = True
        self.panel.title.setText("等一下…")
        self.panel.body.setText("我还没见过你诶，等一下，让我来带你设置一下吧！")
        self.panel.bullets.setText("")
        self.panel.status.setText("")
        self.panel.dots.setText("")
        self._set_buttons([])
        self.skip_btn.hide()
        self._park_rows()

    def _grow(self):
        if self._closing:
            return
        self.bg.set_growing(True)
        self.animate_surface(self.rect(), 820, self._fly_rows)

    def _fly_rows(self) -> None:
        """三条 45° 带子分别从屏幕外滑进来（错开 110ms，位置/透明度一起动）。"""
        if self._closing:
            return
        count = self.bg.row_count()
        if not count:
            self._finish_intro()
            return
        self.bg.set_growing(False)           # 窗口定下来了，底图换回高清
        starts = self._row_starts()
        for i in range(count):
            dx0, dy0 = starts[i % len(starts)]
            self.bg.set_row(i, dx=dx0, dy=dy0, alpha=0.0)   # 先站到屏幕外
        # 先准备高清带子，动画过程中只做平移与透明度变化。
        scale, _, _ = self.bg._cover()
        for i in range(count):
            self.bg._scaled_row(i, scale)
        self._row_group = QParallelAnimationGroup(self)
        for i in range(count):
            dx0, dy0 = starts[i % len(starts)]
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(760)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _tick(value, index=i, dx0=dx0, dy0=dy0):
                self.bg.set_row(index, dx=dx0 * (1.0 - value),
                                dy=dy0 * (1.0 - value),
                                alpha=min(1.0, value * 1.7))

            anim.valueChanged.connect(_tick)
            sequence = QSequentialAnimationGroup(self._row_group)
            sequence.addPause(85 * i)
            sequence.addAnimation(anim)
            self._row_group.addAnimation(sequence)
        self._row_group.finished.connect(self._finish_intro)
        self._row_group.start()

    def _finish_intro(self) -> None:
        """带子落位 → 上第一步文案（也是从下往上淡入）。"""
        if self._closing:
            return
        self._intro = False
        self.bg.set_growing(False)
        self._panel_intro_size = None
        self.bg.reset_rows()
        self.skip_btn.show()
        # 先按大窗口重排，再上第一步 —— 顺序反了的话，文字动画会拿旧位置当基准
        self._layout_panel()
        self._show_step(0)

    # -- 步骤 ---------------------------------------------------------- #
    def _show_step(self, index: int) -> None:
        self._step = index
        self._stop_lines('step')
        self.tutorial.animation.stop()
        self.tutorial.hide()
        self.panel.status.clear()
        teaching = 2 <= index < 2+len(TUTORIALS)
        self.panel.layout().setContentsMargins(*( (32,26,32,22) if teaching else (46,40,46,34)))
        self.panel.title.setStyleSheet(f'color:{INK};border:0;background:transparent;font-size:{28 if teaching else TITLE_FONT}px;font-weight:700;')
        self.panel.body.setStyleSheet(f'color:{SUB};border:0;background:transparent;font-size:{15 if teaching else BODY_FONT}px;')
        self._layout_panel()
        self.panel.status.setStyleSheet(
            f"color: {SUB}; border: 0; background: transparent; font-size: 14px;")
        if index == 0:
            self.panel.title.setText("你好呀！")
            self.panel.body.setText(
                "感谢你选择 AtlasMap！请跟着我们一步步来，"
                "先选好游戏目录，就能浏览和导出地图。")
            self.panel.bullets.setText(
                "·  浏览地图、选择导出范围、查看任务进度\n\n"
                "·  导出模型与材质，按地图源数据恢复灯光\n\n"
                "·  需要渲染时，在「进 UE」配置引擎与 Blender")
            self._set_buttons([self.next_btn])
            self.next_btn.setText("下一步")
            self.next_btn.setEnabled(True)
            self.panel.status.setText("")
        elif index == 1:
            self.panel.title.setText("接下来，选择我们要工作的目录")
            self.panel.body.setText(
                "我会读取该游戏的 Paks 包，不修改任何游戏文件。"
                "如果装在默认位置，直接点「自动检测」就行。")
            self.panel.bullets.setText("")
            self._set_buttons([self.auto_btn, self.pick_btn, self.next_btn])
            self.next_btn.setText("下一步")
            self.next_btn.setEnabled(bool(self._paks))
        elif 2 <= index < 2 + len(TUTORIALS):
            tutorial = TUTORIALS[index-2]
            self.panel.title.setText(tutorial['title'])
            self.panel.body.setText(tutorial['body'])
            self.panel.bullets.setText(tutorial['bullets'])
            self._set_buttons([self.back_btn, self.next_btn])
            self.next_btn.setText("下一步")
            self.next_btn.setEnabled(True)
            self._layout_panel()
            self.tutorial.show_tutorial(tutorial, animated=self.isVisible())
        else:
            self.panel.title.setText("准备好了！")
            self.panel.body.setText(
                "感谢你！现在软件已经准备好了，随时为你服务。"
                "从地图库选择地图开始；需要灯光预览时，打开「进 UE」。")
            self.panel.bullets.setText("")
            self._set_buttons([self.back_btn, self.next_btn])
            self.next_btn.setText("开始使用")
            self.panel.status.setText("")
            self.next_btn.setEnabled(True)
        self.panel.dots.setText("●" * (index + 1) + "○" * (self.STEPS - index - 1))
        if self.isVisible():
            self._animate_lines([self.panel.title, self.panel.body,
                                 self.panel.bullets, self.panel.extra])

    def showEvent(self, event) -> None:                      # noqa: N802, D102
        super().showEvent(event)
        if not self._intro and not getattr(self, "_first_shown", False):
            self._first_shown = True
            QTimer.singleShot(90, lambda: self._animate_lines(
                [self.panel.title, self.panel.body,
                 self.panel.bullets, self.panel.extra]))

    def _status(self, text: str, color: str = SUB) -> None:
        self.panel.status.setStyleSheet(
            f"color: {color}; border: 0; background: transparent; font-size: 14px;")
        self.panel.status.setText(text)
        if text and self.isVisible():
            self._animate_lines([self.panel.status], duration=360, stagger=0,
                                dist=12, slot="status")

    # -- 目录 ---------------------------------------------------------- #
    def _accept_dir(self, root: str) -> bool:
        paks = L._paks_under(root)                            # noqa: SLF001
        if not paks:
            return False
        self._game_root = root
        self._paks = paks
        try:
            L.set_game_root(root)
        except Exception:                                    # noqa: BLE001
            pass
        return True

    def _auto_detect(self) -> None:
        self._status("等一下哦…", SUB)
        self.panel.repaint()
        QApplication.processEvents()

        def _work() -> None:
            root = L.find_game_root() or ""
            if root and self._accept_dir(root):
                self._status(f"好耶耶！这是正确的目录！！\n{self._paks}", GOOD)
                self.next_btn.setEnabled(True)
            else:
                self._status("没能自动找到，点「手动选择…」指给我看吧。", BAD)
                self.next_btn.setEnabled(False)

        QTimer.singleShot(220, _work)

    def _pick_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = L.find_game_root() or self._game_root or ("C:\\" if os.name == "nt"
                                                          else os.path.expanduser("~"))
        chosen = QFileDialog.getExistingDirectory(
            self, "选择游戏安装目录（含 Content\\Paks 的那一层）", start)
        if not chosen:
            self._status("那再想想，随时可以点「手动选择…」。", SUB)
            return
        if self._accept_dir(chosen):
            self._status(f"好耶耶！这是正确的目录！！\n{self._paks}", GOOD)
            self.next_btn.setEnabled(True)
        else:
            self._status("这个目录里没有 Content\\Paks，换一个试试？", BAD)
            self.next_btn.setEnabled(False)

    # -- 翻页/收尾 ------------------------------------------------------ #
    def _on_next(self) -> None:
        if self._closing or self._intro:
            return
        if self._step < self.STEPS - 1:
            self._show_step(self._step + 1)
            return
        if not self._paks:
            self._show_step(1)
            self._status("先选一个能读到 Paks 的游戏目录吧。", BAD)
            return
        self._finish(True)

    def _finish(self, ok: bool) -> None:
        if self._closing:
            return
        self._closing = True
        mark_done()
        self._intro_delay.stop()
        if getattr(self, "_row_group", None) is not None:
            self._row_group.stop()
        for slot in list(getattr(self, "_anims", {})):
            self._stop_lines(slot)
        self.next_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self._intro = True
        self._panel_intro_size = (self.panel.width(), self.panel.height())
        self.bg.set_growing(True)
        w, h = min(560, self.width()), min(346, self.height())
        target = QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(420)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade_anim = fade
        fade.start()
        self.animate_surface(target, 420, lambda: self._done(ok))

    def _done(self, ok: bool) -> None:
        try:
            self.hide()
            self.close()
        except Exception:                                    # noqa: BLE001
            pass
        self.finished.emit(ok)

    def keyPressEvent(self, event) -> None:                  # noqa: N802, D102
        if event.key() == Qt.Key_Escape:
            self._finish(False)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_next()
            return
        super().keyPressEvent(event)

    def start(self):
        """固定透明画布上展开内容，避免系统窗口逐帧 resize 的抖动。"""
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1500, 940)
        self._intro = True
        self.setGeometry(area)
        self._full_rect = QRect(area)
        w = min(760, max(320, int(area.width() * 0.4)), area.width())
        h = min(470, max(300, int(area.height() * 0.45)), area.height())
        self.surfaceRect = QRect((self.width() - w) // 2,
                                 (self.height() - h) // 2, w, h)
        self._intro_text()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._animate_lines([self.panel.title, self.panel.body], duration=440)
        self._intro_delay.start(1000)

    def closeEvent(self, event):
        if not self._closing:
            event.ignore()
            self._finish(False)
        else:
            super().closeEvent(event)
