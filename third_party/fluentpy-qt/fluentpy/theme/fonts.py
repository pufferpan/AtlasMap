"""Shared UI typography; keep CJK fallback explicit for Qt-painted text."""

from ..qt import QtGui

UI_FONT_FAMILIES = (
    "Segoe UI Variable Text",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Noto Sans CJK SC",
    "Noto Sans",
)


def ui_font(pixel_size: int, base: QtGui.QFont | None = None) -> QtGui.QFont:
    font = QtGui.QFont(base) if base is not None else QtGui.QFont()
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setStyleHint(QtGui.QFont.StyleHint.SansSerif)
    font.setPixelSize(pixel_size)
    return font
