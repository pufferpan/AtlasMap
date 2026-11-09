"""Model-backed combo boxes and popup selection views."""

from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .action_menu import ActionMenu
from .button import Button
from .line_edit import (
    LineEdit,
    SearchLineEdit,
    _input_border_color,
    _input_lower_color,
    _input_surface_color,
)
from .scroll_bar import FluentScrollBar

USER_ROLE = QtCore.Qt.ItemDataRole.UserRole
DISPLAY_ROLE = QtCore.Qt.ItemDataRole.DisplayRole


class ComboBox(QtWidgets.QWidget):
    """Single choice with a live Qt model, item data and an optional placeholder."""

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)
    activated = Signal(int)
    textActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QtGui.QStandardItemModel(self)
        self._model.setColumnCount(1)
        self._current = QtCore.QPersistentModelIndex()
        self._last_state = (-1, "")
        self._placeholder = ""
        self._max_visible = 8
        self._popup = None
        self._hover = self._pressed = False
        self._multiple = self._tree = self._searchable = self._transparent = False
        self._text_color = None
        self._focus_progress = 0.0
        self._focus_motion = QtCore.QVariantAnimation(self)
        self._focus_motion.setDuration(150)
        self._focus_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._focus_motion.valueChanged.connect(self._focus_value)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setMinimumSize(180, 34)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self._connect_model()
        theme.subscribe(self, self._apply_theme)

    def sizeHint(self):
        return QtCore.QSize(220, 36)

    def minimumSizeHint(self):
        return QtCore.QSize(180, 34)

    def model(self):
        """The live QAbstractItemModel; external models remain caller owned."""
        return self._model

    def setModel(self, model):
        """Bind a Qt model without copying its rows or taking ownership."""
        if not isinstance(model, QtCore.QAbstractItemModel):
            raise TypeError("model must be a QAbstractItemModel")
        if model is self._model:
            return
        self.hide_popup()
        self._disconnect_model()
        self._model = model
        self._current = QtCore.QPersistentModelIndex()
        self._connect_model()
        self._reset_extra_selection()
        self._select(self._first_enabled())
        self._model_replaced()

    def _model_replaced(self):
        pass

    def _connect_model(self):
        for signal in (
            self._model.rowsInserted,
            self._model.rowsRemoved,
            self._model.rowsMoved,
            self._model.modelReset,
            self._model.dataChanged,
            self._model.layoutChanged,
        ):
            signal.connect(self._model_changed)
        self._model.destroyed.connect(self._model_destroyed)

    def _disconnect_model(self):
        for signal in (
            self._model.rowsInserted,
            self._model.rowsRemoved,
            self._model.rowsMoved,
            self._model.modelReset,
            self._model.dataChanged,
            self._model.layoutChanged,
        ):
            signal.disconnect(self._model_changed)
        self._model.destroyed.disconnect(self._model_destroyed)

    def _model_destroyed(self):
        self.hide_popup()
        self._model = QtGui.QStandardItemModel(self)
        self._model.setColumnCount(1)
        self._current = QtCore.QPersistentModelIndex()
        self._connect_model()
        self._reset_extra_selection()
        self._model_replaced()
        self._sync_editor()
        self._publish()

    def _model_changed(self, *args):
        if not self._current.isValid() and self._last_state[0] >= 0:
            self._current = QtCore.QPersistentModelIndex(self._first_enabled())
        self._sync_editor(model_update=True)
        self._prune_selection()
        self._publish()
        if self._popup is not None and self._popup._opened:
            self._popup.schedule_refresh()

    def count(self):
        return self._model.rowCount()

    def addItem(self, text, userData=None, *, icon=None):
        """Append text, optional application data and a QIcon."""
        self.insertItem(self.count(), text, userData, icon=icon)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def add_item(self, text, userData=None):
        self.addItem(text, userData)

    def insertItem(self, index, text, userData=None, *, icon=None):
        was_empty = not self.count()
        row = max(0, min(int(index), self.count()))
        # Mutation deliberately uses the public model API, including custom models.
        if not self._model.insertRow(row):
            raise ValueError("model does not support inserting rows")
        item = self._model.index(row, 0)
        # QAbstractListModel exposes one column but keeps columnCount private
        # in some Python bindings. Ask for the inserted index instead.
        if not item.isValid():
            self._model.insertColumn(0)
            item = self._model.index(row, 0)
        if not item.isValid():
            self._model.removeRow(row)
            raise ValueError("model does not expose column zero")
        self._model.setData(item, str(text), QtCore.Qt.ItemDataRole.EditRole)
        self._model.setData(item, userData, USER_ROLE)
        if icon is not None:
            self._model.setData(item, QtGui.QIcon(icon), QtCore.Qt.ItemDataRole.DecorationRole)
        if was_empty and not self._multiple:
            self._select(item)

    def removeItem(self, index):
        if 0 <= index < self.count():
            self._model.removeRow(index)

    def clear(self):
        """Remove rows from the bound model. Use clearSelection to keep its data."""
        self.hide_popup()
        self._model.removeRows(0, self.count())
        self._select(QtCore.QModelIndex())
        self._reset_extra_selection()

    def itemText(self, index):
        return str(self._model.index(index, 0).data(DISPLAY_ROLE) or "")

    def setItemText(self, index, text):
        self._model.setData(self._model.index(index, 0), str(text), QtCore.Qt.ItemDataRole.EditRole)

    def itemData(self, index, role=USER_ROLE):
        return self._model.index(index, 0).data(role)

    def setItemData(self, index, value, role=USER_ROLE):
        self._model.setData(self._model.index(index, 0), value, role)

    def setItemEnabled(self, index, enabled):
        """Convenience for QStandardItemModel; custom models supply flags()."""
        if not isinstance(self._model, QtGui.QStandardItemModel):
            raise TypeError("set item flags in your custom model")
        item = self._model.item(index)
        if item is not None:
            item.setEnabled(bool(enabled))

    def findText(self, text):
        return next((row for row in range(self.count()) if self.itemText(row) == text), -1)

    def findData(self, value, role=USER_ROLE):
        return next((row for row in range(self.count()) if self.itemData(row, role) == value), -1)

    def currentIndex(self):
        return self._current.row() if self._current.isValid() else -1

    def currentModelIndex(self):
        """Selected QModelIndex, retaining the parent for tree choices."""
        return QtCore.QModelIndex(self._current)

    def currentText(self):
        return str(self._current.data(DISPLAY_ROLE) or "") if self._current.isValid() else ""

    def currentData(self, role=USER_ROLE):
        return self._current.data(role) if self._current.isValid() else None

    def setCurrentIndex(self, index):
        if index == -1:
            self._select(QtCore.QModelIndex())
        elif 0 <= index < self.count():
            item = self._model.index(index, 0)
            if self._eligible(item):
                self._select(item)

    def setCurrentModelIndex(self, index):
        if index.isValid() and index.model() is not self._model:
            raise ValueError("index belongs to another model")
        if not index.isValid() or self._eligible(index):
            self._select(index)

    def setCurrentText(self, text):
        row = self.findText(text)
        if row >= 0:
            self.setCurrentIndex(row)

    def setPlaceholderText(self, text):
        self._placeholder = str(text)
        self.update()

    def placeholderText(self):
        return self._placeholder

    def setMaxVisibleItems(self, count):
        if not 1 <= int(count) <= 30:
            raise ValueError("visible item count must be between 1 and 30")
        self._max_visible = int(count)

    def maxVisibleItems(self):
        return self._max_visible

    def _eligible(self, index):
        flags = index.flags()
        return (
            index.isValid()
            and bool(flags & QtCore.Qt.ItemFlag.ItemIsEnabled)
            and bool(flags & QtCore.Qt.ItemFlag.ItemIsSelectable)
        )

    def _first_enabled(self):
        return next(
            (
                self._model.index(row, 0)
                for row in range(self.count())
                if self._eligible(self._model.index(row, 0))
            ),
            QtCore.QModelIndex(),
        )

    def _select(self, index):
        self._current = QtCore.QPersistentModelIndex(index)
        self._sync_editor()
        self._publish()

    def _sync_editor(self, *, model_update=False):
        pass

    def _publish(self):
        state = (self.currentIndex(), self.currentText())
        previous = self._last_state
        self._last_state = state
        if state[0] != previous[0]:
            self.currentIndexChanged.emit(state[0])
        if state[1] != previous[1]:
            self.currentTextChanged.emit(state[1])
        self.setAccessibleDescription(state[1] or self._placeholder)
        self.update()

    def _reset_extra_selection(self):
        pass

    def _prune_selection(self):
        pass

    def _is_selected(self, index):
        return index == self._current

    def _activate(self, index):
        if not self._eligible(index):
            return
        self._select(index)
        self.activated.emit(index.row())
        self.textActivated.emit(self.currentText())
        self.hide_popup()

    def show_popup(self):
        """Open the shared in-window animated menu; never create a popup HWND."""
        if not self.isEnabled() or not self.isVisible() or not self.count():
            return
        if self._popup is None:
            self._popup = _ComboPopup(self)
        if self._popup._opened:
            self.hide_popup()
            return
        self._popup.refresh(reset_search=True)
        self._popup.popup(self)
        self._popup.focus_view()

    def hide_popup(self):
        if self._popup is not None:
            self._popup.dismiss(immediate=True)
        self.update()

    showPopup = show_popup
    hidePopup = hide_popup

    def view(self):
        """The native QListView or QTreeView used inside the shared menu."""
        if self._popup is None:
            self._popup = _ComboPopup(self)
        return self._popup.view

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        activate = self._pressed and self.rect().contains(event.position().toPoint())
        self._pressed = False
        self.update()
        if activate and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.show_popup()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (
            QtCore.Qt.Key.Key_Space,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_F4,
        ) or (
            key == QtCore.Qt.Key.Key_Down
            and event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier
        ):
            self.show_popup()
        elif key == QtCore.Qt.Key.Key_Escape:
            self.hide_popup()
        elif key in (
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.Key.Key_Up,
            QtCore.Qt.Key.Key_Home,
            QtCore.Qt.Key.Key_End,
        ):
            if self._multiple or self._tree:
                self.show_popup()
                event.accept()
                return
            choices = [
                row for row in range(self.count()) if self._eligible(self._model.index(row, 0))
            ]
            if choices:
                old = choices.index(self.currentIndex()) if self.currentIndex() in choices else -1
                new = (
                    0
                    if key == QtCore.Qt.Key.Key_Home
                    else len(choices) - 1
                    if key == QtCore.Qt.Key.Key_End
                    else max(
                        0, min(len(choices) - 1, old + (1 if key == QtCore.Qt.Key.Key_Down else -1))
                    )
                )
                self._activate(self._model.index(choices[new], 0))
        else:
            return super().keyPressEvent(event)
        event.accept()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = self._pressed = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._animate_focus(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._animate_focus(0.0)
        super().focusOutEvent(event)

    def _animate_focus(self, value):
        self._focus_motion.stop()
        self._focus_motion.setStartValue(self._focus_progress)
        self._focus_motion.setEndValue(value)
        self._focus_motion.start()

    def _focus_value(self, value):
        self._focus_progress = float(value)
        self.update()

    def hideEvent(self, event):
        self.hide_popup()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.EnabledChange and not self.isEnabled():
            self.hide_popup()
        super().changeEvent(event)

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self._transparent or self._hover or self._pressed:
            bg = _input_surface_color()
            if self._transparent:
                bg.setAlpha(10 if theme.mode.value == "light" else 20)
            painter.setBrush(bg)
            painter.setPen(
                QtGui.QPen(_input_border_color(), 1)
                if not self._transparent
                else QtCore.Qt.PenStyle.NoPen
            )
            painter.drawRoundedRect(rect, theme.tokens.radius, theme.tokens.radius)
            if not self._transparent:
                painter.setPen(QtGui.QPen(_input_lower_color(), 1))
                painter.drawLine(
                    QtCore.QLineF(6, self.height() - 1, self.width() - 6, self.height() - 1)
                )
        if self._focus_progress and self.isEnabled():
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.accent), 2))
            half = (self.width() - 14) * self._focus_progress / 2
            painter.drawLine(
                QtCore.QLineF(
                    self.width() / 2 - half,
                    self.height() - 2,
                    self.width() / 2 + half,
                    self.height() - 2,
                )
            )
        color = QtGui.QColor(
            theme.tokens.disabled
            if not self.isEnabled()
            else theme.tokens.text
            if self.currentText()
            else theme.tokens.text_muted
        )
        if (
            self._transparent
            and self._text_color is not None
            and self.currentText()
            and self.isEnabled()
        ):
            color = self._text_color
        if not self._multiple or not self.selectedIndexes():
            text = self.currentText() or self._placeholder
            painter.setPen(color)
            painter.drawText(
                QtCore.QRect(12, 0, self.width() - 46, self.height()),
                QtCore.Qt.AlignmentFlag.AlignVCenter,
                self.fontMetrics().elidedText(
                    text, QtCore.Qt.TextElideMode.ElideRight, self.width() - 46
                ),
            )
        _draw_chevron(
            painter, QtCore.QRectF(self.width() - 27, self.height() / 2 - 5, 12, 10), color
        )


class ModelComboBox(ComboBox):
    """Explicit model-bound variant; setModel accepts QAbstractItemModel."""


class EditableComboBox(ComboBox):
    """Editable choice. Enter selects an existing item or appends a new value."""

    editTextChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_edit = LineEdit(parent=self, show_clear_button=False)
        self._line_edit.set_trailing_inset(38)
        self._line_edit.textChanged.connect(self._edited)
        self._line_edit.returnPressed.connect(self._commit_text)
        self._line_edit.installEventFilter(self)
        self._drop_button = _ComboDropButton(self)
        self._drop_button.clicked.connect(self.show_popup)
        self.setFocusProxy(self._line_edit)
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self._auto_completer = QtWidgets.QCompleter(self._model, self)
        self._auto_completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self._auto_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.setCompleter(self._auto_completer)

    def lineEdit(self):
        return self._line_edit

    def currentText(self):
        return self._line_edit.text() if hasattr(self, "_line_edit") else super().currentText()

    def setCurrentText(self, text):
        self.setEditText(text)

    def setEditText(self, text):
        row = self.findText(str(text))
        self._current = QtCore.QPersistentModelIndex(self._model.index(row, 0))
        with QtCore.QSignalBlocker(self._line_edit):
            self._line_edit.setText(str(text))
        self._publish()
        self.editTextChanged.emit(str(text))

    def setPlaceholderText(self, text):
        super().setPlaceholderText(text)
        self._line_edit.setPlaceholderText(str(text))

    def setCompleter(self, completer):
        previous = self._line_edit.completer()
        if previous is not None:
            previous.activated[str].disconnect(self._completion_activated)
        self._line_edit.setCompleter(completer)
        if completer is not None:
            completer.setMaxVisibleItems(self._max_visible)
            completer.activated[str].connect(self._completion_activated)
            self._style_completer(completer)

    def completer(self):
        return self._line_edit.completer()

    def _style_completer(self, completer):
        popup = completer.popup()
        popup.setFont(self.font())
        popup.setVerticalScrollBar(FluentScrollBar(parent=popup))
        popup.setStyleSheet(
            f"QAbstractItemView {{background:{theme.tokens.surface};color:{theme.tokens.text};border:1px solid {theme.tokens.border};padding:4px;outline:none;}} QAbstractItemView::item {{min-height:30px;padding:0 8px;}} QAbstractItemView::item:selected {{background:{theme.tokens.accent};color:white;}}"
        )

    def _model_replaced(self):
        self._auto_completer.setModel(self._model)

    def _completion_activated(self, text):
        self.setEditText(text)
        self._commit_text()

    def _sync_editor(self, *, model_update=False):
        if hasattr(self, "_line_edit"):
            if model_update and not self._current.isValid() and self._last_state[0] == -1:
                return  # Unrelated model changes must preserve an uncommitted draft.
            with QtCore.QSignalBlocker(self._line_edit):
                self._line_edit.setText(super().currentText())

    def _edited(self, text):
        if text != super().currentText():
            self._current = QtCore.QPersistentModelIndex()
        self._publish()
        self.editTextChanged.emit(text)

    def _commit_text(self):
        text = self.currentText()
        if not text:
            return
        index = self.findText(text)
        if index < 0:
            self.addItem(text)
            index = self.count() - 1
        self._activate(self._model.index(index, 0))

    def clear(self):
        super().clear()
        self.setEditText("")

    def eventFilter(self, watched, event):
        if watched is self._line_edit and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() in (QtCore.Qt.Key.Key_F4, QtCore.Qt.Key.Key_Down) and (
                self.completer() is None or not self.completer().popup().isVisible()
            ):
                self.show_popup()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        # QLineEdit emits returnPressed then propagates Enter to its parent.
        # It must not reopen the choice popup after committing the value.
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._line_edit.setGeometry(self.rect())
        self._drop_button.setGeometry(self.width() - 36, 1, 35, max(1, self.height() - 2))

    def paintEvent(self, event):
        pass

    def _apply_theme(self):
        super()._apply_theme()
        if hasattr(self, "_line_edit") and self.completer() is not None:
            self._style_completer(self.completer())


class EditableModelComboBox(EditableComboBox):
    """Editable choice that binds directly to a caller's Qt model."""


class MultiSelectionComboBox(ComboBox):
    """Independent multiple selection, removable tags and a searchable list.

    Selection does not change CheckStateRole in a shared source model.
    """

    selectionChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._multiple = self._searchable = True
        self._selected = []
        self._last_selection = []
        self._tag_buttons = []
        self.setPlaceholderText("选择多个选项")

    def selectedIndexes(self):
        return [QtCore.QModelIndex(index) for index in self._selected if index.isValid()]

    def selectedTexts(self):
        return [str(index.data(DISPLAY_ROLE) or "") for index in self.selectedIndexes()]

    def selectedData(self, role=USER_ROLE):
        return [index.data(role) for index in self.selectedIndexes()]

    def setSelectedIndexes(self, indexes):
        """Accept row numbers for flat lists or QModelIndex values for trees."""
        converted = []
        for value in indexes:
            index = (
                self._model.index(value, 0) if isinstance(value, int) else QtCore.QModelIndex(value)
            )
            if not index.isValid() or index.model() is not self._model or not self._eligible(index):
                raise ValueError("selection must contain enabled indexes from this model")
            if index not in converted:
                converted.append(index)
        self._selected = [QtCore.QPersistentModelIndex(index) for index in converted]
        self._selection_updated()

    def clearSelection(self):
        self._selected = []
        self._selection_updated()

    def currentText(self):
        return "、".join(self.selectedTexts()) if hasattr(self, "_selected") else ""

    def _select(self, index):
        # Current index is a cursor only; it never adds an implicit selection.
        self._current = QtCore.QPersistentModelIndex(index)
        self._publish()

    def _activate(self, index):
        if not self._eligible(index):
            return
        persistent = QtCore.QPersistentModelIndex(index)
        if persistent in self._selected:
            self._selected.remove(persistent)
        else:
            self._selected.append(persistent)
        self._current = persistent
        self._selection_updated()

    def _is_selected(self, index):
        return index in self._selected

    def _prune_selection(self):
        if hasattr(self, "_selected"):
            self._selected = [index for index in self._selected if index.isValid()]
            self._selection_updated()

    def _reset_extra_selection(self):
        if hasattr(self, "_selected"):
            self.clearSelection()

    def _selection_updated(self):
        indexes = self.selectedIndexes()
        identity = [
            (
                QtCore.QPersistentModelIndex(index),
                str(index.data(DISPLAY_ROLE) or ""),
                index.data(USER_ROLE),
            )
            for index in indexes
        ]
        if identity != self._last_selection:
            self._last_selection = identity
            self.selectionChanged.emit(indexes)
        self._publish()
        self._layout_tags()
        if self._popup is not None:
            self._popup.view.viewport().update()

    def _layout_tags(self):
        for button in self._tag_buttons:
            button.hide()
            button.deleteLater()
        self._tag_buttons = []
        selected = self.selectedIndexes()
        x, available = 7, max(0, self.width() - 40)
        for number, index in enumerate(selected):
            text = str(index.data(DISPLAY_ROLE) or "")
            suffix = " ×"
            button = Button(text + suffix, self)
            # Match Button._draw_content: use its font and horizontal padding,
            # including the close glyph. Leave room for the half-pixel border.
            metrics = button.fontMetrics()
            padding = button._h_padding * 2 + 2
            width = min(150, metrics.horizontalAdvance(button.text()) + padding)
            if metrics.horizontalAdvance(button.text()) + padding > width:
                label = metrics.elidedText(
                    text,
                    QtCore.Qt.TextElideMode.ElideRight,
                    max(0, width - padding - metrics.horizontalAdvance(suffix)),
                )
                button.setText(label + suffix)
            remaining = len(selected) - number
            reserve = (
                metrics.horizontalAdvance("+" + str(remaining - 1)) + padding + 5
                if remaining > 1
                else 0
            )
            overflow = x + width + reserve > available
            if overflow:
                button.setText("+" + str(remaining))
                width = metrics.horizontalAdvance(button.text()) + padding
                button.setToolTip("、".join(str(item.data() or "") for item in selected[number:]))
                button.clicked.connect(self.show_popup)
                if width > available - x:
                    button.deleteLater()
                    break
            else:
                button.setToolTip("移除 " + text)
                button.clicked.connect(
                    lambda checked=False, item=QtCore.QPersistentModelIndex(index): self._activate(
                        QtCore.QModelIndex(item)
                    )
                )
            button.setFixedSize(width, 26)
            button.setMinimumHeight(26)
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.TabFocus)
            button.setAccessibleName(button.toolTip())
            button.move(x, (self.height() - 26) // 2)
            button.show()
            self._tag_buttons.append(button)
            x += button.width() + 5
            if overflow:
                break

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_tags()


class TreeComboBox(ComboBox):
    """Native QTreeView selection. Leaves are selectable; parents expand."""

    currentModelIndexChanged = Signal(QtCore.QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree = self._searchable = True
        self._last_tree_index = QtCore.QPersistentModelIndex()
        self.setPlaceholderText("选择一个项目")

    def _eligible(self, index):
        return super()._eligible(index) and self._model.rowCount(index) == 0

    def _publish(self):
        super()._publish()
        if hasattr(self, "_last_tree_index") and self._last_tree_index != self._current:
            self._last_tree_index = QtCore.QPersistentModelIndex(self._current)
            self.currentModelIndexChanged.emit(self.currentModelIndex())

    def currentPath(self):
        parts, index = [], self.currentModelIndex()
        while index.isValid():
            parts.insert(0, str(index.data(DISPLAY_ROLE) or ""))
            index = index.parent()
        return parts


class MultiSelectionTreeComboBox(MultiSelectionComboBox):
    """Native hierarchy with independent leaf selection and removable tags."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree = True

    def _eligible(self, index):
        return super()._eligible(index) and self._model.rowCount(index) == 0


class TransparentComboBox(ComboBox):
    """Borderless choice for toolbars; hover and focus remain visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._transparent = True

    def setTextColor(self, color):
        value = QtGui.QColor(color) if color is not None else None
        if value is not None and not value.isValid():
            raise ValueError("invalid text color")
        self._text_color = value
        self.update()


class FontComboBox(ComboBox):
    """System font families with search, live sample rows and a QFont signal."""

    currentFontChanged = Signal(QtGui.QFont)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._searchable = True
        self.addItems(QtGui.QFontDatabase.families())
        self.currentTextChanged.connect(self._font_changed)
        self.setCurrentFont(QtGui.QFont())

    def currentFont(self):
        return QtGui.QFont(self.currentText())

    def setCurrentFont(self, font):
        value = QtGui.QFont(font)
        index = self.findText(value.family())
        if index < 0:
            resolved = QtGui.QFontInfo(value).family()
            index = self.findText(resolved)
        if index >= 0:
            self.setCurrentIndex(index)

    def _font_changed(self, text):
        self.currentFontChanged.emit(self.currentFont())


class _ComboDropButton(QtWidgets.QAbstractButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("展开选项")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        _draw_chevron(
            painter,
            QtCore.QRectF(self.width() / 2 - 6, self.height() / 2 - 5, 12, 10),
            QtGui.QColor(theme.tokens.text_muted),
        )


class _ComboContent(QtWidgets.QWidget):
    def __init__(self, owner, popup):
        super().__init__()
        self.owner, self.popup = owner, popup

    def sizeHint(self):
        return QtCore.QSize(max(180, self.owner.width() - 14), self.popup.content_height())


class _ComboPopup(ActionMenu):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self.proxy = QtCore.QSortFilterProxyModel(self)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setAutoAcceptChildRows(True)
        self.proxy.setFilterKeyColumn(0)
        self.content = _ComboContent(owner, self)
        layout = QtWidgets.QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.search = SearchLineEdit("搜索选项", self.content)
        self.search.setVisible(owner._searchable)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.view = QtWidgets.QTreeView() if owner._tree else QtWidgets.QListView()
        self.view.setModel(self.proxy)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBar(FluentScrollBar(parent=self.view))
        self.view.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.view.setItemDelegate(_ChoiceDelegate(owner, self.view))
        self.view.clicked.connect(self._clicked)
        self.view.installEventFilter(self)
        if owner._tree:
            self.view.setHeaderHidden(True)
            self.view.setIndentation(20)
            self.view.setAnimated(True)
            self.view.setUniformRowHeights(True)
            self.view.setExpandsOnDoubleClick(False)
        layout.addWidget(self.view)
        self.empty = QtWidgets.QLabel("没有匹配的选项")
        self.empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        layout.addWidget(self.empty)
        self.set_content_widget(self.content)
        self.content.setFocusProxy(self.search if owner._searchable else self.view)
        self.aboutToHide.connect(owner.update)
        self._style_view()
        theme.subscribe(self, self._style_view)

    def content_height(self):
        return min(self.owner.maxVisibleItems(), max(1, self.proxy.rowCount())) * 34 + (
            42 if self.owner._searchable else 0
        )

    def schedule_refresh(self):
        # The proxy/view must finish processing the source model's signal first.
        # Mapping indexes synchronously inside layoutChanged can invalidate Qt's
        # in-flight selection update (particularly on a sort followed by a rename).
        self._refresh_timer.start(0)

    def refresh(self, reset_search=False):
        if self.proxy.sourceModel() is not self.owner.model():
            self.proxy.setSourceModel(self.owner.model())
        if reset_search:
            self.search.clear()
        self.view.setFixedHeight(
            min(self.owner.maxVisibleItems(), max(1, self._visible_rows())) * 34
        )
        self.content.setFixedHeight(self.view.height() + (42 if self.owner._searchable else 0))
        selected = self.owner.currentModelIndex()
        if selected.isValid():
            index = self.proxy.mapFromSource(selected)
            ancestor = index.parent()
            if self.owner._tree:
                while ancestor.isValid():
                    self.view.expand(ancestor)
                    ancestor = ancestor.parent()
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)
        self.empty.setVisible(self.proxy.rowCount() == 0)
        self.view.setVisible(self.proxy.rowCount() > 0)
        self.view.viewport().update()
        if self._opened:
            self._place()

    def _visible_rows(self):
        # Qt still handles all indexes and traversal; this only sizes the view.
        return self.proxy.rowCount() if not self.owner._tree else self.owner.maxVisibleItems()

    def _place(self):
        # Keep the anchor visible by shortening the native scrollable view to
        # whichever side has more room, before the common menu positions it.
        if self._anchor is not None and not self._placing:
            window = self.parentWidget()
            top = self._anchor.mapTo(window, QtCore.QPoint()).y()
            space = max(top - 6, window.height() - top - self._anchor.height() - 6)
            search_height = 42 if self.owner._searchable else 0
            desired = min(self.owner.maxVisibleItems(), max(1, self._visible_rows())) * 34
            self.view.setFixedHeight(max(34, min(desired, space - search_height - 32)))
            self.content.setFixedHeight(self.view.height() + search_height)
        super()._place()

    def _filter(self, text):
        self.proxy.setFilterFixedString(text)
        if self.owner._tree and text:
            self.view.expandAll()
        self.refresh()

    def focus_view(self):
        (self.search if self.owner._searchable else self.view).setFocus(
            QtCore.Qt.FocusReason.PopupFocusReason
        )

    def _clicked(self, index):
        source = self.proxy.mapToSource(index)
        if self.owner._tree and self.proxy.rowCount(index):
            self.view.setExpanded(index, not self.view.isExpanded(index))
        else:
            self.owner._activate(source)

    def eventFilter(self, watched, event):
        if self._opened and event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if watched is self.search and key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up):
                self.view.setFocus()
                if not self.view.currentIndex().isValid():
                    self.view.setCurrentIndex(self.proxy.index(0, 0))
                return True
            if watched in (self.search, self.view) and key in (
                QtCore.Qt.Key.Key_Return,
                QtCore.Qt.Key.Key_Enter,
                QtCore.Qt.Key.Key_Space,
            ):
                if watched is self.search and key == QtCore.Qt.Key.Key_Space:
                    return False
                index = self.view.currentIndex()
                if not index.isValid():
                    index = self.proxy.index(0, 0)
                if index.isValid():
                    self._clicked(index)
                return True
        return super().eventFilter(watched, event)

    def _style_view(self):
        self.view.setFont(ui_font(theme.tokens.font_size))
        palette = self.view.palette()
        for role in (
            QtGui.QPalette.ColorRole.Text,
            QtGui.QPalette.ColorRole.WindowText,
            QtGui.QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(role, QtGui.QColor(theme.tokens.text))
        self.view.setPalette(palette)
        self.view.setStyleSheet(
            f"QAbstractItemView {{background:transparent;color:{theme.tokens.text};border:none;outline:none;}}"
        )
        self.empty.setStyleSheet(f"color:{theme.tokens.text_muted};background:transparent;")
        self.view.viewport().setAutoFillBackground(False)
        self.view.viewport().update()


class _ChoiceDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner

    def sizeHint(self, option, index):
        return QtCore.QSize(180, 34)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        source = index.model().mapToSource(index)
        selected = self.owner._is_selected(source)
        enabled = bool(index.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
        rect = QtCore.QRectF(option.rect).adjusted(1, 1, -1, -1)
        if selected or option.state & (
            QtWidgets.QStyle.StateFlag.State_MouseOver | QtWidgets.QStyle.StateFlag.State_Selected
        ):
            color = QtGui.QColor(theme.tokens.accent if selected else theme.tokens.text)
            color.setAlpha(28 if selected else 10 if theme.mode.value == "light" else 20)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 4, 4)
        left = rect.left() + 11
        if self.owner._multiple and self.owner._eligible(source):
            box = QtCore.QRectF(left, rect.center().y() - 7, 14, 14)
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(theme.tokens.accent if selected else theme.tokens.text_muted), 1
                )
            )
            painter.setBrush(
                QtGui.QColor(theme.tokens.accent) if selected else QtCore.Qt.BrushStyle.NoBrush
            )
            painter.drawRoundedRect(box, 3, 3)
            if selected:
                painter.setPen(QtGui.QPen(QtGui.QColor("white"), 1.5))
                path = QtGui.QPainterPath(QtCore.QPointF(left + 3, box.top() + 7))
                path.lineTo(left + 6, box.top() + 10)
                path.lineTo(left + 11, box.top() + 4)
                painter.drawPath(path)
            left += 24
        elif selected:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(theme.tokens.accent))
            painter.drawRoundedRect(QtCore.QRectF(rect.left(), rect.top() + 8, 3, 16), 1.5, 1.5)
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QtGui.QIcon) and not icon.isNull():
            icon.paint(painter, QtCore.QRect(round(left), round(rect.center().y() - 8), 16, 16))
            left += 24
        font = (
            QtGui.QFont(str(index.data())) if isinstance(self.owner, FontComboBox) else option.font
        )
        font.setPixelSize(theme.tokens.font_size)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.tokens.text if enabled else theme.tokens.disabled))
        text_rect = QtCore.QRectF(left, rect.top(), max(0, rect.right() - left - 8), rect.height())
        text = QtGui.QFontMetrics(font).elidedText(
            str(index.data() or ""), QtCore.Qt.TextElideMode.ElideRight, round(text_rect.width())
        )
        painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


def _draw_chevron(painter, rect, color):
    painter.setPen(
        QtGui.QPen(color, 1.45, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(
        QtCore.QLineF(rect.left() + 2, rect.top() + 3, rect.center().x(), rect.bottom() - 2)
    )
    painter.drawLine(
        QtCore.QLineF(rect.center().x(), rect.bottom() - 2, rect.right() - 2, rect.top() + 3)
    )
