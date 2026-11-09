"""Native FluentPy controls and application setup functions; no visual fallbacks."""
from PySide6.QtWidgets import QApplication
from app.fluentpy_adapter import *
from app.fluent_controls import (LineEdit,TextEdit,CodeEditor,EditableComboBox,
    SpinBox,DoubleSpinBox,WarningNotice,Dialog,ChoiceDialog,message,confirm,
    text_menu,add_context_action,set_warning,set_details,scroll_area)

def apply_dark_palette(app=None, dark: bool = True) -> None:
    """Dark QPalette for the stock Qt widgets that FluentPy does not restyle
    (QTreeWidget / QListWidget / QTableWidget / QScrollArea / plain QWidget)."""
    app = app or QApplication.instance()
    if app is None:
        return
    try:
        app.setStyle("Fusion")
    except Exception:                                       # noqa: BLE001
        pass
    from PySide6.QtGui import QColor as _QColor, QPalette as _QPalette

    if dark:
        window = _QColor(32, 32, 32)
        base = _QColor(38, 38, 38)
        text = _QColor(236, 236, 236)
        button = _QColor(45, 45, 45)
        disabled = _QColor(120, 120, 120)
    else:
        window = _QColor(243, 246, 250)
        base = _QColor(255, 255, 255)
        text = _QColor(26, 26, 26)
        button = _QColor(250, 250, 250)
        disabled = _QColor(150, 150, 150)

    palette = _QPalette()
    palette.setColor(_QPalette.Window, window)
    palette.setColor(_QPalette.WindowText, text)
    palette.setColor(_QPalette.Base, base)
    palette.setColor(_QPalette.AlternateBase, _QColor(45, 45, 45) if dark else _QColor(245, 247, 250))
    palette.setColor(_QPalette.ToolTipBase, base)
    palette.setColor(_QPalette.ToolTipText, text)
    palette.setColor(_QPalette.Text, text)
    palette.setColor(_QPalette.Button, button)
    palette.setColor(_QPalette.ButtonText, text)
    palette.setColor(_QPalette.BrightText, _QColor(255, 90, 90))
    palette.setColor(_QPalette.Link, _QColor(0, 103, 192))
    palette.setColor(_QPalette.Highlight, _QColor(0, 103, 192))
    palette.setColor(_QPalette.HighlightedText, _QColor(255, 255, 255))
    palette.setColor(_QPalette.Disabled, _QPalette.Text, disabled)
    palette.setColor(_QPalette.Disabled, _QPalette.ButtonText, disabled)
    palette.setColor(_QPalette.Disabled, _QPalette.WindowText, disabled)
    palette.setColor(_QPalette.PlaceholderText, _QColor(150, 150, 150))
    app.setPalette(palette)
