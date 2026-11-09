"""Top-accent notifications using the existing Toast surface, stack and close control."""

from __future__ import annotations

import operator

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .button import Button
from .toast import Toast


def _validated_color(value):
    if value is None:
        return None
    if not isinstance(value, (str, QtGui.QColor, QtCore.Qt.GlobalColor)):
        raise TypeError("color must be a QColor, string, Qt.GlobalColor or None")
    color = QtGui.QColor(value)
    if not color.isValid():
        raise ValueError("invalid toast color")
    return color


class ColorToast(Toast):
    """Top-strip notification with a shared, publicly composable content_layout."""

    actionTriggered = Signal()
    colorChanged = Signal(QtGui.QColor)
    TONES = ("success", "error", "warning", "accent", "info")

    def __init__(
        self,
        title,
        detail="",
        parent=None,
        *,
        color=None,
        tone="accent",
        action_text="",
        action_callback=None,
        close_on_action=True,
        card_width=None,
        target=None,
    ):
        if not isinstance(title, str) or not isinstance(detail, str):
            raise TypeError("title and detail must be strings")
        if tone not in self.TONES:
            raise ValueError(f"tone must be one of {self.TONES}")
        self._custom_color = _validated_color(color)
        self._tone = tone
        self._card_width = self._validate_width(card_width)
        self._bar_display = QtGui.QColor()
        self._last_color = QtGui.QColor()
        self._action_callback = None
        self._pending_timeout = None
        self._hovering = False
        self._validate_action(action_text, action_callback, close_on_action)
        super().__init__(title, detail, parent, target=target)
        # Keep Qt children parented throughout: nothing briefly becomes a window.
        root = self.layout()
        while root.count():
            item = root.takeAt(0)
            child = item.layout()
            if child is not None:
                while child.count():
                    child.takeAt(0)
                child.deleteLater()
        root.setContentsMargins(33, 27, 33, 35)
        root.setSpacing(0)
        self._icon.hide()
        self._content = QtWidgets.QWidget(self)
        self.content_widget = self._content
        self._content.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        column = QtWidgets.QVBoxLayout(self._content)
        self.content_layout = column
        column.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.addWidget(self._title, 1)
        header.addWidget(self.close_button, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self.close_button.setFixedSize(24, 24)
        self._detail_row = QtWidgets.QWidget(self._content)
        body = QtWidgets.QVBoxLayout(self._detail_row)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        body.addWidget(self._detail)
        self._detail_row.setVisible(bool(detail))
        self._detail.setVisible(bool(detail))
        self._action_row = QtWidgets.QWidget(self._content)
        actions = QtWidgets.QHBoxLayout(self._action_row)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        self.action_button = Button("", self._action_row)
        self.action_button.clicked.connect(self._run_action)
        actions.addWidget(self.action_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()
        column.addLayout(header)
        column.addWidget(self._detail_row)
        column.addWidget(self._action_row)
        root.addWidget(self._content, 1)
        self._timeout = QtCore.QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.close)
        self._color_motion = QtCore.QVariantAnimation(self)
        self._color_motion.setDuration(160)
        self._color_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._color_motion.valueChanged.connect(self._set_bar_color)
        self.set_action(action_text, action_callback, close_on_action=close_on_action)
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)
        self._apply_theme()
        self._content.installEventFilter(self)

    @staticmethod
    def _validate_width(width):
        if width is not None:
            if isinstance(width, bool) or not isinstance(width, int):
                raise TypeError("card_width must be an int or None")
            if not 120 <= width <= 1200:
                raise ValueError("card_width must be between 120 and 1200")
        return width

    @staticmethod
    def _validate_action(text, callback, close_on_action):
        if not isinstance(text, str):
            raise TypeError("action_text must be a string")
        if callback is not None and not callable(callback):
            raise TypeError("action_callback must be callable or None")
        if not isinstance(close_on_action, bool):
            raise TypeError("close_on_action must be a bool")

    @classmethod
    def notify(
        cls,
        title,
        *,
        detail="",
        parent=None,
        placement="top-right",
        tone="accent",
        color=None,
        action_text="",
        action_callback=None,
        close_on_action=True,
        card_width=None,
        timeout_ms=4000,
        target=None,
    ):
        if placement not in cls.PLACEMENTS:
            raise ValueError(f"placement must be one of {cls.PLACEMENTS}")
        timeout_ms = cls._validate_timeout(timeout_ms)
        toast = cls(
            title,
            detail,
            parent or QtWidgets.QApplication.activeWindow(),
            tone=tone,
            color=color,
            action_text=action_text,
            action_callback=action_callback,
            close_on_action=close_on_action,
            card_width=card_width,
            target=target,
        )
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.set_timeout(timeout_ms)
        toast.show_at(placement)
        return toast

    @classmethod
    def success(cls, title, **kwargs):
        kwargs.setdefault("tone", "success")
        return cls.notify(title, **kwargs)

    @classmethod
    def error(cls, title, **kwargs):
        kwargs.setdefault("tone", "error")
        return cls.notify(title, **kwargs)

    @classmethod
    def warning(cls, title, **kwargs):
        kwargs.setdefault("tone", "warning")
        return cls.notify(title, **kwargs)

    @classmethod
    def info(cls, title, **kwargs):
        kwargs.setdefault("tone", "info")
        return cls.notify(title, **kwargs)

    def color(self):
        if self._custom_color is not None:
            return QtGui.QColor(self._custom_color)
        dark = theme.mode.value == "dark"
        return QtGui.QColor(
            {
                "success": "#6ccb5f" if dark else "#0f7b0f",
                "error": "#ff99a4" if dark else "#c42b1c",
                "warning": "#fce100" if dark else "#9d5d00",
                "accent": theme.tokens.accent,
                "info": "#a5a5a5" if dark else "#858585",
            }[self._tone]
        )

    def set_color(self, color):
        self._custom_color = _validated_color(color)
        self._refresh_bar()

    setColor = set_color

    def tone(self):
        return self._tone

    def set_tone(self, tone):
        if tone not in self.TONES:
            raise ValueError(f"tone must be one of {self.TONES}")
        self._tone = tone
        self._custom_color = None
        self._refresh_bar()

    def title(self):
        return self._title.text()

    def detail(self):
        return self._detail.text()

    def card_width(self):
        return self._card_width

    def set_title(self, title):
        if not isinstance(title, str):
            raise TypeError("title must be a string")
        self._title.setText(title)
        self.setAccessibleName(title)
        self._refresh_geometry()

    def set_detail(self, detail):
        if not isinstance(detail, str):
            raise TypeError("detail must be a string")
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        self._detail_row.setVisible(bool(detail))
        self.setAccessibleDescription(detail)
        self._refresh_geometry()

    def set_card_width(self, width):
        self._card_width = self._validate_width(width)
        self._refresh_geometry()

    def set_action(self, text, callback=None, *, close_on_action=True):
        self._validate_action(text, callback, close_on_action)
        if self._action_callback is not None:
            try:
                self.actionTriggered.disconnect(self._action_callback)
            except (RuntimeError, TypeError):
                pass
        self._action_callback = callback
        if callback is not None:
            self.actionTriggered.connect(callback)
        self._close_on_action = close_on_action
        self.action_button.setText(text)
        self._action_row.setVisible(bool(text))
        self._refresh_geometry()

    def _run_action(self):
        close = self._close_on_action
        self.actionTriggered.emit()
        if close:
            try:
                if self.isVisible():
                    self.close()
            except RuntimeError:
                pass

    def sizeHint(self):
        if not hasattr(self, "content_layout"):
            return super().sizeHint()
        self.ensurePolished()

        def text_width(label):
            return max(
                (
                    label.fontMetrics().horizontalAdvance(line) + 1
                    for line in label.text().splitlines()
                ),
                default=0,
            )

        title = text_width(self._title) + self.close_button.width() + 12
        detail = text_width(self._detail)
        # Include developer-added widgets/layouts in the natural width, while
        # still letting word-wrapped labels shrink inside an explicit width.
        natural = max(title, detail, self.content_layout.sizeHint().width())
        margins = self.layout().contentsMargins()
        width = (
            self._card_width + 33
            if self._card_width is not None
            else min(553, max(273, natural + margins.left() + margins.right()))
        )
        return QtCore.QSize(width, self.heightForWidth(width))

    def heightForWidth(self, width):
        if not hasattr(self, "content_layout"):
            return super().heightForWidth(width)
        self.ensurePolished()
        # Let Qt measure the very layout that will paint the content. Separate
        # label/button estimates miss wrap boundaries and custom widget heights.
        layout = self.layout()
        return max(layout.minimumSize().height(), layout.totalHeightForWidth(max(1, width)))

    def _refresh_geometry(self, *, invalidate_content=True):
        if invalidate_content and hasattr(self, "content_layout"):
            self.content_layout.invalidate()
        if hasattr(self, "_content"):
            self._content.updateGeometry()
        self.layout().invalidate()
        self.updateGeometry()
        if self._placement is not None:
            self._position()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_content", None):
            if event.type() == QtCore.QEvent.Type.LayoutRequest:
                self._refresh_geometry(invalidate_content=False)
            return False
        return super().eventFilter(watched, event)

    def _card_path(self):
        if self._target is not None:
            return super()._card_path()
        path = QtGui.QPainterPath()
        path.addRoundedRect(self._card_rect(), 6, 6)
        return path

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setClipPath(self._card_path())
        rect = self._card_rect()
        painter.fillRect(QtCore.QRectF(rect.left(), rect.top(), rect.width(), 3), self._bar_display)

    def _refresh_bar(self):
        target = self.color()
        if target != self._last_color:
            self._last_color = QtGui.QColor(target)
            self.colorChanged.emit(QtGui.QColor(target))
        if hasattr(self, "_color_motion"):
            self._color_motion.stop()
            if self.isVisible() and self._bar_display.isValid() and self._bar_display != target:
                self._color_motion.setStartValue(self._bar_display)
                self._color_motion.setEndValue(target)
                self._color_motion.start()
                return
        self._set_bar_color(target)

    def _set_bar_color(self, color):
        self._bar_display = QtGui.QColor(color)
        self.update()

    def _apply_theme(self):
        super()._apply_theme()
        self.setStyleSheet(
            self.styleSheet() + "QLabel#toastTitle,QLabel#toastDetail {font-size:14px;}"
        )
        self._title.setFont(ui_font(14))
        bold = self._title.font()
        bold.setWeight(QtGui.QFont.Weight.DemiBold)
        self._title.setFont(bold)
        self._detail.setFont(ui_font(14))
        self._refresh_bar()
        if self._placement is not None:
            self._position()

    @staticmethod
    def _validate_timeout(value):
        value = operator.index(value)
        if not 0 <= value <= 2_147_483_647:
            raise ValueError("timeout_ms must be between 0 and 2147483647")
        return value

    def set_timeout(self, timeout_ms):
        timeout_ms = self._validate_timeout(timeout_ms)
        self._timeout.stop()
        self._pending_timeout = timeout_ms or None
        self._start_timeout()

    def show_at(self, placement="top-right"):
        super().show_at(placement)
        self._start_timeout()

    def _start_timeout(self):
        if (
            self._pending_timeout is not None
            and self.isVisible()
            and not self._closing
            and not self._hovering
            and self._reveal.state() == QtCore.QAbstractAnimation.State.Stopped
        ):
            self._timeout.start(self._pending_timeout)
            self._pending_timeout = None

    def _reveal_finished(self):
        super()._reveal_finished()
        if self.isVisible():
            self._start_timeout()

    def enterEvent(self, event):
        self._hovering = True
        if self._timeout.isActive():
            self._pending_timeout = max(1, self._timeout.remainingTime())
            self._timeout.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self._start_timeout()
        super().leaveEvent(event)

    def closeEvent(self, event):
        self._timeout.stop()
        self._pending_timeout = None
        super().closeEvent(event)

    def hideEvent(self, event):
        self._timeout.stop()
        self._pending_timeout = None
        self._hovering = False
        self._color_motion.stop()
        self._bar_display = self.color()
        super().hideEvent(event)
