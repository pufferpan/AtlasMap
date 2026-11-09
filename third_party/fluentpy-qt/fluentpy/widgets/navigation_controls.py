from __future__ import annotations

from dataclasses import dataclass

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font


@dataclass
class _RouteItem:
    route_key: str
    text: str
    widget: QtWidgets.QWidget


class BreadcrumbBar(QtWidgets.QWidget):
    currentChanged = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._entries: list[tuple[str, str]] = []
        self._items: list[QtWidgets.QAbstractButton] = []
        self._current = ""
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.setMinimumHeight(28)
        theme.subscribe(self, self._apply_theme)

    def add_item(self, route_key: str, text: str) -> None:
        if route_key in {key for key, _text in self._entries}:
            return
        self._entries.append((route_key, text))
        self.set_current_item(route_key)
        self._rebuild_items()

    def addItem(self, routeKey: str, text: str) -> None:
        self.add_item(routeKey, text)

    def set_current_item(self, route_key: str) -> None:
        if route_key == self._current:
            return
        self._current = route_key
        found = False
        for button in self._items:
            selected = button.property("routeKey") == route_key
            button.setProperty("selected", selected)
            button.update()
            found = found or selected
        if found:
            self.currentChanged.emit(route_key)

    def setCurrentItem(self, routeKey: str) -> None:
        self.set_current_item(routeKey)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rebuild_items()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
QLabel#breadcrumbSeparator {{
    color: {theme.tokens.text_muted};
    background: transparent;
    padding-top: 1px;
}}
"""
        )
        for button in self._items:
            button.update()

    def _rebuild_items(self) -> None:
        self._clear_layout()
        self._items.clear()
        visible_entries = self._visible_entries()
        for index, entry in enumerate(visible_entries):
            if index:
                separator = QtWidgets.QLabel(">")
                separator.setObjectName("breadcrumbSeparator")
                self._layout.addWidget(separator)
            route_key, text = entry
            button = _BreadcrumbButton(text)
            button.setProperty("routeKey", route_key)
            button.setProperty("selected", route_key == self._current)
            if route_key:
                button.clicked.connect(
                    lambda _checked=False, key=route_key: self.set_current_item(key)
                )
            else:
                button.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
                button.setEnabled(False)
            self._layout.addWidget(button)
            self._items.append(button)
        self._layout.addStretch(1)
        self._apply_theme()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _visible_entries(self) -> list[tuple[str, str]]:
        if len(self._entries) <= 4:
            return list(self._entries)
        if self.width() <= 0:
            return list(self._entries)

        metrics = self.fontMetrics()

        def entry_width(entry: tuple[str, str]) -> int:
            return metrics.horizontalAdvance(entry[1]) + 14

        separator_width = 16
        total = sum(entry_width(entry) for entry in self._entries)
        total += separator_width * max(0, len(self._entries) - 1)
        if total <= self.width():
            return list(self._entries)

        result: list[tuple[str, str]] = [self._entries[0], ("", "...")]
        tail: list[tuple[str, str]] = []
        budget = self.width() - entry_width(result[0]) - 32 - separator_width * 2
        for entry in reversed(self._entries[1:]):
            needed = entry_width(entry) + (separator_width if tail else 0)
            if budget - needed < 90 and tail:
                break
            tail.insert(0, entry)
            budget -= needed
            if len(tail) >= 4:
                break
        result.extend(tail or [self._entries[-1]])
        return result


class _BreadcrumbButton(QtWidgets.QAbstractButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setProperty("selected", False)
        self._hover = False
        self._pressed = False

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self.fontMetrics().horizontalAdvance(self.text()) + 8, 24)

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
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        color = QtGui.QColor(theme.tokens.text)
        if not self.property("selected") and not self._hover:
            color = QtGui.QColor(theme.tokens.text_muted)
        if self._pressed:
            color.setAlpha(150)
        painter.setPen(color)
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.text())


class Pivot(QtWidgets.QWidget):
    currentChanged = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, segmented: bool = False) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._items: list[_RouteItem] = []
        self._current = ""
        self._segmented = segmented
        self._indicator_x = 0.0
        self._indicator_w = 0.0
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_indicator_value)
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0 if segmented else 10)
        self.setFixedHeight(32 if segmented else 42)
        theme.subscribe(self, self.update)

    def add_item(self, route_key: str, text: str) -> None:
        button = _PivotButton(text, segmented=self._segmented)
        button.clicked.connect(lambda _checked=False, key=route_key: self.set_current_item(key))
        self._layout.addWidget(button)
        self._items.append(_RouteItem(route_key, text, button))
        if not self._current:
            self.set_current_item(route_key, animated=False)

    def addItem(self, routeKey: str, text: str) -> None:
        self.add_item(routeKey, text)

    def set_item_enabled(self, route_key: str, enabled: bool) -> None:
        """Enable a navigation entry without changing the selected page."""
        for item in self._items:
            if item.route_key == route_key:
                item.widget.setEnabled(bool(enabled))
                return

    def set_current_item(self, route_key: str, animated: bool = True) -> None:
        if route_key == self._current:
            return
        self._current = route_key
        current = self.current_item()
        for item in self._items:
            item.widget.setProperty("selected", item.route_key == route_key)
            item.widget.update()
        if current:
            target = self._indicator_target(current)
            self._animate_indicator(target, animated)
        self.currentChanged.emit(route_key)

    def setCurrentItem(self, routeKey: str) -> None:
        self.set_current_item(routeKey)

    def current_item(self) -> QtWidgets.QWidget | None:
        for item in self._items:
            if item.route_key == self._current:
                return item.widget
        return None

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        current = self.current_item()
        if current:
            self._indicator_x, self._indicator_w = self._indicator_target(current)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._items:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._segmented:
            bg = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "light" else "#ffffff")
            bg.setAlpha(142 if theme.tokens.mode.value == "light" else 15)
            border = (
                QtGui.QColor(0, 0, 0, 20)
                if theme.tokens.mode.value == "light"
                else QtGui.QColor(255, 255, 255, 18)
            )
            painter.setBrush(bg)
            painter.setPen(QtGui.QPen(border, 1))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
            selected = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "light" else "#ffffff")
            selected.setAlpha(180 if theme.tokens.mode.value == "light" else 18)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(selected)
            painter.drawRoundedRect(
                QtCore.QRectF(self._indicator_x, 2, self._indicator_w, self.height() - 4), 5, 5
            )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.tokens.accent))
        painter.drawRoundedRect(
            QtCore.QRectF(self._indicator_x + self._indicator_w / 2 - 8, self.height() - 3, 16, 3),
            1.5,
            1.5,
        )

    def _indicator_target(self, widget: QtWidgets.QWidget) -> tuple[float, float]:
        return float(widget.x()), float(widget.width())

    def _animate_indicator(self, target: tuple[float, float], animated: bool) -> None:
        if not animated:
            self._indicator_x, self._indicator_w = target
            self.update()
            return
        self._animation.stop()
        self._animation.setStartValue(QtCore.QPointF(self._indicator_x, self._indicator_w))
        self._animation.setEndValue(QtCore.QPointF(target[0], target[1]))
        self._animation.start()

    def _set_indicator_value(self, value: object) -> None:
        point = value if isinstance(value, QtCore.QPointF) else QtCore.QPointF()
        self._indicator_x = point.x()
        self._indicator_w = point.y()
        self.update()


class SegmentedWidget(Pivot):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, segmented=True)


class _PivotButton(QtWidgets.QAbstractButton):
    def __init__(self, text: str, *, segmented: bool = False) -> None:
        super().__init__()
        self.setText(text)
        self._segmented = segmented
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setProperty("selected", False)
        self._hover = False
        self.setMinimumWidth(82 if segmented else 42)

    def sizeHint(self) -> QtCore.QSize:
        width = self.fontMetrics().horizontalAdvance(self.text()) + (42 if self._segmented else 16)
        return QtCore.QSize(
            max(width, 82 if self._segmented else 42), 30 if self._segmented else 38
        )

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        if self._hover and not self._segmented:
            color = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "dark" else "#000000")
            color.setAlpha(12)
            painter.fillRect(self.rect().adjusted(0, 3, 0, -5), color)
        text = QtGui.QColor(theme.tokens.text)
        if not self.property("selected") and not self._hover:
            text = QtGui.QColor(theme.tokens.text_muted)
        painter.setPen(text)
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.text())


class SegmentedToolWidget(QtWidgets.QWidget):
    currentChanged = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._items: list[_RouteItem] = []
        self._current = ""
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self.setFixedHeight(32)
        theme.subscribe(self, self.update)

    def add_item(self, route_key: str, icon: QtGui.QIcon) -> None:
        button = _ToolSegmentButton(icon)
        button.clicked.connect(lambda _checked=False, key=route_key: self.set_current_item(key))
        self._layout.addWidget(button)
        self._items.append(_RouteItem(route_key, "", button))
        if not self._current:
            self.set_current_item(route_key)

    def addItem(self, routeKey: str, icon: QtGui.QIcon) -> None:
        self.add_item(routeKey, icon)

    def set_current_item(self, route_key: str) -> None:
        self._current = route_key
        for item in self._items:
            item.widget.setProperty("selected", item.route_key == route_key)
            item.widget.update()
        self.currentChanged.emit(route_key)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        bg = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "light" else "#ffffff")
        bg.setAlpha(105 if theme.tokens.mode.value == "light" else 12)
        border = (
            QtGui.QColor(0, 0, 0, 20)
            if theme.tokens.mode.value == "light"
            else QtGui.QColor(255, 255, 255, 18)
        )
        painter.setBrush(bg)
        painter.setPen(QtGui.QPen(border, 1))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)


class _ToolSegmentButton(QtWidgets.QAbstractButton):
    def __init__(self, icon: QtGui.QIcon) -> None:
        super().__init__()
        self._icon = icon
        self.setFixedSize(50, 32)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setProperty("selected", False)
        self._hover = False

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        selected = bool(self.property("selected"))
        if selected:
            painter.setBrush(QtGui.QColor(theme.tokens.accent))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0, 0, -1, -1), 5, 5)
        elif self._hover:
            hover = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "dark" else "#000000")
            hover.setAlpha(13)
            painter.setBrush(hover)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2), 4, 4)
        icon_color = QtGui.QColor(
            "#000000" if selected and theme.tokens.mode.value == "dark" else theme.tokens.text
        )
        _draw_tinted_icon(painter, self._icon, QtCore.QRect(17, 9, 16, 16), icon_color)


class TabBar(QtWidgets.QWidget):
    currentChanged = Signal(str)
    tabCloseRequested = Signal(int)
    tabAddRequested = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._items: list[_RouteItem] = []
        self._current = ""
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._add = QtWidgets.QToolButton()
        self._add.setText("+")
        self._add.setFixedSize(36, 36)
        self._add.clicked.connect(self.tabAddRequested.emit)
        self._layout.addWidget(self._add)
        self._layout.addStretch(1)
        self.setFixedHeight(38)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def add_tab(self, route_key: str, text: str, icon: QtGui.QIcon = QtGui.QIcon()) -> None:
        if any(item.route_key == route_key for item in self._items):
            return
        button = _TabButton(route_key, text, icon)
        button.clicked.connect(lambda _checked=False, key=route_key: self.set_current_tab(key))
        button.closeRequested.connect(lambda key=route_key: self._close_tab(key))
        self._layout.insertWidget(max(0, self._layout.count() - 2), button)
        self._items.append(_RouteItem(route_key, text, button))
        if not self._current:
            self.set_current_tab(route_key)

    def addTab(self, routeKey: str, text: str, icon: QtGui.QIcon = QtGui.QIcon()) -> None:
        self.add_tab(routeKey, text, icon)

    def set_current_tab(self, route_key: str) -> None:
        if route_key == self._current or not any(
            item.route_key == route_key for item in self._items
        ):
            return
        self._current = route_key
        for item in self._items:
            item.widget.setProperty("selected", item.route_key == route_key)
            item.widget.update()
        self.currentChanged.emit(route_key)

    def setCurrentTab(self, routeKey: str) -> None:
        self.set_current_tab(routeKey)

    def close_tab(self, route_key: str) -> None:
        """Close a document tab through the same signal path as its close button."""
        self._close_tab(route_key)

    def _close_tab(self, route_key: str) -> None:
        for index, item in enumerate(list(self._items)):
            if item.route_key != route_key:
                continue
            self._layout.removeWidget(item.widget)
            item.widget.deleteLater()
            self._items.remove(item)
            self.tabCloseRequested.emit(index)
            if self._current == route_key:
                if self._items:
                    replacement = min(len(self._items) - 1, max(0, index - 1))
                    self.set_current_tab(self._items[replacement].route_key)
                else:
                    self._current = ""
                    self.currentChanged.emit("")
            return

    def _apply_theme(self) -> None:
        self._add.setStyleSheet(
            f"""
QToolButton {{
    color: {theme.tokens.text};
    background: transparent;
    border: none;
    font-size: 20px;
}}
QToolButton:hover {{
    background: rgba(255, 255, 255, 18);
    border-radius: 4px;
}}
"""
        )


class _TabButton(QtWidgets.QAbstractButton):
    closeRequested = Signal()

    def __init__(self, route_key: str, text: str, icon: QtGui.QIcon) -> None:
        super().__init__()
        self.route_key = route_key
        self._icon = icon
        self.setText(text)
        self.setProperty("selected", False)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(36)
        self.setMinimumWidth(108)
        self.setMaximumWidth(200)
        self._hover = False

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(
            min(200, max(108, self.fontMetrics().horizontalAdvance(self.text()) + 68)), 36
        )

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        close_rect = QtCore.QRect(self.width() - 30, 6, 24, 24)
        if event.button() == QtCore.Qt.MouseButton.LeftButton and close_rect.contains(
            event.position().toPoint()
        ):
            self.closeRequested.emit()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        selected = bool(self.property("selected"))
        if selected or self._hover:
            bg = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "light" else "#ffffff")
            bg.setAlpha(
                180 if selected and theme.tokens.mode.value == "light" else 24 if selected else 14
            )
            painter.setBrush(bg)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 2.5, -0.5, -0.5), 5, 5)
        color = QtGui.QColor(theme.tokens.text)
        if not selected:
            color = QtGui.QColor(theme.tokens.text_muted)
        _draw_tinted_icon(painter, self._icon, QtCore.QRect(13, 10, 16, 16), color)
        painter.setPen(color)
        painter.drawText(
            QtCore.QRectF(36, 0, self.width() - 68, self.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        painter.setPen(
            QtGui.QPen(color, 1.4, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        x = self.width() - 18
        painter.drawLine(QtCore.QLineF(x - 4, 14, x + 4, 22))
        painter.drawLine(QtCore.QLineF(x + 4, 14, x - 4, 22))


def _draw_tinted_icon(
    painter: QtGui.QPainter,
    icon: QtGui.QIcon,
    rect: QtCore.QRect,
    color: QtGui.QColor,
) -> None:
    if icon.isNull():
        return
    pixmap = QtGui.QPixmap(rect.size())
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    icon_painter = QtGui.QPainter(pixmap)
    icon.paint(icon_painter, QtCore.QRect(QtCore.QPoint(0, 0), rect.size()))
    icon_painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    icon_painter.fillRect(pixmap.rect(), color)
    icon_painter.end()
    painter.drawPixmap(rect, pixmap)
