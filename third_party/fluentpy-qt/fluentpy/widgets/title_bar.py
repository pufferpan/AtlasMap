"""An optional Qt title bar composed from ordinary FluentPy controls.

The owner decides how to frame this widget. An integrated bar uses Qt buttons
with familiar Windows caption glyphs; the Windows resize border, shadow and
window movement remain operating-system behavior. The normal OS title bar is
still available when the application does not enable this optional widget.
"""

from __future__ import annotations

import weakref

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font
from .button import IconButton


class _CaptionButton(IconButton):
    _kind = "text"

    def __init__(self, icon, parent, *, tooltip):
        super().__init__(icon, parent, tooltip=tooltip)
        self.setFixedSize(44, 48)
        self.setAccessibleName(tooltip)

    def _radius(self, rect):
        return 0

    def _surface_hover_color(self):
        if getattr(self, "caption_role", None) == "close":
            return QtGui.QColor("#e81123")
        return super()._surface_hover_color()

    def _surface_pressed_color(self):
        if getattr(self, "caption_role", None) == "close":
            return QtGui.QColor("#c50f1f")
        return super()._surface_pressed_color()

    def _draw_content(self, painter, rect, color):
        foreground = getattr(self.parentWidget(), "_foreground_color", None)
        if self.isEnabled() and foreground is not None:
            color = QtGui.QColor(foreground)
            color.setAlphaF(color.alphaF() * (1.0 - 0.34 * self._press_progress))
        role = getattr(self, "caption_role", None)
        if role is None:
            return super()._draw_content(painter, rect, color)
        if role == "close" and (self._hover_progress > 0.05 or self._press_progress > 0.05):
            color = QtGui.QColor("#ffffff")
        painter.setPen(QtGui.QPen(color, 1.0))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        cx, cy = rect.center().x(), rect.center().y()
        if role == "minimize":
            painter.drawLine(QtCore.QLineF(cx - 5, cy + 0.5, cx + 5, cy + 0.5))
        elif role == "maximize":
            painter.drawRect(QtCore.QRectF(cx - 4.5, cy - 4.5, 9, 9))
        elif role == "restore":
            painter.drawPolyline(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(cx - 2.5, cy - 3.5),
                        QtCore.QPointF(cx - 2.5, cy - 5.5),
                        QtCore.QPointF(cx + 5.5, cy - 5.5),
                        QtCore.QPointF(cx + 5.5, cy + 2.5),
                        QtCore.QPointF(cx + 3.5, cy + 2.5),
                    ]
                )
            )
            painter.drawRect(QtCore.QRectF(cx - 5.5, cy - 3.5, 9, 9))
        else:
            painter.drawLine(QtCore.QLineF(cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5))
            painter.drawLine(QtCore.QLineF(cx + 4.5, cy - 4.5, cx - 4.5, cy + 4.5))


class _WindowTitle(QtWidgets.QLabel):
    """Keep the full accessible title while allowing the layout to shrink it."""

    def __init__(self, parent):
        super().__init__(parent)
        self._full_title = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_title(self, text):
        self._full_title = str(text)
        self.setAccessibleName(self._full_title)
        self._elide()

    def _elide(self):
        text = self.fontMetrics().elidedText(
            self._full_title,
            QtCore.Qt.TextElideMode.ElideRight,
            max(0, self.contentsRect().width()),
        )
        super().setText(text)
        self.setToolTip(self._full_title if text != self._full_title else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.FontChange:
            self._elide()


class FluentTitleBar(QtWidgets.QWidget):
    """Optional 48-pixel title bar with editable Qt layout extension points.

    ``content_layout`` accepts search fields, tabs or other normal widgets;
    ``button_layout`` accepts extra actions before the window caption buttons.
    The owner retains all platform window behavior. Blank/title dragging asks
    an *existing* QWindow to start a system move and never calls ``winId()``.
    """

    def __init__(self, owner: QtWidgets.QWidget) -> None:
        if not isinstance(owner, QtWidgets.QWidget):
            raise TypeError("owner must be a QWidget")
        super().__init__(owner)
        self._owner = owner
        self._double_click_enabled = True
        self._native_caption = False
        self._caption_visibility = (True, True, True)
        self._bar_height = 48
        self._safe_top = 0
        self._background_color = QtGui.QColor(theme.tokens.background)
        self._foreground_color = QtGui.QColor(theme.tokens.text)
        self._startup_splashes = {}
        self._startup_visibility = None
        super().setFixedHeight(self._bar_height)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setAccessibleName("窗口标题栏")
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 0, 0)
        self._layout.setSpacing(4)

        self.back_button = _CaptionButton(fluent_icon(FluentIcon.ARROW_LEFT), self, tooltip="后退")
        self.forward_button = _CaptionButton(
            fluent_icon(FluentIcon.ARROW_RIGHT), self, tooltip="前进"
        )
        self.back_button.setFixedWidth(36)
        self.forward_button.setFixedWidth(36)
        self.back_button.clicked.connect(self._go_back)
        self.forward_button.clicked.connect(self._go_forward)
        self._layout.addWidget(self.back_button)
        self._layout.addWidget(self.forward_button)

        self.icon_label = QtWidgets.QLabel(self)
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._layout.addWidget(self.icon_label)
        self.title_label = _WindowTitle(self)
        self._layout.addWidget(self.title_label, 1)
        self._native_spacer = QtWidgets.QWidget(self)
        self._native_spacer.setObjectName("fluentTitleSpacer")
        self._native_spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self._native_spacer.setFixedHeight(1)
        self._native_spacer.hide()
        self._layout.addWidget(self._native_spacer, 1)

        self._content = QtWidgets.QWidget(self)
        self._content.setObjectName("fluentTitleContent")
        self.content_layout = QtWidgets.QHBoxLayout(self._content)
        self.content_layout.setContentsMargins(4, 0, 8, 0)
        self.content_layout.setSpacing(8)
        self._layout.addWidget(self._content)
        self._actions = QtWidgets.QWidget(self)
        self._actions.setObjectName("fluentTitleActions")
        self.button_layout = QtWidgets.QHBoxLayout(self._actions)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(4)
        self._layout.addWidget(self._actions)

        style = self.style()
        self.minimize_button = _CaptionButton(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarMinButton),
            self,
            tooltip="最小化",
        )
        self.maximize_button = _CaptionButton(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TitleBarMaxButton),
            self,
            tooltip="最大化",
        )
        self.close_button = _CaptionButton(fluent_icon(FluentIcon.DISMISS), self, tooltip="关闭")
        self.minimize_button.caption_role = "minimize"
        self.maximize_button.caption_role = "maximize"
        self.close_button.caption_role = "close"
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            self._layout.addWidget(button)
        self.minimize_button.clicked.connect(self._minimize)
        self.maximize_button.clicked.connect(self._toggle_maximized)
        self.close_button.clicked.connect(self._close)
        owner.windowTitleChanged.connect(self._sync_title)
        owner.windowIconChanged.connect(self._sync_icon)
        owner.installEventFilter(self)
        theme.subscribe(self, self._apply_theme)
        self._sync_title(owner.windowTitle())
        self._sync_icon(owner.windowIcon())
        self._sync_window_state()
        self.sync_navigation()
        self._apply_theme()

    def set_bar_height(self, height: int) -> None:
        """Set the command-row height; caption buttons follow the same height."""
        if isinstance(height, bool) or not isinstance(height, int) or height < 32:
            raise ValueError("title bar height must be an integer of at least 32 pixels")
        self.setFixedHeight(height)

    def bar_height(self) -> int:
        """Return the configured command-row height, excluding safe-area inset."""
        return self._bar_height

    def setFixedHeight(self, height: int) -> None:
        # Keep the existing QWidget entry point useful: toggling the title bar
        # or refreshing native metrics must not undo an application's height.
        self._bar_height = int(height)
        super().setFixedHeight(self._bar_height + self._safe_top)
        self._sync_button_heights()

    def _sync_button_heights(self):
        for name in (
            "back_button",
            "forward_button",
            "minimize_button",
            "maximize_button",
            "close_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setFixedHeight(self._bar_height)

    def set_double_click_enabled(self, enabled: bool) -> None:
        self._double_click_enabled = bool(enabled)

    def double_click_enabled(self) -> bool:
        return self._double_click_enabled

    def set_caption_buttons_visible(
        self, minimize: bool = True, maximize: bool = True, close: bool = True
    ) -> None:
        self._caption_visibility = (bool(minimize), bool(maximize), bool(close))
        for button, visible in (
            (self.minimize_button, minimize),
            (self.maximize_button, maximize),
            (self.close_button, close),
        ):
            button.setVisible(bool(visible) and not self._native_caption)
        if self._native_caption:
            callback = getattr(self._owner, "_set_native_caption_visibility", None)
            if callable(callback):
                callback(*self._caption_visibility)

    def uses_native_caption_buttons(self) -> bool:
        """Whether Windows owns the visible window caption controls."""
        return self._native_caption

    def _set_native_caption(self, enabled, safe_margins=None):
        self._native_caption = bool(enabled)
        safe_margins = safe_margins or QtCore.QMargins()
        top = max(0, safe_margins.top()) if enabled else 0
        self._safe_top = top
        self._layout.setContentsMargins(4, top, 0, 0)
        super().setFixedHeight(self._bar_height + top)
        self._sync_button_heights()
        self.title_label.setVisible(not enabled)
        self._native_spacer.setVisible(enabled)
        self.icon_label.setVisible(not enabled and not self._owner.windowIcon().isNull())
        for button, visible in zip(
            (self.minimize_button, self.maximize_button, self.close_button),
            self._caption_visibility,
        ):
            button.setVisible(visible and not enabled)
        self.setAutoFillBackground(False)
        self._sync_startup_chrome()

    def sync_navigation(self) -> None:
        """Refresh history availability after the owner changes its route."""
        for button, action_name, state_name in (
            (self.back_button, "go_back", "can_go_back"),
            (self.forward_button, "go_forward", "can_go_forward"),
        ):
            action = getattr(self._owner, action_name, None)
            state = getattr(self._owner, state_name, callable(action))
            button.setEnabled(callable(action) and bool(state() if callable(state) else state))

    def _go_back(self):
        action = getattr(self._owner, "go_back", None)
        if callable(action):
            action()
        self.sync_navigation()

    def _go_forward(self):
        action = getattr(self._owner, "go_forward", None)
        if callable(action):
            action()
        self.sync_navigation()

    def _minimize(self):
        self._owner.showMinimized()

    def _close(self):
        self._owner.close()

    def _toggle_maximized(self):
        allowed = (
            self._caption_visibility[1]
            if self._native_caption
            else not self.maximize_button.isHidden()
        )
        if self._native_caption:
            allowed = allowed and bool(
                self._owner.windowFlags() & QtCore.Qt.WindowType.WindowMaximizeButtonHint
            )
        if not allowed or not self.maximize_button.isEnabled():
            return
        if self._owner.isMaximized():
            self._owner.showNormal()
        else:
            self._owner.showMaximized()
        self._sync_window_state()

    def _sync_title(self, title):
        self.title_label.set_title(title)

    def _sync_icon(self, icon):
        self.icon_label.setPixmap(icon.pixmap(16, 16))
        self.icon_label.setVisible(
            not self._native_caption and not self._startup_splashes and not icon.isNull()
        )

    def _register_startup_splash(self, splash):
        token = id(splash)
        if token in self._startup_splashes:
            return
        if not self._startup_splashes:
            names = (
                "back_button",
                "forward_button",
                "icon_label",
                "title_label",
                "_content",
                "_actions",
                "_native_spacer",
            )
            self._startup_visibility = {name: not getattr(self, name).isHidden() for name in names}
        self._startup_splashes[token] = weakref.ref(splash)
        splash.destroyed.connect(self._prune_startup_splashes)
        self._sync_startup_chrome()
        self._apply_theme()

    def _release_startup_splash(self, splash):
        if self._startup_splashes.pop(id(splash), None) is not None:
            try:
                splash.destroyed.disconnect(self._prune_startup_splashes)
            except RuntimeError:
                pass
        self._sync_startup_chrome()
        self._apply_theme()

    def _prune_startup_splashes(self, *_):
        # A splash can be destroyed without an explicit finish/hide call.
        if "_startup_splashes" not in self.__dict__:
            return
        for token, reference in tuple(self._startup_splashes.items()):
            splash = reference()
            try:
                live = splash is not None and splash.isVisible()
            except RuntimeError:
                live = False
            if not live:
                self._startup_splashes.pop(token, None)
        self._sync_startup_chrome()
        self._apply_theme()

    def _startup_surface(self):
        for reference in reversed(tuple(self._startup_splashes.values())):
            splash = reference()
            try:
                if splash is not None and splash.isVisible():
                    return splash
            except RuntimeError:
                pass
        return None

    def _sync_startup_chrome(self):
        if self._startup_splashes:
            for name in (
                "back_button",
                "forward_button",
                "icon_label",
                "title_label",
                "_content",
                "_actions",
            ):
                getattr(self, name).hide()
            self._native_spacer.show()
        elif self._startup_visibility is not None:
            previous, self._startup_visibility = self._startup_visibility, None
            for name, visible in previous.items():
                getattr(self, name).setVisible(visible)
            self.icon_label.setVisible(
                not self._native_caption and not self._owner.windowIcon().isNull()
            )

    def _sync_window_state(self):
        maximized = self._owner.isMaximized()
        label = "还原" if maximized else "最大化"
        pixmap = (
            QtWidgets.QStyle.StandardPixmap.SP_TitleBarNormalButton
            if maximized
            else QtWidgets.QStyle.StandardPixmap.SP_TitleBarMaxButton
        )
        self.maximize_button.setIcon(self.style().standardIcon(pixmap))
        self.maximize_button.caption_role = "restore" if maximized else "maximize"
        self.maximize_button.setToolTip(label)
        self.maximize_button.setAccessibleName(label)

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        getter = getattr(self._owner, "_resolved_shell_color", None)
        if not callable(getter):
            getter = getattr(self._owner, "_resolved_background_color", None)
        background = getter() if callable(getter) else theme.tokens.background
        splash = self._startup_surface()
        if splash is not None:
            background = splash._resolved_background_color()
        foreground = theme.tokens.text
        self._set_visual_colors(background, foreground)
        self.title_label._elide()

    def refresh_theme(self) -> None:
        """Immediately synchronize the title bar with the current theme."""
        self._apply_theme()

    def _set_visual_colors(self, background, foreground) -> None:
        """Apply colors immediately, including during an owner-managed transition."""
        background, foreground = QtGui.QColor(background), QtGui.QColor(foreground)
        if not background.isValid() or background.alpha() != 255 or not foreground.isValid():
            raise ValueError("title bar colors must be valid, with an opaque background")
        self._background_color, self._foreground_color = background, foreground
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, background)
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, foreground)
        # A palette cannot override inherited Qt stylesheets. Scope foreground
        # and transparent layout containers locally; paint the full background
        # ourselves instead of exposing the owner's stale native/QSS surface.
        self.setStyleSheet(
            f"QLabel {{color:{foreground.name()};background:transparent;border:none;}}"
            "QWidget#fluentTitleContent,QWidget#fluentTitleActions,QWidget#fluentTitleSpacer"
            " {background:transparent;border:none;}"
        )
        for name in (
            "back_button",
            "forward_button",
            "minimize_button",
            "maximize_button",
            "close_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setStyleSheet("background:transparent;border:none;")
                button.update()
        # Stylesheet polishing may restore inherited palette roles. Publish
        # the final resolved colors only after every local style is updated.
        self.setPalette(palette)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        splash = self._startup_surface()
        if splash is not None:
            painter.fillRect(self.rect(), splash._resolved_background_color())
            return
        paint_shell = getattr(self._owner, "_paint_shell_surface", None)
        if callable(paint_shell):
            paint_shell(painter, self)
        else:
            painter.fillRect(self.rect(), self._background_color)

    def eventFilter(self, watched, event):
        if watched is self._owner and event.type() == QtCore.QEvent.Type.WindowStateChange:
            self._sync_window_state()
        return super().eventFilter(watched, event)

    def _is_drag_area(self, position):
        # Some native/custom controls ignore a mouse event and let it bubble.
        # Bubbling through the title bar must never turn that into a window
        # move or maximize (for example, double-clicking an extra tool button).
        child = self.childAt(position.toPoint())
        return child is None or child in (
            self.icon_label,
            self.title_label,
            self._content,
            self._actions,
            self._native_spacer,
        )

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_drag_area(
            event.position()
        ):
            handle = self._owner.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._double_click_enabled
            and self._is_drag_area(event.position())
        ):
            self._toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
