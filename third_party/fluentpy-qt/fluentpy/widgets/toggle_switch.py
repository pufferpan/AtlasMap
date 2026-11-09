from __future__ import annotations

from ..qt import Property, QtCore, QtGui, QtWidgets, Signal
from ..theme import theme


class ToggleSwitch(QtWidgets.QAbstractButton):
    toggledByUser = Signal(bool)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 24)
        self._hovered = False
        self._knob_offset = self._target_offset()
        self._animation = QtCore.QPropertyAnimation(self, b"knobOffset", self)
        self._animation.setDuration(theme.tokens.animation_ms)
        self.clicked.connect(self._animate_to_state)
        theme.subscribe(self, self.update)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(46, 24)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def get_knob_offset(self) -> float:
        return self._knob_offset

    def set_knob_offset(self, value: float) -> None:
        self._knob_offset = value
        self.update()

    knobOffset = Property(float, get_knob_offset, set_knob_offset)

    def setChecked(self, checked: bool) -> None:
        self._animation.stop()
        super().setChecked(checked)
        self._knob_offset = self._target_offset()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        track = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            track_color = QtGui.QColor(tokens.accent)
            if self._hovered:
                track_color = track_color.lighter(112)
            if self.isDown():
                track_color = track_color.darker(115)
        else:
            track_color = QtGui.QColor("#000000" if tokens.mode.value == "light" else "#ffffff")
            track_color.setAlpha(8 if tokens.mode.value == "light" else 15)
            if self._hovered:
                track_color.setAlpha(14 if tokens.mode.value == "light" else 22)
            if self.isDown():
                track_color.setAlpha(20 if tokens.mode.value == "light" else 10)
        if not self.isEnabled():
            track_color = QtGui.QColor(tokens.disabled)
            track_color.setAlpha(80)

        border = QtGui.QColor("#000000" if tokens.mode.value == "light" else "#ffffff")
        border.setAlpha(60 if not self.isChecked() else 40)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 12, 12)

        knob_size = 18 if not self.isDown() else 16
        knob_y = (self.height() - knob_size) / 2
        knob_x = self._knob_offset + (1 if self.isDown() and not self.isChecked() else 0)
        knob = QtCore.QRectF(knob_x, knob_y, knob_size, knob_size)
        knob_color = QtGui.QColor("#ffffff" if self.isChecked() else tokens.text)
        if not self.isChecked():
            knob_color.setAlpha(190 if tokens.mode.value == "light" else 220)
        if not self.isEnabled():
            knob_color = QtGui.QColor("#dddddd")
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawEllipse(knob)

    def _target_offset(self) -> float:
        return 25.0 if self.isChecked() else 3.0

    def _animate_to_state(self) -> None:
        self._animation.stop()
        self._animation.setDuration(theme.tokens.animation_ms)
        self._animation.setStartValue(self._knob_offset)
        self._animation.setEndValue(self._target_offset())
        self._animation.start()
        self.toggledByUser.emit(self.isChecked())
