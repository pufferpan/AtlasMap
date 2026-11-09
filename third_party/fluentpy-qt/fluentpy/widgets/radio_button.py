from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


class RadioButton(QtWidgets.QAbstractButton):
    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setText(text)
        self.setObjectName("fluentRadioButton")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMinimumHeight(30)
        self._hovered = False
        self._hover_progress = 0.0
        self._inner_progress = 0.0
        self._hover_animation = QtCore.QVariantAnimation(self)
        self._hover_animation.setDuration(theme.tokens.animation_ms)
        self._hover_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_progress)
        self._inner_animation = QtCore.QVariantAnimation(self)
        self._inner_animation.setDuration(theme.tokens.animation_ms)
        self._inner_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._inner_animation.valueChanged.connect(self._set_inner_progress)
        theme.subscribe(self, self.update)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self.fontMetrics().horizontalAdvance(self.text()) + 34, 30)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self._animate_hover(1.0)
        self._animate_inner(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self._animate_hover(0.0)
        self._animate_inner(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        center = QtCore.QPointF(10, self.height() / 2)
        outer_radius = 9.0
        if self.isChecked():
            border = QtGui.QColor(tokens.accent)
            fill = QtGui.QColor(tokens.accent)
        else:
            border = QtGui.QColor("#000000" if tokens.mode.value == "light" else "#ffffff")
            border.setAlpha(120 if tokens.mode.value == "light" else 150)
            fill = QtGui.QColor(0, 0, 0, 0)
        if self._hover_progress and not self.isChecked():
            border = _mix_color(border, QtGui.QColor(tokens.accent), self._hover_progress * 0.45)

        painter.setPen(QtGui.QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawEllipse(center, outer_radius, outer_radius)

        if self.isChecked():
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor("#ffffff"))
            inner_radius = 3.5 + 1.2 * self._inner_progress
            painter.drawEllipse(center, inner_radius, inner_radius)

        text_color = QtGui.QColor(tokens.text if self.isEnabled() else tokens.disabled)
        painter.setPen(text_color)
        painter.drawText(
            QtCore.QRectF(28, 0, self.width() - 28, self.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )

    def _animate_hover(self, end: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(end)
        self._hover_animation.start()

    def _animate_inner(self, end: float) -> None:
        self._inner_animation.stop()
        self._inner_animation.setStartValue(self._inner_progress)
        self._inner_animation.setEndValue(end)
        self._inner_animation.start()

    def _set_hover_progress(self, value: object) -> None:
        self._hover_progress = float(value)
        self.update()

    def _set_inner_progress(self, value: object) -> None:
        self._inner_progress = float(value)
        self.update()


def _mix_color(start: QtGui.QColor, end: QtGui.QColor, progress: float) -> QtGui.QColor:
    progress = max(0.0, min(1.0, progress))
    return QtGui.QColor(
        round(start.red() + (end.red() - start.red()) * progress),
        round(start.green() + (end.green() - start.green()) * progress),
        round(start.blue() + (end.blue() - start.blue()) * progress),
        round(start.alpha() + (end.alpha() - start.alpha()) * progress),
    )
