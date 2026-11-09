"""Qt backend facade.

PySide6 is the primary backend. PyQt6 support can be added here without
changing the widget modules.
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Property, Signal, Slot

    QT_API = "PySide6"
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
        from PyQt6.QtCore import pyqtProperty as Property
        from PyQt6.QtCore import pyqtSignal as Signal
        from PyQt6.QtCore import pyqtSlot as Slot

        QT_API = "PyQt6"
    except ImportError as exc:  # pragma: no cover - depends on local Qt install.
        raise ImportError(
            "FluentPy requires PySide6 or PyQt6. Install one with "
            "`python -m pip install PySide6` or `python -m pip install PyQt6`."
        ) from exc

__all__ = [
    "Property",
    "QT_API",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "Signal",
    "Slot",
]
