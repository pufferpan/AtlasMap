from __future__ import annotations

import weakref
from dataclasses import dataclass

from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from ..theme.fonts import ui_font
from .scroll_bar import FluentScrollBar


class NavigationItem(QtWidgets.QWidget):
    clicked = Signal(bool)
    changed = Signal()

    EXPAND_WIDTH = 312

    def __init__(
        self,
        icon: QtGui.QIcon,
        text: str = "",
        selectable: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self._selectable = selectable
        self._compacted = True
        self._selected = False
        self._about_selected = False
        self._pressed = False
        self._hover = False
        self.setFixedSize(40, 36)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        theme.subscribe(self, self.update)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.setToolTip(text)
        self.update()
        self.changed.emit()

    def setIcon(self, icon: QtGui.QIcon) -> None:
        if icon.cacheKey() == self._icon.cacheKey():
            return
        self._icon = icon
        self.update()
        self.changed.emit()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.EnabledChange:
            self.update()
            self.changed.emit()

    def setCompacted(self, compacted: bool) -> None:
        if compacted == self._compacted:
            return
        self._compacted = compacted
        self.setFixedSize(40, 36) if compacted else self.setFixedSize(self.EXPAND_WIDTH, 36)
        self.update()

    def setSelected(self, selected: bool) -> None:
        if not self._selectable:
            return
        self._selected = selected
        self._about_selected = False
        self.update()

    def setAboutSelected(self, selected: bool) -> None:
        self._about_selected = selected
        self.update()

    def indicatorRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0, 10, 3, 16)

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
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if was_pressed and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(True)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.TextAntialiasing
            | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        if self._pressed:
            painter.setOpacity(0.7)
        if not self.isEnabled():
            painter.setOpacity(0.4)

        base = 255 if tokens.mode.value == "dark" else 0
        if self._selected:
            painter.setBrush(QtGui.QColor(base, base, base, 6 if self._hover else 10))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()), 5, 5)
        elif (self._hover or self._about_selected) and self.isEnabled():
            painter.setBrush(QtGui.QColor(base, base, base, 6 if self._about_selected else 10))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()), 5, 5)

        icon_rect = QtCore.QRectF(11.5, 10, 16, 16)
        if self._icon.isNull():
            self._draw_menu_icon(painter, icon_rect)
        else:
            self._draw_tinted_icon(painter, icon_rect.toRect())

        if self._compacted:
            return

        font = QtGui.QFont("Microsoft YaHei UI")
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(tokens.text))
        painter.drawText(
            QtCore.QRectF(44, 0, self.width() - 57, self.height()),
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )

    def _draw_menu_icon(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        painter.save()
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(theme.tokens.text),
                1.55,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        for y in (rect.top() + 4, rect.center().y(), rect.bottom() - 3):
            painter.drawLine(QtCore.QLineF(rect.left() + 1, y, rect.right() - 1, y))
        painter.restore()

    def _draw_tinted_icon(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        pixmap = QtGui.QPixmap(rect.size())
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        icon_painter = QtGui.QPainter(pixmap)
        self._icon.paint(icon_painter, QtCore.QRect(QtCore.QPoint(0, 0), rect.size()))
        icon_painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        icon_painter.fillRect(pixmap.rect(), QtGui.QColor(theme.tokens.text))
        icon_painter.end()
        painter.drawPixmap(rect, pixmap)


class NavigationSeparator(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._compacted = True
        self.setFixedSize(48, 3)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        theme.subscribe(self, self.update)

    def setCompacted(self, compacted: bool) -> None:
        self._compacted = compacted
        self.setFixedSize(48 if compacted else NavigationItem.EXPAND_WIDTH + 10, 3)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        base = 255 if theme.tokens.mode.value == "dark" else 0
        painter.setPen(QtGui.QPen(QtGui.QColor(base, base, base, 15), 1))
        painter.drawLine(0, 1, self.width(), 1)


class NavigationReturnButton(NavigationItem):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(QtGui.QIcon(), "", selectable=False, parent=parent)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = QtGui.QColor(theme.tokens.text)
        painter.setPen(
            QtGui.QPen(color, 1.45, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        center_y = self.height() / 2
        painter.drawLine(QtCore.QLineF(24, center_y - 6, 17, center_y))
        painter.drawLine(QtCore.QLineF(17, center_y, 24, center_y + 6))
        painter.drawLine(QtCore.QLineF(18, center_y, 31, center_y))


class _NavigationIndicator(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        theme.subscribe(self, self.update)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(theme.tokens.accent))
        rect = QtCore.QRectF(self.rect()).adjusted(0, 0, -0.5, -0.5)
        painter.drawRoundedRect(rect, rect.width() / 2, rect.width() / 2)


class _SidebarSurface(QtWidgets.QWidget):
    """Paint structural scroll/fixed regions against one sidebar surface."""

    def __init__(self, sidebar, parent=None):
        super().__init__(parent)
        self._sidebar_ref = weakref.ref(sidebar)
        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        sidebar = self._sidebar_ref()
        if sidebar is not None:
            painter = QtGui.QPainter(self)
            sidebar._paint_sidebar_surface(painter, self)


class NavigationSidebar(QtWidgets.QFrame):
    currentChanged = Signal(int)
    expandedChanged = Signal(bool)
    filterChanged = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigationSidebar")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._expanded = False
        self._collapsed_width = 48
        self._expanded_width = 322
        self._items: list[NavigationItem] = []
        self._item_visibility: list[bool] = []
        self._widgets: list[QtWidgets.QWidget] = []
        self._current_index = -1
        self._filter_text = ""
        self._header_content = None
        self._footer_content = None
        self.setFixedWidth(self._collapsed_width)
        self._indicator = _NavigationIndicator(self)
        self._indicator.setGeometry(4, 15, 3, 16)
        self._indicator.hide()
        self._indicator_animation = QtCore.QPropertyAnimation(self._indicator, b"geometry", self)
        self._indicator_animation.setDuration(210)
        self._indicator_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        self._width_animation = QtCore.QPropertyAnimation(self, b"minimumWidth", self)
        self._width_animation.setDuration(150)
        self._width_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
        self._width_animation.valueChanged.connect(self._sync_width)

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 5, 0, 5)
        self._layout.setSpacing(4)

        self.header_widget = _SidebarSurface(self, self)
        self._header_layout = QtWidgets.QVBoxLayout(self.header_widget)
        self._header_layout.setContentsMargins(4, 0, 4, 0)
        self._header_layout.setSpacing(4)
        self._header_slot = _SidebarSurface(self, self.header_widget)
        self._header_slot_layout = QtWidgets.QVBoxLayout(self._header_slot)
        self._header_slot_layout.setContentsMargins(4, 0, 4, 4)
        self._header_slot.hide()

        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setObjectName("navigationScroll")
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setViewport(_SidebarSurface(self))
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(0)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBar(FluentScrollBar(parent=self.scroll_area))
        self.scroll_area.setHorizontalScrollBar(
            FluentScrollBar(QtCore.Qt.Orientation.Horizontal, self.scroll_area)
        )
        self.scroll_area.setStyleSheet(
            "QScrollArea#navigationScroll, QScrollArea#navigationScroll > QWidget { background: transparent; border: none; }"
        )
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_widget = _SidebarSurface(self)
        self.scroll_widget.setAutoFillBackground(False)
        self._top_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self._top_layout.setContentsMargins(4, 0, 4, 0)
        self._top_layout.setSpacing(4)
        self._top_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        # QScrollArea.setWidget() enables auto-fill on its child. Leave the
        # sidebar's themed surface visible instead of the OS Base palette.
        self.scroll_widget.setAutoFillBackground(False)
        self.scroll_widget.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._refresh_indicator)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._update_surface_regions)

        self.footer_widget = _SidebarSurface(self, self)
        self._bottom_layout = QtWidgets.QVBoxLayout(self.footer_widget)
        self._bottom_layout.setContentsMargins(4, 0, 4, 0)
        self._bottom_layout.setSpacing(4)
        self._footer_slot = _SidebarSurface(self, self.footer_widget)
        self._footer_slot_layout = QtWidgets.QVBoxLayout(self._footer_slot)
        self._footer_slot_layout.setContentsMargins(4, 0, 4, 4)
        self._footer_slot.hide()
        self._bottom_layout.addWidget(self._footer_slot)

        self._return = NavigationReturnButton(self)
        self._return.hide()

        self._toggle = NavigationItem(QtGui.QIcon(), "菜单", selectable=False, parent=self)
        self._toggle.clicked.connect(lambda _by_user=True: self.toggle())

        self._layout.addWidget(self.header_widget)
        self._layout.addWidget(self.scroll_area, 1)
        self._layout.addWidget(self.footer_widget)
        self._header_layout.addWidget(self._return, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._header_layout.addWidget(self._toggle, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._header_layout.addWidget(self._header_slot)
        self._widgets.extend([self._return, self._toggle])

        self._empty_label = QtWidgets.QLabel("没有匹配的项目", self.scroll_widget)
        self._empty_label.setWordWrap(True)
        self._empty_label.setContentsMargins(8, 8, 8, 8)
        self._empty_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self._empty_label.hide()
        self._top_layout.addWidget(self._empty_label)
        self._refresh_sidebar_theme()
        theme.subscribe(self, self._refresh_sidebar_theme)

        theme.subscribe(self, self.update)
        self._sync_widgets()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def add_item(self, icon: QtGui.QIcon, text: str) -> NavigationItem:
        return self._add_item(icon, text, self._top_layout)

    def add_footer_item(self, icon: QtGui.QIcon, text: str) -> NavigationItem:
        return self._add_item(icon, text, self._bottom_layout)

    def add_header_item(self, icon: QtGui.QIcon, text: str) -> NavigationItem:
        """Add a fixed entry above the independently scrolling middle list."""
        return self._add_item(icon, text, self._header_layout)

    def set_header_widget(self, widget: QtWidgets.QWidget | None) -> None:
        """Own an optional fixed header widget, hidden when the rail is compact."""
        self._set_custom_widget("header", widget)

    def set_footer_widget(self, widget: QtWidgets.QWidget | None) -> None:
        """Own an optional footer widget above the fixed footer entries."""
        self._set_custom_widget("footer", widget)

    def _set_custom_widget(self, zone, widget):
        if widget is not None and not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("widget must be a QWidget or None")
        internal = (
            self,
            self.header_widget,
            self.footer_widget,
            self.scroll_widget,
            self.scroll_area,
            self._header_slot,
            self._footer_slot,
            *self._widgets,
        )
        if widget is not None and (widget in internal or widget.isAncestorOf(self)):
            raise ValueError("custom content cannot be a structural sidebar widget or an ancestor")
        other = self._footer_content if zone == "header" else self._header_content
        if widget is not None and widget is other:
            raise ValueError("a widget can belong to only one custom zone")
        name = f"_{zone}_content"
        old = getattr(self, name)
        if old is widget:
            return
        slot = getattr(self, f"_{zone}_slot")
        layout = getattr(self, f"_{zone}_slot_layout")
        destroyed = (
            self._header_content_destroyed if zone == "header" else self._footer_content_destroyed
        )
        if old is not None:
            old.destroyed.disconnect(destroyed)
            layout.removeWidget(old)
            old.hide()
            old.deleteLater()
        setattr(self, name, widget)
        if widget is not None:
            layout.addWidget(widget)
            widget.destroyed.connect(destroyed)
            widget.show()
        slot.setVisible(widget is not None and self._expanded)
        self._layout.activate()
        self._refresh_indicator()

    def _header_content_destroyed(self):
        self._header_content = None
        self._header_slot.hide()

    def _footer_content_destroyed(self):
        self._footer_content = None
        self._footer_slot.hide()

    def filter_text(self) -> str:
        return self._filter_text

    def set_filter_text(self, text: str) -> None:
        """Filter middle entries without disabling routes or changing pages."""
        text = str(text)
        if text == self._filter_text:
            return
        self._filter_text = text
        self._apply_filter()
        self.filterChanged.emit(text)

    def _apply_filter(self):
        query = self._filter_text.strip().casefold()
        shown = 0
        for index, item in enumerate(self._items):
            middle = item.parentWidget() is self.scroll_widget
            display = self._item_visibility[index] and (
                not middle or query in item.text().casefold()
            )
            item.setVisible(display)
            shown += int(middle and display)
        for widget in self._widgets:
            if isinstance(widget, NavigationSeparator):
                widget.setVisible(not query)
        self._empty_label.setVisible(bool(query) and shown == 0 and self._expanded)
        self._top_layout.activate()
        self._refresh_indicator()

    def _refresh_sidebar_theme(self):
        self._empty_label.setFont(ui_font(theme.tokens.font_size - 1))
        self._empty_label.setStyleSheet(
            f"color: {theme.tokens.text_muted}; background: transparent;"
        )
        self._update_surface_regions()

    def _update_surface_regions(self, *_arguments):
        self.update()
        for surface in (
            self.header_widget,
            self._header_slot,
            self.scroll_area.viewport(),
            self.scroll_widget,
            self.footer_widget,
            self._footer_slot,
        ):
            surface.update()

    setHeaderWidget = set_header_widget
    setFooterWidget = set_footer_widget
    addHeaderItem = add_header_item
    setFilterText = set_filter_text

    def add_separator(self) -> None:
        separator = NavigationSeparator(self)
        self._top_layout.addWidget(separator, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._widgets.append(separator)
        separator.setCompacted(not self._expanded)
        self._sync_item_widths()

    def set_current_index(self, index: int, animated: bool = True) -> None:
        if not self.is_item_visible(index) or index == self._current_index:
            return
        previous_index = self._current_index
        self._current_index = index
        for item_index, item in enumerate(self._items):
            item.setSelected(item_index == index)
        current = self._items[index]
        if current.parentWidget() is self.scroll_widget and not current.isHidden():
            self.scroll_area.ensureWidgetVisible(current, 0, 4)
        self._move_indicator(index, animated=animated and previous_index >= 0)
        self.currentChanged.emit(index)

    def is_item_visible(self, index: int) -> bool:
        """Return configured visibility, including when the window is hidden."""
        return 0 <= index < len(self._items) and self._item_visibility[index]

    def set_item_visible(self, index: int, visible: bool) -> None:
        """Hide an entry without removing its page index or layout position."""
        if index < 0 or index >= len(self._items):
            return
        visible = bool(visible)
        if self._item_visibility[index] == visible:
            return
        self._item_visibility[index] = visible
        self._apply_filter()
        self._layout.invalidate()
        self._layout.activate()
        if not self.is_item_visible(self._current_index):
            replacement = next(
                (i for i, enabled in enumerate(self._item_visibility) if enabled), -1
            )
            if replacement >= 0:
                self.set_current_index(replacement, animated=False)
            else:
                self._current_index = -1
                for item in self._items:
                    item.setSelected(False)
                self.currentChanged.emit(-1)
        self._refresh_indicator()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded_width(self, width: int) -> None:
        """Set the expanded width without changing the default appearance."""
        if not isinstance(width, int) or width < 120:
            raise ValueError("Expanded navigation width must be at least 120 pixels")
        self._expanded_width = width
        if self._expanded:
            self._width_animation.stop()
            self._sync_width(width)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        start = self.width()
        end = self._expanded_width if expanded else self._collapsed_width
        self._width_animation.stop()
        self._width_animation.setStartValue(start)
        self._width_animation.setEndValue(end)
        if self.isVisible():
            self._width_animation.start()
        else:
            self._sync_width(end)
        self._sync_widgets()
        self.expandedChanged.emit(expanded)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        self._paint_sidebar_surface(painter, self)

    def _paint_sidebar_surface(self, painter, surface):
        tokens = theme.tokens
        window = self.window()
        paint_shell = getattr(window, "_paint_shell_surface", None)
        if callable(paint_shell):
            paint_shell(painter, surface)
            return
        resolver = getattr(window, "_resolved_background_color", None)
        base = (
            resolver()
            if callable(resolver)
            else window.palette().color(QtGui.QPalette.ColorRole.Window)
        )
        # Windows' scroll viewport may paint its explicit Window palette even
        # with auto-fill disabled and a transparent stylesheet. Paint each
        # structural region opaquely, using the same absolute sidebar gradient.
        painter.fillRect(surface.rect(), base)
        if surface is not self:
            position = surface.mapTo(self, QtCore.QPoint())
            painter.translate(-position.x(), -position.y())
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect())
        if tokens.mode.value == "light":
            color = QtGui.QColor(255, 255, 255, 180 if theme.active else 220)
        else:
            color = QtGui.QColor(32, 32, 32, 200 if theme.active else 230)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(rect)

        if self._expanded:
            tint = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if tokens.mode.value == "light":
                tint.setColorAt(0, QtGui.QColor(255, 255, 255, 185))
                tint.setColorAt(1, QtGui.QColor(240, 248, 251, 170))
            else:
                tint.setColorAt(0, QtGui.QColor(22, 24, 26, 214))
                tint.setColorAt(1, QtGui.QColor(16, 21, 25, 204))
            painter.setBrush(tint)
            painter.drawRect(rect)

        divider = (
            QtGui.QColor(0, 0, 0, 15)
            if tokens.mode.value == "light"
            else QtGui.QColor(255, 255, 255, 18)
        )
        painter.setPen(QtGui.QPen(divider, 1))
        painter.drawLine(QtCore.QLineF(rect.right() - 0.5, 0, rect.right() - 0.5, rect.bottom()))

    def _sync_shell_material(self):
        resolver = getattr(self.window(), "backdrop_applied", None)
        transparent = bool(resolver()) if callable(resolver) else False
        for surface in (
            self,
            self.header_widget,
            self._header_slot,
            self.scroll_area.viewport(),
            self.scroll_widget,
            self.footer_widget,
            self._footer_slot,
        ):
            surface.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, not transparent)
            surface.setAutoFillBackground(False)
            surface.update()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_indicator"):
            self._sync_item_widths()
            self._refresh_indicator()
            self._update_surface_regions()

    def event(self, event: QtCore.QEvent) -> bool:
        result = super().event(event)
        if event.type() == QtCore.QEvent.Type.LayoutRequest and hasattr(self, "_indicator"):
            self._refresh_indicator()
        return result

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.LayoutRequest):
            if hasattr(self, "scroll_widget") and obj in (
                self.scroll_widget,
                self.scroll_area.viewport(),
            ):
                self._sync_item_widths()
                self._refresh_indicator()
        return super().eventFilter(obj, event)

    def _add_item(
        self,
        icon: QtGui.QIcon,
        text: str,
        layout: QtWidgets.QVBoxLayout,
    ) -> NavigationItem:
        item = NavigationItem(icon, text, parent=self)
        item.setCompacted(not self._expanded)
        item.clicked.connect(lambda _by_user=True, entry=item: self._select_item(entry))
        self._items.append(item)
        self._item_visibility.append(True)
        self._widgets.append(item)
        layout.addWidget(item, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._apply_filter()
        self._sync_item_widths()
        if self._current_index == -1:
            self.set_current_index(len(self._items) - 1)
        return item

    def _select_item(self, item: NavigationItem) -> None:
        if item in self._items:
            self.set_current_index(self._items.index(item))

    def _remove_item(self, index: int) -> NavigationItem:
        """Remove a row while preserving the remaining rows' identities."""
        self._indicator_animation.stop()
        previous = (
            self._items[self._current_index] if self.is_item_visible(self._current_index) else None
        )
        item = self._items.pop(index)
        self._item_visibility.pop(index)
        self._widgets.remove(item)
        parent_layout = item.parentWidget().layout()
        if parent_layout is not None:
            parent_layout.removeWidget(item)
        item.hide()
        item.setParent(None)
        self._current_index = -1
        if previous in self._items:
            selected = self._items.index(previous)
        else:
            selected = next((i for i in range(len(self._items)) if self.is_item_visible(i)), -1)
        for entry in self._items:
            entry.setSelected(False)
        if selected >= 0:
            self.set_current_index(selected, animated=False)
        else:
            self._indicator.hide()
        self._apply_filter()
        self._sync_item_widths()
        return item

    def _indicator_target(self, index: int) -> QtCore.QRect:
        item = self._items[index]
        pos = item.mapTo(self, QtCore.QPoint(0, 0))
        return QtCore.QRect(pos.x(), pos.y() + 10, 3, 16)

    def _move_indicator(self, index: int, animated: bool) -> None:
        if not self._indicator_visible(index):
            self._indicator_animation.stop()
            self._indicator.hide()
            return
        target = self._indicator_target(index)
        self._indicator.show()
        self._indicator.raise_()
        if not animated:
            self._indicator_animation.stop()
            self._indicator.setGeometry(target)
            return
        self._indicator_animation.stop()
        self._indicator_animation.setDuration(210)
        self._indicator_animation.setStartValue(self._indicator.geometry())
        self._indicator_animation.setEndValue(target)
        self._indicator_animation.start()

    def _sync_width(self, value: object) -> None:
        width = int(value)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self._sync_item_widths()

    def _sync_item_widths(self) -> None:
        # Each row follows the current animated width, including both margins.
        width = max(40, self.width() - 8)
        # In a compact rail a 16px scrollbar would consume the icon's hit area.
        # QScrollArea continues to process wheel scrolling with its bar hidden.
        policy = (
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self._expanded and self.width() >= 64
            else QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if self.scroll_area.verticalScrollBarPolicy() != policy:
            self.scroll_area.setVerticalScrollBarPolicy(policy)
        for widget in self._widgets:
            row_width = (
                max(1, self.scroll_area.viewport().width() - 8)
                if widget.parentWidget() is self.scroll_widget
                else width
            )
            if widget.width() != row_width:
                widget.setFixedWidth(row_width)

    def _sync_widgets(self) -> None:
        compacted = not self._expanded
        for widget in self._widgets:
            if hasattr(widget, "setCompacted"):
                widget.setCompacted(compacted)  # type: ignore[attr-defined]
        for zone in ("header", "footer"):
            getattr(self, f"_{zone}_slot").setVisible(
                self._expanded and getattr(self, f"_{zone}_content") is not None
            )
        self._empty_label.setVisible(
            self._expanded
            and bool(self._filter_text.strip())
            and not any(
                not item.isHidden()
                for item in self._items
                if item.parentWidget() is self.scroll_widget
            )
        )
        self._sync_item_widths()
        self._refresh_indicator()

    def _indicator_visible(self, index):
        if not self.is_item_visible(index) or self._items[index].isHidden():
            return False
        if self._items[index].parentWidget() is self.scroll_widget:
            viewport = self.scroll_area.viewport()
            visible = QtCore.QRect(viewport.mapTo(self, QtCore.QPoint()), viewport.size())
            return visible.contains(self._indicator_target(index))
        return True

    def _refresh_indicator(self) -> None:
        animation = self._indicator_animation
        if not self._indicator_visible(self._current_index):
            animation.stop()
            self._indicator.hide()
            return
        target = self._indicator_target(self._current_index)
        self._indicator.show()
        self._indicator.raise_()
        if animation.state() != QtCore.QAbstractAnimation.State.Running:
            self._indicator.setGeometry(target)
        elif animation.endValue() != target:
            # Layout requests during expansion must not finish the selection
            # transition. A moving footer only updates its remaining endpoint.
            remaining = max(1, animation.duration() - animation.currentTime())
            start = self._indicator.geometry()
            animation.stop()
            animation.setDuration(remaining)
            animation.setStartValue(start)
            animation.setEndValue(target)
            animation.start()


class AnimatedStackedWidget(QtWidgets.QStackedWidget):
    """Fade and slide pages without retaining interrupted transition state.

    Page-owned opacity effects are reused and restored. Other page-owned
    graphics effects are preserved; those pages use the slide animation alone.
    Effects belonging to children (for example card shadows) are untouched.
    """

    currentAboutToChange = Signal(int, int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 180
        self._animation: QtCore.QAbstractAnimation | None = None
        self._transition_widget: QtWidgets.QWidget | None = None
        self._transition_effect: QtWidgets.QGraphicsOpacityEffect | None = None
        self._transition_owns_effect = False
        self._transition_opacity = 1.0
        self._transition_origin = QtCore.QPoint()
        self._transition_destroy_connection = None
        self._transition_serial = 0
        self.setObjectName("animatedStackedWidget")
        self.currentChanged.connect(self._stack_index_changed)
        self.widgetRemoved.connect(self._stack_widget_removed)

    def setAnimationDuration(self, duration_ms: int) -> None:
        self._duration = max(0, duration_ms)
        if self._duration == 0:
            self._clear_transition()

    def setCurrentIndex(self, index: int) -> None:
        self.setCurrentIndexAnimated(index)

    def setCurrentWidget(self, widget: QtWidgets.QWidget) -> None:
        self.setCurrentIndexAnimated(self.indexOf(widget))

    def setCurrentIndexAnimated(self, index: int) -> None:
        if index < 0 or index >= self.count() or index == self.currentIndex():
            return
        self._clear_transition()
        old_index = self.currentIndex()
        old_widget = self.currentWidget()
        new_widget = self.widget(index)
        serial = self._transition_serial
        self.currentAboutToChange.emit(old_index, index)
        # A signal handler is allowed to navigate again or remove the page.
        if serial != self._transition_serial or self.widget(index) is not new_widget:
            return

        if self._duration <= 0 or old_widget is None:
            QtWidgets.QStackedWidget.setCurrentIndex(self, index)
            return

        direction = 1 if index > old_index else -1
        offset = 22 * direction
        existing_effect = new_widget.graphicsEffect()
        effect = None
        if existing_effect is None:
            effect = QtWidgets.QGraphicsOpacityEffect(new_widget)
            self._transition_owns_effect = True
            self._transition_opacity = 1.0
            new_widget.setGraphicsEffect(effect)
        elif isinstance(existing_effect, QtWidgets.QGraphicsOpacityEffect):
            effect = existing_effect
            self._transition_opacity = effect.opacity()
        self._transition_widget = new_widget
        self._transition_effect = effect
        self._transition_origin = self.contentsRect().topLeft()
        self._transition_destroy_connection = new_widget.destroyed.connect(
            self._transition_page_destroyed
        )
        if effect is not None:
            effect.setOpacity(0.0)
        QtWidgets.QStackedWidget.setCurrentIndex(self, index)
        if serial != self._transition_serial or self.currentWidget() is not new_widget:
            return
        # QStackedLayout establishes the canonical page geometry on selection.
        # A hidden page's old pos() may still be an interrupted animation frame.
        end_pos = new_widget.pos()
        self._transition_origin = QtCore.QPoint(end_pos)
        start_pos = end_pos + QtCore.QPoint(offset, 0)
        new_widget.move(start_pos)

        slide = QtCore.QPropertyAnimation(new_widget, b"pos", self)
        slide.setStartValue(start_pos)
        slide.setEndValue(end_pos)
        slide.setDuration(self._duration)
        slide.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        group = QtCore.QParallelAnimationGroup(self)
        if effect is not None:
            opacity = QtCore.QPropertyAnimation(effect, b"opacity", group)
            opacity.setStartValue(0.0)
            opacity.setEndValue(self._transition_opacity)
            opacity.setDuration(self._duration)
            opacity.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            group.addAnimation(opacity)
        group.addAnimation(slide)
        group.finished.connect(self._finish_transition)
        self._animation = group
        group.start()

    def removeWidget(self, widget: QtWidgets.QWidget) -> None:
        if widget is self._transition_widget:
            self._clear_transition()
        super().removeWidget(widget)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        # A new layout geometry supersedes the in-flight position endpoints.
        if hasattr(self, "_animation"):
            self._clear_transition()
        super().resizeEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        if hasattr(self, "_animation"):
            self._clear_transition()
        super().hideEvent(event)

    def _stack_index_changed(self, _index: int) -> None:
        # NavigationView also supports direct, nonanimated Qt base calls.
        if (
            self._transition_widget is not None
            and self.currentWidget() is not self._transition_widget
        ):
            self._clear_transition()

    def _stack_widget_removed(self, _index: int) -> None:
        widget = self._transition_widget
        # Compare identities without dereferencing a page whose C++ destructor
        # may have caused QStackedLayout to emit widgetRemoved already.
        if widget is not None and not any(self.widget(i) is widget for i in range(self.count())):
            self._clear_transition()

    def _transition_page_destroyed(self, *_arguments) -> None:
        self._transition_widget = None
        self._transition_effect = None
        self._clear_transition()

    def _finish_transition(self) -> None:
        self._clear_transition()

    def _clear_transition(self) -> None:
        animation = self._animation
        widget = self._transition_widget
        effect = self._transition_effect
        owns_effect = self._transition_owns_effect
        opacity = self._transition_opacity
        origin = self._transition_origin
        connection = self._transition_destroy_connection
        self._transition_serial += 1
        self._animation = None
        self._transition_widget = None
        self._transition_effect = None
        self._transition_owns_effect = False
        self._transition_destroy_connection = None
        if connection is not None:
            QtCore.QObject.disconnect(connection)
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        if widget is not None:
            try:
                if effect is not None and widget.graphicsEffect() is effect:
                    if owns_effect:
                        widget.setGraphicsEffect(None)
                    else:
                        effect.setOpacity(opacity)
                if widget is self.currentWidget():
                    self.layout().setGeometry(self.contentsRect())
                else:
                    widget.move(origin)
            except RuntimeError:
                # A direct page.deleteLater() may remove its C++ QWidget before
                # the stack's removal signal arrives. No page/effect is retained.
                pass


@dataclass(frozen=True)
class NavigationPage:
    route_key: str
    widget: QtWidgets.QWidget
    item: NavigationItem


class _NavigationPageLink(QtCore.QObject):
    """A Qt-owned receiver keeps page destruction independent of wrappers."""

    def __init__(self, owner: "NavigationView", route_key: str) -> None:
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)
        self.route_key = route_key
        self.connection = None
        self.item_connection = None
        owner.destroyed.connect(self.owner_destroyed)

    @Slot()
    def owner_destroyed(self) -> None:
        self._owner_ref = lambda: None

    @Slot()
    def page_destroyed(self) -> None:
        owner = self._owner_ref()
        if owner is not None:
            # QStackedLayout removes its widget after QObject.destroyed. Wait
            # for widgetRemoved before publishing the coherent route snapshot.
            owner._destroyed_routes.add(self.route_key)


class NavigationView(QtWidgets.QWidget):
    currentChanged = Signal(str)
    routesChanged = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.sidebar = NavigationSidebar(self)
        self.stack = AnimatedStackedWidget(self)
        self._pages: list[NavigationPage] = []
        self._routes: dict[str, NavigationPage] = {}
        self._page_links: dict[str, _NavigationPageLink] = {}
        self._destroyed_routes: set[str] = set()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.sidebar.currentChanged.connect(self._on_sidebar_current_changed)
        self.stack.widgetRemoved.connect(self._on_stack_widget_removed)

    def add_sub_interface(
        self,
        widget: QtWidgets.QWidget,
        icon: QtGui.QIcon,
        text: str,
        route_key: str | None = None,
        position: str = "top",
    ) -> NavigationItem:
        if not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("widget must be a QWidget")
        if self.route_for_widget(widget) is not None:
            raise ValueError("A widget can belong to only one navigation route")
        if widget in (self, self.sidebar, self.stack) or widget.isAncestorOf(self):
            raise ValueError("A structural widget or ancestor cannot be a navigation page")
        key = route_key or widget.objectName() or self._make_route_key(text)
        if key in self._routes:
            raise ValueError(f"Navigation route already exists: {key}")
        if position not in {"top", "scroll", "header", "bottom"}:
            raise ValueError("position must be top, scroll, header or bottom")

        previous_route = self.current_route()
        widget.setObjectName(key)
        add_item = {
            "header": self.sidebar.add_header_item,
            "bottom": self.sidebar.add_footer_item,
        }.get(position, self.sidebar.add_item)
        blocker = QtCore.QSignalBlocker(self.sidebar)
        item = add_item(icon, text)
        page = NavigationPage(key, widget, item)
        self._pages.append(page)
        self._routes[key] = page
        link = _NavigationPageLink(self, key)
        link.connection = widget.destroyed.connect(link.page_destroyed)
        self._page_links[key] = link
        self.stack.addWidget(widget)
        if len(self._pages) == 1:
            self.sidebar.set_current_index(0)
            QtWidgets.QStackedWidget.setCurrentIndex(self.stack, 0)
        elif not previous_route:
            self.sidebar.set_current_index(len(self._pages) - 1, animated=False)
            QtWidgets.QStackedWidget.setCurrentWidget(self.stack, widget)
        self.stack.show()
        del blocker
        link.item_connection = item.changed.connect(self.routesChanged)
        self.routesChanged.emit()
        current_route = self.current_route()
        if previous_route != current_route:
            self.currentChanged.emit(current_route)
        return item

    def pages(self) -> tuple[NavigationPage, ...]:
        """Return an ordered snapshot of the registered page objects."""
        return tuple(self._pages)

    def widget_for_route(self, route_key: str) -> QtWidgets.QWidget | None:
        page = self._routes.get(route_key)
        return page.widget if page is not None else None

    def route_for_widget(self, widget: QtWidgets.QWidget) -> str | None:
        return next((page.route_key for page in self._pages if page.widget is widget), None)

    def remove_page(self, route_key: str, delete: bool = False) -> QtWidgets.QWidget | None:
        """Detach a page, optionally scheduling its deletion, without reordering survivors."""
        return self._remove_page(route_key, delete=delete)

    remove_sub_interface = remove_page
    removeSubInterface = remove_page

    def _remove_page(
        self,
        route_key: str,
        *,
        delete: bool = False,
        stack_removed: bool = False,
        destroyed: bool = False,
    ) -> QtWidgets.QWidget | None:
        page = self._routes.get(route_key)
        if page is None:
            return None
        selected = self.sidebar._current_index
        previous_route = (
            self._pages[selected].route_key
            if 0 <= selected < len(self._pages) and self.sidebar.is_item_visible(selected)
            else ""
        )
        index = self._pages.index(page)
        self._pages.pop(index)
        self._routes.pop(route_key)
        self._destroyed_routes.discard(route_key)
        link = self._page_links.pop(route_key)
        link._owner_ref = lambda: None
        if link.connection is not None and not destroyed:
            QtCore.QObject.disconnect(link.connection)
        if link.item_connection is not None:
            QtCore.QObject.disconnect(link.item_connection)
        link.deleteLater()
        blocker = QtCore.QSignalBlocker(self.sidebar)
        item = self.sidebar._remove_item(index)
        item.deleteLater()
        if not stack_removed:
            self.stack.removeWidget(page.widget)
            page.widget.hide()
            page.widget.setParent(None)
        selected = self.sidebar._current_index
        if selected >= 0:
            QtWidgets.QStackedWidget.setCurrentWidget(self.stack, self._pages[selected].widget)
            self.stack.show()
        else:
            self.stack.hide()
        del blocker
        current_route = self.current_route()
        self.routesChanged.emit()
        if previous_route != current_route:
            self.currentChanged.emit(current_route)
        if delete and not destroyed:
            page.widget.deleteLater()
        return None if destroyed else page.widget

    @Slot(int)
    def _on_stack_widget_removed(self, _index: int) -> None:
        present = tuple(self.stack.widget(i) for i in range(self.stack.count()))
        for page in tuple(self._pages):
            if not any(page.widget is widget for widget in present):
                self._remove_page(
                    page.route_key,
                    stack_removed=True,
                    destroyed=page.route_key in self._destroyed_routes,
                )

    def addSubInterface(
        self,
        widget: QtWidgets.QWidget,
        icon: QtGui.QIcon,
        text: str,
        routeKey: str | None = None,
        position: str = "top",
    ) -> NavigationItem:
        return self.add_sub_interface(widget, icon, text, routeKey, position)

    def add_separator(self) -> None:
        self.sidebar.add_separator()

    def set_current_route(self, route_key: str, animated: bool = True) -> None:
        page = self._routes.get(route_key)
        if not page or not self.is_route_visible(route_key):
            return
        self.stack.show()
        index = self._pages.index(page)
        if self.stack.currentIndex() == index:
            self.sidebar.set_current_index(index, animated=False)
            return
        if animated:
            self.sidebar.set_current_index(index)
            return

        was_blocked = self.sidebar.blockSignals(True)
        self.sidebar.set_current_index(index, animated=False)
        self.sidebar.blockSignals(was_blocked)
        QtWidgets.QStackedWidget.setCurrentIndex(self.stack, index)
        self.currentChanged.emit(route_key)

    def setCurrentRoute(self, routeKey: str, animated: bool = True) -> None:
        self.set_current_route(routeKey, animated)

    def current_route(self) -> str:
        route = self.route_for_widget(self.stack.currentWidget())
        return route if route is not None and self.is_route_visible(route) else ""

    def is_route_visible(self, route_key: str) -> bool:
        """Report route availability independently of window visibility."""
        page = self._routes.get(route_key)
        return page is not None and self.sidebar.is_item_visible(self._pages.index(page))

    def set_route_visible(self, route_key: str, visible: bool) -> None:
        """Show or hide a route, preserving its widget and navigation order.

        Hiding the active route selects the first available route. If none
        remain, the content area is hidden until a route becomes available.
        Unknown routes are ignored, matching :meth:`set_current_route`.
        """
        page = self._routes.get(route_key)
        if page is not None and self.is_route_visible(route_key) != bool(visible):
            self.sidebar.set_item_visible(self._pages.index(page), visible)
            self.routesChanged.emit()

    def setRouteVisible(self, routeKey: str, visible: bool) -> None:
        self.set_route_visible(routeKey, visible)

    def isRouteVisible(self, routeKey: str) -> bool:
        return self.is_route_visible(routeKey)

    def _on_sidebar_current_changed(self, index: int) -> None:
        if index == -1:
            self.stack.hide()
            self.currentChanged.emit("")
            return
        if index < 0 or index >= len(self._pages):
            return
        if not self.sidebar.is_item_visible(index):
            return
        self.stack.show()
        self.stack.setCurrentIndexAnimated(index)
        self.currentChanged.emit(self._pages[index].route_key)

    def _make_route_key(self, text: str) -> str:
        base = "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_") or "page"
        key = base
        suffix = 2
        while key in self._routes:
            key = f"{base}_{suffix}"
            suffix += 1
        return key
