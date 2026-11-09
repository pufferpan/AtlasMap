"""Passive Qt card containers with independent child controls."""

from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


def _mix(first: QtGui.QColor, second: QtGui.QColor, amount: float) -> QtGui.QColor:
    amount = max(0.0, min(1.0, amount))
    return QtGui.QColor.fromRgbF(
        first.redF() + (second.redF() - first.redF()) * amount,
        first.greenF() + (second.greenF() - first.greenF()) * amount,
        first.blueF() + (second.blueF() - first.blueF()) * amount,
        first.alphaF() + (second.alphaF() - first.alphaF()) * amount,
    )


class CardWidget(QtWidgets.QFrame):
    """A passive surface; callers install their own ordinary Qt layout.

    The card does not handle clicks or keyboard activation. Buttons, inputs,
    and other child widgets retain their own ordinary Qt interactions.
    """

    _static_surface = False

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._border_radius = 8
        self._hover_progress = 0.0
        self._hovered = False
        self._hover_animation = QtCore.QVariantAnimation(self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_progress)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def border_radius(self) -> int:
        return self._border_radius

    def set_border_radius(self, radius: int) -> None:
        if not isinstance(radius, int) or isinstance(radius, bool):
            raise TypeError("border radius must be an int")
        if radius < 0:
            raise ValueError("border radius must be nonnegative")
        if radius != self._border_radius:
            self._border_radius = radius
            self.update()

    def borderRadius(self) -> int:
        return self.border_radius()

    def setBorderRadius(self, radius: int) -> None:
        self.set_border_radius(radius)

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = float(value)
        self._update_shadow()
        self.update()

    def _animate_hover(self, value: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(value)
        self._hover_animation.start()

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        self._hovered = self.isEnabled()
        self._animate_hover(float(self._hovered))
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._hover_animation.stop()
        self._hovered = False
        self._set_hover_progress(0.0)
        super().hideEvent(event)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.EnabledChange:
            if not self.isEnabled():
                self._hovered = False
                self._hover_animation.stop()
                self._hover_progress = 0.0
            self._update_shadow()
            self.update()
        super().changeEvent(event)

    def _surface_color(self) -> QtGui.QColor:
        tokens = theme.tokens
        color = QtGui.QColor(tokens.surface)
        if not self.isEnabled():
            return _mix(color, QtGui.QColor(tokens.background), 0.40)
        if self._static_surface:
            return color
        hover = QtGui.QColor("#f8f9fb" if tokens.mode.value == "light" else tokens.surface_hover)
        return _mix(color, hover, self._hover_progress)

    def _update_shadow(self) -> None:
        """Subclass hook: update visual elevation without moving the widget."""

    def _apply_theme(self) -> None:
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._update_shadow()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(self._border_radius, max(0.0, min(rect.width(), rect.height()) / 2))
        painter.setBrush(self._surface_color())
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
        painter.drawRoundedRect(rect, radius, radius)


class SimpleCardWidget(CardWidget):
    """A passive card whose background stays static on hover."""

    _static_surface = True


class ElevatedCardWidget(CardWidget):
    """A card with a light animated shadow, keeping layout geometry fixed."""

    _static_surface = True

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)
        self._update_shadow()

    def _update_shadow(self) -> None:
        shadow = getattr(self, "_shadow", None)
        if shadow is None:
            return
        hover = self._hover_progress if self.isEnabled() else 0.0
        shadow.setBlurRadius(12 + 6 * hover)
        shadow.setOffset(0, 2 + 2 * hover)
        alpha = (16 + 8 * hover) if theme.tokens.mode.value == "light" else (30 + 10 * hover)
        shadow.setColor(QtGui.QColor(0, 0, 0, round(alpha)))
