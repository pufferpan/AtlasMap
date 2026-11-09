from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import weakref

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import ThemeMode, theme
from ..theme.fonts import ui_font
from ..window_effects import apply_integrated_window_frame, apply_system_backdrop


class _NavigationShell(QtWidgets.QWidget):
    def paintEvent(self, event):
        paint = getattr(self.window(), "_paint_shell_surface", None)
        if callable(paint):
            painter = QtGui.QPainter(self)
            paint(painter, self)
        else:
            super().paintEvent(event)


class _ContentCornerClipper(QtCore.QObject):
    """Clip only a child page stack; the native window keeps its system frame."""

    def __init__(self, stack):
        super().__init__(stack)
        self._stack_ref = weakref.ref(stack)
        stack.installEventFilter(self)
        self._fit()

    def _fit(self):
        stack = self._stack_ref()
        if stack is None or stack.width() <= 0 or stack.height() <= 0:
            return
        width, height = stack.width(), stack.height()
        radius = min(10.0, width / 2, height / 2)
        path = QtGui.QPainterPath()
        path.moveTo(0, height)
        path.lineTo(0, radius)
        path.arcTo(0, 0, radius * 2, radius * 2, 180, -90)
        path.lineTo(width, 0)
        path.lineTo(width, height)
        path.closeSubpath()
        stack.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    def eventFilter(self, watched, event):
        if self.__dict__.get("_stack_ref") is not None and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
        ):
            self._fit()
        return False


class FluentWindow(QtWidgets.QMainWindow):
    """A normal Qt main window with optional navigation and custom chrome.

    A simple window keeps its original ``content_layout``. Registering a page
    adds a NavigationView to that same layout; it never replaces user content.
    Native window chrome remains the default. All page switches share one
    route selection and history, including switches made from the sidebar.
    """

    currentChanged = Signal(str)
    historyChanged = Signal()
    backdropChanged = Signal(bool)

    def __init__(self, title: str = "FluentPy", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setWindowTitle(title)
        self.resize(980, 640)
        self._active = True
        self._navigation_view = None
        self._navigation_shell = None
        self._top_navigation = None
        self._top_scroll = None
        self._navigation_mode = "auto"
        self._navigation_width = 220
        self._navigation_breakpoint = 880
        self._last_auto_expanded = None
        self._route_history: list[str] = []
        self._history_index = -1
        self._history_switch = False
        self._title_bar = None
        self._title_bar_enabled = False
        self._native_caption = False
        self._integrated_windows_frame = False
        self._background_colors = None
        self._backdrop_enabled = False
        self._backdrop_applied = False
        self._backdrop_snapshot_depth = 0
        self._backdrop_refresh = QtCore.QTimer(self)
        self._backdrop_refresh.setSingleShot(True)
        self._backdrop_refresh.timeout.connect(self._apply_backdrop)
        self._root = QtWidgets.QWidget()
        self._root.setObjectName("fluentRoot")
        self._root.setAutoFillBackground(True)
        self._layout = QtWidgets.QVBoxLayout(self._root)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(16)
        self.setCentralWidget(self._root)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)
        from ..theme.transition import WindowThemeTransition

        self._theme_transition = WindowThemeTransition(self, theme)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._apply_theme()
        self._sync_navigation_mode()
        self._sync_native_caption_area()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_navigation_view"):
            self._sync_navigation_mode()
        if hasattr(self, "_title_bar_enabled"):
            self._sync_native_caption_area()

    def paintEvent(self, event):
        if self._backdrop_applied:
            painter = QtGui.QPainter(self)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
            color = (
                self._resolved_shell_color()
                if self._backdrop_snapshot_depth
                else QtGui.QColor("transparent")
            )
            painter.fillRect(self.rect(), color)
            return
        super().paintEvent(event)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.ActivationChange:
            self._active = self.isActiveWindow()
            theme.set_active(self._active)
            self._apply_backdrop()
        if event.type() == QtCore.QEvent.Type.WindowStateChange and hasattr(
            self, "_native_caption"
        ):
            self._sync_native_caption_area()
            if self._native_windows_platform():
                self._apply_backdrop()
        super().changeEvent(event)

    @property
    def content_layout(self) -> QtWidgets.QVBoxLayout:
        return self._layout

    def set_dark(self, enabled: bool) -> None:
        theme.set_mode(ThemeMode.DARK if enabled else ThemeMode.LIGHT)

    def set_theme_transition_enabled(self, enabled: bool) -> None:
        """Blend the complete Qt window when switching light/dark themes."""
        self._theme_transition.set_enabled(enabled)

    def is_theme_transition_enabled(self) -> bool:
        return self._theme_transition.enabled

    def navigation_view(self):
        """Create and return the window's optional NavigationView."""
        if self._navigation_view is None:
            from .navigation import NavigationView

            self._navigation_shell = _NavigationShell(self._root)
            self._navigation_shell.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
            layout = QtWidgets.QVBoxLayout(self._navigation_shell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self._top_scroll = QtWidgets.QScrollArea(self._navigation_shell)
            self._top_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self._top_scroll.setWidgetResizable(True)
            self._top_scroll.setFixedHeight(54)
            self._top_scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._top_scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            from .scroll_bar import FluentScrollBar

            self._top_scroll.setHorizontalScrollBar(
                FluentScrollBar(QtCore.Qt.Orientation.Horizontal, self._top_scroll)
            )
            self._top_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            self._top_scroll.viewport().setAutoFillBackground(False)
            self._top_scroll.hide()
            layout.addWidget(self._top_scroll)
            self._navigation_view = NavigationView(self._navigation_shell)
            self._navigation_view.sidebar.set_expanded_width(self._navigation_width)
            layout.addWidget(self._navigation_view, 1)
            self._layout.addWidget(self._navigation_shell, 1)
            self._navigation_view.currentChanged.connect(self._on_route_changed)
            self._navigation_view.routesChanged.connect(self._on_routes_changed)
            # Navigation can be added after a visible window has already
            # enabled Mica. Its freshly constructed surfaces must inherit
            # the accepted material state immediately.
            self._navigation_view.sidebar._sync_shell_material()
            self._navigation_view.stack.setPalette(self._theme_palette)
            self._navigation_view.stack.setAutoFillBackground(True)
            self._content_corner_clipper = _ContentCornerClipper(self._navigation_view.stack)
            self._sync_navigation_mode()
        return self._navigation_view

    def add_page(
        self,
        widget: QtWidgets.QWidget,
        text: str,
        icon: QtGui.QIcon | None = None,
        route: str | None = None,
        position: str = "scroll",
    ):
        if not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("page must be a QWidget")
        if widget is self or widget is self._root or widget.isAncestorOf(self):
            raise ValueError("a window or its ancestor cannot be a page")
        return self.navigation_view().add_sub_interface(
            widget, icon or QtGui.QIcon(), text, route, position
        )

    def add_sub_interface(self, widget, icon, text, route_key=None, position="scroll"):
        return self.add_page(widget, text, icon, route_key, position)

    def addSubInterface(self, widget, icon, text, routeKey=None, position="scroll"):
        return self.add_sub_interface(widget, icon, text, routeKey, position)

    def remove_page(self, route: str, *, delete: bool = False):
        if self._navigation_view is None:
            return None
        return self._navigation_view.remove_page(route, delete=delete)

    def current_route(self) -> str:
        return self._navigation_view.current_route() if self._navigation_view is not None else ""

    def current_page(self):
        if self._navigation_view is None or not self.current_route():
            return None
        return self._navigation_view.widget_for_route(self.current_route())

    def switch_to(self, widget_or_route, animated: bool = True) -> bool:
        if self._navigation_view is None:
            return False
        key = (
            self._navigation_view.route_for_widget(widget_or_route)
            if isinstance(widget_or_route, QtWidgets.QWidget)
            else str(widget_or_route)
        )
        if not key or not self._navigation_view.is_route_visible(key):
            return False
        self._navigation_view.set_current_route(key, animated)
        return self.current_route() == key

    switchTo = switch_to

    def _on_route_changed(self, route: str) -> None:
        if route and not self._history_switch:
            if self._history_index < 0 or self._route_history[self._history_index] != route:
                del self._route_history[self._history_index + 1 :]
                self._route_history.append(route)
                self._history_index = len(self._route_history) - 1
        if self._top_navigation is not None:
            blocked = self._top_navigation.blockSignals(True)
            self._top_navigation.set_current_item(route, animated=self.isVisible())
            self._top_navigation.blockSignals(blocked)
        self._sync_history()
        self.currentChanged.emit(route)

    def _on_routes_changed(self) -> None:
        # Route deletion/hiding must not leave dead entries in the history.
        current = self.current_route()
        before = self._route_history[: self._history_index + 1]
        after = self._route_history[self._history_index + 1 :]
        available = self._navigation_view.is_route_visible
        before = [key for key in before if available(key)]
        after = [key for key in after if available(key)]
        self._route_history = before + after
        self._history_index = len(before) - 1
        if current and (
            self._history_index < 0 or self._route_history[self._history_index] != current
        ):
            self._route_history = before + [current]
            self._history_index = len(before)
        self._rebuild_top_navigation()
        self._sync_history()

    def _history_target(self, direction: int) -> int:
        index = self._history_index + direction
        while 0 <= index < len(self._route_history):
            if (
                self._route_history[index] != self.current_route()
                and self._navigation_view is not None
                and self._navigation_view.is_route_visible(self._route_history[index])
            ):
                return index
            index += direction
        return -1

    def can_go_back(self) -> bool:
        return self._history_target(-1) >= 0

    def can_go_forward(self) -> bool:
        return self._history_target(1) >= 0

    def _move_history(self, direction: int) -> bool:
        index = self._history_target(direction)
        if index < 0:
            return False
        previous = self._history_index
        self._history_index = index
        self._history_switch = True
        try:
            if not self.switch_to(self._route_history[index]):
                self._history_index = previous
                return False
        finally:
            self._history_switch = False
        self._sync_history()
        return True

    def go_back(self) -> bool:
        return self._move_history(-1)

    def go_forward(self) -> bool:
        return self._move_history(1)

    def _sync_history(self) -> None:
        if self._title_bar is not None and hasattr(self._title_bar, "sync_navigation"):
            self._title_bar.sync_navigation()
        self.historyChanged.emit()

    def set_navigation_mode(self, mode: str) -> None:
        if mode not in {"auto", "expanded", "compact", "top"}:
            raise ValueError("mode must be auto, expanded, compact or top")
        self._navigation_mode = mode
        self._last_auto_expanded = None
        self._sync_navigation_mode()

    def navigation_mode(self) -> str:
        return self._navigation_mode

    def set_navigation_width(self, width: int) -> None:
        if not isinstance(width, int) or width < 120:
            raise ValueError("navigation width must be at least 120 pixels")
        self._navigation_width = width
        if self._navigation_view is not None:
            self._navigation_view.sidebar.set_expanded_width(width)

    def set_navigation_breakpoint(self, width: int) -> None:
        if not isinstance(width, int) or width < 320:
            raise ValueError("navigation breakpoint must be at least 320 pixels")
        self._navigation_breakpoint = width
        self._last_auto_expanded = None
        self._sync_navigation_mode()

    def _sync_navigation_mode(self) -> None:
        if self._navigation_view is None:
            return
        top = self._navigation_mode == "top"
        self._top_scroll.setVisible(top)
        self._navigation_view.sidebar.setVisible(not top)
        if top:
            if self._top_navigation is None:
                self._rebuild_top_navigation()
            return
        expanded = (
            self.width() >= self._navigation_breakpoint
            if self._navigation_mode == "auto"
            else self._navigation_mode == "expanded"
        )
        if self._navigation_mode != "auto" or expanded != self._last_auto_expanded:
            self._navigation_view.sidebar.set_expanded(expanded)
            self._last_auto_expanded = expanded

    def _rebuild_top_navigation(self) -> None:
        if self._navigation_view is None:
            return
        from .navigation_controls import Pivot

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(16, 0, 16, 0)
        pivot = Pivot(container)
        for page in self._navigation_view.pages():
            if self._navigation_view.is_route_visible(page.route_key):
                pivot.add_item(page.route_key, page.item.text())
                pivot.set_item_enabled(page.route_key, page.item.isEnabled())
        pivot.set_current_item(self.current_route(), animated=False)
        pivot.currentChanged.connect(self.switch_to)
        layout.addWidget(pivot)
        layout.addStretch(1)
        container.setMinimumWidth(layout.sizeHint().width())
        self._top_navigation = pivot
        # QScrollArea takes ownership and disposes its previous widget.
        self._top_scroll.setWidget(container)
        container.setAutoFillBackground(False)

    def title_bar(self):
        return self._title_bar

    def set_title_bar(self, widget: QtWidgets.QWidget) -> None:
        if not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("title bar must be a QWidget")
        if widget is self or widget is self._root or widget.isAncestorOf(self):
            raise ValueError("title bar cannot be the window or an ancestor")
        if widget is not self._title_bar:
            if self._title_bar is not None:
                self._title_bar.destroyed.disconnect(self._title_bar_destroyed)
            self._title_bar = widget
            widget.destroyed.connect(self._title_bar_destroyed)
            self.setMenuWidget(widget)
        self.set_title_bar_enabled(True)
        self._sync_history()

    def set_title_bar_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._title_bar_enabled and (not enabled or self._title_bar is not None):
            return
        if enabled and self._title_bar is None:
            from .title_bar import FluentTitleBar

            self._title_bar = FluentTitleBar(self)
            self._title_bar.destroyed.connect(self._title_bar_destroyed)
            self.setMenuWidget(self._title_bar)
        visible, geometry, state = self.isVisible(), self.geometry(), self.windowState()
        self._title_bar_enabled = enabled
        self._native_caption = False
        self._integrated_windows_frame = enabled and self._native_windows_platform()
        flags = self.windowFlags()
        frameless = QtCore.Qt.WindowType.FramelessWindowHint
        flags = QtCore.Qt.WindowType(
            int(flags) | int(frameless) if enabled else int(flags) & ~int(frameless)
        )
        self.setWindowFlags(flags)
        if self._title_bar is not None:
            self._title_bar.setVisible(enabled)
            if hasattr(self._title_bar, "_set_native_caption"):
                self._title_bar._set_native_caption(self._native_caption)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            if enabled and not self._native_caption:
                application.installEventFilter(self)
                self.setMouseTracking(True)
            else:
                application.removeEventFilter(self)
                self.unsetCursor()
        self.setGeometry(geometry)
        self.setWindowState(state)
        if visible:
            self.show()
        self._sync_native_caption_area()
        self._sync_history()

    @staticmethod
    def _native_windows_platform() -> bool:
        application = QtWidgets.QApplication.instance()
        return (
            sys.platform == "win32"
            and application is not None
            and application.platformName().lower() == "windows"
        )

    def uses_native_caption_buttons(self) -> bool:
        """True for the default OS frame; an integrated caption is Qt-rendered."""
        return self._native_windows_platform() and not self._title_bar_enabled

    def _sync_native_caption_area(self, *_arguments) -> None:
        if self._title_bar is None:
            return
        if hasattr(self._title_bar, "_set_native_caption"):
            self._title_bar._set_native_caption(False)

    def _set_native_caption_visibility(self, minimize, maximize, close):
        if not self._native_caption:
            return
        visible, geometry, state = self.isVisible(), self.geometry(), self.windowState()
        flags = self.windowFlags()
        flags |= QtCore.Qt.WindowType.CustomizeWindowHint
        for flag, enabled in (
            (QtCore.Qt.WindowType.WindowMinimizeButtonHint, minimize),
            (QtCore.Qt.WindowType.WindowMaximizeButtonHint, maximize),
            (QtCore.Qt.WindowType.WindowCloseButtonHint, close),
        ):
            flags = QtCore.Qt.WindowType(
                int(flags) | int(flag) if enabled else int(flags) & ~int(flag)
            )
        self.setWindowFlags(flags)
        self.setGeometry(geometry)
        self.setWindowState(state)
        if visible:
            self.show()
        self._sync_native_caption_area()

    def _title_bar_destroyed(self) -> None:
        # This may run during QObject teardown; do not call native Qt methods.
        self._title_bar = None

    def is_title_bar_enabled(self) -> bool:
        return self._title_bar_enabled

    def _resize_edges(self, point: QtCore.QPoint):
        edges = QtCore.Qt.Edge(0)
        if self.isMaximized() or self.isFullScreen():
            return edges
        if self.minimumWidth() < self.maximumWidth():
            if point.x() < 5:
                edges |= QtCore.Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 5:
                edges |= QtCore.Qt.Edge.RightEdge
        if self.minimumHeight() < self.maximumHeight():
            if point.y() < 5:
                edges |= QtCore.Qt.Edge.TopEdge
            elif point.y() >= self.height() - 5:
                edges |= QtCore.Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if (
            event.type() == QtCore.QEvent.Type.Show
            and self.property("fluentLazyThemeRefresh") is True
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self
            and hasattr(self, "_theme_palette")
        ):
            self._set_widget_theme_palette(watched, self._theme_palette)
        if (
            self._title_bar_enabled
            and not self._native_caption
            and event.type() in (QtCore.QEvent.Type.MouseMove, QtCore.QEvent.Type.MouseButtonPress)
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self
        ):
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = self._resize_edges(point)
            if edges:
                horizontal = bool(edges & (QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.RightEdge))
                vertical = bool(edges & (QtCore.Qt.Edge.TopEdge | QtCore.Qt.Edge.BottomEdge))
                if horizontal and vertical:
                    same = bool(edges & QtCore.Qt.Edge.LeftEdge) == bool(
                        edges & QtCore.Qt.Edge.TopEdge
                    )
                    cursor = (
                        QtCore.Qt.CursorShape.SizeFDiagCursor
                        if same
                        else QtCore.Qt.CursorShape.SizeBDiagCursor
                    )
                else:
                    cursor = (
                        QtCore.Qt.CursorShape.SizeHorCursor
                        if horizontal
                        else QtCore.Qt.CursorShape.SizeVerCursor
                    )
                self.setCursor(cursor)
                if (
                    event.type() == QtCore.QEvent.Type.MouseButtonPress
                    and event.button() == QtCore.Qt.MouseButton.LeftButton
                ):
                    handle = self.windowHandle()
                    if handle is not None and handle.startSystemResize(edges):
                        return True
            else:
                self.unsetCursor()
        return super().eventFilter(watched, event)

    def nativeEvent(self, event_type, message):
        if getattr(self, "_backdrop_enabled", False) and self._native_windows_platform():
            backdrop_message = ctypes.wintypes.MSG.from_address(int(message))
            if backdrop_message.message == 0x0086 and self._backdrop_applied:
                return True, self._forward_nonclient_activation(
                    backdrop_message.hWnd,
                    backdrop_message.wParam,
                    -1 if self._integrated_windows_frame else backdrop_message.lParam,
                )
            if backdrop_message.message in (0x001A, 0x031A, 0x031E, 0x0320, 0x0218):
                self._backdrop_refresh.start(80)
        if getattr(self, "_integrated_windows_frame", False):
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE
                # Keep the native styles and DWM shadow, remove only the
                # separately drawn caption. The Qt bar is the sole caption.
                if self.isMaximized() and not self.isFullScreen():

                    class _MonitorInfo(ctypes.Structure):
                        _fields_ = [
                            ("size", ctypes.wintypes.DWORD),
                            ("monitor", ctypes.wintypes.RECT),
                            ("work", ctypes.wintypes.RECT),
                            ("flags", ctypes.wintypes.DWORD),
                        ]

                    user32 = ctypes.windll.user32
                    user32.MonitorFromWindow.argtypes = [
                        ctypes.wintypes.HWND,
                        ctypes.wintypes.DWORD,
                    ]
                    user32.MonitorFromWindow.restype = ctypes.wintypes.HANDLE
                    user32.GetMonitorInfoW.argtypes = [
                        ctypes.wintypes.HANDLE,
                        ctypes.POINTER(_MonitorInfo),
                    ]
                    monitor = user32.MonitorFromWindow(msg.hWnd, 2)
                    info = _MonitorInfo()
                    info.size = ctypes.sizeof(info)
                    if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                        target = ctypes.wintypes.RECT.from_address(msg.lParam)
                        target.left, target.top = info.work.left, info.work.top
                        target.right, target.bottom = info.work.right, info.work.bottom
                return True, 0
            if msg.message == 0x0084:  # WM_NCHITTEST; coordinates are physical.
                sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                user32 = ctypes.windll.user32
                native_point = ctypes.wintypes.POINT(sx, sy)
                user32.ScreenToClient.argtypes = [
                    ctypes.wintypes.HWND,
                    ctypes.POINTER(ctypes.wintypes.POINT),
                ]
                user32.ScreenToClient(msg.hWnd, ctypes.byref(native_point))
                ratio = self.devicePixelRatioF()
                point = QtCore.QPoint(round(native_point.x / ratio), round(native_point.y / ratio))
                edges = self._resize_edges(point)
                left, right = (
                    bool(edges & QtCore.Qt.Edge.LeftEdge),
                    bool(edges & QtCore.Qt.Edge.RightEdge),
                )
                top, bottom = (
                    bool(edges & QtCore.Qt.Edge.TopEdge),
                    bool(edges & QtCore.Qt.Edge.BottomEdge),
                )
                if top:
                    return True, 13 if left else 14 if right else 12
                if bottom:
                    return True, 16 if left else 17 if right else 15
                if left or right:
                    return True, 10 if left else 11
                bar = self._title_bar
                if bar is not None and not bar.isHidden():
                    local = bar.mapFrom(self, point)
                    if bar.rect().contains(local):
                        if hasattr(bar, "_is_drag_area") and bar._is_drag_area(
                            QtCore.QPointF(local)
                        ):
                            return True, 2  # HTCAPTION: OS move, double click, system menu.
                return True, 1  # HTCLIENT: normal Qt input and caption buttons.
            if msg.message == 0x00A3 and msg.wParam == 2:  # WM_NCLBUTTONDBLCLK
                bar = self._title_bar
                if bar is not None and hasattr(bar, "double_click_enabled"):
                    maximum = getattr(bar, "maximize_button", None)
                    if (
                        not bar.double_click_enabled()
                        or maximum is None
                        or maximum.isHidden()
                        or not maximum.isEnabled()
                    ):
                        return True, 0
        return super().nativeEvent(event_type, message)

    def set_background_colors(self, light, dark) -> None:
        colors = (QtGui.QColor(light), QtGui.QColor(dark))
        if any(not color.isValid() or color.alpha() != 255 for color in colors):
            raise ValueError("background colors must be valid opaque colors")
        self._background_colors = colors
        self._apply_theme()

    def clear_background_colors(self) -> None:
        self._background_colors = None
        self._apply_theme()

    def set_backdrop_enabled(self, enabled: bool) -> None:
        """Use Windows 11 Mica on the shell; content surfaces stay readable."""
        self._backdrop_enabled = bool(enabled)
        if self.isVisible() or self._backdrop_applied:
            self._apply_backdrop()

    def is_backdrop_enabled(self) -> bool:
        return self._backdrop_enabled

    def backdrop_applied(self) -> bool:
        """Whether DWM accepted Mica and the Qt shell exposes the material."""
        return self._backdrop_applied

    def _resolved_background_color(self):
        tokens = theme.tokens
        background = tokens.background if theme.active else tokens.background_inactive
        if self._background_colors is not None:
            background = self._background_colors[1 if tokens.mode is ThemeMode.DARK else 0].name()
        return QtGui.QColor(background)

    def _resolved_shell_color(self):
        """Shared caption/navigation surface, distinct from page content."""
        if self._background_colors is not None:
            return self._resolved_background_color()
        return QtGui.QColor("#f3f3f3" if theme.mode is ThemeMode.LIGHT else "#202020")

    def _paint_shell_surface(self, painter, surface):
        if self._backdrop_applied and not self._backdrop_snapshot_depth:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(surface.rect(), QtGui.QColor("transparent"))
            return
        painter.fillRect(surface.rect(), self._resolved_shell_color())

    def _capture_theme_frame(self):
        # QWidget.grab cannot include DWM's separately composed wallpaper
        # material. Use the matching neutral shell for the short transition;
        # actual Mica is revealed again when the two-frame fade completes.
        self._backdrop_snapshot_depth += 1
        try:
            return self.grab()
        finally:
            self._backdrop_snapshot_depth -= 1

    @staticmethod
    def _set_widget_theme_palette(widget, palette):
        widget.setPalette(palette)
        if isinstance(widget, QtWidgets.QLabel) and widget.objectName() == "muted":
            widget.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)

    def _apply_theme(self) -> None:
        tokens = theme.tokens
        background = self._resolved_background_color().name()
        palette = self.palette()
        for role, color in (
            (QtGui.QPalette.ColorRole.Window, background),
            (QtGui.QPalette.ColorRole.WindowText, tokens.text),
            (QtGui.QPalette.ColorRole.Text, tokens.text),
            (QtGui.QPalette.ColorRole.Base, tokens.surface),
            (QtGui.QPalette.ColorRole.AlternateBase, tokens.surface_high),
            (QtGui.QPalette.ColorRole.Button, tokens.surface),
            (QtGui.QPalette.ColorRole.ButtonText, tokens.text),
            (QtGui.QPalette.ColorRole.PlaceholderText, tokens.text_muted),
            (QtGui.QPalette.ColorRole.Mid, tokens.border),
            (QtGui.QPalette.ColorRole.Highlight, tokens.accent),
            (QtGui.QPalette.ColorRole.HighlightedText, "#ffffff"),
        ):
            palette.setColor(role, QtGui.QColor(color))
        self.setPalette(palette)
        self._root.setPalette(palette)
        self._theme_palette = palette
        # Qt stylesheets stop normal palette inheritance even when their only
        # rules concern fonts/layout. Propagate colors explicitly without
        # replacing the ancestor sheet and repolishing its whole subtree.
        for widget in self.findChildren(QtWidgets.QWidget):
            if self.property("fluentLazyThemeRefresh") is not True or widget.isVisible():
                self._set_widget_theme_palette(widget, palette)
        stylesheet = f"""
QWidget {{
    font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI";
    font-size: {tokens.font_size}px;
}}
QLabel {{
    background: transparent;
    border: none;
}}
"""
        if self.styleSheet() != stylesheet:
            self.setStyleSheet(stylesheet)
        if self._title_bar is not None and hasattr(self._title_bar, "refresh_theme"):
            self._title_bar.refresh_theme()
        if self.isVisible():
            self._apply_backdrop()

    def _apply_backdrop(self) -> None:
        mapped = (
            self.isVisible()
            and self._native_windows_platform()
            and not self.testAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        )
        accepted = apply_system_backdrop(
            self, theme.tokens.mode, theme.active, self._backdrop_enabled and mapped
        )
        applied = bool(accepted and self._backdrop_enabled and mapped)
        changed = applied != self._backdrop_applied
        if changed and hasattr(self, "_theme_transition"):
            self._theme_transition.finish()
        self._backdrop_applied = applied
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, applied)
        self._root.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, applied)
        self._root.setAutoFillBackground(not applied)
        if self._navigation_view is not None:
            self._navigation_view.sidebar._sync_shell_material()
        if self._integrated_windows_frame:
            apply_integrated_window_frame(self, theme.tokens.mode)
        if applied and changed:
            self._forward_nonclient_activation(
                int(self.winId()),
                int(self.isActiveWindow()),
                -1 if self._integrated_windows_frame else 0,
            )
        if changed:
            self.update()
            self._root.update()
            if self._title_bar is not None:
                self._title_bar.update()
            self.backdropChanged.emit(applied)

    @staticmethod
    def _forward_nonclient_activation(hwnd, active, parameter):
        # Qt suppresses NC activation for a frameless caption. DWM needs this
        # notification to distinguish active wallpaper-tinted Mica from its
        # inactive neutral surface; normal WM_ACTIVATE still reaches Qt.
        procedure = ctypes.windll.user32.DefWindowProcW
        procedure.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        procedure.restype = ctypes.c_ssize_t
        return int(procedure(hwnd, 0x0086, active, parameter))
