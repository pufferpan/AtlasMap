"""Whole-window theme compositing, without per-frame style recalculation."""

from __future__ import annotations

import weakref

from ..qt import QtCore, QtGui, QtWidgets


class _ThemeFrame(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.setObjectName("fluentThemeTransition")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.frame = QtGui.QPixmap()
        self.target_frame = QtGui.QPixmap()
        self.opacity = 1.0
        self.hide()

    def paintEvent(self, event):
        del event
        if not self.frame.isNull():
            painter = QtGui.QPainter(self)
            # Cover every pixel opaquely first: Qt need not repaint the entire
            # live control tree underneath this layer on every animation tick.
            painter.drawPixmap(
                QtCore.QPoint(), self.target_frame if not self.target_frame.isNull() else self.frame
            )
            painter.setOpacity(self.opacity)
            painter.drawPixmap(QtCore.QPoint(), self.frame)


class WindowThemeTransition(QtCore.QObject):
    """Blend cached complete old/new frames, then reveal the live new theme.

    Mode and accent are applied once. The animation only changes the opacity
    of a Qt pixmap, including the integrated title bar and its caption glyphs.
    Input passes through; a reversal captures the current blended frame.
    """

    def __init__(self, owner, manager):
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)
        self.enabled = False
        self.duration = 280
        self.layer = None
        self._updates_suspended = False
        self._input_filter_installed = False
        self._generation = 0
        self._cancel_generation = -1
        self._input_timer = QtCore.QTimer(self)
        self._input_timer.setSingleShot(True)
        self._input_timer.timeout.connect(self._release_for_input)
        self._warm_timer = QtCore.QTimer(self)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.timeout.connect(self._warm_capture)
        self.animation = QtCore.QVariantAnimation(self)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self.finish)
        manager.modeAboutToChange.connect(self._prepare)
        manager.modeChanged.connect(self._start)
        owner.installEventFilter(self)

    @property
    def owner(self):
        reference = self.__dict__.get("_owner_ref")
        return reference() if reference is not None else None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.enabled:
            self._warm_timer.start(80)
        if not self.enabled:
            self._warm_timer.stop()
            self.finish()

    def _warm_capture(self):
        # Prime Qt's backing/effect caches after the initial window paint,
        # instead of paying the first capture's allocation cost on a click.
        owner = self.owner
        if owner is not None and self.enabled and owner.isVisible() and not self.is_running():
            self._capture_frame(owner)

    @staticmethod
    def _capture_frame(owner):
        capture = getattr(owner, "_capture_theme_frame", None)
        return capture() if callable(capture) else owner.grab()

    def is_running(self):
        return self.layer is not None and not self.layer.isHidden()

    def _prepare(self, _tokens):
        window = self.owner
        if window is None:
            return
        self._warm_timer.stop()
        if (
            not self.enabled
            or not window.isVisible()
            or window.isMinimized()
            or not window.updatesEnabled()
            or self.duration <= 0
        ):
            self.finish()
            return
        self.animation.stop()
        self._generation += 1
        self._input_timer.stop()
        # A visible previous layer is deliberately included when reversing.
        frame = self._capture_frame(window)
        if frame.isNull():
            self.finish()
            return
        window.setUpdatesEnabled(False)
        self._updates_suspended = True
        if self.layer is None:
            self.layer = _ThemeFrame(window)
        self.layer.frame = frame
        self.layer.target_frame = QtGui.QPixmap()
        self.layer.opacity = 1.0
        self.layer.setGeometry(window.rect())
        self.layer.show()
        self.layer.raise_()

    def _start(self, _tokens):
        if not self._updates_suspended:
            return
        # Re-enable painting before the forced capture. Some scroll-area
        # descendants otherwise render black while updates are disabled. No
        # event processing occurs here, so no intermediate frame is exposed.
        self._resume_updates()
        try:
            self.layer.hide()
            frame = self._capture_frame(self.owner)
            if frame.isNull():
                self.finish()
                return
            self.layer.target_frame = frame
            self.layer.show()
            self.layer.raise_()
        finally:
            self._resume_updates()
        self.animation.setDuration(self.duration)
        app = QtWidgets.QApplication.instance()
        if app is not None and not self._input_filter_installed:
            app.installEventFilter(self)
            self._input_filter_installed = True
        self.animation.start()

    def _resume_updates(self):
        if self._updates_suspended:
            self._updates_suspended = False
            owner = self.owner
            if owner is not None:
                owner.setUpdatesEnabled(True)

    def _advance(self, value):
        if self.layer is not None:
            self.layer.opacity = float(value)
            self.layer.update()

    def finish(self):
        self.animation.stop()
        self._input_timer.stop()
        if self._input_filter_installed:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._input_filter_installed = False
        self._resume_updates()
        if self.layer is not None:
            self.layer.hide()
            self.layer.frame = QtGui.QPixmap()
            self.layer.target_frame = QtGui.QPixmap()

    def _release_for_input(self):
        # The triggering click/key may itself reverse the theme. A new
        # generation owns its blended start frame and must keep animating.
        if self._cancel_generation == self._generation:
            self.finish()

    def eventFilter(self, watched, event):
        # Cyclic GC can clear a Python wrapper while Qt is still delivering
        # child/destruction events. Never call Qt or inspect fields then.
        owner = self.owner
        if owner is None:
            return False
        kind = event.type()
        if watched is owner and kind == QtCore.QEvent.Type.Show and self.enabled:
            self._warm_timer.start(80)
        if watched is owner and kind in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Hide,
            QtCore.QEvent.Type.Close,
            QtCore.QEvent.Type.WindowStateChange,
        ):
            self.finish()
            self._warm_timer.stop()
        elif (
            kind
            in (
                QtCore.QEvent.Type.KeyPress,
                QtCore.QEvent.Type.InputMethod,
                QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QEvent.Type.Wheel,
                QtCore.QEvent.Type.MouseMove,
            )
            and self.enabled
            and self.is_running()
            and isinstance(watched, QtWidgets.QWidget)
            and (watched is owner or owner.isAncestorOf(watched))
        ):
            release = kind in (
                QtCore.QEvent.Type.KeyPress,
                QtCore.QEvent.Type.InputMethod,
                QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QEvent.Type.Wheel,
            )
            dragging = kind == QtCore.QEvent.Type.MouseMove and bool(
                event.buttons() & QtCore.Qt.MouseButton.LeftButton
            )
            if release or dragging:
                self._cancel_generation = self._generation
                self._input_timer.start(0)
        return False
