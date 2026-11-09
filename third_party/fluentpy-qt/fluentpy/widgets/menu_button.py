"""Buttons that open an ActionMenu anchored to their owner window."""

from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtWidgets
from .action_menu import ActionMenu
from .button import AccentButton, Button


class _MenuButtonMixin:
    """Share menu lifetime and chevron animation across menu triggers."""

    _menu_only = False

    def __init__(
        self,
        text: str = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        menu: ActionMenu | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._menu = None
        self._menu_anchor = None
        self._arrow_progress = 0.0
        self._arrow_animation = self._make_state_animation("_arrow_progress")
        self._chevron = fluent_icon(FluentIcon.CHEVRON_DOWN)
        self.clicked.connect(self.show_menu)
        self.set_menu(menu)

    def set_menu(self, menu: ActionMenu | None) -> None:
        """Reconnect menu signals and close a popup owned by this trigger."""
        if menu is not None and not isinstance(menu, ActionMenu):
            raise TypeError("menu must be an ActionMenu or None")
        if self._menu is menu:
            return
        if self._menu is not None:
            if self._menu.anchor_widget() is (self._menu_anchor or self):
                self._menu.dismiss(immediate=True)
            self._menu.aboutToShow.disconnect(self._menu_opening)
            self._menu.aboutToHide.disconnect(self._menu_closing)
            self._menu.destroyed.disconnect(self._menu_destroyed)
        self._menu = menu
        if menu is not None:
            menu.aboutToShow.connect(self._menu_opening)
            menu.aboutToHide.connect(self._menu_closing)
            menu.destroyed.connect(self._menu_destroyed)
        self._menu_closing()

    def setMenu(self, menu: ActionMenu | None) -> None:
        self.set_menu(menu)

    def menu(self) -> ActionMenu | None:
        return self._menu

    def show_menu(self) -> None:
        """Toggle the attached menu at this button's anchor."""
        if self.isEnabled() and self._menu is not None:
            anchor = self._menu_anchor or self
            if self._menu.isVisible() and self._menu.anchor_widget() is anchor:
                self._menu.dismiss()
            else:
                self._menu.popup(anchor)

    def showMenu(self) -> None:
        self.show_menu()

    def _menu_opening(self):
        end = float(
            self._menu is not None and self._menu.anchor_widget() is (self._menu_anchor or self)
        )
        self._animate_state(self._arrow_animation, self._arrow_progress, end, 160)

    def _menu_closing(self):
        self._animate_state(self._arrow_animation, self._arrow_progress, 0.0, 160)

    def _menu_destroyed(self):
        self._menu = None
        self._arrow_animation.stop()
        self._arrow_progress = 0.0
        self.update()

    def sizeHint(self):
        if self._menu_only:
            return QtCore.QSize(32, 32)
        size = super().sizeHint()
        size.setWidth(size.width() + 24)
        return size

    def _draw_content(self, painter, rect, color):
        if not self._menu_only:
            super()._draw_content(painter, rect.adjusted(0, 0, -24, 0), color)
        center = (
            QtCore.QPointF(self.rect().center())
            if self._menu_only
            else QtCore.QPointF(rect.right() - 15, rect.center().y())
        )
        painter.save()
        painter.translate(center)
        painter.rotate(180 * self._arrow_progress)
        self._draw_tinted_icon(painter, QtCore.QRect(-6, -6, 12, 12), color, self._chevron)
        painter.restore()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Down:
            self.show_menu()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        if self._menu is not None and self._menu.anchor_widget() is (self._menu_anchor or self):
            self._menu.dismiss(immediate=True)
        self._arrow_animation.stop()
        self._arrow_progress = 0.0
        super().hideEvent(event)


class DropDownButton(_MenuButtonMixin, Button):
    """Standard button that opens its attached ActionMenu."""


class AccentDropDownButton(_MenuButtonMixin, AccentButton):
    """Accent button that opens its attached ActionMenu."""
