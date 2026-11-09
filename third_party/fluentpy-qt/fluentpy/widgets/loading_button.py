"""Busy-state feedback for application-managed tasks."""

from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets, Signal
from .button import AccentButton


class LoadingButton(AccentButton):
    """Show progress and block activation until an application task finishes.

    Call ``set_loading`` from the GUI thread when the task starts or finishes.
    The button preserves its externally configured enabled state.
    """

    loadingChanged = Signal(bool)

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        self._loading = False
        self._desired_enabled = True
        self._idle_text = str(text)
        self._spin = 0.0
        super().__init__(text, parent)
        self._spinner = QtCore.QVariantAnimation(self)
        self._spinner.setStartValue(0.0)
        self._spinner.setEndValue(1.0)
        self._spinner.setDuration(1100)
        self._spinner.setLoopCount(-1)
        self._spinner.valueChanged.connect(self._spin_changed)
        self._loading_ancestors = []
        self._watch_loading_ancestors()

    def _watch_loading_ancestors(self):
        for ancestor in self._loading_ancestors:
            try:
                ancestor.removeEventFilter(self)
            except RuntimeError:
                pass
        self._loading_ancestors = []
        ancestor = self.parentWidget()
        while ancestor is not None:
            ancestor.installEventFilter(self)
            self._loading_ancestors.append(ancestor)
            ancestor = ancestor.parentWidget()

    def _sync_spinner(self):
        if self._loading and self.isVisible() and self._visual_enabled():
            if self._spinner.state() != QtCore.QAbstractAnimation.State.Running:
                self._spinner.start()
        else:
            self._spinner.stop()

    def eventFilter(self, watched, event):
        # Qt does not send EnabledChange to an already disabled child. Busy
        # buttons are deliberately disabled, so observe their ancestors too.
        if event.type() in (
            QtCore.QEvent.Type.EnabledChange,
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Hide,
        ):
            self._sync_spinner()
        return super().eventFilter(watched, event)

    def event(self, event):
        result = super().event(event)
        if event.type() == QtCore.QEvent.Type.ParentChange and hasattr(self, "_loading_ancestors"):
            self._watch_loading_ancestors()
            self._sync_spinner()
        return result

    def is_loading(self) -> bool:
        return self._loading

    def set_loading(self, loading: bool, *, text: str = "处理中…") -> None:
        """Update busy feedback, restoring the idle text on completion."""
        loading = bool(loading)
        if loading == self._loading:
            if loading:
                QtWidgets.QPushButton.setText(self, text)
            return
        if loading:
            self._idle_text = self.text()
        self._loading = loading
        QtWidgets.QPushButton.setText(self, text if loading else self._idle_text)
        QtWidgets.QWidget.setEnabled(self, self._desired_enabled and not loading)
        if loading and self.isVisible() and self._visual_enabled():
            self._spinner.start()
        else:
            self._spinner.stop()
        self.updateGeometry()
        self.update()
        self.loadingChanged.emit(loading)

    def setEnabled(self, enabled: bool) -> None:
        self._desired_enabled = bool(enabled)
        super().setEnabled(self._desired_enabled and not self._loading)
        if hasattr(self, "_spinner") and self._loading:
            if self.isVisible() and self._visual_enabled():
                if self._spinner.state() != QtCore.QAbstractAnimation.State.Running:
                    self._spinner.start()
            else:
                self._spinner.stop()

    def setDisabled(self, disabled: bool) -> None:
        self.setEnabled(not disabled)

    def setText(self, text: str) -> None:
        if self._loading:
            self._idle_text = str(text)
        else:
            super().setText(text)

    def _visual_enabled(self):
        parent = self.parentWidget()
        return self.isEnabled() or (
            self._loading and self._desired_enabled and (parent is None or parent.isEnabled())
        )

    def _spin_changed(self, value):
        self._spin = float(value)
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        size = super().sizeHint()
        if self._loading:
            size.setWidth(size.width() + 22)
        return size

    def _draw_content(self, painter, rect, color):
        if not self._loading:
            super()._draw_content(painter, rect, color)
            return
        width = self.fontMetrics().horizontalAdvance(self.text())
        x = rect.center().x() - (width + 24) / 2
        painter.setPen(
            QtGui.QPen(color, 1.8, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawArc(
            QtCore.QRectF(x, rect.center().y() - 7, 14, 14),
            round((90 - self._spin * 360) * 16),
            -105 * 16,
        )
        painter.setPen(color)
        painter.drawText(
            QtCore.QRectF(x + 24, rect.top(), width, rect.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )

    def showEvent(self, event):
        super().showEvent(event)
        if self._loading and self._visual_enabled():
            self._spinner.start()

    def hideEvent(self, event):
        self._spinner.stop()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (
            event.type() == QtCore.QEvent.Type.EnabledChange
            and hasattr(self, "_spinner")
            and self._loading
        ):
            if self.isVisible() and self._visual_enabled():
                if self._spinner.state() != QtCore.QAbstractAnimation.State.Running:
                    self._spinner.start()
            else:
                self._spinner.stop()
