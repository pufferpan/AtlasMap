"""An owned startup surface, independent of any third-party splash widget."""

from __future__ import annotations

import weakref

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from ..theme.fonts import ui_font


class SplashScreen(QtWidgets.QWidget):
    """Cover a parent's content while leaving its existing title bar usable.

    Construct this before starting asynchronous initialization, call show(),
    and call finish() on the GUI thread when initialization has completed.
    This child surface never opens another native window or runs an event loop.
    """

    finished = Signal()

    def __init__(self, icon=None, parent: QtWidgets.QWidget | None = None):
        if not isinstance(parent, QtWidgets.QWidget):
            raise TypeError("SplashScreen requires a QWidget parent")
        super().__init__(parent)
        self._host_ref = weakref.ref(parent)
        self._icon = QtGui.QIcon()
        self._icon_size = QtCore.QSize(96, 96)
        self._text = ""
        self._loading = False
        self._background_colors = None
        self._opacity = 1.0
        self._rotation = 0.0
        self._finishing = False
        self._input_filter_installed = False
        self._previous_focus = None
        self._caption_ref = None
        self._fade = QtCore.QVariantAnimation(self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self._complete)
        self._spinner = QtCore.QVariantAnimation(self)
        self._spinner.setDuration(1100)
        self._spinner.setStartValue(0.0)
        self._spinner.setEndValue(1.0)
        self._spinner.setLoopCount(-1)
        self._spinner.valueChanged.connect(self._set_rotation)
        self.setObjectName("fluentSplashScreen")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("启动页面")
        self.set_icon(icon)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)
        parent.installEventFilter(self)
        self._fit_to_parent()
        self.hide()

    def set_icon(self, icon) -> None:
        if icon is None:
            host = self._host_ref()
            value = host.windowIcon() if host is not None else QtGui.QIcon()
        elif isinstance(icon, FluentIcon):
            value = fluent_icon(icon)
        elif isinstance(icon, (QtGui.QIcon, QtGui.QPixmap, str)):
            value = QtGui.QIcon(icon)
        else:
            raise TypeError("icon must be QIcon, QPixmap, FluentIcon, a path, or None")
        self._icon = QtGui.QIcon(value)
        self.update()

    def icon(self) -> QtGui.QIcon:
        return QtGui.QIcon(self._icon)

    def set_icon_size(self, size) -> None:
        if isinstance(size, int) and not isinstance(size, bool):
            size = QtCore.QSize(size, size)
        if not isinstance(size, QtCore.QSize) or size.width() <= 0 or size.height() <= 0:
            raise ValueError("icon size must be a positive int or QSize")
        self._icon_size = QtCore.QSize(size)
        self.update()

    def icon_size(self) -> QtCore.QSize:
        return QtCore.QSize(self._icon_size)

    def set_text(self, text: str) -> None:
        self._text = str(text)
        self.setAccessibleDescription(self._text)
        self.update()

    def text(self) -> str:
        return self._text

    def set_loading(self, loading: bool) -> None:
        self._loading = bool(loading)
        self._sync_spinner()
        self.update()

    def is_loading(self) -> bool:
        return self._loading

    def set_background_colors(self, light, dark) -> None:
        colors = (QtGui.QColor(light), QtGui.QColor(dark))
        if any(not color.isValid() or color.alpha() != 255 for color in colors):
            raise ValueError("splash backgrounds must be valid opaque colors")
        self._background_colors = colors
        self.update()
        self._refresh_caption()

    def clear_background_colors(self) -> None:
        self._background_colors = None
        self.update()
        self._refresh_caption()

    @Slot()
    def finish(self, *, animated: bool = True) -> None:
        """Dismiss once, optionally fading; repeated calls do not restart it."""
        if self.isHidden() or self._finishing:
            return
        self._finishing = True
        if not animated or not self.isVisible():
            self._complete()
            return
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _complete(self):
        if not self._finishing:
            return
        self._finishing = False
        self.hide()
        self.finished.emit()

    def _set_opacity(self, value):
        self._opacity = float(value)
        # While loading the solid surface occludes the expensive page tree;
        # only the short fade needs the real content painted underneath.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, self._opacity >= 1.0)
        self.update()

    def _set_rotation(self, value):
        self._rotation = float(value)
        self.update(self._content_rects()[2].toAlignedRect().adjusted(-3, -3, 3, 3))

    def _sync_spinner(self):
        if self._loading and self.isVisible():
            if self._spinner.state() != QtCore.QAbstractAnimation.State.Running:
                self._spinner.start()
        else:
            self._spinner.stop()

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.update()
        self._refresh_caption()

    def _resolved_background_color(self):
        return (
            QtGui.QColor(self._background_colors[1 if theme.mode.value == "dark" else 0])
            if self._background_colors
            else QtGui.QColor(theme.tokens.background)
        )

    def _refresh_caption(self):
        caption = self._caption_ref() if self._caption_ref is not None else None
        if caption is not None:
            try:
                caption.refresh_theme()
            except RuntimeError:
                self._caption_ref = None

    def _sync_caption(self):
        host = self._host_ref()
        caption = host.menuWidget() if isinstance(host, QtWidgets.QMainWindow) else None
        if (
            caption is None
            or caption.isHidden()
            or not self.isVisible()
            or not callable(getattr(caption, "_register_startup_splash", None))
        ):
            caption = None
        old = self._caption_ref() if self._caption_ref is not None else None
        if old is caption:
            return
        if old is not None:
            try:
                old._release_startup_splash(self)
            except RuntimeError:
                pass
        self._caption_ref = weakref.ref(caption) if caption is not None else None
        if caption is not None:
            caption._register_startup_splash(self)

    def _release_caption(self):
        caption = self._caption_ref() if self._caption_ref is not None else None
        self._caption_ref = None
        if caption is not None:
            try:
                caption._release_startup_splash(self)
            except RuntimeError:  # Caption may have been replaced or destroyed.
                pass

    def _fit_to_parent(self):
        host = self._host_ref()
        if host is None:
            return
        rect = host.rect()
        # Reuse the real caption already on this window, including native
        # resizing and its customized controls. Do not build a second caption.
        if isinstance(host, QtWidgets.QMainWindow):
            caption = host.menuWidget()
            if caption is not None and not caption.isHidden():
                rect.setTop(min(rect.bottom() + 1, caption.geometry().bottom() + 1))
        self.setGeometry(rect)
        self._sync_caption()

    def _covered(self, watched):
        host = self._host_ref()
        target = watched
        while target is not None and not isinstance(target, QtWidgets.QWidget):
            target = target.parent()
        if host is None or target is None or target is self or self.isAncestorOf(target):
            return False
        if target is host:
            return True
        if not host.isAncestorOf(target):
            return False
        bounds = QtCore.QRect(target.mapTo(host, QtCore.QPoint()), target.size())
        return self.geometry().intersects(bounds)

    def eventFilter(self, watched, event):
        # The parent is watched for geometry for the entire child's lifetime.
        # The application input filter exists only while the splash is visible.
        host_ref = self.__dict__.get("_host_ref")
        if host_ref is None:
            return False
        if watched is host_ref() and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.LayoutRequest,
            QtCore.QEvent.Type.Show,
        ):
            self._fit_to_parent()
        if (
            self.isVisible()
            and event.type()
            in (
                QtCore.QEvent.Type.KeyPress,
                QtCore.QEvent.Type.KeyRelease,
                QtCore.QEvent.Type.Shortcut,
                QtCore.QEvent.Type.ShortcutOverride,
                QtCore.QEvent.Type.InputMethod,
            )
            and self._covered(watched)
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def focusNextPrevChild(self, next):
        candidate = self.nextInFocusChain() if next else self.previousInFocusChain()
        while candidate is not self:
            if (
                not self._covered(candidate)
                and candidate.isVisible()
                and candidate.isEnabled()
                and candidate.focusPolicy() & QtCore.Qt.FocusPolicy.TabFocus
            ):
                candidate.setFocus(
                    QtCore.Qt.FocusReason.TabFocusReason
                    if next
                    else QtCore.Qt.FocusReason.BacktabFocusReason
                )
                return True
            candidate = candidate.nextInFocusChain() if next else candidate.previousInFocusChain()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self._fade.stop()
        self._finishing = False
        self._opacity = 1.0
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._fit_to_parent()
        self.raise_()
        previous = QtWidgets.QApplication.focusWidget()
        self._previous_focus = (
            weakref.ref(previous) if previous is not None and previous is not self else None
        )
        self.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        app = QtWidgets.QApplication.instance()
        if app is not None and not self._input_filter_installed:
            app.installEventFilter(self)
            self._input_filter_installed = True
        self._sync_spinner()

    def hideEvent(self, event):
        completing = self._finishing
        self._fade.stop()
        self._spinner.stop()
        self._finishing = False
        self._release_caption()
        app = QtWidgets.QApplication.instance()
        if app is not None and self._input_filter_installed:
            app.removeEventFilter(self)
            self._input_filter_installed = False
        previous = self._previous_focus() if self._previous_focus is not None else None
        self._previous_focus = None
        if previous is not None:
            try:
                if (
                    app is not None
                    and previous.isVisible()
                    and previous.isEnabled()
                    and (self.hasFocus() or app.focusWidget() is None)
                ):
                    previous.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            except RuntimeError:  # Its page may have been removed while loading.
                pass
        super().hideEvent(event)
        if completing:
            # Minimize/hide during the short exit must not resurrect a
            # completed startup screen when the window is restored.
            self.hide()
            self.finished.emit()

    def _content_rects(self):
        area = QtCore.QRectF(self.rect()).adjusted(24, 24, -24, -24)
        if area.width() <= 0 or area.height() <= 0:
            return QtCore.QRectF(), QtCore.QRectF(), QtCore.QRectF()
        text_height = min(self.fontMetrics().height() * 2, area.height() / 3) if self._text else 0
        loading_height = 22 if self._loading else 0
        extra = (20 + text_height if text_height else 0) + (
            18 + loading_height if loading_height else 0
        )
        factor = min(
            1.0,
            area.width() / self._icon_size.width(),
            max(0, area.height() - extra) / self._icon_size.height(),
        )
        width, height = self._icon_size.width() * factor, self._icon_size.height() * factor
        top = area.center().y() - (height + extra) / 2
        icon = QtCore.QRectF(area.center().x() - width / 2, top, width, height)
        text = QtCore.QRectF(area.left(), icon.bottom() + 20, area.width(), text_height)
        loading_top = (text.bottom() if text_height else icon.bottom()) + 18
        loading = QtCore.QRectF(area.center().x() - 11, loading_top, 22, loading_height)
        return icon, text, loading

    def paintEvent(self, event):
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        painter.fillRect(self.rect(), self._resolved_background_color())
        icon, text, loading = self._content_rects()
        if not icon.isEmpty():
            self._icon.paint(painter, icon.toAlignedRect(), QtCore.Qt.AlignmentFlag.AlignCenter)
        if self._text and not text.isEmpty():
            painter.setPen(QtGui.QColor(theme.tokens.text_muted))
            painter.drawText(
                text,
                QtCore.Qt.AlignmentFlag.AlignHCenter
                | QtCore.Qt.AlignmentFlag.AlignVCenter
                | QtCore.Qt.TextFlag.TextWordWrap,
                self._text,
            )
        if self._loading and not loading.isEmpty():
            painter.setPen(
                QtGui.QPen(
                    QtGui.QColor(theme.tokens.accent),
                    2.2,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                )
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawArc(
                loading.adjusted(2, 2, -2, -2), round((90 - self._rotation * 360) * 16), -110 * 16
            )
