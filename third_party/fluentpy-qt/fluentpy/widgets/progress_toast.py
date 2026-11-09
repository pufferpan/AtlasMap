"""A small task notification with animated progress and terminal states."""

from __future__ import annotations

import math
import operator

from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from .toast import Toast


def _state_color(state, severity="info"):
    dark = theme.mode.value == "dark"
    if state == "success":
        return QtGui.QColor("#6ccb5f" if dark else "#0f7b0f")
    if state == "error":
        return QtGui.QColor("#ff99a4" if dark else "#c42b1c")
    if severity == "warning":
        return QtGui.QColor("#fce100" if dark else "#9d5d00")
    return QtGui.QColor(theme.tokens.accent)


def _timeout_milliseconds(value):
    value = operator.index(value)
    if not 0 <= value <= 2_147_483_647:
        raise ValueError("timeout_ms must be between zero and 2147483647")
    return value


class _TaskIcon(QtWidgets.QWidget):
    def __init__(self, parent, severity="info"):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.state = self.previous = "running"
        self.severity = severity
        self.phase, self.mix = 0.0, 1.0
        self.setAccessibleName("进行中")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 20, self.height() / 20)
        if self.mix < 1:
            self._draw(painter, self.previous, 1 - self.mix)
        self._draw(painter, self.state, self.mix)

    def _draw(self, painter, state, opacity):
        painter.save()
        painter.setOpacity(opacity)
        color = _state_color(state, self.severity)
        if state == "running" and self.severity == "warning":
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QtCore.QRectF(2, 2, 16, 16))
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor("#201900" if theme.mode.value == "dark" else "white"),
                    1.4,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QtCore.QPointF(10, 6), QtCore.QPointF(10, 10.5))
            painter.drawPoint(QtCore.QPointF(10, 14))
        elif state == "running":
            faint = QtGui.QColor(color)
            faint.setAlpha(40)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(faint, 2))
            painter.drawEllipse(QtCore.QRectF(3, 3, 14, 14))
            painter.setPen(
                QtGui.QPen(color, 2, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
            )
            painter.drawArc(
                QtCore.QRectF(3, 3, 14, 14), round((90 - self.phase * 360) * 16), -105 * 16
            )
        else:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QtCore.QRectF(1, 1, 18, 18))
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor("#142014" if theme.mode.value == "dark" else "white"),
                    1.6,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
            )
            if state == "success":
                path = QtGui.QPainterPath(QtCore.QPointF(5.5, 10))
                path.lineTo(8.5, 13)
                path.lineTo(14.5, 7)
                painter.drawPath(path)
            else:
                painter.drawLine(QtCore.QPointF(7, 7), QtCore.QPointF(13, 13))
                painter.drawLine(QtCore.QPointF(13, 7), QtCore.QPointF(7, 13))
        painter.restore()


class ProgressToast(Toast):
    """A task toast: update 0–100 progress, then finish or fail in place.

    This only renders task state; it does not perform downloads or other work.
    With a parent it remains a child overlay, without a native popup window.
    Completion timeouts count after entry and pause while hovered.
    """

    progressChanged = Signal(float)
    stateChanged = Signal(str)
    finished = Signal(bool)

    SHOW_DURATION = 340
    HIDE_DURATION = 220

    def __init__(
        self,
        title: str,
        detail: str = "",
        parent=None,
        *,
        target=None,
        indeterminate=False,
        severity="info",
    ):
        if severity not in ("info", "warning"):
            raise ValueError("severity must be info or warning")
        self._severity = severity
        self._width_override = None
        super().__init__(title, detail, parent, target=target)
        self._slide_distance = 20
        self._state = "running"
        self._value = self._display_value = 0.0
        self._indeterminate = bool(indeterminate)
        self._phase = 0.0
        self._pending_timeout = None
        self._hovering = False
        self._icon_mix = 1.0
        previous_icon = self._icon
        self._icon = _TaskIcon(self, severity)
        self.layout().replaceWidget(previous_icon, self._icon)
        previous_icon.hide()
        previous_icon.deleteLater()
        self._timeout = QtCore.QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.close)
        self._activity = QtCore.QVariantAnimation(self)
        self._activity.setStartValue(0.0)
        self._activity.setEndValue(1.0)
        self._activity.setDuration(1400)
        self._activity.setLoopCount(-1)
        self._activity.valueChanged.connect(self._set_phase)
        self._progress_motion = QtCore.QVariantAnimation(self)
        self._progress_motion.setDuration(220)
        self._progress_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._progress_motion.valueChanged.connect(self._set_display_value)
        self._width_motion = QtCore.QVariantAnimation(self)
        self._width_motion.setDuration(240)
        self._width_motion.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self._width_motion.valueChanged.connect(self._set_display_width)
        self._width_motion.finished.connect(self._width_finished)
        self._state_motion = QtCore.QVariantAnimation(self)
        self._state_motion.setDuration(200)
        self._state_motion.valueChanged.connect(self._set_icon_mix)
        self._state_motion.finished.connect(self._stop_completed_activity)

    @classmethod
    def start(
        cls,
        title: str,
        *,
        detail: str = "",
        parent=None,
        placement="bottom-right",
        indeterminate=False,
        severity="info",
    ):
        """Create and show an owned toast. Close it or report completion."""
        if placement not in cls.PLACEMENTS:
            raise ValueError(f"placement must be one of {cls.PLACEMENTS}")
        toast = cls(
            title,
            detail,
            parent or QtWidgets.QApplication.activeWindow(),
            indeterminate=indeterminate,
            severity=severity,
        )
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.show_at(placement)
        return toast

    @classmethod
    def success(
        cls,
        title: str,
        *,
        detail: str = "",
        placement="top-right",
        timeout_ms=2000,
        parent=None,
        target=None,
    ):
        timeout_ms = _timeout_milliseconds(timeout_ms)
        if placement not in cls.PLACEMENTS:
            raise ValueError(f"placement must be one of {cls.PLACEMENTS}")
        toast = cls(title, detail, parent or QtWidgets.QApplication.activeWindow(), target=target)
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.finish(timeout_ms=timeout_ms)
        toast.show_at(placement)
        return toast

    def value(self) -> float:
        """返回任务的目标进度（0–100），缓动中的显示值可以暂时落后。"""
        return self._value

    def state(self) -> str:
        """返回 running、success 或 error。"""
        return self._state

    def is_indeterminate(self) -> bool:
        return self._indeterminate

    @Slot(float)
    def set_progress(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("progress must be finite")
        if self._state != "running" or self._closing:
            return
        value = max(0.0, min(100.0, value))
        self.set_indeterminate(False)
        if value != self._value:
            self._value = value
            self.progressChanged.emit(value)
        self._animate_progress(value / 100)

    def setProgress(self, value: float) -> None:
        self.set_progress(value)

    def set_indeterminate(self, enabled: bool) -> None:
        if self._state == "running" and not self._closing:
            self._indeterminate = bool(enabled)
            self.update()

    def setIndeterminate(self, enabled: bool) -> None:
        self.set_indeterminate(enabled)

    def set_title(self, title: str) -> None:
        if self._closing:
            return
        before = self.width()
        self._title.setText(str(title))
        self._width_motion.stop()
        self._width_override = None
        after = super().sizeHint().width()
        if self.isVisible() and before != after:
            self._width_override = before
            self._width_motion.setStartValue(float(before))
            self._width_motion.setEndValue(float(after))
            self._width_motion.start()
        elif self._placement is not None:
            self._position()

    def finish(self, title: str | None = None, *, timeout_ms: int = 1800) -> None:
        """Fill the bar and change to success; zero timeout stays until closed."""
        self._complete("success", title, timeout_ms)

    def fail(self, title: str | None = None, *, timeout_ms: int = 0) -> None:
        """Change to error, preserving the last progress. Persistent by default."""
        self._complete("error", title, timeout_ms)

    def _complete(self, state, title, timeout_ms):
        if self._state != "running" or self._closing:
            return
        timeout_ms = _timeout_milliseconds(timeout_ms)
        self._state = state
        self._indeterminate = False
        if title is not None:
            self.set_title(title)
        if state == "success":
            changed = self._value != 100.0
            self._value = 100.0
            self._animate_progress(1.0)
            if changed:
                self.progressChanged.emit(100.0)
        self._icon.previous, self._icon.state = self._icon.state, state
        self._icon.setAccessibleName("已完成" if state == "success" else "失败")
        self._state_motion.setStartValue(0.0)
        self._state_motion.setEndValue(1.0)
        self._state_motion.start()
        self._pending_timeout = int(timeout_ms) or None
        self._start_timeout()
        self.stateChanged.emit(state)
        self.finished.emit(state == "success")
        self.update()

    def _animate_progress(self, value):
        self._progress_motion.stop()
        self._progress_motion.setStartValue(self._display_value)
        self._progress_motion.setEndValue(value)
        self._progress_motion.start()

    def _set_display_value(self, value):
        self._display_value = float(value)
        self.update()

    def _set_phase(self, value):
        self._phase = self._icon.phase = float(value)
        self._icon.update()
        self.update()

    def _set_icon_mix(self, value):
        self._icon_mix = self._icon.mix = float(value)
        self._icon.update()
        self.update()

    def _set_display_width(self, value):
        self._width_override = round(value)
        self._position()

    def _width_finished(self):
        self._width_override = None
        if self._placement is not None:
            self._position()

    def sizeHint(self):
        size = super().sizeHint()
        if self._width_override is not None:
            size.setWidth(self._width_override)
        return size

    def _stop_completed_activity(self):
        if self._state != "running":
            self._activity.stop()

    def _start_timeout(self):
        if (
            self._pending_timeout is not None
            and self.isVisible()
            and not self._closing
            and not self._hovering
            and self._reveal.state() == QtCore.QAbstractAnimation.State.Stopped
        ):
            self._timeout.start(self._pending_timeout)
            self._pending_timeout = None

    def _reveal_finished(self):
        super()._reveal_finished()
        if not self._closing and self.isVisible():
            self._start_timeout()

    def showEvent(self, event):
        super().showEvent(event)
        if self._state == "running":
            self._activity.start()

    def hideEvent(self, event):
        self._timeout.stop()
        self._pending_timeout = None
        self._hovering = False
        self._width_override = None
        for animation in (
            self._activity,
            self._progress_motion,
            self._width_motion,
            self._state_motion,
        ):
            animation.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._timeout.stop()
        self._pending_timeout = None
        self._activity.stop()
        self._width_motion.stop()
        super().closeEvent(event)

    def enterEvent(self, event):
        self._hovering = True
        if self._timeout.isActive():
            self._pending_timeout = max(1, self._timeout.remainingTime())
            self._timeout.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self._start_timeout()
        super().leaveEvent(event)

    def _apply_theme(self):
        super()._apply_theme()
        self.setStyleSheet(self.styleSheet() + "QLabel#toastTitle { font-weight: 400; }")
        font = self._title.font()
        font.setWeight(QtGui.QFont.Weight.Normal)
        self._title.setFont(font)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setClipPath(self._card_path())
        rect = self._card_rect()
        # Blend the accent into green/red while the status icon crossfades.
        source, target = (
            _state_color("running", self._severity),
            _state_color(self._state, self._severity),
        )
        color = QtGui.QColor.fromRgbF(
            *(a + (b - a) * self._icon_mix for a, b in zip(source.getRgbF(), target.getRgbF()))
        )
        track = QtGui.QColor(color)
        track.setAlpha(30 if theme.mode.value == "light" else 45)
        bar = QtCore.QRectF(rect.left(), rect.bottom() - 3, rect.width(), 3)
        painter.fillRect(bar, track)
        if self._indeterminate and self._state == "running":
            # One segment stays inside the track for the entire cycle. Smooth
            # reversals avoid wrapping into two disconnected visible pieces.
            width = bar.width() * 0.3
            position = (1.0 - math.cos(2.0 * math.pi * self._phase)) / 2.0
            x = bar.left() + (bar.width() - width) * position
            painter.fillRect(QtCore.QRectF(x, bar.top(), width, bar.height()), color)
        else:
            painter.fillRect(
                QtCore.QRectF(
                    bar.left(), bar.top(), bar.width() * self._display_value, bar.height()
                ),
                color,
            )
