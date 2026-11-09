"""Three-column date picker with C acceleration and Python calendar fallback."""

from __future__ import annotations

from ..backends import date as calendar
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font


class _DateWheel(QtWidgets.QWidget):
    acceptRequested = Signal()
    cancelRequested = Signal()

    ROW_HEIGHT = 44
    RADIUS = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.value = (2024, 1, 1)
        self.minimum = (1900, 1, 1)
        self.maximum = (2100, 12, 31)
        self.column = 0
        self._values = ((), (), ())
        self._offsets = [0.0, 0.0, 0.0]
        self._animations = []
        self._wheel_remainders = [0, 0, 0]
        self._wheel_mode = None
        self._drag_origin = None
        self._drag_last_y = 0.0
        self._drag_pixels = 0.0
        self._dragged = False
        for column in range(3):
            animation = QtCore.QVariantAnimation(self)
            animation.setDuration(130)
            animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(lambda value, c=column: self._animate(c, value))
            self._animations.append(animation)
        self.setFixedHeight(self.ROW_HEIGHT * (2 * self.RADIUS + 1))
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("日期滚轮：年、月、日")
        self.setAccessibleDescription(
            "左右切换列，上下选择，Enter 确认，Escape 取消。也可滚动、拖动或点击日期。"
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        theme.subscribe(self, self._refresh_theme)
        self._refresh_theme()

    def _refresh_theme(self) -> None:
        self.setFont(ui_font(16, self.font()))
        self.update()

    def set_value(self, value, minimum, maximum, column=0) -> None:
        for animation in self._animations:
            animation.stop()
        self._offsets = [0.0, 0.0, 0.0]
        self._wheel_remainders = [0, 0, 0]
        self._wheel_mode = None
        self.minimum, self.maximum = minimum, maximum
        self.value = calendar.clamp_date(*value, minimum=minimum, maximum=maximum)
        self.column = column
        self._refresh_values()

    def _refresh_values(self) -> None:
        self._values = tuple(
            calendar.column_values(
                *self.value,
                column,
                radius=self.RADIUS + 1,
                minimum=self.minimum,
                maximum=self.maximum,
            )
            for column in range(3)
        )
        self.setAccessibleDescription(
            f"当前 {self.value[0]}年{self.value[1]}月{self.value[2]}日。"
            "左右切换列，上下选择，Enter 确认，Escape 取消。"
        )
        self.update()

    def step(self, column: int, steps: int, *, animate: bool = True) -> None:
        self.column = column
        previous = self.value
        self.value = calendar.step_date(
            *self.value,
            column,
            steps,
            minimum=self.minimum,
            maximum=self.maximum,
        )
        self._refresh_values()
        if animate and self.value != previous:
            animation = self._animations[column]
            animation.stop()
            animation.setStartValue(float(self.ROW_HEIGHT if steps > 0 else -self.ROW_HEIGHT))
            animation.setEndValue(0.0)
            animation.start()

    def _animate(self, column, offset) -> None:
        self._offsets[column] = float(offset)
        self.update()

    def _column_at(self, x: float) -> int:
        count = self._column_count()
        return max(0, min(count - 1, int(x * count / max(1, self.width()))))

    def _column_count(self) -> int:
        return 3

    def _format_value(self, column, value) -> str:
        return f"{value}{('年', '月', '日')[column]}"

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        column = self._column_at(event.position().x())
        self.column = column
        mode = "pixel" if not event.pixelDelta().isNull() else "angle"
        if mode != self._wheel_mode:
            self._wheel_remainders = [0, 0, 0]
            self._wheel_mode = mode
        if mode == "pixel":
            self._wheel_remainders[column] += event.pixelDelta().y()
            threshold = self.ROW_HEIGHT
        else:
            self._wheel_remainders[column] += event.angleDelta().y()
            threshold = 120
        steps = int(self._wheel_remainders[column] / threshold)
        if steps:
            self._wheel_remainders[column] -= steps * threshold
            self.step(column, -steps)
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.column = self._column_at(event.position().x())
        self._animations[self.column].stop()
        self._drag_origin = event.position()
        self._drag_last_y = event.position().y()
        self._drag_pixels = 0.0
        self._dragged = False
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_origin is None:
            return super().mouseMoveEvent(event)
        self._drag_pixels += event.position().y() - self._drag_last_y
        self._drag_last_y = event.position().y()
        self._dragged |= abs(event.position().y() - self._drag_origin.y()) > 4
        steps = int(self._drag_pixels / self.ROW_HEIGHT)
        if steps:
            self.step(self.column, -steps, animate=False)
            self._drag_pixels -= steps * self.ROW_HEIGHT
        self._offsets[self.column] = self._drag_pixels
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self._drag_origin is None:
            return super().mouseReleaseEvent(event)
        if self._dragged:
            steps = int(round(self._drag_pixels / self.ROW_HEIGHT))
            if steps:
                self.step(self.column, -steps, animate=False)
        else:
            row = int(event.position().y() / self.ROW_HEIGHT) - self.RADIUS
            if row:
                self.step(self.column, row)
        self._offsets[self.column] = 0.0
        self._drag_origin = None
        self.update()
        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.acceptRequested.emit()
        elif key == QtCore.Qt.Key.Key_Escape:
            self.cancelRequested.emit()
        elif key in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right):
            self.column = (
                self.column + (1 if key == QtCore.Qt.Key.Key_Right else -1)
            ) % self._column_count()
            self.update()
        elif key in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down):
            self.step(self.column, -1 if key == QtCore.Qt.Key.Key_Up else 1)
        elif key in (QtCore.Qt.Key.Key_PageUp, QtCore.Qt.Key.Key_PageDown):
            self.step(self.column, -5 if key == QtCore.Qt.Key.Key_PageUp else 5)
        else:
            return super().keyPressEvent(event)
        event.accept()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setFont(ui_font(16, self.font()))
        tokens = theme.tokens
        width = self.width() / self._column_count()
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens.border), 1))
        for column in range(1, self._column_count()):
            painter.drawLine(
                QtCore.QPointF(column * width, 0), QtCore.QPointF(column * width, self.height())
            )
        selected = QtCore.QRectF(0, self.RADIUS * self.ROW_HEIGHT, self.width(), self.ROW_HEIGHT)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        accent = QtGui.QColor(tokens.accent)
        painter.setBrush(accent)
        painter.drawRoundedRect(selected, 6, 6)
        selected_text = QtGui.QColor("#102429" if QtGui.qGray(accent.rgb()) > 170 else "#ffffff")
        for column, values in enumerate(self._values):
            painter.save()
            painter.setClipRect(QtCore.QRectF(column * width, 0, width, self.height()))
            for index, value in enumerate(values):
                if value is None:
                    continue
                y = (index - 1) * self.ROW_HEIGHT + self._offsets[column]
                row_rect = QtCore.QRectF(column * width, y, width, self.ROW_HEIGHT)
                painter.setPen(QtGui.QColor(tokens.text))
                painter.drawText(
                    row_rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._format_value(column, value)
                )
                painter.save()
                painter.setClipRect(selected, QtCore.Qt.ClipOperation.IntersectClip)
                painter.setPen(selected_text)
                painter.drawText(
                    row_rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._format_value(column, value)
                )
                painter.restore()
            painter.restore()


class _DateAction(QtWidgets.QAbstractButton):
    def __init__(self, confirm: bool, parent=None) -> None:
        super().__init__(parent)
        self.confirm = confirm
        self.setAccessibleName("确认日期" if confirm else "取消日期选择")
        self.setToolTip(self.accessibleName())
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(48)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self.underMouse() or self.hasFocus():
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(theme.tokens.surface_high))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(4, 5, -4, -5), 5, 5)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(theme.tokens.text),
                1.6,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        center = QtCore.QPointF(self.rect().center())
        if self.confirm:
            path = QtGui.QPainterPath(center + QtCore.QPointF(-8, 0))
            path.lineTo(center + QtCore.QPointF(-3, 5))
            path.lineTo(center + QtCore.QPointF(8, -6))
            painter.drawPath(path)
        else:
            painter.drawLine(center + QtCore.QPointF(-6, -6), center + QtCore.QPointF(6, 6))
            painter.drawLine(center + QtCore.QPointF(6, -6), center + QtCore.QPointF(-6, 6))


class _DatePanel(QtWidgets.QFrame):
    def paintEvent(self, event) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor(theme.tokens.surface))
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, 8, 8)
        painter.drawLine(
            QtCore.QPointF(1, self.height() - 48),
            QtCore.QPointF(self.width() - 1, self.height() - 48),
        )


class _DatePopup(QtWidgets.QFrame):
    accepted = Signal()
    closed = Signal()

    def __init__(self, parent) -> None:
        super().__init__(
            parent,
            QtCore.Qt.WindowType.Popup
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("fluentDatePopup")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAccessibleName("日期选择器")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 16)
        root.setSpacing(0)
        self.panel = _DatePanel(self)
        root.addWidget(self.panel)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 5)
        shadow.setColor(QtGui.QColor(0, 0, 0, 45))
        self.panel.setGraphicsEffect(shadow)
        layout = QtWidgets.QVBoxLayout(self.panel)
        layout.setContentsMargins(6, 6, 6, 0)
        layout.setSpacing(0)
        self.wheel = _DateWheel(self.panel)
        layout.addWidget(self.wheel)
        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(0)
        self.confirm_button = _DateAction(True, self.panel)
        self.cancel_button = _DateAction(False, self.panel)
        footer.addWidget(self.confirm_button)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self.confirm_button.clicked.connect(self.accepted)
        self.cancel_button.clicked.connect(self.close)
        self.wheel.acceptRequested.connect(self.accepted)
        self.wheel.cancelRequested.connect(self.close)
        self.setFixedSize(360, self.wheel.height() + 80)
        theme.subscribe(self, self._refresh_theme)

    def _refresh_theme(self) -> None:
        self.panel.update()
        self.confirm_button.update()
        self.cancel_button.update()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.closed.emit()
        super().hideEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)


class DatePicker(QtWidgets.QWidget):
    """Year/month/day field with a confirmed, three-wheel date flyout.

    An unselected picker returns an invalid QDate. Calendar calculations prefer
    the compiled C backend and remain available with the Python fallback.
    """

    dateChanged = Signal(QtCore.QDate)
    dateAccepted = Signal(QtCore.QDate)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        calendar.backend_name()
        super().__init__(parent)
        self._minimum = (1900, 1, 1)
        self._maximum = (2100, 12, 31)
        self._date = QtCore.QDate()
        self._popup = None
        self._hover = False
        self._pressed = False
        self._column = 0
        calendar.clamp_date(*self._minimum, minimum=self._minimum, maximum=self._maximum)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("日期")
        self.setAccessibleDescription(
            "点击年、月、日打开日期选择器；使用方向键选择，Enter 确认，Escape 取消。"
        )
        self._refresh_theme()
        theme.subscribe(self, self._refresh_theme)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(300, 38)

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(240, 34)

    def date(self) -> QtCore.QDate:
        return QtCore.QDate(self._date)

    def acceleration_backend(self) -> str:
        return calendar.backend_name()

    def set_date(self, value: QtCore.QDate) -> None:
        if not isinstance(value, QtCore.QDate):
            raise TypeError("date must be a QDate")
        if not value.isValid():
            self.clear()
            return
        parts = calendar.clamp_date(*value.getDate(), minimum=self._minimum, maximum=self._maximum)
        result = QtCore.QDate(*parts)
        if result != self._date:
            self._date = result
            self.setToolTip(result.toString("yyyy-MM-dd"))
            self.update()
            self.dateChanged.emit(self.date())
        self._sync_popup()

    def setDate(self, value: QtCore.QDate) -> None:
        self.set_date(value)

    def clear(self) -> None:
        if self._popup is not None:
            self._popup.close()
        if self._date.isValid():
            self._date = QtCore.QDate()
            self.setToolTip("")
            self.update()
            self.dateChanged.emit(self.date())

    def set_date_range(self, minimum: QtCore.QDate, maximum: QtCore.QDate) -> None:
        if not isinstance(minimum, QtCore.QDate) or not isinstance(maximum, QtCore.QDate):
            raise TypeError("date bounds must be QDate values")
        if not minimum.isValid() or not maximum.isValid():
            raise ValueError("date bounds must be valid")
        lower, upper = minimum.getDate(), maximum.getDate()
        calendar.clamp_date(*lower, minimum=lower, maximum=upper)
        self._minimum, self._maximum = lower, upper
        if self._date.isValid():
            self.set_date(self._date)
        self._sync_popup()

    def minimum_date(self) -> QtCore.QDate:
        return QtCore.QDate(*self._minimum)

    def maximum_date(self) -> QtCore.QDate:
        return QtCore.QDate(*self._maximum)

    def setMinimumDate(self, value: QtCore.QDate) -> None:
        self.set_date_range(value, self.maximum_date())

    def setMaximumDate(self, value: QtCore.QDate) -> None:
        self.set_date_range(self.minimum_date(), value)

    def show_popup(self) -> None:
        if not self.isEnabled():
            return
        if self._popup is None:
            self._popup = _DatePopup(self)
            self._popup.accepted.connect(self._accept_pending)
            self._popup.closed.connect(self._popup_closed)
        if self._popup.isVisible():
            self._popup.close()
            return
        self._sync_popup(force=True)
        self._popup.adjustSize()
        # Align the selected wheel row with the collapsed field.
        selected_y = (
            16
            + self._popup.wheel.RADIUS * self._popup.wheel.ROW_HEIGHT
            + self._popup.wheel.ROW_HEIGHT // 2
        )
        anchor = self.mapToGlobal(QtCore.QPoint(0, self.height() // 2 - selected_y))
        screen = QtGui.QGuiApplication.screenAt(anchor) or QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 800)
        anchor.setX(
            max(available.left(), min(anchor.x() - 12, available.right() - self._popup.width() + 1))
        )
        anchor.setY(
            max(available.top(), min(anchor.y(), available.bottom() - self._popup.height() + 1))
        )
        self._popup.move(anchor)
        self._popup.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen,
            self.window().testAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen),
        )
        self._popup.show()
        self._popup.raise_()
        self._popup.wheel.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        self.update()

    def _sync_popup(self, *, force: bool = False) -> None:
        if self._popup is not None and (force or self._popup.isVisible()):
            value = self._date if self._date.isValid() else QtCore.QDate.currentDate()
            self._popup.wheel.set_value(value.getDate(), self._minimum, self._maximum, self._column)

    def _accept_pending(self) -> None:
        value = QtCore.QDate(*self._popup.wheel.value)
        self._popup.close()
        self.set_date(value)
        self.dateAccepted.emit(self.date())
        self.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

    def _popup_closed(self) -> None:
        self._pressed = False
        self.update()

    def _refresh_theme(self) -> None:
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self._column = max(0, min(2, int(event.position().x() * 3 / max(1, self.width()))))
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
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

    def keyPressEvent(self, event) -> None:
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

    def hideEvent(self, event) -> None:
        if self._popup is not None:
            self._popup.close()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if (
            event.type() == QtCore.QEvent.Type.EnabledChange
            and not self.isEnabled()
            and self._popup is not None
        ):
            self._popup.close()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        del event
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
        width = self.width() / 3
        for column in (1, 2):
            painter.drawLine(
                QtCore.QPointF(column * width, 1), QtCore.QPointF(column * width, self.height() - 1)
            )
        if self.hasFocus() and self.isEnabled():
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.accent), 2))
            painter.drawLine(
                QtCore.QPointF(5, self.height() - 1),
                QtCore.QPointF(self.width() - 5, self.height() - 1),
            )
        values = (
            (f"{self._date.year()}年", f"{self._date.month()}月", f"{self._date.day()}日")
            if self._date.isValid()
            else ("年", "月", "日")
        )
        color = tokens.text if self._date.isValid() else tokens.text_muted
        painter.setPen(QtGui.QColor(color if self.isEnabled() else tokens.disabled))
        for column, value in enumerate(values):
            painter.drawText(
                QtCore.QRectF(column * width, 0, width, self.height()),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                value,
            )
