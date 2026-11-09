"""Confirmed time wheels in an animated, in-window flyout."""

from ..backends import time as clock
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .date_picker import _DateAction, _DateWheel


class _TimeWheel(_DateWheel):
    def __init__(self, parent=None):
        self.use_12_hour = False
        super().__init__(parent)
        self.value = (0, 0)
        self.setAccessibleName("时间滚轮：小时、分钟")

    def _column_count(self):
        return 3 if self.use_12_hour else 2

    def _format_value(self, column, value):
        if column == 2:
            return "PM" if value else "AM"
        return str(value) if column == 0 and self.use_12_hour else f"{value:02d}"

    def set_value(self, value, use_12_hour=False, column=0):
        self.value = clock.validate_time(*value)
        clock.display_time(*self.value, use_12_hour)
        self.use_12_hour = use_12_hour
        for animation in self._animations:
            animation.stop()
        self._offsets = [0.0, 0.0, 0.0]
        self._wheel_remainders = [0, 0, 0]
        self._wheel_mode = None
        self._drag_origin = None
        self._drag_pixels = 0.0
        self.column = max(0, min(column, self._column_count() - 1))
        self.setAccessibleName(
            "时间滚轮：小时、分钟、AM或PM" if use_12_hour else "时间滚轮：小时、分钟"
        )
        self._refresh_values()

    def _refresh_values(self):
        self._values = tuple(
            clock.column_values(*self.value, column, self.RADIUS + 1, self.use_12_hour)
            for column in range(self._column_count())
        )
        self.setAccessibleDescription(
            f"当前待选时间 {self.value[0]:02d}:{self.value[1]:02d}。左右切换列，上下选择；Enter确认，Escape取消。"
        )
        self.update()

    def step(self, column, steps, *, animate=True):
        previous = self.value
        self.value = clock.step_time(*self.value, column, steps, self.use_12_hour)
        self.column = column
        self._refresh_values()
        if animate and self.value != previous:
            animation = self._animations[column]
            animation.stop()
            offset = self._offsets[column] + (self.ROW_HEIGHT if steps > 0 else -self.ROW_HEIGHT)
            animation.setStartValue(
                float(max(-2 * self.ROW_HEIGHT, min(2 * self.ROW_HEIGHT, offset)))
            )
            animation.setEndValue(0.0)
            animation.start()

    def mouseReleaseEvent(self, event):
        active = (
            event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_origin is not None
        )
        dragged, remainder, previous = self._dragged, self._drag_pixels, self.value
        if (
            self.use_12_hour
            and self.column == 2
            and self._drag_origin is not None
            and not self._dragged
        ):
            index = int(event.position().y() / self.ROW_HEIGHT) + 1
            if not 0 <= index < len(self._values[2]) or self._values[2][index] is None:
                self._drag_origin = None
                self._offsets[2] = 0.0
                self.update()
                event.accept()
                return
        super().mouseReleaseEvent(event)
        if not active:
            return
        animation = self._animations[self.column]
        if dragged:
            offset = (
                remainder - round(remainder / self.ROW_HEIGHT) * self.ROW_HEIGHT
                if self.value != previous
                else remainder
            )
            animation.stop()
            animation.setStartValue(float(offset))
            animation.setEndValue(0.0)
            animation.start()
        elif animation.state() == QtCore.QAbstractAnimation.State.Running:
            # The shared click handler resets offsets after selecting a row.
            self._offsets[self.column] = float(animation.currentValue())


class _TimeSurface(QtWidgets.QWidget):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(10.5, 8.5, -10.5, -12.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.save()
        painter.translate(0, 2)
        for spread in range(10, 0, -1):
            painter.setPen(
                QtGui.QPen(QtGui.QColor(0, 0, 0, 1 if theme.mode.value == "light" else 2), spread)
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()
        painter.setBrush(QtGui.QColor(theme.tokens.surface))
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
        painter.drawPath(path)
        painter.drawLine(
            QtCore.QPointF(rect.left(), self.height() - 60),
            QtCore.QPointF(rect.right(), self.height() - 60),
        )


class _TimeFlyout(QtWidgets.QWidget):
    accepted = Signal()
    closed = Signal()

    def __init__(self, anchor):
        super().__init__(anchor.window(), QtCore.Qt.WindowType.Widget)
        anchor.destroyed.connect(self.deleteLater)
        self._anchor = anchor
        self._opened = False
        self._closing = False
        self._watching = []
        self._progress = 0.0
        self._rest = QtCore.QPoint()
        self._placing = False
        self._filter_installed = False
        self.setObjectName("fluentTimeFlyout")
        self.setAccessibleName("时间选择器")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.surface = _TimeSurface(self)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self.surface)
        self.surface.setGraphicsEffect(self._opacity)
        layout = QtWidgets.QVBoxLayout(self.surface)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(0)
        self.wheel = _TimeWheel(self.surface)
        layout.addWidget(self.wheel)
        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(0)
        self.confirm_button = _DateAction(True, self.surface)
        self.cancel_button = _DateAction(False, self.surface)
        self.confirm_button.setAccessibleName("确认时间")
        self.cancel_button.setAccessibleName("取消时间选择")
        self.confirm_button.setToolTip("确认时间")
        self.cancel_button.setToolTip("取消时间选择")
        footer.addWidget(self.confirm_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self.confirm_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.dismiss)
        self.wheel.acceptRequested.connect(self._accept)
        self.wheel.cancelRequested.connect(self.dismiss)
        self._reveal = QtCore.QVariantAnimation(self)
        self._reveal.valueChanged.connect(self._set_progress)
        self._reveal.finished.connect(self._motion_finished)
        theme.subscribe(self, self._refresh_theme)
        self.hide()

    def _refresh_theme(self):
        self.surface.update()
        self.confirm_button.update()
        self.cancel_button.update()

    def _accept(self):
        if self._opened and not self._closing:
            self.accepted.emit()

    def open(self):
        anchor = self._anchor
        if not anchor.isEnabled() or not anchor.isVisible() or anchor.window().height() < 126:
            return
        if self._opened:
            self.dismiss(immediate=True)
        owner = anchor.window()
        if self.parentWidget() is not owner:
            self.setParent(owner, QtCore.Qt.WindowType.Widget)
        for other in owner.findChildren(_TimeFlyout):
            if other is not self:
                other.dismiss(immediate=True)
        self._opened = True
        self._closing = False
        self._progress = 0.0
        self.surface.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        node = anchor
        while node is not None:
            self._watching.append(node)
            node.installEventFilter(self)
            if node is owner:
                break
            node = node.parentWidget()
        QtWidgets.QApplication.instance().installEventFilter(self)
        self._filter_installed = True
        self._place()
        if not self._opened:
            return
        self._set_progress(0.0)
        self.show()
        self.raise_()
        self.wheel.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        self._animate(1.0, 220)

    def dismiss(self, _checked=False, *, immediate=False):
        if not self._opened:
            return
        self._closing = True
        self.surface.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        for animation in self.wheel._animations:
            animation.stop()
        self.wheel._drag_origin = None
        if immediate or self._progress < 0.001:
            self._reveal.stop()
            self._finish_hide()
        else:
            self._animate(0.0, 140)

    def _animate(self, target, duration):
        self._reveal.stop()
        self._reveal.setDuration(duration)
        self._reveal.setEasingCurve(
            QtCore.QEasingCurve.Type.OutCubic if target else QtCore.QEasingCurve.Type.InCubic
        )
        self._reveal.setStartValue(self._progress)
        self._reveal.setEndValue(target)
        self._reveal.start()

    def _set_progress(self, value):
        self._progress = float(value)
        self._opacity.setOpacity(self._progress)
        self.surface.move(self._rest + QtCore.QPoint(0, round(-6 * (1 - self._progress))))

    def _motion_finished(self):
        if self._closing:
            self._finish_hide()

    def _remove_watchers(self):
        if self._filter_installed:
            QtWidgets.QApplication.instance().removeEventFilter(self)
            self._filter_installed = False
        for widget in self._watching:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watching.clear()

    def _finish_hide(self):
        self._opened = False
        self._closing = False
        self._remove_watchers()
        self.hide()
        self.closed.emit()
        if self._anchor.isVisible() and self._anchor.isEnabled():
            self._anchor.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

    def _place(self):
        if self._placing or not self._opened:
            return
        self._placing = True
        try:
            owner = self.parentWidget()
            self.setGeometry(owner.rect())
            anchor = QtCore.QRect(self._anchor.mapTo(owner, QtCore.QPoint()), self._anchor.size())
            if not anchor.intersects(owner.rect()) or owner.height() < 126:
                self.dismiss(immediate=True)
                return
            rows = max(1, min(9, (self.height() - 82) // 44))
            rows -= (rows + 1) % 2
            radius = (rows - 1) // 2
            if self.wheel.RADIUS != radius:
                self.wheel.RADIUS = radius
                self.wheel.setFixedHeight(rows * 44)
                self.wheel._refresh_values()
            width = max(0, min(340, self.width() - 8))
            height = self.wheel.height() + 74
            self.surface.resize(width, height)
            self.surface.layout().activate()
            x = max(4, min(anchor.left() - 10, self.width() - width - 4))
            selected_y = 14 + self.wheel.RADIUS * 44 + 22
            y = max(4, min(anchor.center().y() - selected_y, self.height() - height - 4))
            self._rest = QtCore.QPoint(x, y)
            self._set_progress(self._progress)
        finally:
            self._placing = False

    def eventFilter(self, watched, event):
        if not self._opened:
            return False
        kind = event.type()
        if watched in self._watching:
            if kind in (
                QtCore.QEvent.Type.Hide,
                QtCore.QEvent.Type.Close,
                QtCore.QEvent.Type.WindowDeactivate,
            ):
                self.dismiss(immediate=True)
            elif kind == QtCore.QEvent.Type.EnabledChange and not watched.isEnabled():
                self.dismiss(immediate=True)
            elif kind in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Move) and not self._closing:
                self._place()
        if (
            isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self.window()
            and self._opened
        ):
            key = (
                event.key()
                if kind in (QtCore.QEvent.Type.ShortcutOverride, QtCore.QEvent.Type.KeyPress)
                else None
            )
            if kind == QtCore.QEvent.Type.ShortcutOverride and key in (
                QtCore.Qt.Key.Key_Left,
                QtCore.Qt.Key.Key_Right,
                QtCore.Qt.Key.Key_Up,
                QtCore.Qt.Key.Key_Down,
                QtCore.Qt.Key.Key_PageUp,
                QtCore.Qt.Key.Key_PageDown,
                QtCore.Qt.Key.Key_Return,
                QtCore.Qt.Key.Key_Enter,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.Key.Key_Tab,
                QtCore.Qt.Key.Key_Backtab,
            ):
                event.accept()
                return True
            if kind == QtCore.QEvent.Type.KeyPress:
                if self._closing:
                    return True
                if key == QtCore.Qt.Key.Key_Escape:
                    self.dismiss()
                    return True
                if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
                    widgets = [self.wheel, self.confirm_button, self.cancel_button]
                    focus = QtWidgets.QApplication.focusWidget()
                    index = widgets.index(focus) if focus in widgets else 0
                    backwards = key == QtCore.Qt.Key.Key_Backtab or bool(
                        event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
                    )
                    widgets[(index + (-1 if backwards else 1)) % 3].setFocus(
                        QtCore.Qt.FocusReason.TabFocusReason
                    )
                    return True
        return False

    def mousePressEvent(self, event):
        self.dismiss()
        event.accept()

    def hideEvent(self, event):
        if self._opened:
            self._reveal.stop()
            self._opened = False
            self._closing = False
            self._remove_watchers()
            self.closed.emit()
        super().hideEvent(event)


class TimePicker(QtWidgets.QWidget):
    """Hour/minute picker with optional AM/PM and confirm-to-commit editing.

    Values are QTime in 24-hour form, to minute precision. An empty selection
    returns an invalid QTime. Each wheel is independent; minutes do not carry.
    """

    timeChanged = Signal(QtCore.QTime)
    timeAccepted = Signal(QtCore.QTime)

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, use_12_hour: bool = False):
        clock.backend_name()
        clock.display_time(0, 0, use_12_hour)
        super().__init__(parent)
        self._use_12_hour = use_12_hour
        self._time = QtCore.QTime()
        self._popup = None
        self._column = 0
        self._hover = False
        self._pressed = False
        self.setAccessibleName("时间")
        self.setAccessibleDescription("点击小时、分钟打开选择器；确认后保存，取消保持原值。")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        theme.subscribe(self, self._refresh_theme)
        self._refresh_theme()

    def sizeHint(self):
        return QtCore.QSize(300, 38)

    def minimumSizeHint(self):
        return QtCore.QSize(210 if self._use_12_hour else 160, 34)

    def time(self) -> QtCore.QTime:
        """Return a copy of the committed QTime, or an invalid QTime if empty."""
        return QtCore.QTime(self._time)

    def acceleration_backend(self) -> str:
        return clock.backend_name()

    def set_time(self, value: QtCore.QTime) -> None:
        """Set time to minute precision; invalid QTime clears the selection."""
        if not isinstance(value, QtCore.QTime):
            raise TypeError("time must be a QTime")
        if not value.isValid():
            self.clear()
            return
        result = QtCore.QTime(*clock.validate_time(value.hour(), value.minute()))
        if result != self._time:
            self._time = result
            self._update_description()
            self.update()
            self.timeChanged.emit(self.time())
        self._sync_popup()

    def setTime(self, value: QtCore.QTime) -> None:
        self.set_time(value)

    def clear(self) -> None:
        """Clear the selected time and discard any open draft."""
        if self._popup is not None:
            self._popup.dismiss(immediate=True)
        if self._time.isValid():
            self._time = QtCore.QTime()
            self._update_description()
            self.update()
            self.timeChanged.emit(self.time())

    def is_12_hour_clock(self) -> bool:
        return self._use_12_hour

    def set_12_hour_clock(self, enabled: bool) -> None:
        """Change presentation without changing the committed canonical time."""
        clock.display_time(0, 0, enabled)
        if enabled == self._use_12_hour:
            return
        if self._popup is not None:
            self._popup.dismiss(immediate=True)
        self._use_12_hour = enabled
        self._column = 0
        self._update_description()
        self.updateGeometry()
        self.update()

    def set12HourClock(self, enabled: bool) -> None:
        self.set_12_hour_clock(enabled)

    def is12HourClock(self) -> bool:
        return self.is_12_hour_clock()

    def _update_description(self):
        self.setToolTip(
            self._time.toString("h:mm AP" if self._use_12_hour else "HH:mm")
            if self._time.isValid()
            else ""
        )
        self.setAccessibleDescription(
            "当前时间："
            + (self._time.toString("HH:mm") if self._time.isValid() else "未选择")
            + "。确认后保存，Escape取消。"
        )

    def show_popup(self) -> None:
        """Open an in-window draft; clicking outside cancels without committing."""
        if not self.isEnabled() or not self.isVisible():
            return
        if self._popup is None:
            self._popup = _TimeFlyout(self)
            self._popup.accepted.connect(self._accept_pending)
            self._popup.closed.connect(self.update)
        if self._popup._opened and not self._popup._closing:
            self._popup.dismiss()
            return
        if self._popup._opened:
            self._popup.dismiss(immediate=True)
        self._sync_popup(force=True)
        self._popup.open()

    def _sync_popup(self, *, force=False):
        if self._popup is not None and (force or self._popup._opened and not self._popup._closing):
            value = self._time if self._time.isValid() else QtCore.QTime.currentTime()
            self._popup.wheel.set_value(
                (value.hour(), value.minute()), self._use_12_hour, self._column
            )

    def _accept_pending(self):
        value = QtCore.QTime(*self._popup.wheel.value)
        self._popup.dismiss()
        self.set_time(value)
        self.timeAccepted.emit(self.time())

    def _refresh_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            count = 3 if self._use_12_hour else 2
            self._column = max(
                0, min(count - 1, int(event.position().x() * count / max(1, self.width())))
            )
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        activate = (
            self._pressed
            and event.button() == QtCore.Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        )
        self._pressed = False
        if activate:
            self.show_popup()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (
            QtCore.Qt.Key.Key_Space,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.Key.Key_F4,
        ):
            self.show_popup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self._pressed = False
        if self._popup is not None:
            self._popup.dismiss(immediate=True)
        super().hideEvent(event)

    def changeEvent(self, event):
        if (
            event.type() == QtCore.QEvent.Type.EnabledChange
            and not self.isEnabled()
            and self._popup is not None
        ):
            self._popup.dismiss(immediate=True)
        super().changeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        tokens = theme.tokens
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        surface = (
            tokens.surface_pressed
            if self._pressed
            else tokens.surface_hover
            if self._hover
            else tokens.surface
        )
        painter.setBrush(QtGui.QColor(surface))
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens.border), 1))
        painter.drawRoundedRect(rect, tokens.radius, tokens.radius)
        count = 3 if self._use_12_hour else 2
        width = self.width() / count
        for column in range(1, count):
            painter.drawLine(
                QtCore.QPointF(column * width, 1), QtCore.QPointF(column * width, self.height() - 1)
            )
        if self.hasFocus() and self.isEnabled():
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.accent), 2))
            painter.drawLine(
                QtCore.QPointF(5, self.height() - 1),
                QtCore.QPointF(self.width() - 5, self.height() - 1),
            )
        if self._time.isValid():
            h, m, period = clock.display_time(
                self._time.hour(), self._time.minute(), self._use_12_hour
            )
            values = (
                str(h) if self._use_12_hour else f"{h:02d}",
                f"{m:02d}",
                "PM" if period else "AM",
            )[:count]
        else:
            values = ("小时", "分钟", "AM/PM")[:count]
        painter.setPen(
            QtGui.QColor(
                (tokens.text if self._time.isValid() else tokens.text_muted)
                if self.isEnabled()
                else tokens.disabled
            )
        )
        for column, value in enumerate(values):
            painter.drawText(
                QtCore.QRectF(column * width, 0, width, self.height()),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                value,
            )
