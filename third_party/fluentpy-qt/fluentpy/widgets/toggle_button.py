"""Checkable buttons with animated selection state."""

from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtGui, QtWidgets
from ..theme import theme
from .button import Button, _mix_color, _readable_on


class ToggleButton(Button):
    """Checkable button with an animated selected state.

    Selection uses Qt's checked/toggled API and supports QButtonGroup.
    """

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._selection = 0.0
        self._selection_animation = self._make_state_animation("_selection")
        self.setCheckable(True)
        self.toggled.connect(self._selection_changed)

    def _selection_changed(self, checked):
        if self.isVisible():
            self._animate_state(
                self._selection_animation, self._selection, 1.0 if checked else 0.0, 180
            )
        else:
            self._selection_animation.stop()
            self._selection = float(checked)
            self.update()

    def _surface_color(self):
        return _mix_color(
            super()._surface_color(), QtGui.QColor(theme.tokens.accent), self._selection
        )

    def _surface_hover_color(self):
        return _mix_color(
            super()._surface_hover_color(),
            QtGui.QColor(theme.tokens.accent).lighter(104),
            self._selection,
        )

    def _surface_pressed_color(self):
        return _mix_color(
            super()._surface_pressed_color(),
            QtGui.QColor(theme.tokens.accent).darker(110),
            self._selection,
        )

    def _draw_content(self, painter, rect, color):
        if self.isEnabled():
            color = _mix_color(
                color, _readable_on(QtGui.QColor(theme.tokens.accent)), self._selection
            )
        super()._draw_content(painter, rect, color)

    def hideEvent(self, event):
        self._selection_animation.stop()
        self._selection = float(self.isChecked())
        super().hideEvent(event)


class PillToggleButton(ToggleButton):
    _pill = True


class ToggleIconButton(ToggleButton):
    def __init__(
        self, icon: FluentIcon | QtGui.QIcon, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__("", parent)
        self.setIcon(fluent_icon(icon) if isinstance(icon, FluentIcon) else icon)
        self.setFixedSize(32, 32)
