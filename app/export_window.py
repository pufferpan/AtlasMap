"""Compact export progress window with a persistent, wrapping log viewer."""
from __future__ import annotations

from collections import deque
import os
import subprocess
import time
from typing import Optional

from PySide6.QtCore import QObject,QEvent,QEasingCurve, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen, QShortcut, QTextOption
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QWidget

from functools import lru_cache
from app.glow import render_glow
from app.transitions import SurfaceWindow
from core.system_usage import SystemUsage
from app import fluent_api as F

SMALL_W, SMALL_H = 640, 500
MARGIN = 26
SHRINK_MS = 760


@lru_cache(maxsize=24)
def _export_glow(width, height, frame, accelerated):
    return render_glow(width, height, frame * .08, 'red' if accelerated else 'dark', .8, divisor=4)


class _TransitionSurface(QWidget):
    """Animate one cached card; live text layout stays out of animation frames."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.pixmap = None
        self.hide()

    def paintEvent(self, event):
        if self.pixmap is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self.pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.owner._celebration is not None:
                self.owner.details_requested.emit()
                return
            source = self.owner._surface
            point = QPoint(int(event.position().x() * source.width() / max(1, self.width())),
                           int(event.position().y() * source.height() / max(1, self.height())))
            button = self.owner.btn_stop
            if not button.isHidden() and button.geometry().contains(point):
                button.click()


def _btn(text, parent, primary=False):
    button = (F.PrimaryPushButton if primary else F.PushButton)(text, parent)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(34)
    return button


class _SurfaceEvents(QObject):
    def __init__(self,surface,owner):
        super().__init__(surface)
        self.owner=owner
        surface.installEventFilter(self)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Resize and hasattr(self.owner,'log_view'):
            self.owner._layout()
        elif event.type()==QEvent.MouseButtonDblClick and event.button()==Qt.LeftButton and event.position().y()<55:
            self.owner.reveal_debug_button()
            return True
        elif event.type()==QEvent.MouseButtonPress:self.owner.mousePressEvent(event)
        elif event.type()==QEvent.MouseMove:self.owner.mouseMoveEvent(event)
        elif event.type()==QEvent.MouseButtonRelease:self.owner.mouseReleaseEvent(event)
        return False


def _ExportSurface(owner):
    surface=F.CardWidget(owner)
    surface.window_events=_SurfaceEvents(surface,owner)
    return surface


class ExportWindow(SurfaceWindow):
    stop_requested = Signal()
    log_requested = Signal()
    closed = Signal()
    transition_finished = Signal()
    details_requested = Signal()
    save_log_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._parent = parent
        self.setWindowTitle("AtlasMap · 导出日志")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._title = "正在导出"
        self._accelerated = False
        self._subtitle = ""
        self._phase = "正在启动…"
        self._phase_locked = False
        self._fraction = None
        self._done = False
        self._ok = True
        self._elapsed = 0.0
        self._started = time.monotonic()
        self._tick = 0.0
        self._open = ""
        self._out = ""
        self._queue = deque(maxlen=8000)
        self._drag_offset = None
        self._transitioning = False
        self._last_tick = time.monotonic()
        self._surface = _ExportSurface(self)
        self._transition_surface = _TransitionSurface(self)
        self._snapshot_cache = {}
        self._celebration = None
        self._defer_live_log = False
        self._usage = SystemUsage()
        self._usage_snapshot = {}
        self._island = None
        self._map_preview=None
        self._preview_feed=True
        self._escape = QShortcut(QKeySequence('Esc'),self)
        self._escape.activated.connect(self.close)

        self.title_label=QLabel(self._surface)
        title_font=QFont(self.font());title_font.setPixelSize(23);title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.subtitle_label=QLabel(self._surface);self.subtitle_label.setWordWrap(True)
        self.phase_label=QLabel(self._surface)
        self.elapsed_label=QLabel(self._surface)
        self.log_hint=QLabel('实时日志 · 自动换行 · 可选中复制',self._surface)
        self.progress_bar=F.ProgressBar(self._surface)
        self.progress_bar.setTextVisible(False)
        self.log_view = F.CodeEditor(self._surface)
        F.add_context_action(self.log_view,'导出完整日志',lambda:self.save_log_requested.emit())
        self.log_view.setObjectName("exportLiveLog")
        self.log_view.setMinimumHeight(30)
        self.log_view.setReadOnly(True)
        self.log_view.text_edit.document().setMaximumBlockCount(2000)
        self.log_view.text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_view.text_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.log_view.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from app.failure_notice import failure_notice
        self.failure_notice=failure_notice(self._surface)
        self.failure_log_button=_btn('查看任务日志',self.failure_notice)
        self.failure_log_button.clicked.connect(self.log_requested.emit)
        self.failure_notice.content_layout.addWidget(self.failure_log_button)
        from core.export_failure import FailureTracker
        self._failure_tracker=FailureTracker()

        self.btn_stop = _btn("终止导出", self._surface, True)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_close = _btn("关闭", self._surface)
        self.btn_close.clicked.connect(self.close)
        self.btn_open = _btn("打开导出目录", self._surface)
        self.btn_open.clicked.connect(self._on_open)
        self.btn_copy = _btn("复制日志", self._surface)
        self.btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.log_view.toPlainText()))
        self.btn_save_log = _btn("导出完整日志", self._surface)
        self.btn_save_log.setToolTip('保存整次任务的主流程和所有分块日志')
        self.btn_save_log.clicked.connect(lambda:self.save_log_requested.emit())
        self.btn_close.hide()
        self.btn_open.hide()
        self.btn_debug = _btn("调试", self._surface)
        self.btn_debug.setCheckable(True)
        self.btn_debug.setToolTip("显示系统 CPU 与内存占用")
        self.btn_debug.toggled.connect(self._toggle_debug)
        self.btn_debug.hide()
        self.btn_hide = _btn("隐藏", self._surface)
        self.btn_hide.clicked.connect(self._hide_to_island)
        self.btn_preview=_btn('3D 预览',self._surface)
        self.btn_preview.hide()
        self.usage_label = QLabel(self._surface)
        self.usage_label.setStyleSheet("color:#b7d9ff;font-size:11px;background:rgba(43,87,154,65);border-radius:5px;padding:2px 5px;")
        self.usage_label.hide()
        self._debug_shortcut = QShortcut(QKeySequence(Qt.Key_F12), self)
        self._debug_shortcut.activated.connect(self.reveal_debug_button)
        self._usage_timer = QTimer(self)
        self._usage_timer.setInterval(1000)
        self._usage_timer.timeout.connect(self._update_usage)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._on_tick)

    def _layout_surface(self):
        if self._transitioning or self._celebration is not None:
            self._transition_surface.setGeometry(self.surfaceRect)
        else:
            self._surface.setGeometry(self.surfaceRect)

    def visual_surface(self):
        return self._transition_surface if self._transitioning or self._celebration is not None else self._surface

    def set_accelerated(self, enabled=True):
        self._accelerated = enabled
        if enabled:
            self.btn_stop.setStyleSheet(self.btn_stop.styleSheet().replace('#0a84ff', '#D13438').replace('#237bc2', '#b82c30'))
            self.usage_label.setStyleSheet('color:#ffd7d7;font-size:11px;background:rgba(160,30,40,90);border-radius:5px;padding:2px 5px;')

    def begin(self, title, subtitle="", start_rect=None, target_rect=None, present=True, duration=SHRINK_MS):
        from core.export_failure import FailureTracker
        from app.failure_notice import show_failure
        self._failure_tracker=FailureTracker(title)
        show_failure(self.failure_notice,None)
        self.log_view.show()
        self._title = title
        self._subtitle = "实时日志持续显示，长行自动换行"
        self._phase = "正在启动…"
        self._done = False
        self._ok = True
        self._fraction = None
        self._started = time.monotonic()
        self._elapsed = 0.0
        self._queue.clear()
        self._snapshot_cache.clear()
        self._celebration = None
        self.log_view.text_edit.clear()
        self._last_tick = time.monotonic()
        self.btn_debug.setChecked(False)
        self.btn_debug.hide()
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("终止导出")
        self.btn_stop.show()
        self.btn_close.hide()
        self.btn_open.hide()
        if not present:
            return
        screen = QGuiApplication.screenAt(start_rect.center()) if start_rect is not None else None
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1600, 900)
        width = min(SMALL_W, max(360, area.width() - MARGIN * 2))
        height = min(SMALL_H, max(320, area.height() - MARGIN * 2))
        target = QRect(area.right() - width - MARGIN + 1, area.bottom() - height - MARGIN + 1, width, height)
        if target_rect is not None:
            target = QRect(target_rect)
        start = QRect(start_rect).intersected(area) if start_rect is not None else target
        if not start.isValid():
            start = target
        self.show_transition(start, target, duration)

    def show_transition(self, start, target, duration=SHRINK_MS, easing=QEasingCurve.InOutCubic):
        """Present existing progress from a shared origin without clearing its log/state."""
        bounds = start.united(target)
        key = (target.width(), target.height())
        if key not in self._snapshot_cache:
            self.prepare_transition(target.size())
        self._transition_surface.pixmap = self._snapshot_cache[key]
        self._surface.hide()
        self._transitioning = True
        self.setGeometry(bounds)
        self.surfaceRect = start.translated(-bounds.topLeft())
        self._transition_surface.show()
        self.show()
        self.raise_()
        self._timer.start()
        if start != target:
            self.animate_surface(target.translated(-bounds.topLeft()), duration,
                                 lambda: self._finish_shrink(target), easing)
        else:
            self._finish_shrink(target)

    def prepare_transition(self, size):
        self._surface.resize(size)
        self._layout()
        self._snapshot_cache[(size.width(), size.height())] = self._surface.grab()

    def _finish_shrink(self, target):
        self.setGeometry(target)
        self._transitioning = False
        self.surfaceRect = self.rect()
        if self._celebration is None:
            self._transition_surface.hide()
            self._surface.show()
        else:
            self._surface.hide()
            self._transition_surface.show()
        self.transition_finished.emit()

    def reveal_debug_button(self):
        self.btn_debug.show()
        self._layout()
        self.btn_debug.raise_()
        self.update()

    def _hide_to_island(self):
        if self._map_preview is not None:self._map_preview.hide()
        if self._island is None:
            from app.export_island import ExportIsland
            self._island = ExportIsland(self, [self])
        self._island.collapse()

    def _toggle_debug(self, visible):
        self.usage_label.setVisible(visible)
        if visible:
            self._usage.reset()
            self._update_usage()
            self._usage_timer.start()
        else:
            self._usage_timer.stop()
        self._surface.update()

    def _update_usage(self):
        sample = self._usage.sample()
        self._usage_snapshot = sample
        cpu = '采样中' if sample['cpu_percent'] is None else f"{sample['cpu_percent']:.1f}%"
        if sample['memory_total']:
            used = sample['memory_used'] / 1024**3
            total = sample['memory_total'] / 1024**3
            memory = f"{used:.1f}/{total:.1f} GB ({sample['memory_percent']:.0f}%)"
        else:
            memory = '暂不可用'
        self.usage_label.setText(f"CPU {cpu}  ·  内存 {memory}")
        self.usage_label.setToolTip("整台电脑的 CPU 和物理内存占用，每秒刷新")

    def feed(self, line):
        self._failure_tracker.observe(line)
        if self._map_preview is not None and self._preview_feed:self._map_preview.feed(line)
        if line:self._queue.append(line.rstrip())

    def bind_preview(self,controller,feed=True):
        self._map_preview=controller;self._preview_feed=feed
        self.btn_preview.clicked.connect(controller.show)
        self.btn_preview.show();self._layout()

    def set_fraction(self, value):
        self._fraction = max(0.0, min(1.0, float(value)))

    def _flush_log(self, all_lines=False):
        if not self._queue:return
        lines = [self._queue.popleft() for _ in range(len(self._queue) if all_lines else min(500, len(self._queue)))]
        scrollbar = self.log_view.text_edit.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 2
        previous = scrollbar.value()
        self.log_view.text_edit.appendPlainText("\n".join(lines))
        scrollbar.setValue(scrollbar.maximum() if follow else previous)
        important = [text for text in lines if any(token in text for token in
                     ("[headless]", "[light]", "[collision]", "步骤", "失败", "错误", "并行校验"))]
        if important and not self._phase_locked:self._phase = important[-1].strip()

    def _on_tick(self):
        self.progress_bar.setRange(0,0 if self._fraction is None and not self._done else 1000)
        if self._fraction is not None:self.progress_bar.setValue(round(self._fraction*1000))
        now = time.monotonic()
        self._tick += max(0.0, now - self._last_tick)
        self._last_tick = now
        if not self._done:self._elapsed = time.monotonic() - self._started
        if not self._transitioning:
            if not self._defer_live_log:
                self._flush_log()
            self._sync_labels()
            self._surface.update()

    def finish(self, code, out_dir="", open_path="", open_label="",failure=None):
        from app.failure_notice import show_failure
        failure=failure or self._failure_tracker.finish(code)
        show_failure(self.failure_notice,failure,compact=True)
        if self._map_preview is not None and self._preview_feed:self._map_preview.finish(code)
        self._flush_log(True)
        self._elapsed = time.monotonic() - self._started
        self._done = True
        self._ok = int(code) == 0
        self._out = out_dir or ""
        self._open = open_path or self._out
        if open_label:self.btn_open.setText(open_label)
        self._title = "导出完成" if self._ok else ("导出已停止" if code == -2 else "导出失败")
        self._phase_locked=True
        self._phase='任务已完成' if self._ok else ('任务已终止，排队分块已取消' if code == -2 else '导出失败，详情见下方日志')
        self._subtitle = self._out if self._ok else f"退出码 {code}，错误详情和上下文保留在下方日志中"
        if failure is not None:
            self._phase=failure.stage
            self._subtitle=failure.title+' · '+failure.stage
        self._fraction = 1.0 if self._ok else None
        self.btn_stop.hide()
        self.btn_close.show()
        self.btn_open.setVisible(bool(self._open))
        self._layout()
        self._surface.update()

    def _on_stop(self):
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("正在终止…")
        self._phase_locked=True
        self._phase='正在终止导出进程…'
        self._surface.update()
        self.stop_requested.emit()

    def _on_open(self):
        target = os.path.normpath(self._open or self._out)
        if os.path.isfile(target) and target.lower().endswith('.blend'):
            from core import exporter
            blender=str(exporter.load_settings().get('blender') or '')
            if os.path.isfile(blender):subprocess.Popen([blender,target])
            else:subprocess.Popen(['explorer','/select,',target])
        elif os.path.isfile(target) and target.lower().endswith(".uproject"):
            subprocess.Popen(["explorer", "/select,", target])
        elif os.path.isdir(target):subprocess.Popen(["explorer", target])
        elif os.path.isdir(os.path.dirname(target)):subprocess.Popen(["explorer", os.path.dirname(target)])

    def _layout(self):
        width, height = self._surface.width(), self._surface.height()
        compact_footer = width < 580
        two_rows = compact_footer and not self.btn_open.isHidden()
        log_top = min(193,max(130,height-210))
        self.log_view.setGeometry(20, log_top, width - 40, max(30, height-log_top-(117 if two_rows else 74)))
        self.btn_copy.setGeometry(20, height - 55, 102, 34)
        self.btn_save_log.setGeometry(132, height - 55, 114, 34)
        self.btn_stop.setGeometry(width - 126, height - 55, 106, 34)
        self.btn_close.setGeometry(width - 126, height - 55, 106, 34)
        self.btn_open.setGeometry(width - 274, height - 55, 138, 34)
        if compact_footer:
            self.btn_copy.setGeometry(16, height - 55, 76, 34)
            self.btn_save_log.setGeometry(100, height - 55, 112, 34)
            self.btn_stop.setGeometry(width - 110, height - 55, 94, 34)
            self.btn_close.setGeometry(width - 90, height - 55, 74, 34)
            self.btn_open.setGeometry(20, height - 98, width - 40, 34)
        if width < 360:
            self.btn_copy.setGeometry(16,height-55,66,34)
            self.btn_copy.setText('复制')
            self.btn_save_log.setGeometry(90,height-55,108,34)
        else:
            self.btn_copy.setText('复制日志')
        self.btn_hide.setGeometry(width - 78, 17, 58, 34)
        preview_width=90 if self._map_preview is not None else 0
        self.btn_preview.setGeometry(width-168,17,84,34)
        self.btn_debug.setGeometry(width-142-preview_width, 17, 58, 34)
        self.usage_label.setGeometry(20, 166, width - 40, 23)
        self.progress_bar.setGeometry(20,104,width-40,6)
        title_width=width-(166 if not self.btn_debug.isHidden() else 102)-preview_width
        self.title_label.setGeometry(20,17,title_width,34)
        self.subtitle_label.setGeometry(20,56,width-40,38)
        self.phase_label.setGeometry(20,120,width-40,22)
        self.elapsed_label.setGeometry(20,145,width-40,20)
        self.log_hint.setGeometry(20,170,width-40,20)
        has_failure=getattr(self,'failure_notice',None) is not None and self.failure_notice.failure is not None
        if hasattr(self,'failure_notice'):
            self.failure_notice.setGeometry(20,112,width-40,max(80,height-(235 if two_rows else 188)))
            self.log_view.setVisible(not has_failure)
            for widget in (self.phase_label,self.elapsed_label,self.log_hint,self.progress_bar):widget.setVisible(not has_failure)
        self._sync_labels()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._transitioning:
            self.surfaceRect = self.rect()

    def _sync_labels(self):
        self.title_label.setText(self.title_label.fontMetrics().elidedText(self._title,Qt.ElideRight,self.title_label.width()))
        self.subtitle_label.setText(self._subtitle)
        self.phase_label.setText(self.phase_label.fontMetrics().elidedText(self._phase,Qt.ElideMiddle,self.phase_label.width()))
        minutes,seconds=divmod(int(self._elapsed),60)
        self.elapsed_label.setText(f'用时 {minutes} 分 {seconds} 秒')
        self.log_hint.setVisible(not self.btn_debug.isChecked() and self.failure_notice.failure is None)

    def mousePressEvent(self, event):
        if not self._transitioning and event.button() == Qt.LeftButton and event.position().y() < 55:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        if self._island is not None:
            self._island.close()
        self._snapshot_cache.clear()
        self._transition_surface.pixmap = None
        self._timer.stop()
        self._usage_timer.stop()
        if self._surface_anim is not None:
            self._surface_anim.stop()
        super().closeEvent(event)
        self.closed.emit()
