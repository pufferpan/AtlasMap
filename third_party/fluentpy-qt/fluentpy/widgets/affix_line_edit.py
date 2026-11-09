"""Prefix and suffix adornments around the existing native LineEdit."""

from ..qt import QtCore, QtWidgets, Signal
from ..theme import theme
from .line_edit import LineEdit


class AffixLineEdit(LineEdit):
    """Only the editable middle is returned by text(); full_text() includes affixes."""

    prefixChanged = Signal(str)
    suffixChanged = Signal(str)

    def __init__(
        self, placeholder="", parent=None, *, prefix="", suffix="", show_clear_button=True
    ):
        if not isinstance(prefix, str) or not isinstance(suffix, str):
            raise TypeError("prefix and suffix must be strings")
        super().__init__(placeholder, parent, show_clear_button=show_clear_button)
        self._prefix, self._suffix = prefix, suffix
        self._prefix_label = QtWidgets.QLabel(self)
        self._suffix_label = QtWidgets.QLabel(self)
        for label in (self._prefix_label, self._suffix_label):
            label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._refresh_affixes()
        theme.subscribe(self, self._refresh_affixes)

    def prefix(self):
        return self._prefix

    def suffix(self):
        return self._suffix

    def full_text(self):
        return self._prefix + self.text() + self._suffix

    def set_prefix(self, text):
        if not isinstance(text, str):
            raise TypeError("prefix must be a string")
        if text != self._prefix:
            self._prefix = text
            self._refresh_affixes()
            self.prefixChanged.emit(text)

    def set_suffix(self, text):
        if not isinstance(text, str):
            raise TypeError("suffix must be a string")
        if text != self._suffix:
            self._suffix = text
            self._refresh_affixes()
            self.suffixChanged.emit(text)

    setPrefix = set_prefix
    setSuffix = set_suffix
    fullText = full_text

    def set_clear_button_enabled(self, enabled):
        super().set_clear_button_enabled(enabled)
        if hasattr(self, "_prefix_label"):
            self._layout_affixes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_prefix_label"):
            self._layout_affixes()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "_prefix_label") and event.type() in (
            QtCore.QEvent.Type.EnabledChange,
            QtCore.QEvent.Type.FontChange,
            QtCore.QEvent.Type.LayoutDirectionChange,
        ):
            self._refresh_affixes()

    def _refresh_affixes(self):
        for label, text in ((self._prefix_label, self._prefix), (self._suffix_label, self._suffix)):
            label.setFont(self.font())
            label.setToolTip(text)
            label.setStyleSheet(
                f"QLabel {{background:{theme.tokens.surface_low}; color:{theme.tokens.text if self.isEnabled() else theme.tokens.disabled}; border:1px solid {theme.tokens.border}; border-radius:3px;}}"
            )
        self.setAccessibleDescription(
            f"前缀：{self._prefix or '无'}；后缀：{self._suffix or '无'}。"
        )
        self._layout_affixes()

    def _layout_affixes(self):
        # Reserve some editable area even with long decorations in a narrow field.
        clear = 28 if self._show_clear_button else 0
        budget = max(0, self.width() - 60 - clear)
        widths = [
            label.fontMetrics().horizontalAdvance(text) + 18 if text else 0
            for label, text in (
                (self._prefix_label, self._prefix),
                (self._suffix_label, self._suffix),
            )
        ]
        total = sum(widths)
        if total > budget and total:
            widths = [round(width * budget / total) for width in widths]
        for index, (label, text) in enumerate(
            ((self._prefix_label, self._prefix), (self._suffix_label, self._suffix))
        ):
            width = widths[index]
            label.setVisible(bool(text) and width > 8)
            label.setText(
                label.fontMetrics().elidedText(
                    text, QtCore.Qt.TextElideMode.ElideRight, max(0, width - 12)
                )
            )
            label.setGeometry(
                4 if index == 0 else self.width() - 4 - width, 4, width, max(0, self.height() - 8)
            )
        self._leading_inset = widths[0] + 10 if self._prefix else 10
        self._trailing_inset = (widths[1] + 10 if self._suffix else 10) + clear
        self._apply_text_margins()
        self._position_clear_button()
