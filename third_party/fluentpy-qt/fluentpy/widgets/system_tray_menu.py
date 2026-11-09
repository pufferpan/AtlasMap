"""Themed native menus for QSystemTrayIcon."""

from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


class SystemTrayMenu(QtWidgets.QMenu):
    """Native QMenu for system tray icons and OS-managed popup menus.

    Qt handles positioning and dismissal; theme changes update the item colors.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size))
        self.aboutToShow.connect(self._apply_theme)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def add_action(
        self,
        text,
        *,
        icon=None,
        callback=None,
        checkable=False,
        checked=False,
        enabled=True,
        shortcut="",
    ):
        action = QtGui.QAction(str(text), self)
        if icon is not None:
            value = fluent_icon(icon) if isinstance(icon, FluentIcon) else QtGui.QIcon(icon)
            action.setProperty("_fluentTrayIcon", value)
            action.setIcon(value)
        action.setCheckable(checkable)
        action.setChecked(checked)
        action.setEnabled(enabled)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        if callback is not None:
            action.triggered.connect(callback)
        self.addAction(action)
        return action

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size))
        self.setStyleSheet(f"""QMenu {{background:{theme.tokens.surface};color:{theme.tokens.text};border:1px solid {theme.tokens.border};border-radius:7px;padding:5px;}}
QMenu::item {{padding:7px 30px 7px 28px;border-radius:4px;}}
QMenu::item:selected {{background:{theme.tokens.accent};color:white;}}
QMenu::item:disabled {{color:{theme.tokens.disabled};}}
QMenu::separator {{height:1px;background:{theme.tokens.border};margin:4px 7px;}}""")
        for action in self.actions():
            source = action.property("_fluentTrayIcon")
            if isinstance(source, QtGui.QIcon):
                pixmap = source.pixmap(20, 20)
                painter = QtGui.QPainter(pixmap)
                painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QtGui.QColor(theme.tokens.text))
                painter.end()
                action.setIcon(QtGui.QIcon(pixmap))
