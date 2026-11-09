from __future__ import annotations

from ..qt import QtWidgets
from ..theme import theme
from ._style import progress_stylesheet


class ProgressBar(QtWidgets.QProgressBar):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def _apply_theme(self) -> None:
        self.setStyleSheet(progress_stylesheet(theme.tokens))
