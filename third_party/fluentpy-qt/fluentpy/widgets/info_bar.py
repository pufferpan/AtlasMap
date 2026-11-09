"""FluentPy message bars composed from our notification and Qt widgets.

The public reference is used for interaction goals only. Layout, rendering,
ownership, timing and placement reuse FluentPy's own notification components.
"""

from __future__ import annotations

import math

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .color_toast import ColorToast, _validated_color
from .progress_bar import ProgressBar
from .progress_toast import _TaskIcon


class _MessageIcon(QtWidgets.QWidget):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.source = None
        self.setFixedSize(20, 24)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = self.bar.color()
        if self.source is not None:
            icon = fluent_icon(self.source) if isinstance(self.source, FluentIcon) else self.source
            ratio = self.devicePixelRatioF()
            pixmap = icon.pixmap(QtCore.QSize(20, 20) * ratio)
            pixmap.setDevicePixelRatio(ratio)
            if isinstance(self.source, FluentIcon):
                tint = QtGui.QPainter(pixmap)
                tint.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
                tint.fillRect(pixmap.rect(), color)
                tint.end()
            painter.drawPixmap(QtCore.QRect(0, 2, 20, 20), pixmap)
            return
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QRectF(1, 3, 18, 18))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor("#18201c" if theme.mode.value == "dark" else "#ffffff"),
                1.5,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        tone = self.bar.tone()
        if tone == "success":
            path = QtGui.QPainterPath(QtCore.QPointF(5.5, 12))
            path.lineTo(8.5, 15)
            path.lineTo(14.5, 9)
            painter.drawPath(path)
        elif tone == "error":
            painter.drawLine(QtCore.QPointF(7, 9), QtCore.QPointF(13, 15))
            painter.drawLine(QtCore.QPointF(13, 9), QtCore.QPointF(7, 15))
        else:
            font = ui_font(14)
            font.setWeight(QtGui.QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(
                self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "!" if tone == "warning" else "i"
            )


class InfoBar(ColorToast):
    """A tinted message bar, used inline or in any existing notification stack.

    ``content_layout`` remains the single public column for custom Qt controls.
    ``orientation`` arranges title and body; extra content follows below them.
    """

    closed = Signal()

    def __init__(
        self,
        title,
        detail="",
        parent=None,
        *,
        tone="info",
        orientation="horizontal",
        closable=True,
        icon=None,
        color=None,
        background=None,
        dark_background=None,
        action_text="",
        action_callback=None,
        close_on_action=True,
        card_width=None,
        target=None,
    ):
        self._validate_orientation(orientation)
        if not isinstance(closable, bool):
            raise TypeError("closable must be a bool")
        self._validate_icon(icon)
        self._backgrounds = self._validate_backgrounds(background, dark_background)
        self._orientation = orientation
        self._overlay_mode = False
        self._display_background = QtGui.QColor()
        self._closed_emitted = False
        super().__init__(
            title,
            detail,
            parent,
            tone=tone,
            color=color,
            action_text=action_text,
            action_callback=action_callback,
            close_on_action=close_on_action,
            card_width=card_width,
            target=target,
        )
        root = self.layout()
        root.setContentsMargins(31, 24, 31, 30)
        root.setSpacing(12)
        self._text_row = self.content_layout.itemAt(0).layout()
        self._text_row.removeWidget(self.close_button)
        self.content_layout.removeWidget(self._detail_row)
        self._text_row.addWidget(self._detail_row)
        self._status_icon = _MessageIcon(self)
        self._status_icon.source = QtGui.QIcon(icon) if isinstance(icon, QtGui.QIcon) else icon
        root.insertWidget(0, self._status_icon, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.close_button, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._background_motion = QtCore.QVariantAnimation(self)
        self._background_motion.setDuration(180)
        self._background_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._background_motion.valueChanged.connect(self._set_display_background)
        policy = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.set_orientation(orientation)
        self.set_closable(closable)
        self._refresh_background()

    @staticmethod
    def _validate_orientation(value):
        if value not in ("horizontal", "vertical"):
            raise ValueError("orientation must be horizontal or vertical")

    @staticmethod
    def _validate_icon(value):
        if value is not None and not isinstance(value, (FluentIcon, QtGui.QIcon)):
            raise TypeError("icon must be a FluentIcon, QIcon or None")

    @staticmethod
    def _validate_backgrounds(light, dark):
        if light is None:
            if dark is not None:
                raise ValueError("dark_background requires background")
            return None
        return (_validated_color(light), _validated_color(dark if dark is not None else light))

    @classmethod
    def notify(
        cls, title, *, detail="", parent=None, placement="top-center", timeout_ms=4000, **options
    ):
        if placement not in cls.PLACEMENTS:
            raise ValueError(f"placement must be one of {cls.PLACEMENTS}")
        timeout_ms = cls._validate_timeout(timeout_ms)
        bar = cls(title, detail, parent or QtWidgets.QApplication.activeWindow(), **options)
        bar.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        bar.set_timeout(timeout_ms)
        bar.show_at(placement)
        return bar

    def orientation(self):
        return self._orientation

    def set_orientation(self, orientation):
        self._validate_orientation(orientation)
        self._orientation = orientation
        horizontal = orientation == "horizontal"
        self._text_row.setDirection(
            QtWidgets.QBoxLayout.Direction.LeftToRight
            if horizontal
            else QtWidgets.QBoxLayout.Direction.TopToBottom
        )
        self._text_row.setSpacing(12 if horizontal else 4)
        self._text_row.setStretch(0, 0)
        self._text_row.setStretch(1, 1 if horizontal else 0)
        self._title.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred
            if horizontal
            else QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self._refresh_geometry()

    def is_closable(self):
        return not self.close_button.isHidden()

    def set_closable(self, closable):
        if not isinstance(closable, bool):
            raise TypeError("closable must be a bool")
        self.close_button.setVisible(closable)
        self._refresh_geometry()

    def set_icon(self, icon):
        self._validate_icon(icon)
        self._status_icon.source = QtGui.QIcon(icon) if isinstance(icon, QtGui.QIcon) else icon
        self._status_icon.update()

    def set_background(self, light=None, dark=None):
        self._backgrounds = self._validate_backgrounds(light, dark)
        self._refresh_background()

    def color(self):
        if self._custom_color is None and self._tone == "info":
            return QtGui.QColor(theme.tokens.accent)
        return super().color()

    def background_color(self):
        if self._backgrounds is not None:
            return QtGui.QColor(self._backgrounds[theme.mode.value == "dark"])
        dark = theme.mode.value == "dark"
        base = QtGui.QColor("#292d32" if dark else "#fafbfc")
        color = self.color()
        mix = 0.22 if dark else 0.12
        return QtGui.QColor.fromRgbF(
            *(a + (b - a) * mix for a, b in zip(base.getRgbF()[:3], color.getRgbF()[:3]))
        )

    def sizeHint(self):
        if not hasattr(self, "_text_row"):
            return super().sizeHint()
        self.ensurePolished()

        def width(label):
            return max(
                (
                    label.fontMetrics().horizontalAdvance(line) + 1
                    for line in label.text().splitlines()
                ),
                default=0,
            )

        title, detail = width(self._title), width(self._detail)
        text = (
            title + detail + (12 if title and detail else 0)
            if self._orientation == "horizontal"
            else max(title, detail)
        )
        inner = max(text, self.content_layout.sizeHint().width())
        margins = self.layout().contentsMargins()
        extra = (
            margins.left() + margins.right() + self._status_icon.width() + self.layout().spacing()
        )
        if self.is_closable():
            extra += self.close_button.width() + self.layout().spacing()
        total = (
            self._card_width + 33
            if self._card_width is not None
            else min(753, max(313, inner + extra))
        )
        return QtCore.QSize(total, self.heightForWidth(total))

    def show_at(self, placement="top-center"):
        if placement not in self.PLACEMENTS:
            raise ValueError(f"placement must be one of {self.PLACEMENTS}")
        self._overlay_mode = True
        super().show_at(placement)

    def _set_reveal_progress(self, value):
        if self._overlay_mode:
            return super()._set_reveal_progress(value)
        self._reveal_progress = max(0.0, min(1.0, float(value)))
        self._opacity.setOpacity(self._reveal_progress)

    def showEvent(self, event):
        if not self._overlay_mode:
            self._reveal.stop()
            self._closing = False
            self._allow_close = False
            self._set_reveal_progress(1.0)
        self._closed_emitted = False
        super().showEvent(event)
        if not self._overlay_mode:
            self._start_timeout()

    def hideEvent(self, event):
        self._background_motion.stop()
        self._display_background = self.background_color()
        super().hideEvent(event)
        self._overlay_mode = False

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted() and not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()

    def _refresh_bar(self):
        super()._refresh_bar()
        if hasattr(self, "_status_icon"):
            self._status_icon.update()
        self._refresh_background()

    def _refresh_background(self):
        target = self.background_color()
        if hasattr(self, "_background_motion"):
            self._background_motion.stop()
            if (
                self.isVisible()
                and self._display_background.isValid()
                and self._display_background != target
            ):
                self._background_motion.setStartValue(self._display_background)
                self._background_motion.setEndValue(target)
                self._background_motion.start()
                return
        self._set_display_background(target)

    def _set_display_background(self, value):
        self._display_background = QtGui.QColor(value)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        path = self._card_path()
        painter.save()
        painter.translate(0, 2)
        for spread in range(8, 0, -1):
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 2), spread))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()
        fill = (
            self._display_background
            if self._display_background.isValid()
            else self.background_color()
        )
        border = fill.lighter(120) if theme.mode.value == "dark" else fill.darker(106)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(fill)
        painter.drawPath(path)


class _InfoProgressBar(ProgressBar):
    def __init__(self, bar):
        self.bar = bar
        super().__init__(bar.content_widget)

    def _apply_theme(self):
        super()._apply_theme()
        self.setStyleSheet(
            self.styleSheet() + f"QProgressBar::chunk {{background:{self.bar.color().name()};}}"
        )


class ProgressInfoBar(InfoBar):
    """A task message bar with a spinner and the existing native ProgressBar."""

    progressChanged = Signal(float)
    stateChanged = Signal(str)
    finished = Signal(bool)

    def __init__(self, title, detail="", parent=None, *, indeterminate=False, **options):
        if not isinstance(indeterminate, bool):
            raise TypeError("indeterminate must be a bool")
        options.setdefault("tone", "info")
        super().__init__(title, detail, parent, **options)
        self._state = "running"
        self._value = 0.0
        self._indeterminate = indeterminate
        self._task_icon = _TaskIcon(self)
        self._task_custom_icon = False
        self.layout().replaceWidget(self._status_icon, self._task_icon)
        self._status_icon.hide()
        self.set_icon(self._status_icon.source)
        self.progress_bar = _InfoProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.content_layout.addWidget(self.progress_bar)
        self.progress_bar.setVisible(not indeterminate)
        self._activity = QtCore.QVariantAnimation(self)
        self._activity.setDuration(1200)
        self._activity.setStartValue(0.0)
        self._activity.setEndValue(1.0)
        self._activity.setLoopCount(-1)
        self._activity.valueChanged.connect(self._set_phase)
        self._progress_motion = QtCore.QVariantAnimation(self)
        self._progress_motion.setDuration(220)
        self._progress_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._progress_motion.valueChanged.connect(
            lambda value: self.progress_bar.setValue(round(value))
        )
        self._refresh_bar()
        self._refresh_geometry()

    @classmethod
    def start(
        cls,
        title,
        *,
        detail="",
        parent=None,
        placement="top-center",
        indeterminate=False,
        **options,
    ):
        return cls.notify(
            title,
            detail=detail,
            parent=parent,
            placement=placement,
            timeout_ms=0,
            indeterminate=indeterminate,
            **options,
        )

    @classmethod
    def success(
        cls, title, *, detail="", parent=None, placement="top-center", timeout_ms=1800, **options
    ):
        timeout_ms = cls._validate_timeout(timeout_ms)
        bar = cls.start(title, detail=detail, parent=parent, placement=placement, **options)
        bar.finish(timeout_ms=timeout_ms)
        return bar

    @classmethod
    def error(
        cls, title, *, detail="", parent=None, placement="top-center", timeout_ms=0, **options
    ):
        timeout_ms = cls._validate_timeout(timeout_ms)
        bar = cls.start(title, detail=detail, parent=parent, placement=placement, **options)
        bar.fail(timeout_ms=timeout_ms)
        return bar

    def state(self):
        return self._state

    def value(self):
        return self._value

    def is_indeterminate(self):
        return self._indeterminate

    def set_icon(self, icon):
        super().set_icon(icon)
        custom = icon is not None
        if custom != self._task_custom_icon:
            previous = self._status_icon if self._task_custom_icon else self._task_icon
            following = self._status_icon if custom else self._task_icon
            self.layout().replaceWidget(previous, following)
            previous.hide()
            following.show()
            self._task_custom_icon = custom
            self._refresh_geometry()

    def set_progress(self, value):
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
        self._animate_progress(value)

    def set_indeterminate(self, enabled):
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if self._state != "running" or self._closing:
            return
        self._indeterminate = enabled
        self.progress_bar.setVisible(not enabled)
        self._refresh_geometry()

    def finish(self, title=None, *, timeout_ms=1800):
        self._complete("success", title, timeout_ms)

    def fail(self, title=None, *, timeout_ms=0):
        self._complete("error", title, timeout_ms)

    def _complete(self, state, title, timeout_ms):
        timeout_ms = self._validate_timeout(timeout_ms)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if self._state != "running" or self._closing:
            return
        self._state = state
        self._activity.stop()
        self._indeterminate = False
        self._task_icon.state = state
        self._task_icon.setAccessibleName("已完成" if state == "success" else "失败")
        self.set_tone(state)
        if title is not None:
            self.set_title(title)
        if state == "success":
            changed = self._value != 100.0
            self._value = 100.0
            self._animate_progress(100.0)
            if changed:
                self.progressChanged.emit(100.0)
        self.progress_bar.setVisible(True)
        self._refresh_geometry()
        self.set_timeout(timeout_ms)
        self.stateChanged.emit(state)
        self.finished.emit(state == "success")

    def _animate_progress(self, value):
        self._progress_motion.stop()
        if not self.isVisible():
            self.progress_bar.setValue(round(value * 10))
            return
        self._progress_motion.setStartValue(float(self.progress_bar.value()))
        self._progress_motion.setEndValue(value * 10)
        self._progress_motion.start()

    def _set_phase(self, value):
        self._task_icon.phase = float(value)
        self._task_icon.update()

    def _refresh_bar(self):
        super()._refresh_bar()
        if hasattr(self, "progress_bar"):
            self.progress_bar._apply_theme()

    def showEvent(self, event):
        super().showEvent(event)
        if self._state == "running":
            self._activity.start()

    def hideEvent(self, event):
        self._activity.stop()
        self._progress_motion.stop()
        self.progress_bar.setValue(round(self._value * 10))
        super().hideEvent(event)

    def closeEvent(self, event):
        self._activity.stop()
        super().closeEvent(event)
