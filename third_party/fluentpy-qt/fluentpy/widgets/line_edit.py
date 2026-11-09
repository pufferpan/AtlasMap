from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


class LineEdit(QtWidgets.QLineEdit):
    def __init__(
        self,
        placeholder: str = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        show_clear_button: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._show_clear_button = show_clear_button
        self._hover_progress = 0.0
        self._focus_progress = 0.0
        self._press_progress = 0.0
        self._hover_animation = self._make_state_animation("_hover_progress")
        self._focus_animation = self._make_state_animation("_focus_progress")
        self._press_animation = self._make_state_animation("_press_progress")
        self._trailing_inset = 34 if show_clear_button else 10
        self._leading_inset = 10
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(34)
        self.setFrame(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self._apply_text_margins()
        self._clear_button = _ClearButton(self)
        self._clear_button.clicked.connect(self.clear)
        self._clear_button.hide()
        self._clear_action = self._clear_button
        self.textChanged.connect(self._update_clear_action)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def set_clear_button_enabled(self, enabled: bool) -> None:
        self._show_clear_button = enabled
        self._trailing_inset = 34 if enabled else 10
        self._apply_text_margins()
        self._update_clear_action(self.text())

    def set_trailing_inset(self, width: int) -> None:
        self._trailing_inset = max(0, width)
        self._apply_text_margins()
        self._position_clear_button()

    def set_leading_inset(self, width: int) -> None:
        self._leading_inset = max(0, width)
        self._apply_text_margins()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_clear_button()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._animate_state(self._hover_animation, self._hover_progress, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._animate_state(self._hover_animation, self._hover_progress, 0.0)
        super().leaveEvent(event)

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        self._animate_state(self._focus_animation, self._focus_progress, 1.0, 140)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        self._animate_state(self._focus_animation, self._focus_progress, 0.0, 160)
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._animate_state(self._press_animation, self._press_progress, 1.0, 70)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._animate_state(self._press_animation, self._press_progress, 0.0, 130)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.tokens.radius

        bg = _input_surface_color()
        bg = _mix_color(bg, _input_hover_color(), self._hover_progress)
        bg = _mix_color(bg, _input_pressed_color(), self._press_progress)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        border = _input_border_color()
        active_border = QtGui.QColor(theme.tokens.accent)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        line_left = rect.left() + radius + 2
        line_right = rect.right() - radius - 2
        line_y = rect.bottom() - 1
        lower = _input_lower_color()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(clip)
        painter.setPen(QtGui.QPen(lower, 1))
        painter.drawLine(QtCore.QLineF(line_left, line_y, line_right, line_y))
        if self._focus_progress:
            line_width = max(24.0, (line_right - line_left) * self._focus_progress)
            center = rect.center().x()
            painter.setPen(QtGui.QPen(active_border, 2))
            painter.drawLine(
                QtCore.QLineF(
                    max(line_left, center - line_width / 2),
                    line_y,
                    min(line_right, center + line_width / 2),
                    line_y,
                )
            )
        painter.restore()
        painter.end()
        super().paintEvent(event)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"""
QLineEdit {{
    background: transparent;
    color: {theme.tokens.text};
    border: none;
    padding: 0;
    selection-background-color: {theme.tokens.accent};
    font-size: {theme.tokens.font_size}px;
}}
QLineEdit:disabled {{
    color: {theme.tokens.disabled};
}}
"""
        )
        self._clear_button.update()
        self.update()

    def _update_clear_action(self, text: str) -> None:
        self._clear_button.setVisible(self._show_clear_button and bool(text))
        self._position_clear_button()

    def _position_clear_button(self) -> None:
        if not self._show_clear_button:
            self._clear_button.hide()
            return
        size = 24
        right_margin = max(4, self._trailing_inset - size - 4)
        self._clear_button.setGeometry(
            self.width() - right_margin - size,
            int((self.height() - size) / 2),
            size,
            size,
        )

    def _apply_text_margins(self) -> None:
        self.setTextMargins(self._leading_inset, 0, self._trailing_inset, 0)

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


class TextEdit(QtWidgets.QTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setMinimumHeight(128)
        self.setAcceptRichText(True)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def _apply_theme(self) -> None:
        tokens = theme.tokens
        bg = (
            "rgba(255, 255, 255, 0.7)"
            if tokens.mode.value == "light"
            else "rgba(255, 255, 255, 0.0605)"
        )
        hover = (
            "rgba(249, 249, 249, 0.5)"
            if tokens.mode.value == "light"
            else "rgba(255, 255, 255, 0.0837)"
        )
        border = (
            "rgba(0, 0, 0, 0.073)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.053)"
        )
        lower = (
            "rgba(0, 0, 0, 0.183)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.08)"
        )
        self.setStyleSheet(
            f"""
QTextEdit {{
    background: {bg};
    color: {tokens.text};
    border: 1px solid {border};
    border-bottom: 1px solid {lower};
    border-radius: {tokens.radius}px;
    padding: 10px 12px;
    selection-background-color: {tokens.accent};
    font-size: {tokens.font_size}px;
}}
QTextEdit:hover {{
    background: {hover};
}}
QTextEdit:focus {{
    border: 1px solid {border};
    border-bottom: 1px solid {tokens.accent};
}}
"""
        )


RichTextEdit = TextEdit


class SearchLineEdit(LineEdit):
    def __init__(self, placeholder: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(placeholder, parent)
        self.set_leading_inset(34)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = QtGui.QColor(theme.tokens.text_muted)
        color.setAlpha(210)
        painter.setPen(
            QtGui.QPen(color, 1.45, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        circle = QtCore.QRectF(13, self.height() / 2 - 5, 10, 10)
        painter.drawEllipse(circle)
        painter.drawLine(
            QtCore.QLineF(
                circle.right() - 1.5, circle.bottom() - 1.5, circle.right() + 3, circle.bottom() + 3
            )
        )


class PasswordLineEdit(LineEdit):
    def __init__(self, placeholder: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(placeholder, parent, show_clear_button=False)
        self._password_visible = False
        self.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.set_trailing_inset(38)
        self._reveal_button = _RevealButton(self)
        self._reveal_button.clicked.connect(self._toggle_password_visible)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reveal_button.setGeometry(self.width() - 32, int((self.height() - 24) / 2), 24, 24)

    def _toggle_password_visible(self) -> None:
        self._password_visible = not self._password_visible
        self.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Normal
            if self._password_visible
            else QtWidgets.QLineEdit.EchoMode.Password
        )
        self._reveal_button.setChecked(self._password_visible)


class SpinBox(QtWidgets.QSpinBox):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        _init_spin_box_chrome(self)
        self.setMinimumHeight(34)
        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setFrame(False)
        self.setRange(0, 999)
        self._up_button = _SpinArrowButton("up", self)
        self._down_button = _SpinArrowButton("down", self)
        self._up_button.clicked.connect(lambda: self.stepBy(1))
        self._down_button.clicked.connect(lambda: self.stepBy(-1))
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        _spin_box_enter_event(self)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        _spin_box_leave_event(self)
        super().leaveEvent(event)

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        _spin_box_focus_in_event(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        _spin_box_focus_out_event(self)
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        _spin_box_mouse_press_event(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        _spin_box_mouse_release_event(self)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        button_w = 28
        half_h = max(14, self.height() // 2)
        self._up_button.setGeometry(self.width() - button_w - 2, 2, button_w, half_h - 2)
        self._down_button.setGeometry(
            self.width() - button_w - 2, half_h, button_w, self.height() - half_h - 2
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        _paint_spin_box_chrome(self)
        super().paintEvent(event)

    def _apply_theme(self) -> None:
        _apply_spin_box_theme(self)
        self._up_button.update()
        self._down_button.update()


class DoubleSpinBox(QtWidgets.QDoubleSpinBox):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        _init_spin_box_chrome(self)
        self.setMinimumHeight(34)
        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setFrame(False)
        self.setRange(0.0, 999.0)
        self.setDecimals(1)
        self._up_button = _SpinArrowButton("up", self)
        self._down_button = _SpinArrowButton("down", self)
        self._up_button.clicked.connect(lambda: self.stepBy(1))
        self._down_button.clicked.connect(lambda: self.stepBy(-1))
        _apply_spin_box_theme(self)
        theme.subscribe(self, self._apply_theme)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        _spin_box_enter_event(self)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        _spin_box_leave_event(self)
        super().leaveEvent(event)

    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        _spin_box_focus_in_event(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        _spin_box_focus_out_event(self)
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        _spin_box_mouse_press_event(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        _spin_box_mouse_release_event(self)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        button_w = 28
        half_h = max(14, self.height() // 2)
        self._up_button.setGeometry(self.width() - button_w - 2, 2, button_w, half_h - 2)
        self._down_button.setGeometry(
            self.width() - button_w - 2, half_h, button_w, self.height() - half_h - 2
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        _paint_spin_box_chrome(self)
        super().paintEvent(event)

    def _apply_theme(self) -> None:
        _apply_spin_box_theme(self)
        self._up_button.update()
        self._down_button.update()


def _init_spin_box_chrome(widget: QtWidgets.QAbstractSpinBox) -> None:
    widget.setFont(ui_font(theme.tokens.font_size, widget.font()))
    widget._hover_progress = 0.0  # type: ignore[attr-defined]
    widget._focus_progress = 0.0  # type: ignore[attr-defined]
    widget._press_progress = 0.0  # type: ignore[attr-defined]
    widget._hover_animation = _make_spin_animation(widget, "_hover_progress")  # type: ignore[attr-defined]
    widget._focus_animation = _make_spin_animation(widget, "_focus_progress")  # type: ignore[attr-defined]
    widget._press_animation = _make_spin_animation(widget, "_press_progress")  # type: ignore[attr-defined]
    widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_MacShowFocusRect, False)


def _make_spin_animation(widget: QtWidgets.QAbstractSpinBox, attr: str) -> QtCore.QVariantAnimation:
    animation = QtCore.QVariantAnimation(widget)
    animation.setDuration(theme.tokens.animation_ms)
    animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
    animation.valueChanged.connect(
        lambda value, target=widget, name=attr: _set_spin_state(target, name, float(value))
    )
    return animation


def _animate_spin_state(
    widget: QtWidgets.QAbstractSpinBox,
    attr: str,
    end: float,
    duration: int | None = None,
) -> None:
    animation = getattr(widget, attr)
    progress_name = attr.replace("_animation", "_progress")
    animation.stop()
    animation.setDuration(duration or theme.tokens.animation_ms)
    animation.setStartValue(float(getattr(widget, progress_name)))
    animation.setEndValue(end)
    animation.start()


def _set_spin_state(widget: QtWidgets.QAbstractSpinBox, attr: str, value: float) -> None:
    setattr(widget, attr, max(0.0, min(1.0, value)))
    widget.update()


def _spin_box_enter_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_hover_animation", 1.0)


def _spin_box_leave_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_hover_animation", 0.0)
    _animate_spin_state(widget, "_press_animation", 0.0, 90)


def _spin_box_focus_in_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_focus_animation", 1.0, 140)


def _spin_box_focus_out_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_focus_animation", 0.0, 160)


def _spin_box_mouse_press_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_press_animation", 1.0, 70)


def _spin_box_mouse_release_event(widget: QtWidgets.QAbstractSpinBox) -> None:
    _animate_spin_state(widget, "_press_animation", 0.0, 130)


def _paint_spin_box_chrome(widget: QtWidgets.QAbstractSpinBox) -> None:
    painter = QtGui.QPainter(widget)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    rect = QtCore.QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    radius = theme.tokens.radius

    bg = _input_surface_color()
    bg = _mix_color(bg, _input_hover_color(), float(getattr(widget, "_hover_progress", 0.0)))
    bg = _mix_color(bg, _input_pressed_color(), float(getattr(widget, "_press_progress", 0.0)))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(rect, radius, radius)

    border = _input_border_color()
    painter.setPen(QtGui.QPen(border, 1))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)

    line_left = rect.left() + radius + 2
    line_right = rect.right() - radius - 2
    line_y = rect.bottom() - 1
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(clip)
    painter.setPen(QtGui.QPen(_input_lower_color(), 1))
    painter.drawLine(QtCore.QLineF(line_left, line_y, line_right, line_y))
    focus_progress = float(getattr(widget, "_focus_progress", 0.0))
    if focus_progress:
        line_width = max(24.0, (line_right - line_left) * focus_progress)
        center = rect.center().x()
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.accent), 2))
        painter.drawLine(
            QtCore.QLineF(
                max(line_left, center - line_width / 2),
                line_y,
                min(line_right, center + line_width / 2),
                line_y,
            )
        )
    painter.restore()
    painter.end()


def _apply_spin_box_theme(widget: QtWidgets.QAbstractSpinBox) -> None:
    tokens = theme.tokens
    widget.setStyleSheet(
        f"""
QAbstractSpinBox {{
    background: transparent;
    color: {tokens.text};
    border: none;
    padding: 0 34px 0 10px;
    selection-background-color: {tokens.accent};
    font-size: {tokens.font_size}px;
}}
"""
    )


class _SpinArrowButton(QtWidgets.QAbstractButton):
    def __init__(self, direction: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.direction = direction
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._hover_progress = 0.0
        self._hover_animation = QtCore.QVariantAnimation(self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_progress)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._animate_hover(1.0, 90)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._animate_hover(0.0, 140)
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(4, 1, -4, -1)

        fill = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
        fill.setAlpha(
            round((14 if theme.tokens.mode.value == "light" else 22) * self._hover_progress)
        )
        if fill.alpha() > 0:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)

        color = QtGui.QColor("#5f6368" if theme.tokens.mode.value == "light" else "#f2f5fa")
        painter.setPen(
            QtGui.QPen(
                color,
                1.35,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        cx = self.width() / 2
        cy = self.height() / 2
        if self.direction == "up":
            path = QtGui.QPainterPath(QtCore.QPointF(cx - 4, cy + 2))
            path.lineTo(cx, cy - 2)
            path.lineTo(cx + 4, cy + 2)
        else:
            path = QtGui.QPainterPath(QtCore.QPointF(cx - 4, cy - 2))
            path.lineTo(cx, cy + 2)
            path.lineTo(cx + 4, cy - 2)
        painter.drawPath(path)

    def _animate_hover(self, end: float, duration: int) -> None:
        self._hover_animation.stop()
        self._hover_animation.setDuration(duration)
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(end)
        self._hover_animation.start()

    def _set_hover_progress(self, value: object) -> None:
        self._hover_progress = float(value)
        self.update()


class _ClearButton(QtWidgets.QAbstractButton):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setFixedSize(24, 24)
        self._hover_progress = 0.0
        self._press_progress = 0.0
        self._hover_animation = self._make_animation("_hover_progress")
        self._press_animation = self._make_animation("_press_progress")

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._animate(self._hover_animation, self._hover_progress, 1.0, 90)
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._animate(self._hover_animation, self._hover_progress, 0.0, 140)
        self._animate(self._press_animation, self._press_progress, 0.0, 90)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._animate(self._press_animation, self._press_progress, 1.0, 60)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._animate(self._press_animation, self._press_progress, 0.0, 120)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(3, 3, -3, -3)

        fill = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
        hover_alpha = 18 if theme.tokens.mode.value == "light" else 26
        press_alpha = 28 if theme.tokens.mode.value == "light" else 38
        fill.setAlpha(
            round(hover_alpha * self._hover_progress + press_alpha * self._press_progress)
        )
        if fill.alpha() > 0:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)

        color = QtGui.QColor("#5f6368" if theme.tokens.mode.value == "light" else "#f2f5fa")
        if self._press_progress:
            color = _mix_color(color, QtGui.QColor(theme.tokens.text), self._press_progress)
        painter.setPen(
            QtGui.QPen(color, 1.25, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        icon = QtCore.QRectF(self.rect()).adjusted(8, 8, -8, -8)
        painter.drawLine(QtCore.QLineF(icon.topLeft(), icon.bottomRight()))
        painter.drawLine(QtCore.QLineF(icon.topRight(), icon.bottomLeft()))

    def _make_animation(self, attr: str) -> QtCore.QVariantAnimation:
        animation = QtCore.QVariantAnimation(self)
        animation.setDuration(theme.tokens.animation_ms)
        animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(
            lambda value, name=attr: self._set_state_value(name, float(value))
        )
        return animation

    def _animate(
        self,
        animation: QtCore.QVariantAnimation,
        start: float,
        end: float,
        duration: int,
    ) -> None:
        animation.stop()
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _set_state_value(self, attr: str, value: float) -> None:
        setattr(self, attr, max(0.0, min(1.0, value)))
        self.update()


class _RevealButton(_ClearButton):
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(3, 3, -3, -3)
        fill = QtGui.QColor("#000000" if theme.tokens.mode.value == "light" else "#ffffff")
        fill.setAlpha(
            round((18 if theme.tokens.mode.value == "light" else 26) * self._hover_progress)
        )
        if fill.alpha() > 0:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)

        color = QtGui.QColor("#5f6368" if theme.tokens.mode.value == "light" else "#f2f5fa")
        painter.setPen(
            QtGui.QPen(color, 1.2, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
        )
        eye = QtGui.QPainterPath()
        eye.moveTo(6, 12)
        eye.cubicTo(8, 8, 16, 8, 18, 12)
        eye.cubicTo(16, 16, 8, 16, 6, 12)
        painter.drawPath(eye)
        painter.drawEllipse(QtCore.QRectF(10, 10, 4, 4))
        if not self.isChecked():
            painter.drawLine(QtCore.QLineF(7, 17, 17, 7))


def _input_surface_color() -> QtGui.QColor:
    color = QtGui.QColor("#ffffff")
    color.setAlphaF(0.70 if theme.tokens.mode.value == "light" else 0.0605)
    return color


def _input_hover_color() -> QtGui.QColor:
    color = QtGui.QColor("#f9f9f9" if theme.tokens.mode.value == "light" else "#ffffff")
    color.setAlphaF(0.50 if theme.tokens.mode.value == "light" else 0.0837)
    return color


def _input_pressed_color() -> QtGui.QColor:
    color = QtGui.QColor("#f9f9f9" if theme.tokens.mode.value == "light" else "#ffffff")
    color.setAlphaF(0.30 if theme.tokens.mode.value == "light" else 0.0326)
    return color


def _input_border_color() -> QtGui.QColor:
    return (
        QtGui.QColor(0, 0, 0, 18)
        if theme.tokens.mode.value == "light"
        else QtGui.QColor(255, 255, 255, 14)
    )


def _input_lower_color() -> QtGui.QColor:
    return (
        QtGui.QColor(0, 0, 0, 46)
        if theme.tokens.mode.value == "light"
        else QtGui.QColor(255, 255, 255, 24)
    )


def _mix_color(start: QtGui.QColor, end: QtGui.QColor, progress: float) -> QtGui.QColor:
    progress = max(0.0, min(1.0, progress))
    return QtGui.QColor(
        round(start.red() + (end.red() - start.red()) * progress),
        round(start.green() + (end.green() - start.green()) * progress),
        round(start.blue() + (end.blue() - start.blue()) * progress),
        round(start.alpha() + (end.alpha() - start.alpha()) * progress),
    )
