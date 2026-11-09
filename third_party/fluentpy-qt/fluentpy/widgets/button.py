from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


class Button(QtWidgets.QPushButton):
    _h_padding = 12
    _v_padding = 5
    _kind = "standard"
    _pill = False

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(32)
        self.setIconSize(QtCore.QSize(16, 16))
        self._apply_font()
        self._hovered = False
        self._hover_progress = 0.0
        self._press_progress = 0.0
        self._keyboard_activation = False
        self._keyboard_focus = False
        self._hover_animation = self._make_state_animation("_hover_progress")
        self._press_animation = self._make_state_animation("_press_progress")
        theme.changed.connect(self._on_theme_changed)

    def sizeHint(self) -> QtCore.QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        icon_width = 0 if self.icon().isNull() else self.iconSize().width() + 8
        return QtCore.QSize(max(80, text_width + icon_width + self._h_padding * 2), 32)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self._animate_state(self._hover_animation, self._hover_progress, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self._animate_state(self._hover_animation, self._hover_progress, 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._keyboard_focus = False
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._animate_state(self._press_animation, self._press_progress, 1.0, 70)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._animate_state(self._press_animation, self._press_progress, 0.0, 140)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and self.isEnabled():
            if not event.isAutoRepeat():
                self._keyboard_activation = True
                self.setDown(True)
                self._animate_state(self._press_animation, self._press_progress, 1.0, 70)
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Space and not event.isAutoRepeat():
            self._animate_state(self._press_animation, self._press_progress, 1.0, 70)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (
            event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter)
            and self._keyboard_activation
        ):
            self._keyboard_activation = False
            self.setDown(False)
            self._animate_state(self._press_animation, self._press_progress, 0.0, 140)
            if self.isEnabled():
                self.click()
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Space:
            self._animate_state(self._press_animation, self._press_progress, 0.0, 140)
        super().keyReleaseEvent(event)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() not in (
            QtCore.Qt.FocusReason.MouseFocusReason,
            QtCore.Qt.FocusReason.ActiveWindowFocusReason,
            QtCore.Qt.FocusReason.PopupFocusReason,
        )
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._keyboard_activation = self._keyboard_focus = False
        self.setDown(False)
        if hasattr(self, "_press_animation"):
            self._animate_state(self._press_animation, self._press_progress, 0.0, 100)
        super().focusOutEvent(event)

    def _reset_interaction(self):
        self._keyboard_activation = self._keyboard_focus = self._hovered = False
        self.setDown(False)
        for animation in (self._hover_animation, self._press_animation):
            animation.stop()
        self._hover_progress = self._press_progress = 0.0
        self.update()

    def hideEvent(self, event):
        self._reset_interaction()
        super().hideEvent(event)

    def changeEvent(self, event):
        if (
            event.type() == QtCore.QEvent.Type.EnabledChange
            and hasattr(self, "_press_animation")
            and not self.isEnabled()
        ):
            self._reset_interaction()
        super().changeEvent(event)

    def _visual_enabled(self):
        return self.isEnabled()

    def _draw_focus_ring(self, painter, rect, *, accent=False):
        if self.hasFocus() and self._keyboard_focus and self.isEnabled():
            color = (
                QtGui.QColor("#ffffff" if theme.mode.value == "light" else "#101010")
                if accent
                else QtGui.QColor(theme.tokens.accent)
            )
            painter.setPen(QtGui.QPen(color, 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(2, 2, -2, -2),
                max(2, self._radius(rect) - 2),
                max(2, self._radius(rect) - 2),
            )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        rect = self._paint_rect()
        radius = self._radius(rect)
        color = self._surface_color()
        if not self._visual_enabled():
            color.setAlpha(min(color.alpha(), 76 if tokens.mode.value == "light" else 46))
        else:
            color = _mix_color(color, self._surface_hover_color(), self._hover_progress)
            color = _mix_color(color, self._surface_pressed_color(), self._press_progress)

        painter.setBrush(color)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

        self._draw_button_border(painter, rect, radius)

        text_color = QtGui.QColor(tokens.text if self._visual_enabled() else tokens.disabled)
        if self._press_progress:
            text_color.setAlphaF(1.0 - 0.34 * self._press_progress)
        self._draw_content(painter, rect, text_color)
        self._draw_focus_ring(painter, rect)

    def _draw_content(
        self, painter: QtGui.QPainter, rect: QtCore.QRectF, color: QtGui.QColor
    ) -> None:
        painter.setPen(color)
        content_rect = rect.adjusted(self._h_padding, 0, -self._h_padding, 0)

        if not self.icon().isNull():
            icon_size = self.iconSize()
            text_width = self.fontMetrics().horizontalAdvance(self.text())
            gap = 8 if self.text() else 0
            total_width = icon_size.width() + gap + text_width
            x = int(content_rect.center().x() - total_width / 2)
            icon_rect = QtCore.QRect(
                x,
                int(content_rect.center().y() - icon_size.height() / 2),
                icon_size.width(),
                icon_size.height(),
            )
            self._draw_tinted_icon(painter, icon_rect, color)
            text_rect = QtCore.QRect(
                icon_rect.right() + gap + 1,
                int(content_rect.y()),
                max(text_width, 1),
                int(content_rect.height()),
            )
            painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())
            return
        painter.drawText(content_rect, QtCore.Qt.AlignmentFlag.AlignCenter, self.text())

    def _draw_tinted_icon(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        color: QtGui.QColor,
        icon: QtGui.QIcon | None = None,
    ) -> None:
        ratio = self.devicePixelRatioF()
        pixmap = QtGui.QPixmap(rect.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)

        icon_painter = QtGui.QPainter(pixmap)
        (self.icon() if icon is None else icon).paint(
            icon_painter, QtCore.QRect(QtCore.QPoint(0, 0), rect.size())
        )
        icon_painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        icon_painter.fillRect(pixmap.rect(), color)
        icon_painter.end()

        painter.drawPixmap(rect, pixmap)

    def _surface_color(self) -> QtGui.QColor:
        if self._kind in {"text", "outlined"}:
            return QtGui.QColor(0, 0, 0, 0)
        color = QtGui.QColor("#ffffff")
        color.setAlphaF(0.70 if theme.tokens.mode.value == "light" else 0.0605)
        return color

    def _surface_hover_color(self) -> QtGui.QColor:
        if self._kind == "text":
            color = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
            color.setAlpha(10 if theme.tokens.mode.value == "light" else 18)
            return color
        if self._kind == "outlined":
            color = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
            color.setAlpha(6 if theme.tokens.mode.value == "light" else 14)
            return color
        color = QtGui.QColor("#f9f9f9" if theme.tokens.mode.value == "light" else "#ffffff")
        color.setAlphaF(0.50 if theme.tokens.mode.value == "light" else 0.0837)
        return color

    def _surface_pressed_color(self) -> QtGui.QColor:
        if self._kind == "text":
            color = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
            color.setAlpha(16 if theme.tokens.mode.value == "light" else 10)
            return color
        if self._kind == "outlined":
            color = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
            color.setAlpha(10 if theme.tokens.mode.value == "light" else 8)
            return color
        color = QtGui.QColor("#f9f9f9" if theme.tokens.mode.value == "light" else "#ffffff")
        color.setAlphaF(0.30 if theme.tokens.mode.value == "light" else 0.0326)
        return color

    def _draw_button_border(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        radius: float,
    ) -> None:
        tokens = theme.tokens
        if self._kind == "text":
            return

        if tokens.mode.value == "light":
            border = QtGui.QColor(0, 0, 0, 22 if self._kind == "outlined" else 18)
            lower = QtGui.QColor(0, 0, 0, int(46 - 28 * self._press_progress))
        else:
            border = QtGui.QColor(255, 255, 255, 24 if self._kind == "outlined" else 14)
            lower = QtGui.QColor(255, 255, 255, int(20 - 6 * self._press_progress))

        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(border, 1))
        painter.drawPath(path)

        if self._kind != "outlined":
            bottom = QtCore.QLineF(
                rect.left() + radius, rect.bottom(), rect.right() - radius, rect.bottom()
            )
            painter.setPen(QtGui.QPen(lower, 1))
            painter.drawLine(bottom)

    def _on_theme_changed(self, _tokens: object) -> None:
        self._apply_font()
        self.update()

    def _apply_font(self) -> None:
        self.setFont(ui_font(theme.tokens.font_size, self.font()))

    def _paint_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    def _radius(self, rect: QtCore.QRectF) -> float:
        return rect.height() / 2 if self._pill else theme.tokens.radius

    def _make_state_animation(self, attr: str) -> QtCore.QVariantAnimation:
        animation = QtCore.QVariantAnimation(self)
        animation.setDuration(theme.tokens.animation_ms)
        animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(
            lambda value, name=attr: self._set_state_value(name, float(value))
        )
        return animation

    def _animate_state(
        self,
        animation: QtCore.QVariantAnimation,
        start: float,
        end: float,
        duration: int | None = None,
    ) -> None:
        animation.stop()
        animation.setDuration(duration or theme.tokens.animation_ms)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _set_state_value(self, attr: str, value: float) -> None:
        setattr(self, attr, max(0.0, min(1.0, value)))
        self.update()


class AccentButton(Button):
    _kind = "accent"

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self._paint_rect()
        radius = self._radius(rect)

        color = QtGui.QColor(tokens.accent)
        if not self._visual_enabled():
            color = QtGui.QColor("#cdcdcd" if tokens.mode.value == "light" else "#343434")
        else:
            color = _mix_color(color, color.lighter(103), self._hover_progress)
            color = _mix_color(color, color.darker(110), self._press_progress)

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, radius, radius)
        top = QtGui.QColor("#ffffff")
        top.setAlpha(70)
        bottom = QtGui.QColor("#000000")
        bottom.setAlpha(int(42 - 30 * self._press_progress))
        painter.setPen(QtGui.QPen(top, 1))
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QtGui.QPen(bottom, 1))
        painter.drawLine(
            QtCore.QLineF(rect.left() + radius, rect.bottom(), rect.right() - radius, rect.bottom())
        )

        text = QtGui.QColor("#ffffff" if tokens.mode.value == "light" else "#000000")
        if self._press_progress:
            text.setAlphaF(1.0 - 0.24 * self._press_progress)
        if not self._visual_enabled():
            text = QtGui.QColor(tokens.disabled)
        self._draw_content(painter, rect, text)
        self._draw_focus_ring(painter, rect, accent=True)


class FilledButton(AccentButton):
    pass


class TextButton(Button):
    _kind = "text"


class HyperlinkButton(TextButton):
    _h_padding = 10

    def __init__(
        self,
        text: str = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        url: str = "",
    ) -> None:
        super().__init__(text, parent)
        self.url = url
        self.clicked.connect(self.open_url)
        self.setIcon(fluent_icon(FluentIcon.OPEN))
        self.setMinimumWidth(0)
        self.setMinimumHeight(30)

    def sizeHint(self) -> QtCore.QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QtCore.QSize(text_width + 34, 30)

    def open_url(self):
        if self.url:
            url = QtCore.QUrl(self.url)
            if url.isValid() and url.scheme().lower() in ("http", "https", "mailto"):
                QtGui.QDesktopServices.openUrl(url)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        rect = self._paint_rect()
        color = self._surface_color()
        if self.isEnabled():
            color = _mix_color(color, self._surface_hover_color(), self._hover_progress)
            color = _mix_color(color, self._surface_pressed_color(), self._press_progress)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, theme.tokens.radius, theme.tokens.radius)

        accent = QtGui.QColor(tokens.accent if self.isEnabled() else tokens.disabled)
        if self._press_progress:
            accent.setAlphaF(1.0 - 0.28 * self._press_progress)

        content_rect = rect.adjusted(self._h_padding, 0, -self._h_padding, 0)
        icon_size = QtCore.QSize(14, 14)
        icon_rect = QtCore.QRect(
            int(content_rect.left()),
            int(content_rect.center().y() - icon_size.height() / 2),
            icon_size.width(),
            icon_size.height(),
        )
        self._draw_tinted_icon(painter, icon_rect, accent)

        text_rect = QtCore.QRectF(
            icon_rect.right() + 8, rect.top(), content_rect.width() - 22, rect.height()
        )
        painter.setPen(accent)
        painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())
        self._draw_focus_ring(painter, rect)


class OutlinedButton(Button):
    _kind = "outlined"


class RoundButton(Button):
    _pill = True


class RoundAccentButton(AccentButton):
    _pill = True


class IconButton(Button):
    def __init__(
        self,
        icon: QtGui.QIcon,
        parent: QtWidgets.QWidget | None = None,
        *,
        tooltip: str = "",
    ) -> None:
        super().__init__("", parent)
        self.setIcon(icon)
        self.setIconSize(QtCore.QSize(16, 16))
        self.setFixedSize(32, 32)
        if tooltip:
            self.setToolTip(tooltip)


class AccentIconButton(AccentButton):
    def __init__(self, icon, parent=None):
        super().__init__("", parent)
        self.setIcon(fluent_icon(icon) if isinstance(icon, FluentIcon) else icon)
        self.setFixedSize(32, 32)


class TransparentIconButton(TextButton):
    def __init__(self, icon, parent=None):
        super().__init__("", parent)
        self.setIcon(fluent_icon(icon) if isinstance(icon, FluentIcon) else icon)
        self.setFixedSize(32, 32)


def _mix_color(start: QtGui.QColor, end: QtGui.QColor, progress: float) -> QtGui.QColor:
    progress = max(0.0, min(1.0, progress))
    return QtGui.QColor(
        round(start.red() + (end.red() - start.red()) * progress),
        round(start.green() + (end.green() - start.green()) * progress),
        round(start.blue() + (end.blue() - start.blue()) * progress),
        round(start.alpha() + (end.alpha() - start.alpha()) * progress),
    )


def _readable_on(color: QtGui.QColor) -> QtGui.QColor:
    luminance = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
    return QtGui.QColor("#000000" if luminance > 0.58 else "#ffffff")
