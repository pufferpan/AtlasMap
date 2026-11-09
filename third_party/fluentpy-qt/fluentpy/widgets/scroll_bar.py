from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme


class FluentScrollBar(QtWidgets.QScrollBar):
    def __init__(
        self,
        orientation: QtCore.Qt.Orientation = QtCore.Qt.Orientation.Vertical,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self._hover = False
        self._pressed = False
        self._dragging = False
        self._drag_offset = 0
        self._thickness = 10.0
        self._thickness_animation = QtCore.QVariantAnimation(self)
        self._thickness_animation.setDuration(120)
        self._thickness_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._thickness_animation.valueChanged.connect(self._set_thickness)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.setStyleSheet("QScrollBar { background: transparent; }")
        self._apply_thickness()
        theme.subscribe(self, self.update)

    def sizeHint(self) -> QtCore.QSize:
        thickness = round(self._thickness)
        if self.orientation() == QtCore.Qt.Orientation.Vertical:
            return QtCore.QSize(thickness, 64)
        return QtCore.QSize(64, thickness)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self._animate_thickness(16.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self._pressed = False
        self._dragging = False
        self._animate_thickness(10.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = self._event_position(event)
        handle = self._handle_rect()
        self._pressed = True
        if handle.contains(event.position()):
            self._dragging = True
            self._drag_offset = round(pos - self._main_start(handle))
        else:
            step = self.pageStep()
            self.setValue(
                self.value() - step if pos < self._main_start(handle) else self.value() + step
            )
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging:
            self._set_value_from_position(self._event_position(event) - self._drag_offset)
            return
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._pressed = False
        self._dragging = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        if self._hover:
            track = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
            track.setAlpha(10 if theme.tokens.mode.value == "light" else 12)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRect(self.rect())
            self._draw_arrows(painter)

        handle = self._handle_rect()
        color = QtGui.QColor("#5e5e5e" if theme.tokens.mode.value == "light" else "#b8bdc8")
        color.setAlpha(178 if self._hover else 150)
        if self._pressed:
            color.setAlpha(210)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        radius = 3 if self._hover else 2
        painter.drawRoundedRect(handle, radius, radius)

    def _draw_arrows(self, painter: QtGui.QPainter) -> None:
        color = QtGui.QColor("#696969" if theme.tokens.mode.value == "light" else "#c4c8d0")
        color.setAlpha(190)
        painter.setBrush(color)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        if self.orientation() == QtCore.Qt.Orientation.Vertical:
            cx = self.width() / 2
            up = QtGui.QPolygonF(
                [
                    QtCore.QPointF(cx, 5),
                    QtCore.QPointF(cx - 4, 10),
                    QtCore.QPointF(cx + 4, 10),
                ]
            )
            down = QtGui.QPolygonF(
                [
                    QtCore.QPointF(cx, self.height() - 5),
                    QtCore.QPointF(cx - 4, self.height() - 10),
                    QtCore.QPointF(cx + 4, self.height() - 10),
                ]
            )
            painter.drawPolygon(up)
            painter.drawPolygon(down)
            return

        cy = self.height() / 2
        left = QtGui.QPolygonF(
            [
                QtCore.QPointF(5, cy),
                QtCore.QPointF(10, cy - 4),
                QtCore.QPointF(10, cy + 4),
            ]
        )
        right = QtGui.QPolygonF(
            [
                QtCore.QPointF(self.width() - 5, cy),
                QtCore.QPointF(self.width() - 10, cy - 4),
                QtCore.QPointF(self.width() - 10, cy + 4),
            ]
        )
        painter.drawPolygon(left)
        painter.drawPolygon(right)

    def _handle_rect(self) -> QtCore.QRectF:
        length = (
            self.height() if self.orientation() == QtCore.Qt.Orientation.Vertical else self.width()
        )
        thickness = (
            self.width() if self.orientation() == QtCore.Qt.Orientation.Vertical else self.height()
        )
        arrow_margin = 16 if self._hover else 4
        track_length = max(1, length - arrow_margin * 2)
        total = max(1, self.maximum() - self.minimum() + self.pageStep())
        handle_length = max(48.0, track_length * self.pageStep() / total)
        travel = max(1.0, track_length - handle_length)
        value_range = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / value_range
        offset = arrow_margin + travel * ratio

        if self.orientation() == QtCore.Qt.Orientation.Vertical:
            width = 6 if self._hover else 3
            x = (thickness - width) / 2
            return QtCore.QRectF(x, offset, width, handle_length)
        height = 6 if self._hover else 3
        y = (thickness - height) / 2
        return QtCore.QRectF(offset, y, handle_length, height)

    def _set_value_from_position(self, position: float) -> None:
        length = (
            self.height() if self.orientation() == QtCore.Qt.Orientation.Vertical else self.width()
        )
        arrow_margin = 16 if self._hover else 4
        handle = self._handle_rect()
        handle_length = (
            handle.height()
            if self.orientation() == QtCore.Qt.Orientation.Vertical
            else handle.width()
        )
        travel = max(1.0, length - arrow_margin * 2 - handle_length)
        ratio = max(0.0, min(1.0, (position - arrow_margin) / travel))
        self.setValue(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def _event_position(self, event: QtGui.QMouseEvent) -> float:
        return (
            event.position().y()
            if self.orientation() == QtCore.Qt.Orientation.Vertical
            else event.position().x()
        )

    def _main_start(self, rect: QtCore.QRectF) -> float:
        return rect.top() if self.orientation() == QtCore.Qt.Orientation.Vertical else rect.left()

    def _animate_thickness(self, end: float) -> None:
        self._thickness_animation.stop()
        self._thickness_animation.setStartValue(self._thickness)
        self._thickness_animation.setEndValue(end)
        self._thickness_animation.start()

    def _set_thickness(self, value: object) -> None:
        self._thickness = float(value)
        self._apply_thickness()
        self.updateGeometry()
        self.update()

    def _apply_thickness(self) -> None:
        thickness = round(self._thickness)
        if self.orientation() == QtCore.Qt.Orientation.Vertical:
            self.setFixedWidth(thickness)
        else:
            self.setFixedHeight(thickness)
