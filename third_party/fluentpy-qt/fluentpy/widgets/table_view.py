"""Qt tables with shared row painting, native models and ordinary editing.

Independently implemented using Qt's public item-view interfaces. No external
table implementation, styles, assets or demonstration data are used.
"""

from __future__ import annotations

import csv
import io
import math
import sys
import weakref

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font
from .action_menu import ActionMenu
from .line_edit import DoubleSpinBox, LineEdit, SpinBox
from .scroll_bar import FluentScrollBar


class _TableCornerFilter(QtCore.QObject):
    def __init__(self, table):
        super().__init__(table)
        self._table_ref = weakref.ref(table)
        for child in table.findChildren(
            QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
        ):
            child.installEventFilter(self)

    def fit(self):
        table = self._table_ref()
        if table is None:
            return
        inset = 1 if table._border_visible else 0
        path = QtGui.QPainterPath()
        path.addRoundedRect(
            QtCore.QRectF(table.rect()).adjusted(inset, inset, -inset, -inset),
            table._border_radius,
            table._border_radius,
        )
        region = QtGui.QRegion(path.toFillPolygon().toPolygon())
        # Clip structural child surfaces, never the table's native window.
        # The parent draws the antialiased outline around these insets.
        for child in table.findChildren(
            QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
        ):
            if child.isWindow() or child is table._context_menu:
                continue
            child.setMask(
                region.translated(-child.x(), -child.y()).intersected(QtGui.QRegion(child.rect()))
            )

    def eventFilter(self, watched, event):
        if self.__dict__.get("_table_ref") is not None and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Move,
            QtCore.QEvent.Type.Show,
        ):
            self.fit()
        return False


class TableItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paint visible cells; retain Qt roles, check states and editor signals."""

    def paint(self, painter, option, index):
        view = self.parent()
        if not isinstance(view, _TableMixin):
            return super().paint(painter, option, index)
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QtWidgets.QStyle.StateFlag.State_Selected)
        focused = bool(opt.state & QtWidgets.QStyle.StateFlag.State_HasFocus)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)
        rect = QtCore.QRectF(option.rect)
        # QTableView may paint a native selected-row panel before invoking the
        # delegate. Reset that cell opaquely before composing our row surface.
        painter.fillRect(rect, QtGui.QColor(theme.tokens.surface))
        row = QtCore.QRectF(0, rect.top(), view.viewport().width(), rect.height())
        rounded = view._row_style == "rounded"
        card = row.adjusted(5, 3, -5, -3) if rounded else row
        if rounded or (view.alternatingRowColors() and index.row() % 2):
            base = theme.tokens.surface_low if rounded else theme.tokens.surface_high
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(base))
            painter.drawRoundedRect(card, 6 if rounded else 0, 6 if rounded else 0)
        if opt.backgroundBrush.style() != QtCore.Qt.BrushStyle.NoBrush:
            painter.fillRect(rect, opt.backgroundBrush)
        hover = view._hover_amount(index)
        if hover:
            color = QtGui.QColor("#000000" if theme.mode.value == "light" else "#ffffff")
            color.setAlpha(round(13 * hover))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(card, 6 if rounded else 0, 6 if rounded else 0)
        if selected:
            target = (
                card
                if view.selectionBehavior() == view.SelectionBehavior.SelectRows
                else rect.adjusted(2, 2, -2, -2)
            )
            color = QtGui.QColor(theme.tokens.accent)
            color.setAlpha(
                round((36 if theme.mode.value == "light" else 48) * view._selection_progress)
            )
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(target, 6 if rounded else 2, 6 if rounded else 2)
            if (
                view.selectionBehavior() == view.SelectionBehavior.SelectRows
                and index.column() == view.columnAt(0)
            ):
                painter.setBrush(QtGui.QColor(theme.tokens.accent))
                painter.drawRoundedRect(
                    QtCore.QRectF(card.left() + 2, rect.center().y() - 9, 3, 18), 1.5, 1.5
                )
        if view._row_style == "line":
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
            painter.drawLine(
                QtCore.QLineF(rect.left(), rect.bottom() - 0.5, rect.right(), rect.bottom() - 0.5)
            )
        # Qt still paints text, icons, checkboxes and disabled states from the
        # caller's model. A selected row uses a readable tint, not white text.
        opt.state &= ~(
            QtWidgets.QStyle.StateFlag.State_Selected
            | QtWidgets.QStyle.StateFlag.State_MouseOver
            | QtWidgets.QStyle.StateFlag.State_HasFocus
        )
        opt.backgroundBrush = QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)
        opt.rect = opt.rect.adjusted(10, 0, -8, 0)
        (opt.widget.style() if opt.widget else view.style()).drawControl(
            QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, view
        )
        if focused and view.hasFocus():
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.accent), 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1.5, 2.5, -1.5, -2.5), 3, 3)
        painter.restore()

    def createEditor(self, parent, option, index):
        value = index.data(QtCore.Qt.ItemDataRole.EditRole)
        if isinstance(value, str):
            return LineEdit(parent=parent, show_clear_button=False)
        if isinstance(value, int) and not isinstance(value, bool) and -(2**31) <= value < 2**31:
            editor = SpinBox(parent)
            editor.setRange(-(2**31), 2**31 - 1)
            return editor
        if isinstance(value, float):
            if not math.isfinite(value):
                return None
            # Preserve the source's round-trip precision and magnitude when
            # entering/leaving an editor without changing its value.
            mantissa, _, exponent = repr(value).lower().partition("e")
            decimals = len(mantissa.partition(".")[2]) - int(exponent or 0)
            if decimals > 323:
                return None
            editor = DoubleSpinBox(parent)
            editor.setDecimals(max(6, decimals))
            editor.setRange(-sys.float_info.max, sys.float_info.max)
            return editor
        return super().createEditor(parent, option, index)

    def editorEvent(self, event, model, option, index):
        adjusted = QtWidgets.QStyleOptionViewItem(option)
        adjusted.rect = adjusted.rect.adjusted(10, 0, -8, 0)
        return super().editorEvent(event, model, adjusted, index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QtCore.QSize(size.width() + 18, size.height())

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(3, 3, -3, -3))


class _TableMixin:
    def _init_table(self):
        self._row_style = "standard"
        self._border_visible = True
        self._border_radius = 8
        self._right_click_selects = True
        self._empty_text = "暂无数据"
        self._hover_index = QtCore.QPersistentModelIndex()
        self._previous_hover = QtCore.QPersistentModelIndex()
        self._hover_progress = 1.0
        self._selection_progress = 1.0
        self._model_connections = []
        self._context_menu = self._context_native = None
        self._hover_animation = self._animation(self._set_hover_progress)
        self._selection_animation = self._animation(self._set_selection_progress)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBar(FluentScrollBar(parent=self))
        self.setHorizontalScrollBar(FluentScrollBar(QtCore.Qt.Orientation.Horizontal, self))
        self.verticalHeader().setDefaultSectionSize(44)
        self.verticalHeader().setMinimumSectionSize(24)
        self.verticalHeader().hide()
        self.horizontalHeader().setMinimumSectionSize(40)
        self.horizontalHeader().setFixedHeight(38)
        self.horizontalHeader().setDefaultAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setHighlightSections(False)
        self.setItemDelegate(TableItemDelegate(self))
        self._corner_filter = _TableCornerFilter(self)
        self._watch_model(self.model())
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def _animation(self, callback):
        animation = QtCore.QVariantAnimation(self)
        animation.setDuration(120)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(callback)
        return animation

    def _watch_model(self, model):
        for connection in self._model_connections:
            QtCore.QObject.disconnect(connection)
        self._model_connections.clear()
        if model is not None:
            for signal in (
                model.modelReset,
                model.layoutChanged,
                model.rowsRemoved,
                model.columnsRemoved,
            ):
                self._model_connections.append(signal.connect(self._reset_visual_state))
        self._reset_visual_state()

    def _reset_visual_state(self, *args):
        self._hover_animation.stop()
        self._selection_animation.stop()
        self._hover_index = QtCore.QPersistentModelIndex()
        self._previous_hover = QtCore.QPersistentModelIndex()
        self._hover_progress = self._selection_progress = 1.0
        self.viewport().update()

    def _hover_amount(self, index):
        row_index = index.siblingAtColumn(0)
        return (
            self._hover_progress
            if row_index == self._hover_index
            else 1.0 - self._hover_progress
            if row_index == self._previous_hover
            else 0.0
        )

    def _set_hover_progress(self, value):
        self._hover_progress = float(value)
        for index in (self._hover_index, self._previous_hover):
            if index.isValid():
                rect = self.visualRect(QtCore.QModelIndex(index))
                rect.setLeft(0)
                rect.setWidth(self.viewport().width())
                self.viewport().update(rect)

    def _set_selection_progress(self, value):
        self._selection_progress = float(value)
        self.viewport().update()

    def row_style(self) -> str:
        return self._row_style

    def set_row_style(self, style: str) -> None:
        if style not in ("standard", "rounded", "line"):
            raise ValueError("row style must be standard, rounded, or line")
        self._row_style = style
        self.viewport().update()

    def set_row_height(self, height: int) -> None:
        if isinstance(height, bool) or not isinstance(height, int) or height < 24:
            raise ValueError("row height must be an integer of at least 24")
        self.verticalHeader().setDefaultSectionSize(height)

    def row_height(self) -> int:
        return self.verticalHeader().defaultSectionSize()

    def set_border_visible(self, visible: bool) -> None:
        self._border_visible = bool(visible)
        self._apply_theme()

    def is_border_visible(self) -> bool:
        return self._border_visible

    def set_border_radius(self, radius: int) -> None:
        if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
            raise ValueError("border radius must be a nonnegative integer")
        self._border_radius = radius
        self._apply_theme()

    def border_radius(self) -> int:
        return self._border_radius

    def set_select_right_clicked_row(self, enabled: bool) -> None:
        self._right_click_selects = bool(enabled)

    def select_right_clicked_row(self) -> bool:
        return self._right_click_selects

    def set_empty_text(self, text: str) -> None:
        self._empty_text = str(text)
        self.viewport().update()

    def empty_text(self) -> str:
        return self._empty_text

    def setBorderVisible(self, visible):
        self.set_border_visible(visible)

    def setBorderRadius(self, radius):
        self.set_border_radius(radius)

    def setSelectRightClickedRow(self, enabled):
        self.set_select_right_clicked_row(enabled)

    def selection_text(self, *, include_headers: bool = False) -> str:
        """TSV in visual row/column order; preserve gaps in sparse selections."""
        selection = self.selectionModel()
        model = self.model()
        if selection is None or model is None:
            return ""
        indexes = [
            i
            for i in selection.selectedIndexes()
            if i.parent() == self.rootIndex()
            and not self.isRowHidden(i.row())
            and not self.isColumnHidden(i.column())
        ]
        if not indexes:
            return ""
        rows = sorted({i.row() for i in indexes}, key=self.verticalHeader().visualIndex)
        columns = sorted({i.column() for i in indexes}, key=self.horizontalHeader().visualIndex)
        values = {(i.row(), i.column()): i.data() for i in indexes}
        if (
            not include_headers
            and len(rows) == len(columns) == 1
            and values.get((rows[0], columns[0])) in ("", None)
        ):
            return ""
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        if include_headers:
            writer.writerow(
                [model.headerData(c, QtCore.Qt.Orientation.Horizontal) for c in columns]
            )
        for row in rows:
            writer.writerow(
                ["" if values.get((row, c)) is None else str(values[row, c]) for c in columns]
            )
        return stream.getvalue().removesuffix("\n")

    def copy_selection(self, *, include_headers: bool = False) -> bool:
        text = self.selection_text(include_headers=include_headers)
        selection = self.selectionModel()
        if not text and not (
            selection
            and any(
                i.parent() == self.rootIndex()
                and not self.isRowHidden(i.row())
                and not self.isColumnHidden(i.column())
                for i in selection.selectedIndexes()
            )
        ):
            return False
        QtWidgets.QApplication.clipboard().setText(text)
        return True

    def _copy_with_headers(self):
        self.copy_selection(include_headers=True)

    def _edit_current(self):
        if self.currentIndex().isValid():
            self.edit(self.currentIndex())

    def createStandardContextMenu(self, position=None):
        """QAction factory shared by the table and workbench's ActionMenu."""
        menu = QtWidgets.QMenu(self)
        has_selection = bool(self.selectionModel() and self.selectionModel().hasSelection())
        for text, name, callback, enabled in (
            ("复制选中内容", "table-copy", self.copy_selection, has_selection),
            ("连同表头复制", "table-copy-headers", self._copy_with_headers, has_selection),
        ):
            action = menu.addAction(text)
            action.setObjectName(name)
            action.setEnabled(enabled)
            action.triggered.connect(callback)
        menu.addSeparator()
        index = self.currentIndex()
        editable = (
            index.isValid()
            and bool(index.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            and bool(index.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
        )
        action = menu.addAction("编辑当前单元格")
        action.setObjectName("table-edit")
        action.setEnabled(editable and self.editTriggers() != self.EditTrigger.NoEditTriggers)
        action.triggered.connect(self._edit_current)
        action = menu.addAction("全选")
        action.setObjectName("table-select-all")
        action.setEnabled(
            self.model() is not None
            and self.model().rowCount(self.rootIndex()) > 0
            and self.selectionMode() != self.SelectionMode.NoSelection
        )
        action.triggered.connect(self.selectAll)
        return menu

    def contextMenuEvent(self, event):
        if self._context_menu is None:
            self._context_menu = ActionMenu(self)
        self._context_menu.dismiss(immediate=True)
        self._context_menu.clear()
        if self._context_native is not None:
            self._context_native.deleteLater()
        self._context_native = self.createStandardContextMenu()
        self._context_menu.addActions(self._context_native.actions())
        if event.reason() == QtGui.QContextMenuEvent.Reason.Keyboard:
            rect = self.visualRect(self.currentIndex())
            point = self.viewport().mapTo(
                self, rect.bottomLeft() if rect.isValid() else QtCore.QPoint(12, 12)
            )
        else:
            point = self.mapFromGlobal(event.globalPos())
        self._context_menu.popup_at(self, point)
        event.accept()

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            index = self.indexAt(event.position().toPoint())
            selection = self.selectionModel()
            if (
                self._right_click_selects
                and index.isValid()
                and selection is not None
                and self.selectionMode() != self.SelectionMode.NoSelection
                and index.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled
                and index.flags() & QtCore.Qt.ItemFlag.ItemIsSelectable
            ):
                flags = QtCore.QItemSelectionModel.SelectionFlag.NoUpdate
                if not selection.isSelected(index):
                    flags = QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
                    if self.selectionBehavior() == self.SelectionBehavior.SelectRows:
                        flags |= QtCore.QItemSelectionModel.SelectionFlag.Rows
                    elif self.selectionBehavior() == self.SelectionBehavior.SelectColumns:
                        flags |= QtCore.QItemSelectionModel.SelectionFlag.Columns
                selection.setCurrentIndex(index, flags)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        index = index.siblingAtColumn(0) if index.isValid() else QtCore.QModelIndex()
        if index != self._hover_index:
            self._previous_hover = self._hover_index
            self._hover_index = QtCore.QPersistentModelIndex(index)
            self._hover_progress = 0.0
            self._hover_animation.stop()
            self._hover_animation.start()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._previous_hover = self._hover_index
        self._hover_index = QtCore.QPersistentModelIndex()
        self._hover_progress = 0.0
        self._hover_animation.stop()
        if self.isVisible():
            self._hover_animation.start()
        else:
            self._hover_progress = 1.0
        super().leaveEvent(event)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        if hasattr(self, "_selection_animation"):
            self._selection_animation.stop()
            if not selected.isEmpty() and self.isVisible():
                self._selection_progress = 0.0
                self._selection_animation.start()
            else:
                self._selection_progress = 1.0

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "_hover_animation"):
            self._hover_animation.stop()
            self._hover_index = QtCore.QPersistentModelIndex()
            self._previous_hover = QtCore.QPersistentModelIndex()

    def hideEvent(self, event):
        if hasattr(self, "_hover_animation"):
            self._reset_visual_state()
            if self._context_menu is not None:
                self._context_menu.dismiss(immediate=True)
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        model = self.model()
        if (model is None or model.rowCount(self.rootIndex()) == 0) and self._empty_text:
            painter = QtGui.QPainter(self.viewport())
            painter.setPen(QtGui.QColor(theme.tokens.text_muted))
            painter.drawText(
                self.viewport().rect().adjusted(16, 16, -16, -16),
                QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.TextFlag.TextWordWrap,
                self._empty_text,
            )

    def _apply_theme(self):
        tokens = theme.tokens
        palette = self.palette()
        for role, color in (
            (QtGui.QPalette.ColorRole.Base, tokens.surface),
            (QtGui.QPalette.ColorRole.Window, tokens.surface),
            (QtGui.QPalette.ColorRole.Text, tokens.text),
            (QtGui.QPalette.ColorRole.WindowText, tokens.text),
            (QtGui.QPalette.ColorRole.ButtonText, tokens.text),
            (QtGui.QPalette.ColorRole.AlternateBase, tokens.surface_high),
            (QtGui.QPalette.ColorRole.Highlight, tokens.accent),
            (QtGui.QPalette.ColorRole.HighlightedText, tokens.text),
        ):
            palette.setColor(role, QtGui.QColor(color))
        palette.setColor(
            QtGui.QPalette.ColorGroup.Disabled,
            QtGui.QPalette.ColorRole.Text,
            QtGui.QColor(tokens.disabled),
        )
        border = f"1px solid {tokens.border}" if self._border_visible else "none"
        styles = (
            f"QTableView {{background:{tokens.surface};color:{tokens.text};border:{border};"
            f"border-radius:{self._border_radius}px;outline:0;gridline-color:{tokens.border};}}"
            f"QHeaderView {{background:{tokens.surface};color:{tokens.text_muted};}}"
            f"QHeaderView::section {{background:{tokens.surface};color:{tokens.text_muted};"
            f"border:none;border-bottom:1px solid {tokens.border};padding:0 10px;font-weight:600;}}"
            f"QTableCornerButton::section {{background:{tokens.surface};border:none;}}"
        )
        if self.styleSheet() != styles:
            self.setStyleSheet(styles)
        for widget in (self, self.viewport(), self.horizontalHeader(), self.verticalHeader()):
            widget.setPalette(palette)
        self._corner_filter.fit()
        self.viewport().update()


class TableView(_TableMixin, QtWidgets.QTableView):
    """A themed QTableView. Qt owns model sorting, filtering and selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_table()

    def setModel(self, model):
        super().setModel(model)
        if hasattr(self, "_model_connections"):
            self._watch_model(model)


class TableWidget(_TableMixin, QtWidgets.QTableWidget):
    """A themed QTableWidget with its original item-based Qt interface."""

    def __init__(self, rows=0, columns=0, parent=None):
        if rows is None:
            rows = 0
        if isinstance(rows, QtWidgets.QWidget):
            if columns != 0 or parent is not None:
                raise TypeError("use TableWidget(parent) or TableWidget(rows, columns, parent)")
            parent, rows = rows, 0
        super().__init__(rows, columns, parent)
        self._init_table()
