"""Segmented password input composed from the existing LineEdit controls."""

from __future__ import annotations

from ..backends import input as policy
from ..qt import QtCore, QtGui, QtWidgets, Signal
from .line_edit import LineEdit


class _CodeCell(LineEdit):
    def __init__(self, editor, index):
        super().__init__(parent=editor, show_clear_button=False)
        self.editor, self.index = editor, index
        self.setMaxLength(2)  # One Unicode scalar can occupy two UTF-16 units.
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(28)
        self.setMaximumWidth(42)
        self.setFixedHeight(36)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.textChanged.connect(self._changed)

    def _changed(self, text):
        if not self.editor._updating:
            self.editor._insert(self.index, text, advance=False)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def paste(self):
        text = QtWidgets.QApplication.clipboard().text()
        if text:
            self.editor._insert(self.index, text, whole=True)

    def insert(self, text):
        if text:
            self.editor._insert(self.index, text)

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.StandardKey.Paste):
            if not self.isReadOnly():
                self.paste()
            event.accept()
            return
        key = event.key()
        if key in (
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.Key.Key_Right,
            QtCore.Qt.Key.Key_Home,
            QtCore.Qt.Key.Key_End,
        ):
            index = (
                0
                if key == QtCore.Qt.Key.Key_Home
                else self.editor._first_empty()
                if key == QtCore.Qt.Key.Key_End
                else self.index + (-1 if key == QtCore.Qt.Key.Key_Left else 1)
            )
            self.editor._focus_cell(index)
            event.accept()
            return
        if not self.isReadOnly() and key in (QtCore.Qt.Key.Key_Backspace, QtCore.Qt.Key.Key_Delete):
            index = self.index
            if key == QtCore.Qt.Key.Key_Backspace and not self.editor._values[index] and index > 0:
                index -= 1
            self.editor._insert(index, "", advance=False)
            self.editor._focus_cell(index)
            event.accept()
            return
        text = event.text()
        if (
            not self.isReadOnly()
            and text
            and text.isprintable()
            and not event.modifiers()
            & (
                QtCore.Qt.KeyboardModifier.ControlModifier
                | QtCore.Qt.KeyboardModifier.AltModifier
                | QtCore.Qt.KeyboardModifier.MetaModifier
            )
        ):
            self.editor._insert(self.index, text)
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        if event.commitString() and not self.isReadOnly():
            super().inputMethodEvent(QtGui.QInputMethodEvent())
            self.editor._insert(self.index, event.commitString())
            event.accept()
        else:
            super().inputMethodEvent(event)


class PinCodeEdit(QtWidgets.QWidget):
    """One native LineEdit per character; masked by default, with whole-code paste."""

    textChanged = Signal(str)
    completed = Signal(str)
    inputRejected = Signal(str)

    def __init__(self, length=4, parent=None, *, masked=True, digits_only=True):
        super().__init__(parent)
        initial = policy.split_code("", length, digits_only)
        if not isinstance(masked, bool):
            raise TypeError("masked must be a bool")
        self._length, self._masked, self._digits_only = len(initial), masked, digits_only
        self._read_only = False
        self._updating = False
        self._values = [""] * self._length
        self._cells = []
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAccessibleName("分格密码输入")
        self._build_cells()

    def _build_cells(self):
        for cell in self._cells:
            self._layout.removeWidget(cell)
            cell.hide()
            cell.deleteLater()
        self._cells = [_CodeCell(self, index) for index in range(self._length)]
        for index, cell in enumerate(self._cells):
            self._layout.addWidget(cell, 1)
            cell.show()
            cell.setAccessibleName(f"第{index + 1}位，共{self._length}位")
            cell.setReadOnly(self._read_only)
        self.setMaximumWidth(self._length * 42 + (self._length - 1) * 10)
        self.setFocusProxy(self._cells[0])
        self.set_masked(self._masked)
        self._sync()
        self.setAccessibleDescription(f"共{self._length}位，支持整段粘贴、方向键移动和退格回删。")
        self.updateGeometry()

    def text(self):
        return "".join(self._values)

    def length(self):
        return self._length

    def is_complete(self):
        return all(self._values)

    def cells(self):
        return tuple(self._cells)

    def is_masked(self):
        return self._masked

    def digits_only(self):
        return self._digits_only

    def is_read_only(self):
        return self._read_only

    def acceleration_backend(self):
        return policy.backend_name()

    def set_text(self, text):
        values = list(policy.split_code(text, self._length, self._digits_only))
        self._assign(values)

    setText = set_text

    def clear(self):
        self._assign([""] * self._length)

    def set_length(self, length):
        values = list(policy.split_code(self.text(), length, self._digits_only, truncate=True))
        if len(values) != self._length:
            previous = self.text()
            self._length = len(values)
            self._values = values
            self._build_cells()
            if self.text() != previous:
                self.textChanged.emit(self.text())

    setLength = set_length

    def set_masked(self, masked):
        if not isinstance(masked, bool):
            raise TypeError("masked must be a bool")
        self._masked = masked
        for cell in self._cells:
            cell.setEchoMode(
                QtWidgets.QLineEdit.EchoMode.Password
                if masked
                else QtWidgets.QLineEdit.EchoMode.Normal
            )
            hints = (
                QtCore.Qt.InputMethodHint.ImhNoPredictiveText
                | QtCore.Qt.InputMethodHint.ImhSensitiveData
            )
            if masked:
                hints |= QtCore.Qt.InputMethodHint.ImhHiddenText
            if self._digits_only:
                hints |= QtCore.Qt.InputMethodHint.ImhDigitsOnly
            cell.setInputMethodHints(hints)

    setMasked = set_masked

    def set_digits_only(self, enabled):
        policy.split_code(self.text(), self._length, enabled)
        self._digits_only = enabled
        self.set_masked(self._masked)

    def set_read_only(self, read_only):
        self._read_only = bool(read_only)
        for cell in self._cells:
            cell.setReadOnly(self._read_only)

    setReadOnly = set_read_only
    isReadOnly = is_read_only

    def paste(self):
        focused = QtWidgets.QApplication.focusWidget()
        index = self._cells.index(focused) if focused in self._cells else 0
        text = QtWidgets.QApplication.clipboard().text()
        if text:
            self._insert(index, text, whole=True)

    def _insert(self, index, text, *, advance=True, whole=False):
        if self._read_only:
            self._sync()
            return
        start = 0 if whole and len(text) >= self._length else index
        try:
            parsed = policy.split_code(text, self._length - start, self._digits_only, truncate=True)
        except (ValueError, TypeError):
            self._sync()
            self.inputRejected.emit(
                "请输入数字0～9。" if self._digits_only else "请输入可显示的字符。"
            )
            return
        values = list(self._values)
        if text:
            for offset, char in enumerate(parsed):
                if not char:
                    break
                values[start + offset] = char
        else:
            values[start] = ""
        self._assign(values)
        if advance:
            self._focus_cell(min(self._length - 1, start + min(len(text), len(parsed))))

    def _assign(self, values):
        changed = values != self._values
        previous = self.text()
        self._values = values
        self._sync()
        if self.text() != previous:
            self.textChanged.emit(self.text())
        if changed and self.is_complete():
            self.completed.emit(self.text())

    def _sync(self):
        self._updating = True
        try:
            for cell, value in zip(self._cells, self._values):
                with QtCore.QSignalBlocker(cell):
                    cell.setText(value)
        finally:
            self._updating = False

    def _first_empty(self):
        return next(
            (index for index, value in enumerate(self._values) if not value), self._length - 1
        )

    def _focus_cell(self, index):
        cell = self._cells[max(0, min(self._length - 1, index))]
        cell.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        cell.selectAll()
