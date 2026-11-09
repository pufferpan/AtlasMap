from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font


class CheckBox(QtWidgets.QAbstractButton):
    stateChanged = Signal(int)

    def __init__(
        self, text: str = "", parent: QtWidgets.QWidget | None = None, *, description: str = ""
    ) -> None:
        super().__init__(parent)
        self._description = str(description)
        self._keyboard_focus = False
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setText(text)
        self.setAccessibleDescription(self._description)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._update_minimum_height()
        self._tristate = False
        self._state = QtCore.Qt.CheckState.Unchecked
        self._hover = False
        self._pressed = False
        theme.subscribe(self, self.update)

    def description(self) -> str:
        return self._description

    def set_description(self, text: str) -> None:
        text = str(text)
        if text == self._description:
            return
        self._description = text
        self.setAccessibleDescription(text)
        self._update_minimum_height()
        self.updateGeometry()
        self.update()

    def setDescription(self, text: str) -> None:
        self.set_description(text)

    def _description_font(self) -> QtGui.QFont:
        font = QtGui.QFont(self.font())
        font.setPixelSize(max(10, QtGui.QFontInfo(font).pixelSize() - 2))
        return font

    def _content_height(self) -> int:
        if not self._description:
            return max(32, self.fontMetrics().height() + 8)
        return max(
            40,
            self.fontMetrics().height() + QtGui.QFontMetrics(self._description_font()).height() + 9,
        )

    def _update_minimum_height(self) -> None:
        self.setMinimumHeight(self._content_height())

    def setTristate(self, enabled: bool = True) -> None:
        self._tristate = enabled

    def isTristate(self) -> bool:
        return self._tristate

    def checkState(self) -> QtCore.Qt.CheckState:
        return self._state

    def setCheckState(self, state: QtCore.Qt.CheckState) -> None:
        if state == self._state:
            return
        self._state = state
        QtWidgets.QAbstractButton.setChecked(self, state == QtCore.Qt.CheckState.Checked)
        self.stateChanged.emit(int(state.value))
        self.update()

    def isChecked(self) -> bool:
        return self._state == QtCore.Qt.CheckState.Checked

    def setChecked(self, checked: bool) -> None:
        self.setCheckState(
            QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        )

    def nextCheckState(self) -> None:
        if self._tristate:
            order = (
                QtCore.Qt.CheckState.Unchecked,
                QtCore.Qt.CheckState.PartiallyChecked,
                QtCore.Qt.CheckState.Checked,
            )
            self.setCheckState(order[(order.index(self._state) + 1) % len(order)])
        else:
            self.setChecked(not self.isChecked())

    def sizeHint(self) -> QtCore.QSize:
        width = self.fontMetrics().horizontalAdvance(self.text())
        if self._description:
            width = max(
                width,
                QtGui.QFontMetrics(self._description_font()).horizontalAdvance(self._description),
            )
        return QtCore.QSize(max(24, width + 34), self._content_height())

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(54 if self.text() or self._description else 24, self._content_height())

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.FontChange and hasattr(self, "_description"):
            self._update_minimum_height()
            self.updateGeometry()

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        self._keyboard_focus = event.reason() in (
            QtCore.Qt.FocusReason.TabFocusReason,
            QtCore.Qt.FocusReason.BacktabFocusReason,
            QtCore.Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        self._keyboard_focus = False
        super().focusOutEvent(event)
        self.update()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._keyboard_focus = False
        self._pressed = event.button() == QtCore.Qt.MouseButton.LeftButton
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        painter.setFont(self.font())

        rtl = self.isRightToLeft()
        title_height = self.fontMetrics().height()
        if self._description:
            secondary_height = QtGui.QFontMetrics(self._description_font()).height()
            top = max(2.0, (self.height() - title_height - secondary_height - 1) / 2)
            box_y = max(2.0, top + title_height / 2 - 10)
            title_rect = QtCore.QRectF(
                2 if rtl else 32, top, max(0, self.width() - 34), title_height
            )
        else:
            box_y = self.height() / 2 - 10
            title_rect = QtCore.QRectF(
                2 if rtl else 32, 0, max(0, self.width() - 34), self.height()
            )
        box = QtCore.QRectF(self.width() - 22 if rtl else 2, box_y, 20, 20)
        painter.save()
        if not self.isEnabled():
            painter.setOpacity(0.45)
        selected = self._state != QtCore.Qt.CheckState.Unchecked
        if selected:
            fill = QtGui.QColor(tokens.accent)
            if self._hover:
                fill = fill.lighter(104)
            if self._pressed:
                fill = fill.darker(110)
            painter.setBrush(fill)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
        else:
            fill = QtGui.QColor("#ffffff" if tokens.mode.value == "light" else "#ffffff")
            fill.setAlpha(150 if tokens.mode.value == "light" else 14)
            border = QtGui.QColor("#7b7f87" if tokens.mode.value == "light" else "#aeb5c3")
            if self._hover:
                fill.setAlpha(185 if tokens.mode.value == "light" else 24)
            painter.setBrush(fill)
            painter.setPen(QtGui.QPen(border, 1))
        painter.drawRoundedRect(box, 4, 4)

        if self._state == QtCore.Qt.CheckState.Checked:
            pen = QtGui.QPen(
                QtGui.QColor("#ffffff"),
                1.7,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            painter.drawLine(
                QtCore.QLineF(box.left() + 5, box.center().y(), box.left() + 9, box.bottom() - 6)
            )
            painter.drawLine(
                QtCore.QLineF(box.left() + 9, box.bottom() - 6, box.right() - 5, box.top() + 6)
            )
        elif self._state == QtCore.Qt.CheckState.PartiallyChecked:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor("#ffffff"))
            painter.drawRoundedRect(
                QtCore.QRectF(box.left() + 5, box.center().y() - 1.5, 10, 3), 1.5, 1.5
            )

        painter.restore()

        text_color = QtGui.QColor(tokens.text if self.isEnabled() else tokens.disabled)
        painter.setPen(text_color)
        title_rect.translate(0, -3)
        alignment = QtCore.Qt.AlignmentFlag.AlignVCenter | (
            QtCore.Qt.AlignmentFlag.AlignRight if rtl else QtCore.Qt.AlignmentFlag.AlignLeft
        )
        title = self.fontMetrics().elidedText(
            self.text(), QtCore.Qt.TextElideMode.ElideRight, int(title_rect.width())
        )
        painter.drawText(title_rect, alignment, title)
        if self._description:
            font = self._description_font()
            painter.setFont(font)
            painter.setPen(QtGui.QColor(tokens.text_muted if self.isEnabled() else tokens.disabled))
            description = QtGui.QFontMetrics(font).elidedText(
                self._description, QtCore.Qt.TextElideMode.ElideRight, int(title_rect.width())
            )
            painter.drawText(
                QtCore.QRectF(
                    title_rect.left(), title_rect.bottom() + 1, title_rect.width(), secondary_height
                ),
                alignment,
                description,
            )
        if self.hasFocus() and self._keyboard_focus:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.accent), 1))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
