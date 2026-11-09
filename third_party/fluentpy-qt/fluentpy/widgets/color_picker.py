"""Transactional color popups composed from FluentPy's native Qt controls."""

from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from .action_menu import ActionMenu
from .button import AccentButton, Button
from .color_panel import ColorPalette, ColorPickerPanel, _color, _hex, _paint_color
from .dialog import MaskedDialog
from .scroll_bar import FluentScrollBar


class ColorDialog(MaskedDialog):
    """An in-window modal editor; only accepting commits the draft color."""

    colorSelected = Signal(QtGui.QColor)
    currentColorChanged = Signal(QtGui.QColor)

    def __init__(self, color="#0078d4", title="选择颜色", parent=None, *, enable_alpha=False):
        owner = parent.window() if parent is not None else QtWidgets.QApplication.activeWindow()
        if owner is None:
            raise ValueError("ColorDialog requires an owner window")
        self._committed = _color(color, enable_alpha)
        self._enable_alpha = bool(enable_alpha)
        super().__init__(title, "", owner)
        self._panel.setMinimumWidth(350)
        self._panel.setMaximumWidth(420)
        self.layout().setContentsMargins(14, 14, 14, 14)
        self._scroll = QtWidgets.QScrollArea(self._panel)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBar(
            FluentScrollBar(QtCore.Qt.Orientation.Vertical, self._scroll)
        )
        self.editor = ColorPickerPanel(self._committed, enable_alpha=enable_alpha)
        self._scroll.setWidget(self.editor)
        self.editor.setAutoFillBackground(False)
        self._scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }"
        )
        self.add_content_widget(self._scroll)
        self.editor.colorChanged.connect(self.currentColorChanged)
        self.editor.validationChanged.connect(self.yes_button.setEnabled)
        self.accepted.connect(self._emit_selected)
        self.finished.connect(self._restore_focus)
        self._previous_focus = None
        self._color_theme()
        theme.subscribe(self, self._color_theme)

    def color(self):
        return QtGui.QColor(self._committed)

    selectedColor = color

    def current_color(self):
        return self.editor.color()

    currentColor = current_color

    def set_color(self, color):
        self._committed = _color(color, self._enable_alpha)
        self.editor.set_previous_color(self._committed)
        self.editor.set_color(self._committed)

    setColor = set_color

    def open(self):
        if self.isVisible():
            return
        self._previous_focus = QtWidgets.QApplication.focusWidget()
        self.editor.set_previous_color(self._committed)
        self.editor.set_color(self._committed)
        self._fit_editor()
        QtWidgets.QApplication.instance().installEventFilter(self)
        super().open()
        self.editor.hex_input.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

    def accept(self):
        if self._finished or not self.editor.validate():
            return
        self._committed = self.editor.color()
        super().accept()

    def _emit_selected(self):
        self.colorSelected.emit(self.color())

    def _restore_focus(self):
        try:
            if self._previous_focus is not None and self._previous_focus.isVisible():
                self._previous_focus.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        except RuntimeError:
            pass
        self._previous_focus = None

    def _fit_editor(self):
        available = self.parentWidget().height() - 180
        self._scroll.setFixedHeight(max(80, min(self.editor.sizeHint().height() + 4, available)))
        self._panel.setMinimumWidth(min(350, max(200, self.parentWidget().width() - 28)))

    def eventFilter(self, watched, event):
        if self.isVisible():
            kind = event.type()
            if watched is self.parentWidget():
                if kind == QtCore.QEvent.Type.Resize:
                    self._fit_editor()
                elif kind in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.Close):
                    self.reject()
            if (
                kind == QtCore.QEvent.Type.KeyPress
                and isinstance(watched, QtWidgets.QWidget)
                and (watched is self or self.isAncestorOf(watched))
            ):
                if event.key() == QtCore.Qt.Key.Key_Escape:
                    self.reject()
                    return True
                if event.key() in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
                    focusable = [
                        w
                        for w in self._panel.findChildren(QtWidgets.QWidget)
                        if w.isVisible()
                        and w.isEnabled()
                        and w.focusPolicy() & QtCore.Qt.FocusPolicy.TabFocus
                    ]
                    if focusable:
                        current = QtWidgets.QApplication.focusWidget()
                        step = (
                            -1
                            if event.key() == QtCore.Qt.Key.Key_Backtab
                            or event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
                            else 1
                        )
                        index = focusable.index(current) if current in focusable else -1
                        focusable[(index + step) % len(focusable)].setFocus(
                            QtCore.Qt.FocusReason.TabFocusReason
                        )
                    return True
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        QtWidgets.QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def _color_theme(self):
        self._shadow.setBlurRadius(22)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(
            QtGui.QColor(0, 0, 0, 38 if theme.tokens.mode.value == "light" else 65)
        )
        self._title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {theme.tokens.text}; background: transparent;"
        )


class ColorPickerButton(Button):
    """Compact chip button hosting a ColorPickerPanel in the existing ActionMenu."""

    colorChanged = Signal(QtGui.QColor)
    colorPreviewed = Signal(QtGui.QColor)

    def __init__(self, color="#0078d4", parent=None, *, enable_alpha=True):
        super().__init__("", parent)
        self._enable_alpha = bool(enable_alpha)
        self._color = _color(color, enable_alpha)
        self.setFixedSize(68, 34)
        self.setAccessibleName("选择颜色")
        self._popup = None
        self.editor = None
        self.confirm_button = None
        self.cancel_button = None
        self.clicked.connect(self.show_popup)
        self._describe()

    def color(self):
        return QtGui.QColor(self._color)

    def set_color(self, color):
        value = _color(color, self._enable_alpha)
        if value == self._color:
            return
        self._color = value
        self._describe()
        self.update()
        self.colorChanged.emit(self.color())

    setColor = set_color

    def _describe(self):
        self.setToolTip(_hex(self._color, self._enable_alpha) if self._color.isValid() else "自动")

    def _create_popup(self):
        self._popup = ActionMenu(self)
        self.destroyed.connect(self._popup.deleteLater)
        content = QtWidgets.QWidget()
        content.setMinimumWidth(300)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(12)
        self.editor = ColorPickerPanel(self._color, enable_alpha=self._enable_alpha)
        layout.addWidget(self.editor)
        row = QtWidgets.QHBoxLayout()
        self.confirm_button = AccentButton("确定")
        self.cancel_button = Button("取消")
        row.addWidget(self.confirm_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.editor.colorChanged.connect(self.colorPreviewed)
        self.editor.validationChanged.connect(self.confirm_button.setEnabled)
        self.confirm_button.clicked.connect(self._confirm)
        self.cancel_button.clicked.connect(self._popup.dismiss)
        self._popup.set_content_widget(content)

    def show_popup(self):
        if not self.isEnabled() or not self.isVisible():
            return
        if self._popup is None:
            self._create_popup()
        if self._popup.isVisible():
            self._popup.dismiss()
            return
        if self.editor is not None:
            self.editor.set_previous_color(self._color)
            self.editor.set_color(self._color)
        self._popup.popup(self)
        if self.editor is not None:
            self.editor.hex_input.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

    showPopup = show_popup

    def _confirm(self):
        if self.editor.validate():
            self.set_color(self.editor.color())
            self._popup.dismiss()

    def _draw_content(self, painter, rect, color):
        chip = QtCore.QRectF(rect.left() + 6, rect.center().y() - 11, 22, 22)
        value = self._color if self._color.isValid() else QtGui.QColor(theme.tokens.text)
        _paint_color(painter, chip, value, 4)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 0.7))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(chip, 4, 4)
        icon = fluent_icon(FluentIcon.CHEVRON_DOWN)
        self._draw_tinted_icon(
            painter,
            QtCore.QRect(round(rect.right() - 20), round(rect.center().y() - 7), 14, 14),
            color,
            icon,
        )

    def hideEvent(self, event):
        if self._popup is not None:
            self._popup.dismiss(immediate=True)
        super().hideEvent(event)


class ColorPaletteButton(ColorPickerButton):
    """Theme palette with automatic color and an optional full color dialog."""

    automaticSelected = Signal()

    def __init__(self, color="#0078d4", parent=None, *, enable_alpha=False):
        super().__init__(
            color if color is not None else "#0078d4", parent, enable_alpha=enable_alpha
        )
        self.palette = None
        self.dialog = None
        if color is None:
            self._color = QtGui.QColor()
            self._describe()

    def is_automatic(self):
        return not self._color.isValid()

    def set_color(self, color):
        if color is None:
            changed = self._color.isValid()
            self._color = QtGui.QColor()
            self._describe()
            self.update()
            if changed:
                self.colorChanged.emit(self.color())
        else:
            super().set_color(color)

    setColor = set_color

    def _create_popup(self):
        self._popup = ActionMenu(self)
        self.destroyed.connect(self._popup.deleteLater)
        self.palette = ColorPalette()
        self.palette.colorSelected.connect(self._choose)
        self.palette.automaticSelected.connect(self._automatic)
        self.palette.moreColorsRequested.connect(self._more_colors)
        self._popup.set_content_widget(self.palette)

    def show_popup(self):
        super().show_popup()
        if self.palette is not None:
            self.palette.set_color(None if self.is_automatic() else self._color)

    showPopup = show_popup

    def _choose(self, color):
        self.set_color(color)
        self._popup.dismiss()

    def _automatic(self):
        self.set_color(None)
        self._popup.dismiss()
        self.automaticSelected.emit()

    def _more_colors(self):
        self._popup.dismiss(immediate=True)
        if self.dialog is None:
            self.dialog = ColorDialog(parent=self.window(), enable_alpha=self._enable_alpha)
            self.destroyed.connect(self.dialog.deleteLater)
            self.dialog.colorSelected.connect(self.set_color)
        self.dialog.set_color(
            self._color if self._color.isValid() else QtGui.QColor(theme.tokens.text)
        )
        self.dialog.open()
