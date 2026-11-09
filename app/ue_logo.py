"""Unreal Engine's installed Slate logo, bundled for source and frozen builds."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def ue_icon() -> QIcon:
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__)))
    # Loading SVG through QIcon depends on a dynamically discovered icon
    # plugin. Render explicitly so source and frozen builds use the same path.
    renderer = QSvgRenderer(os.path.join(root, "assets", "unreal-engine.svg"))
    if not renderer.isValid():
        return QIcon()
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)
