"""Editable shortcut keycaps with an in-window recording dialog."""

from __future__ import annotations

from ..backends import shortcut as policy
from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .button import Button, IconButton, TextButton
from .dialog import MaskedDialog


def _parse(value):
    policy.backend_name()
    if value is None:
        value = ""
    if isinstance(value, str):
        sequence = QtGui.QKeySequence.fromString(
            value, QtGui.QKeySequence.SequenceFormat.PortableText
        )
    elif isinstance(value, QtGui.QKeySequence):
        sequence = QtGui.QKeySequence(value)
    else:
        raise TypeError("shortcut must be PortableText or QKeySequence")
    if sequence.isEmpty():
        if isinstance(value, str) and value.strip():
            raise ValueError("invalid shortcut text")
        return (0, 0)
    if sequence.count() != 1:
        raise ValueError("only one key chord is supported, not multiple strokes")
    combination = sequence[0]
    return policy.normalize(int(combination.key()), combination.keyboardModifiers().value)


def _sequence(chord):
    return QtGui.QKeySequence(chord[0] | chord[1]) if chord[0] else QtGui.QKeySequence()


def _reserved(values):
    if isinstance(values, (str, QtGui.QKeySequence)):
        raise TypeError("reserved sequences must be an iterable of shortcuts")
    return tuple(_parse(value) for value in values)


class _KeyCaps(QtWidgets.QWidget):
    def __init__(self, parent=None, *, large=False):
        super().__init__(parent)
        self._chord = (0, 0)
        self._parts = ()
        self._large = large
        self._reveal = 1.0
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setDuration(130)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self.setMinimumSize(0, 100 if large else 32)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def set_chord(self, chord, *, modifiers_only=False):
        self._chord = chord
        parts = list(policy.modifier_labels(chord[1]))
        if chord[0] and not modifiers_only:
            name = QtGui.QKeySequence(chord[0]).toString(
                QtGui.QKeySequence.SequenceFormat.NativeText
            )
            parts.append(name or "?")
        if tuple(parts) == self._parts:
            return
        self._parts = tuple(parts)
        self.setAccessibleName(" + ".join(parts) if parts else "未设置快捷键")
        self._animation.stop()
        self._animation.setStartValue(0.45)
        self._animation.setEndValue(1.0)
        self._animation.start()
        self.updateGeometry()

    def _animate(self, value):
        self._reveal = float(value)
        self.update()

    def _widths(self):
        metrics = self.fontMetrics()
        return [
            max(
                44 if self._large else 28,
                metrics.horizontalAdvance(text) + (20 if self._large else 14),
            )
            for text in self._parts
        ]

    def sizeHint(self):
        widths = self._widths()
        return QtCore.QSize(
            sum(widths) + max(0, len(widths) - 1) * 6 + 8 if widths else 122,
            120 if self._large else 36,
        )

    def _apply_theme(self):
        self.setFont(ui_font(16 if self._large else 12, self.font()))
        self.updateGeometry()
        self.update()

    def mousePressEvent(self, event):
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._large and self.hasFocus():
            tint = QtGui.QColor(theme.tokens.accent)
            tint.setAlpha(8 if theme.mode.value == "light" else 14)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        if not self._parts:
            painter.setPen(QtGui.QColor(theme.tokens.text_muted))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "按下组合键" if self._large else "未设置快捷键",
            )
            return
        widths = self._widths()
        total = sum(widths) + (len(widths) - 1) * 6
        scale = min(1.0, max(0.0, (self.width() - 8) / max(1, total)))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale, scale)
        painter.setOpacity(self._reveal if self.isEnabled() else 0.45)
        height = 44 if self._large else 28
        x = -total / 2
        for width, text in zip(widths, self._parts):
            rect = QtCore.QRectF(x, -height / 2, width, height)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(theme.tokens.accent))
            painter.drawRoundedRect(rect, 5 if self._large else 4, 5 if self._large else 4)
            painter.setPen(QtGui.QColor("#101f22" if theme.mode.value == "dark" else "#ffffff"))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
            x += width + 6


class ShortcutDialog(MaskedDialog):
    """Record one chord, preview it, then save or discard the edit."""

    def __init__(self, sequence="", parent=None, *, reserved_sequences=(), title="激活快捷键"):
        initial, reserved = _parse(sequence), _reserved(reserved_sequences)
        parent = parent or QtWidgets.QApplication.activeWindow()
        if parent is None:
            raise ValueError("ShortcutDialog requires an owner window")
        self._resolved = True
        self._filter_installed = False
        self._initial = self._candidate = initial
        self._reserved = reserved
        self._previous_focus = None
        super().__init__(title, "按下组合键以更改此快捷键", parent)
        self._panel.setMinimumWidth(0)
        self._panel.setMaximumWidth(460)
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 4)
        self._title_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._content_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.recorder = _KeyCaps(self._panel, large=True)
        self.recorder.setMinimumHeight(126)
        self.add_content_widget(self.recorder)
        self.message_label = QtWidgets.QLabel(self._panel)
        self.message_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumHeight(20)
        self._content_layout.addWidget(self.message_label)
        self.clear_button = TextButton("清除快捷键", self._panel)
        self.clear_button.clicked.connect(self.clear)
        self._content_layout.addWidget(self.clear_button, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.setYesButtonText("保存")
        self.reset_button = Button("重置", self._panel)
        self.reset_button.clicked.connect(self.reset)
        row = self._panel.layout().itemAt(self._panel.layout().count() - 1).layout()
        row.insertWidget(1, self.reset_button)
        self._set_candidate(initial)

    def key_sequence(self):
        return _sequence(self._candidate)

    def reset(self):
        """恢复打开编辑器时的快捷键，不影响外部控件。"""
        self._set_candidate(self._initial)
        self.recorder.setFocus()

    def clear(self):
        """将待保存的快捷键清空。"""
        self._set_candidate((0, 0))
        self.recorder.setFocus()

    def _set_candidate(self, chord):
        self._candidate = chord
        self.recorder.set_chord(chord)
        conflict = policy.conflicts(*chord, self._reserved)
        self.yes_button.setEnabled(not conflict)
        self.message_label.setText(
            "此快捷键已被占用，请换一个组合。"
            if conflict
            else "Tab 切换按钮 · Esc 取消 · 点击键帽继续录制"
        )
        self.message_label.setStyleSheet(
            f"color: {'#c42b1c' if conflict and theme.mode.value == 'light' else '#ff99a4' if conflict else theme.tokens.text_muted}; background: transparent; font-size: 12px;"
        )

    def open(self):
        if self.isVisible() and not self._resolved:
            self.recorder.setFocus()
            return
        self._resolved = False
        self._previous_focus = QtWidgets.QApplication.focusWidget()
        self._set_candidate(self._initial)
        super().open()
        app = QtWidgets.QApplication.instance()
        app.installEventFilter(self)
        self._filter_installed = True
        self.recorder.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

    def accept(self):
        if not policy.conflicts(*self._candidate, self._reserved):
            super().accept()

    def done(self, result):
        self._remove_filter()
        super().done(result)

    def cancel_immediately(self):
        if not self._resolved:
            self._finished = True
            self._result = self.Rejected
            self._fade.stop()
            self._finish_done(self.Rejected)

    def _remove_filter(self):
        if self._filter_installed:
            QtWidgets.QApplication.instance().removeEventFilter(self)
            self._filter_installed = False

    def _finish_done(self, result):
        if self._resolved:
            return
        self._resolved = True
        self._remove_filter()
        super()._finish_done(result)
        try:
            if self._previous_focus is not None and self._previous_focus.isVisible():
                self._previous_focus.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            pass  # The trigger may have been destroyed while the editor was open.
        self._previous_focus = None

    def _fit_to_parent(self):
        super()._fit_to_parent()
        self.layout().setContentsMargins(16, 16, 16, 16)
        self._panel.setFixedWidth(max(0, min(460, self.width() - 32)))
        self._panel.setMaximumHeight(max(0, self.height() - 32))

    def _cycle_focus(self, backward):
        widgets = [
            self.recorder,
            self.clear_button,
            self.yes_button,
            self.reset_button,
            self.cancel_button,
        ]
        widgets = [widget for widget in widgets if widget.isEnabled()]
        current = QtWidgets.QApplication.focusWidget()
        index = widgets.index(current) if current in widgets else 0
        widgets[(index + (-1 if backward else 1)) % len(widgets)].setFocus(
            QtCore.Qt.FocusReason.TabFocusReason
        )

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.parentWidget() and kind in (
            QtCore.QEvent.Type.Hide,
            QtCore.QEvent.Type.Close,
        ):
            self.cancel_immediately()
        if (
            self.isVisible()
            and not self._finished
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self.window()
        ):
            if kind == QtCore.QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if kind == QtCore.QEvent.Type.KeyPress:
                key, modifiers = event.key(), event.modifiers().value
                if key == int(QtCore.Qt.Key.Key_Escape) and not modifiers:
                    self.reject()
                    return True
                if key in (
                    int(QtCore.Qt.Key.Key_Tab),
                    int(QtCore.Qt.Key.Key_Backtab),
                ) and modifiers in (0, int(QtCore.Qt.KeyboardModifier.ShiftModifier.value)):
                    self._cycle_focus(bool(modifiers) or key == int(QtCore.Qt.Key.Key_Backtab))
                    return True
                focus = (
                    self.recorder
                    if watched is self.recorder
                    else QtWidgets.QApplication.focusWidget()
                )
                if focus is self.recorder:
                    if event.isAutoRepeat():
                        return True
                    if key in (
                        int(QtCore.Qt.Key.Key_Control),
                        int(QtCore.Qt.Key.Key_Shift),
                        int(QtCore.Qt.Key.Key_Alt),
                        int(QtCore.Qt.Key.Key_Meta),
                    ):
                        self.recorder.set_chord((0, modifiers), modifiers_only=True)
                    else:
                        try:
                            self._set_candidate(policy.normalize(key, modifiers))
                        except ValueError:
                            self.message_label.setText("这个按键暂不支持，请换一个组合。")
                    event.accept()
                    return True
                if key in (
                    int(QtCore.Qt.Key.Key_Return),
                    int(QtCore.Qt.Key.Key_Enter),
                ) and isinstance(focus, QtWidgets.QAbstractButton):
                    focus.click()
                    return True
            elif kind == QtCore.QEvent.Type.KeyRelease and (
                watched is self.recorder or QtWidgets.QApplication.focusWidget() is self.recorder
            ):
                self.recorder.set_chord(self._candidate)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._remove_filter()
        if not self._resolved:
            self.cancel_immediately()
        super().hideEvent(event)

    def _apply_theme(self):
        super()._apply_theme()
        self._shadow.setColor(QtGui.QColor(0, 0, 0, 30 if theme.mode.value == "light" else 50))
        if hasattr(self, "message_label"):
            self._set_candidate(self._candidate)


class ShortcutPicker(QtWidgets.QFrame):
    """Compact keycaps and an edit button; selection does not register a hotkey."""

    keySequenceChanged = Signal(QtGui.QKeySequence)
    sequenceChanged = Signal(str)

    def acceleration_backend(self) -> str:
        return policy.backend_name()

    def __init__(self, sequence="", parent=None, *, title="激活快捷键"):
        chord = _parse(sequence)
        super().__init__(parent)
        self._chord, self._reserved, self._title = chord, (), str(title)
        self._editor = None
        self.setObjectName("shortcutPicker")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(4)
        self.key_caps = _KeyCaps(self)
        self.key_caps.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.key_caps.set_chord(chord)
        layout.addWidget(self.key_caps)
        self.edit_button = IconButton(fluent_icon(FluentIcon.EDIT), self)
        self.edit_button.setFixedSize(32, 32)
        self.edit_button.setAccessibleName("编辑快捷键")
        self.edit_button.clicked.connect(self.open_editor)
        layout.addWidget(self.edit_button)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def key_sequence(self):
        return _sequence(self._chord)

    def set_key_sequence(self, sequence):
        chord = _parse(sequence)
        if policy.conflicts(*chord, self._reserved):
            raise ValueError("shortcut conflicts with a reserved sequence")
        if self._editor is not None:
            self._editor.cancel_immediately()
        if chord != self._chord:
            self._chord = chord
            self.key_caps.set_chord(chord)
            self.keySequenceChanged.emit(self.key_sequence())
            self.sequenceChanged.emit(
                self.key_sequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
            )

    def keySequence(self):
        return self.key_sequence()

    def setKeySequence(self, sequence):
        self.set_key_sequence(sequence)

    def set_reserved_sequences(self, sequences):
        reserved = _reserved(sequences)
        if self._editor is not None:
            self._editor.cancel_immediately()
        self._reserved = reserved

    def reserved_sequences(self):
        return [_sequence(chord) for chord in self._reserved]

    def clear(self):
        self.set_key_sequence("")

    def open_editor(self):
        if not self.isEnabled():
            return
        if self._editor is not None:
            self._editor.open()
            return
        editor = ShortcutDialog(
            self.key_sequence(),
            self.window(),
            reserved_sequences=self.reserved_sequences(),
            title=self._title,
        )
        self._editor = editor
        editor.accepted.connect(self._editor_accepted)
        editor.finished.connect(self._editor_finished)
        editor.finished.connect(editor.deleteLater)
        self.destroyed.connect(editor.cancel_immediately)
        editor.open()

    def _editor_accepted(self):
        if self._editor is not None:
            chord = _parse(self._editor.key_sequence())
            if chord != self._chord:
                self._chord = chord
                self.key_caps.set_chord(chord)
                self.keySequenceChanged.emit(self.key_sequence())
                self.sequenceChanged.emit(
                    self.key_sequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
                )

    def _editor_finished(self, _result):
        self._editor = None

    def hideEvent(self, event):
        if self._editor is not None:
            self._editor.cancel_immediately()
        super().hideEvent(event)

    def changeEvent(self, event):
        if (
            event.type() == QtCore.QEvent.Type.EnabledChange
            and not self.isEnabled()
            and self._editor is not None
        ):
            self._editor.cancel_immediately()
        super().changeEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Space,
        ):
            self.open_editor()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setStyleSheet(
            f"QFrame#shortcutPicker {{ background: {theme.tokens.surface}; border: 1px solid {theme.tokens.border}; border-radius: 6px; }}"
        )
