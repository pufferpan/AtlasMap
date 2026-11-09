"""A small Fluent code editor with a synchronized gutter and JSON highlighting."""

from __future__ import annotations

import re

from ..backends.text import backend_name, json_spans_native, json_spans_python
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from .scroll_bar import FluentScrollBar


class _JsonHighlighter(QtGui.QSyntaxHighlighter):
    _kinds = ("key", "string", "number", "literal")

    def __init__(self, document: QtGui.QTextDocument) -> None:
        super().__init__(document)
        self.language = "json"
        self.formats: dict[str, QtGui.QTextCharFormat] = {}
        self._select_backend()

    def _select_backend(self) -> None:
        self.backend = backend_name()
        self._scan = json_spans_native if self.backend == "native" else json_spans_python

    def rehighlight(self) -> None:
        # Resolve configuration once per pass, rather than once per line.
        self._select_backend()
        super().rehighlight()

    def set_colors(self, colors: dict[str, str]) -> None:
        self.formats = {}
        for name, color in colors.items():
            text_format = QtGui.QTextCharFormat()
            text_format.setForeground(QtGui.QColor(color))
            self.formats[name] = text_format
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if self.language != "json" or not self.formats:
            return
        for start, length, kind in self._scan(text):
            self.setFormat(start, length, self.formats[self._kinds[kind]])


class _LineNumbers(QtWidgets.QWidget):
    def __init__(self, editor: "_TextArea") -> None:
        super().__init__(editor)
        self.editor = editor
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        self.editor.paint_line_numbers(event)


class _TextArea(QtWidgets.QPlainTextEdit):
    focusChanged = Signal(bool)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.colors = {"background": "#ffffff", "line": "#e8e8e8", "gutter": "#596777"}
        self.indent_size = 4
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.setVerticalScrollBar(FluentScrollBar(parent=self))
        self.setHorizontalScrollBar(FluentScrollBar(QtCore.Qt.Orientation.Horizontal, self))
        self.document().setDocumentMargin(6)
        font = QtGui.QFont()
        font.setFamilies(
            [
                "Consolas",
                "Cascadia Code",
                "Microsoft YaHei UI",
                "Noto Sans Mono CJK SC",
                "DejaVu Sans Mono",
            ]
        )
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        font.setPixelSize(theme.tokens.font_size)
        self.setFont(font)
        self.line_numbers = _LineNumbers(self)
        self.blockCountChanged.connect(self.update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_gutter_width()

    def gutter_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return self.fontMetrics().horizontalAdvance("9") * (digits + 6)

    def update_gutter_width(self, _count: int = 0) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.indent_size)
        self._position_gutter()

    def _position_gutter(self) -> None:
        viewport = self.viewport().geometry()
        self.line_numbers.setGeometry(0, viewport.top(), self.gutter_width(), viewport.height())

    def _update_gutter(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self.line_numbers.scroll(0, dy)
        else:
            self.line_numbers.update(0, rect.y(), self.gutter_width(), rect.height())
        self._position_gutter()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_gutter()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.FontChange and hasattr(self, "line_numbers"):
            self.update_gutter_width()

    def highlight_current_line(self) -> None:
        if not self.hasFocus():
            self.setExtraSelections([])
            self.line_numbers.update()
            return
        selection = QtWidgets.QTextEdit.ExtraSelection()
        selection.format.setBackground(QtGui.QColor(self.colors["line"]))
        selection.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self.line_numbers.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self.viewport())
        painter.setClipRect(event.rect())
        painter.setPen(QtGui.QPen(QtGui.QColor(self.colors.get("guide", "#e8eaf0")), 1))
        space = QtGui.QFontMetricsF(self.font()).horizontalAdvance(" ")
        block = self.firstVisibleBlock()
        while block.isValid():
            rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if rect.top() > event.rect().bottom():
                break
            if block.isVisible() and rect.bottom() >= event.rect().top():
                text = block.text()
                whitespace = text[: len(text) - len(text.lstrip(" \t"))]
                columns = len(whitespace.expandtabs(self.indent_size))
                origin = rect.left() + self.document().documentMargin()
                for column in range(0, columns, self.indent_size):
                    x = origin + column * space
                    if x > self.viewport().width():
                        break
                    if x >= 0:
                        painter.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            block = block.next()

    def paint_line_numbers(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self.line_numbers)
        painter.fillRect(event.rect(), QtGui.QColor(self.colors["background"]))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        current = self.textCursor().blockNumber()
        while block.isValid():
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            height = self.blockBoundingRect(block).height()
            if top > event.rect().bottom():
                break
            if block.isVisible() and top + height >= event.rect().top():
                if self.hasFocus() and block.blockNumber() == current:
                    painter.fillRect(
                        QtCore.QRectF(0, top, self.gutter_width(), height),
                        QtGui.QColor(self.colors["line"]),
                    )
                painter.setPen(QtGui.QColor(self.colors["gutter"]))
                painter.drawText(
                    QtCore.QRectF(
                        0,
                        top,
                        self.gutter_width() - self.fontMetrics().horizontalAdvance(" ") * 3.75,
                        self.fontMetrics().height(),
                    ),
                    QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                    str(block.blockNumber() + 1),
                )
            block = block.next()

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusInEvent(event)
        self.highlight_current_line()
        self.focusChanged.emit(True)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.highlight_current_line()
        self.focusChanged.emit(False)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab) and not self.isReadOnly():
            self._indent(
                key == QtCore.Qt.Key.Key_Backtab
                or bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            )
            event.accept()
            return
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and not self.isReadOnly():
            cursor = self.textCursor()
            prefix = QtGui.QTextCursor(self.document())
            prefix.setPosition(cursor.selectionStart())
            prefix.movePosition(
                QtGui.QTextCursor.MoveOperation.StartOfBlock, QtGui.QTextCursor.MoveMode.KeepAnchor
            )
            before = prefix.selectedText()
            indentation = re.match(r"[ \t]*", before).group()
            if before.rstrip().endswith(("{", "[")):
                indentation += " " * self.indent_size
            cursor.beginEditBlock()
            cursor.insertText("\n" + indentation)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return
        super().keyPressEvent(event)

    def _indent(self, unindent: bool) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection() and not unindent:
            cursor.insertText(
                " " * (self.indent_size - cursor.positionInBlock() % self.indent_size)
            )
            return
        first = self.document().findBlock(cursor.selectionStart())
        last = self.document().findBlock(cursor.selectionEnd())
        if cursor.hasSelection() and cursor.selectionEnd() == last.position():
            last = last.previous()
        edit = QtGui.QTextCursor(self.document())
        edit.beginEditBlock()
        block = first
        while block.isValid() and block.blockNumber() <= last.blockNumber():
            edit.setPosition(block.position())
            if unindent:
                text = block.text()
                count = (
                    1
                    if text.startswith("\t")
                    else min(self.indent_size, len(text) - len(text.lstrip(" ")))
                )
                edit.setPosition(block.position() + count, QtGui.QTextCursor.MoveMode.KeepAnchor)
                edit.removeSelectedText()
            else:
                edit.insertText(" " * self.indent_size)
            block = block.next()
        edit.endEditBlock()
        self.setTextCursor(cursor)


class CodeEdit(QtWidgets.QWidget):
    """Editable JSON/plain text with line numbers and a Fluent focus underline.

    ``text_edit`` exposes the underlying QPlainTextEdit for Qt cursor, selection,
    clipboard and document APIs. Highlighting does not validate JSON.
    """

    textChanged = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, language: str = "json") -> None:
        super().__init__(parent)
        # Reject a forced missing backend here, outside Qt virtual callbacks.
        backend_name()
        self._font_size = theme.tokens.font_size
        self._focus_progress = 0.0
        self._focus_animation = QtCore.QVariantAnimation(self)
        self._focus_animation.setDuration(150)
        self._focus_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._focus_animation.valueChanged.connect(self._update_focus)
        self.text_edit = _TextArea(self)
        self.text_edit.textChanged.connect(self.textChanged.emit)
        self.text_edit.focusChanged.connect(self._focus_changed)
        self.setFocusProxy(self.text_edit)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(160, 80)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(1, 5, 1, 5)
        layout.setSpacing(0)
        layout.addWidget(self.text_edit)
        self._highlighter = _JsonHighlighter(self.text_edit.document())
        self.set_language(language)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def set_code(self, code: str) -> None:
        if self.language() == "json":
            self._highlighter._select_backend()
        self.text_edit.setPlainText(code)

    def code(self) -> str:
        return self.text_edit.toPlainText()

    def set_language(self, language: str) -> None:
        if language not in ("json", "plain"):
            raise ValueError("language must be 'json' or 'plain'")
        if language == "json":
            backend_name()
        self._highlighter.language = language
        self._highlighter.rehighlight()

    def language(self) -> str:
        return self._highlighter.language

    def acceleration_backend(self) -> str:
        """Return the JSON backend used by the current highlighter."""
        return self._highlighter.backend

    def set_font_size(self, pixels: int) -> None:
        """Set the code and gutter font size in logical pixels."""
        if isinstance(pixels, bool) or not isinstance(pixels, int) or pixels <= 0:
            raise ValueError("font size must be a positive integer")
        if pixels != self._font_size:
            self._font_size = pixels
            self._apply_theme()

    def font_size(self) -> int:
        return self._font_size

    def set_indent_size(self, spaces: int) -> None:
        """Set the indentation width used by Tab, Enter and indent guides."""
        if isinstance(spaces, bool) or not isinstance(spaces, int) or spaces <= 0:
            raise ValueError("indent size must be a positive integer")
        self.text_edit.indent_size = spaces
        self.text_edit.update_gutter_width()
        self.text_edit.viewport().update()

    def indent_size(self) -> int:
        return self.text_edit.indent_size

    def setReadOnly(self, read_only: bool) -> None:
        self.text_edit.setReadOnly(read_only)

    def isReadOnly(self) -> bool:
        return self.text_edit.isReadOnly()

    def setPlainText(self, text: str) -> None:
        self.set_code(text)

    def toPlainText(self) -> str:
        return self.code()

    def _focus_changed(self, focused: bool) -> None:
        self._focus_animation.stop()
        self._focus_animation.setStartValue(self._focus_progress)
        self._focus_animation.setEndValue(1.0 if focused else 0.0)
        self._focus_animation.start()

    def _update_focus(self, value: object) -> None:
        self._focus_progress = float(value)
        self.update()

    def _apply_theme(self) -> None:
        light = theme.mode.value == "light"
        self._background = "#ffffff" if light else "#1e1f22"
        self._border = "#eaeaea" if light else "#3c3c3c"
        text = "#002b4d" if light else "#bfc7d5"
        self.text_edit.colors = {
            "background": self._background,
            "gutter": "#9caac0" if light else "#56616e",
            "line": "#f3f6fa" if light else "#25272c",
            "guide": "#e8eaf0" if light else "#34373d",
        }
        self.text_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {self._background}; color: {text}; border: none;"
            f' font-family: "Consolas", "Cascadia Code", "Microsoft YaHei UI", "Noto Sans Mono CJK SC", "DejaVu Sans Mono", monospace; font-size: {self._font_size}px;'
            f" selection-background-color: {'#b8e8eb' if light else '#264f78'};"
            f" selection-color: {text}; }}"
        )
        self._highlighter.set_colors(
            {
                "key": "#9640AD" if light else "#c179b6",
                "string": "#00a42f" if light else "#68a850",
                "number": "#0059ff" if light else "#00b8cc",
                "literal": "#003fff" if light else "#dc8b55",
            }
        )
        self.text_edit.update_gutter_width()
        self.text_edit.highlight_current_line()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QtGui.QColor(self._background))
        painter.setPen(QtGui.QPen(QtGui.QColor(self._border), 1))
        painter.drawRoundedRect(rect, 5, 5)
        if self._focus_progress > 0:
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(rect, 5, 5)
            painter.setClipPath(clip)
            width = rect.width() * self._focus_progress
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.accent), 2))
            painter.drawLine(
                QtCore.QLineF(
                    rect.center().x() - width / 2,
                    rect.bottom() - 0.5,
                    rect.center().x() + width / 2,
                    rect.bottom() - 0.5,
                )
            )
