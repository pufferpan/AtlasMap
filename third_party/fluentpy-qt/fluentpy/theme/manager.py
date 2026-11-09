from __future__ import annotations

import weakref

from ..qt import QtCore, QtWidgets, Signal, Slot
from .tokens import ThemeMode, ThemeTokens, default_tokens

_UNCHANGED = object()


class _ThemeSubscription(QtCore.QObject):
    """A receiver owned by the widget, so Qt disconnects it on destruction."""

    def __init__(self, owner: QtCore.QObject, method_name: str) -> None:
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)
        self._method_name = method_name
        self._dirty = False
        self._show_refreshing = False
        owner.destroyed.connect(self._owner_destroyed)
        if isinstance(owner, QtWidgets.QWidget):
            owner.installEventFilter(self)

    @Slot(object)
    def refresh(self, _tokens: object) -> None:
        owner = self._owner_ref()
        if owner is not None:
            if (
                isinstance(owner, QtWidgets.QWidget)
                and not owner.isVisible()
                and owner.window().property("fluentLazyThemeRefresh") is True
            ):
                self._dirty = True
                return
            self._dirty = False
            getattr(owner, self._method_name)()

    def eventFilter(self, watched, event):
        reference = self.__dict__.get("_owner_ref")
        if reference is None or not self.__dict__.get("_dirty", False):
            return False
        if (
            event.type() == QtCore.QEvent.Type.Show
            and not self._show_refreshing
            and watched is reference()
        ):
            # Show is delivered before the first paint. Clear the flag before
            # invoking user code so a nested hide/show cannot repeat the work.
            self._dirty = False
            self._show_refreshing = True
            try:
                getattr(watched, self._method_name)()
            finally:
                self._show_refreshing = False
        return False

    @Slot()
    def _owner_destroyed(self):
        self._dirty = False
        self._owner_ref = lambda: None


class ThemeManager(QtCore.QObject):
    modeAboutToChange = Signal(object)
    changed = Signal(object)
    modeChanged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._tokens = default_tokens()
        self._active = True

    def subscribe(self, owner: QtCore.QObject, callback) -> None:
        """Connect a no-argument owner method for the owner's Qt lifetime."""
        receiver = _ThemeSubscription(owner, callback.__name__)
        self.changed.connect(receiver.refresh)

    @property
    def tokens(self) -> ThemeTokens:
        return self._tokens

    @property
    def mode(self) -> ThemeMode:
        return self._tokens.mode

    @property
    def active(self) -> bool:
        return self._active

    def set_mode(self, mode: ThemeMode | str) -> None:
        self.set_theme(mode)

    def set_theme(self, mode: ThemeMode | str | None = None, *, accent=_UNCHANGED) -> None:
        """Commit mode and optional accent together, with one style refresh.

        The mode signals bracket all synchronous ``changed`` subscribers so a
        window can capture the old frame and then animate the complete result.
        """
        next_mode = self._tokens.mode if mode is None else ThemeMode(mode)
        next_accent = self._tokens.custom_accent if accent is _UNCHANGED else accent
        mode_changed = next_mode is not self._tokens.mode
        if not mode_changed and next_accent == self._tokens.custom_accent:
            return
        tokens = ThemeTokens(
            mode=next_mode,
            custom_accent=next_accent,
            radius=self._tokens.radius,
            spacing=self._tokens.spacing,
            font_size=self._tokens.font_size,
            animation_ms=self._tokens.animation_ms,
        )
        if mode_changed:
            self.modeAboutToChange.emit(tokens)
        self._tokens = tokens
        self.changed.emit(tokens)
        if mode_changed:
            self.modeChanged.emit(tokens)

    def toggle(self) -> None:
        self.set_mode(ThemeMode.DARK if self._tokens.mode is ThemeMode.LIGHT else ThemeMode.LIGHT)

    def set_accent(self, color: str | None) -> None:
        self.set_theme(accent=color)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.changed.emit(self._tokens)


theme = ThemeManager()
