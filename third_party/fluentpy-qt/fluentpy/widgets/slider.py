from __future__ import annotations

import math

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme


class Slider(QtWidgets.QSlider):
    def __init__(
        self,
        orientation: QtCore.Qt.Orientation = QtCore.Qt.Orientation.Horizontal,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setMinimumSize(34, 34)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._hovered_handle = False
        self._pressed_handle = False
        self._center_progress = 0.0
        self._press_progress = 0.0
        self._track_gradient = None
        self._track_checkerboard = False
        self._track_thickness = 4
        self._drag_offset = 0.0
        self._keyboard_focus = False
        self._pointer_dragging = False
        self._display_position = float(self.sliderPosition())
        self._position_animation = QtCore.QVariantAnimation(self)
        self._position_animation.setDuration(170)
        self._position_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._position_animation.valueChanged.connect(self._set_display_position)
        self._center_animation = QtCore.QVariantAnimation(self)
        self._center_animation.setDuration(theme.tokens.animation_ms)
        self._center_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._center_animation.valueChanged.connect(self._set_center_progress)
        self._press_animation = QtCore.QVariantAnimation(self)
        self._press_animation.setDuration(90)
        self._press_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._press_animation.valueChanged.connect(self._set_press_progress)
        self.setMouseTracking(True)
        self.valueChanged.connect(self._sync_visual_position)
        self.sliderMoved.connect(self._sync_visual_position)
        self.rangeChanged.connect(self._reset_visual_position)
        theme.subscribe(self, self._refresh_style)

    def sizeHint(self):
        return (
            QtCore.QSize(200, 34)
            if self.orientation() == QtCore.Qt.Orientation.Horizontal
            else QtCore.QSize(34, 200)
        )

    def minimumSizeHint(self):
        return (
            QtCore.QSize(60, 34)
            if self.orientation() == QtCore.Qt.Orientation.Horizontal
            else QtCore.QSize(34, 60)
        )

    def _refresh_style(self):
        self.update()

    def set_track_gradient(self, stops, *, checkerboard=False, thickness=10):
        """Use a full-length gradient track while retaining the native slider input."""
        if (
            not isinstance(thickness, int)
            or isinstance(thickness, bool)
            or not 2 <= thickness <= 18
        ):
            raise ValueError("thickness must be an integer between 2 and 18")
        normalized = []
        for position, color in stops:
            position, color = float(position), QtGui.QColor(color)
            if not math.isfinite(position) or not 0 <= position <= 1 or not color.isValid():
                raise ValueError("gradient stops require positions in [0, 1] and valid colors")
            normalized.append((position, color))
        if len(normalized) < 2:
            raise ValueError("a gradient requires at least two stops")
        self._track_gradient = sorted(normalized, key=lambda stop: stop[0])
        self._track_checkerboard = bool(checkerboard)
        self._track_thickness = thickness
        self.update()

    def clear_track_gradient(self):
        self._track_gradient = None
        self._track_checkerboard = False
        self._track_thickness = 4
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        hovered = self._handle_rect().contains(event.position())
        if hovered != self._hovered_handle:
            self._hovered_handle = hovered
            self._animate_center(1.0 if hovered else 0.0)
        if self.isSliderDown():
            self._pointer_dragging = True
            self.setSliderPosition(self._value_at(event.position()))
            self._sync_visual_position()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton or not self.isEnabled():
            return super().mousePressEvent(event)
        self._keyboard_focus = False
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        on_handle = self._handle_rect().contains(event.position())
        axis = (
            event.position().x()
            if self.orientation() == QtCore.Qt.Orientation.Horizontal
            else event.position().y()
        )
        self._drag_offset = axis - self._geometry_values()[3] if on_handle else 0.0
        self._pointer_dragging = on_handle
        self._pressed_handle = True
        self._animate_press(1.0)
        self.setSliderDown(True)
        self.setSliderPosition(self._value_at(event.position()))
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderPosition(self._value_at(event.position()))
            if not self.hasTracking():
                self.setValue(self.sliderPosition())
            self.setSliderDown(False)
            self._pressed_handle = False
            self._animate_press(0.0)
            self._drag_offset = 0.0
            self._pointer_dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if self._hovered_handle:
            self._hovered_handle = False
            self._animate_center(0.0)
        if self._pressed_handle and not self.isSliderDown():
            self._pressed_handle = False
            self._animate_press(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self._draw_track(painter, self.minimum(), self._display_position)
        self._draw_handle(painter, self._display_position, active=True)

    def _point_for_value(self, value):
        start, end, cross, _knob = self._geometry_values(value)
        return (
            QtCore.QPointF(_knob, cross)
            if self.orientation() == QtCore.Qt.Orientation.Horizontal
            else QtCore.QPointF(cross, _knob)
        )

    def _track_rect(self, a, b, thickness):
        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            return QtCore.QRectF(
                min(a.x(), b.x()), a.y() - thickness / 2, abs(b.x() - a.x()), thickness
            )
        return QtCore.QRectF(
            a.x() - thickness / 2, min(a.y(), b.y()), thickness, abs(b.y() - a.y())
        )

    def _draw_track(self, painter, lower, upper):
        tokens = theme.tokens
        start, end = self._point_for_value(self.minimum()), self._point_for_value(self.maximum())
        if self.minimum() == self.maximum():
            first, last, cross, _knob = self._geometry_values()
            if self.orientation() == QtCore.Qt.Orientation.Horizontal:
                start, end = QtCore.QPointF(first, cross), QtCore.QPointF(last, cross)
            else:
                start, end = QtCore.QPointF(cross, first), QtCore.QPointF(cross, last)
        track_color = QtGui.QColor(tokens.text)
        track_color.setAlpha(80 if self.isEnabled() else 34)
        accent = QtGui.QColor(tokens.accent)
        if not self.isEnabled():
            accent = QtGui.QColor(tokens.disabled)

        thickness = self._track_thickness
        track_rect = self._track_rect(start, end, thickness)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        if self._track_gradient is None:
            painter.setBrush(track_color)
            painter.drawRoundedRect(track_rect, 2, 2)
            filled_rect = self._track_rect(
                self._point_for_value(lower), self._point_for_value(upper), 4
            )
            painter.setBrush(accent)
            painter.drawRoundedRect(filled_rect, 2, 2)
        else:
            path = QtGui.QPainterPath()
            path.addRoundedRect(track_rect, thickness / 2, thickness / 2)
            painter.save()
            painter.setClipPath(path)
            if self._track_checkerboard:
                painter.fillRect(track_rect, QtGui.QColor("#ffffff"))
                for x in range(int(track_rect.left()), int(track_rect.right()) + 6, 6):
                    for y in range(int(track_rect.top()), int(track_rect.bottom()) + 6, 6):
                        if (
                            (x - int(track_rect.left())) // 6 + (y - int(track_rect.top())) // 6
                        ) % 2:
                            painter.fillRect(QtCore.QRectF(x, y, 6, 6), QtGui.QColor("#c2c5ca"))
            gradient = QtGui.QLinearGradient(start, end)
            for position, color in self._track_gradient:
                gradient.setColorAt(position, color)
            painter.fillPath(path, gradient)
            painter.restore()

    def _draw_handle(self, painter, value, *, active):
        tokens = theme.tokens
        center = self._point_for_value(value)
        accent = QtGui.QColor(tokens.accent if self.isEnabled() else tokens.disabled)
        hover = self._center_progress if active else 0.0
        press = self._press_progress if active else 0.0
        if active and hover > 0 and self.isEnabled():
            halo = QtGui.QColor(accent)
            halo.setAlpha(round(20 * hover))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, 12 + hover, 12 + hover)
        painter.setBrush(QtGui.QColor(tokens.surface if tokens.mode.value == "dark" else "#ffffff"))
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens.border), 1))
        radius = 9 + 0.65 * hover - 0.35 * press
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        center_radius = max(
            1.9, 4 + (1.4 * self._center_progress - 2.7 * self._press_progress if active else 0)
        )
        painter.drawEllipse(center, center_radius, center_radius)
        if active and self.hasFocus() and self._keyboard_focus and self.isEnabled():
            painter.setPen(QtGui.QPen(accent, 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 12, 12)

    def _geometry_values(self, value=None) -> tuple[float, float, float, float]:
        left = 12.0
        horizontal = self.orientation() == QtCore.Qt.Orientation.Horizontal
        right = float(max(12, (self.width() if horizontal else self.height()) - 12))
        center_y = (self.height() if horizontal else self.width()) / 2
        option = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(option)
        value = self._visual_value() if value is None else value
        fraction = (
            0.0
            if self.maximum() == self.minimum()
            else (float(value) - self.minimum()) / (self.maximum() - self.minimum())
        )
        fraction = max(0.0, min(1.0, fraction))
        if option.upsideDown:
            fraction = 1 - fraction
        knob_x = left + (right - left) * fraction
        return left, right, center_y, knob_x

    def _value_at(self, point):
        start, end, _cross, _knob = self._geometry_values()
        option = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(option)
        axis = point.x() if self.orientation() == QtCore.Qt.Orientation.Horizontal else point.y()
        return QtWidgets.QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            round(axis - start - self._drag_offset),
            max(1, round(end - start)),
            option.upsideDown,
        )

    def _handle_rect(self) -> QtCore.QRectF:
        center = self._point_for_value(self._visual_value())
        return QtCore.QRectF(center.x() - 11, center.y() - 11, 22, 22)

    def _visual_value(self):
        return self._display_position

    def _sync_visual_position(self, *_args):
        target = float(self.sliderPosition())
        if (
            not self.isVisible()
            or not self.isEnabled()
            or (self.isSliderDown() and self._pointer_dragging)
        ):
            self._position_animation.stop()
            self._set_display_position(target)
            return
        if (
            self._position_animation.state() == QtCore.QAbstractAnimation.State.Running
            and self._position_animation.endValue() == target
        ):
            return
        self._position_animation.stop()
        if abs(self._display_position - target) < 0.001:
            self._set_display_position(target)
            return
        self._position_animation.setStartValue(self._display_position)
        self._position_animation.setEndValue(target)
        self._position_animation.start()

    def _set_display_position(self, value):
        self._display_position = float(value)
        self.update()
        self._visual_position_changed()

    def _visual_position_changed(self):
        pass

    def _reset_visual_position(self, *_args):
        self._position_animation.stop()
        self._set_display_position(float(self.sliderPosition()))

    def setSliderPosition(self, value):
        super().setSliderPosition(value)
        self._sync_visual_position()

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() not in (
            QtCore.Qt.FocusReason.MouseFocusReason,
            QtCore.Qt.FocusReason.ActiveWindowFocusReason,
        )
        if self._keyboard_focus:
            self._animate_center(1.0)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        self._animate_center(1.0 if self._hovered_handle else 0.0)
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        self._keyboard_focus = True
        self._animate_center(1.0)
        super().keyPressEvent(event)

    def _cancel_drag(self):
        self._pressed_handle = False
        self._pointer_dragging = False
        self._drag_offset = 0.0
        if self.isSliderDown():
            self.setSliderDown(False)
        self._center_animation.stop()
        self._press_animation.stop()
        self._hovered_handle = False
        self._set_center_progress(0.0)
        self._set_press_progress(0.0)
        self._reset_visual_position()

    def hideEvent(self, event):
        self._cancel_drag()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.EnabledChange and not self.isEnabled():
            self._cancel_drag()
        super().changeEvent(event)

    def _animate_center(self, end: float) -> None:
        self._center_animation.stop()
        if not self.isVisible() or not self.isEnabled() or abs(self._center_progress - end) < 0.001:
            self._set_center_progress(end if self.isVisible() and self.isEnabled() else 0.0)
            return
        self._center_animation.setStartValue(self._center_progress)
        self._center_animation.setEndValue(end)
        self._center_animation.start()

    def _animate_press(self, end: float) -> None:
        self._press_animation.stop()
        if not self.isVisible() or not self.isEnabled() or abs(self._press_progress - end) < 0.001:
            self._set_press_progress(end if self.isVisible() and self.isEnabled() else 0.0)
            return
        self._press_animation.setStartValue(self._press_progress)
        self._press_animation.setEndValue(end)
        self._press_animation.start()

    def _set_center_progress(self, value: object) -> None:
        self._center_progress = float(value)
        self.update()

    def _set_press_progress(self, value: object) -> None:
        self._press_progress = float(value)
        self.update()


class ToolTipSlider(Slider):
    """Slider with an in-window value label following the actual handle."""

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._value_format = "{value}"
        self._value_label = None
        self._tip_requested = False
        self._tip_opacity = 0.0
        self._tip_effect = None
        self._tip_fade = QtCore.QVariantAnimation(self)
        self._tip_fade.setDuration(120)
        self._tip_fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._tip_fade.valueChanged.connect(self._set_tip_opacity)
        self._tip_fade.finished.connect(self._tip_fade_finished)
        self._tip_motion = QtCore.QVariantAnimation(self)
        self._tip_motion.setDuration(150)
        self._tip_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._tip_motion.valueChanged.connect(self._set_tip_position)
        self.sliderMoved.connect(self._update_value_label)
        self.valueChanged.connect(self._update_value_label)

    def setValueFormat(self, value_format):
        """Use a format such as '{value}%' or '{value} px'."""
        value_format = str(value_format)
        try:
            value_format.format(value=self.sliderPosition())
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            raise ValueError("format must accept the value field") from exc
        self._value_format = value_format
        self._update_value_label()

    def valueFormat(self):
        return self._value_format

    def _update_value_label(self, *args):
        if getattr(self, "_tip_requested", False):
            self.show_value_tip()

    def _visual_position_changed(self):
        if getattr(self, "_tip_requested", False) and self._value_label is not None:
            self._tip_motion.stop()
            self._value_label.move(self._tip_target())

    def _tip_target(self):
        label, owner = self._value_label, self.window()
        point = self.mapTo(owner, self._point_for_value(self._visual_value()).toPoint())
        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            x, y = point.x() - label.width() // 2, point.y() - label.height() - 18
            if y < 4:
                y = point.y() + 18
        else:
            x, y = point.x() + 18, point.y() - label.height() // 2
            if x + label.width() > owner.width() - 4:
                x = point.x() - label.width() - 18
        return QtCore.QPoint(
            max(4, min(x, owner.width() - label.width() - 4)),
            max(4, min(y, owner.height() - label.height() - 4)),
        )

    def _set_tip_opacity(self, opacity):
        self._tip_opacity = float(opacity)
        if self._tip_effect is not None:
            self._tip_effect.setOpacity(self._tip_opacity)

    def _set_tip_position(self, point):
        if self._value_label is not None:
            label, owner = self._value_label, self.window()
            self._value_label.move(
                max(4, min(point.x(), owner.width() - label.width() - 4)),
                max(4, min(point.y(), owner.height() - label.height() - 4)),
            )

    def _tip_fade_finished(self):
        if not self._tip_requested and self._value_label is not None:
            self._value_label.hide()

    def _value_label_destroyed(self):
        self._tip_fade.stop()
        self._tip_motion.stop()
        self._value_label = self._tip_effect = None
        self._tip_requested = False
        self._tip_opacity = 0.0

    def show_value_tip(self):
        if not self.isVisible() or not self.isEnabled():
            return
        owner = self.window()
        if self._value_label is None or self._value_label.parentWidget() is not owner:
            if self._value_label is not None:
                self.hide_value_tip(immediate=True)
                self._value_label.destroyed.disconnect(self._value_label_destroyed)
                self._value_label.deleteLater()
            self._value_label = QtWidgets.QLabel(owner)
            self._value_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._value_label.destroyed.connect(self._value_label_destroyed)
            self.destroyed.connect(self._value_label.deleteLater)
            self._tip_effect = QtWidgets.QGraphicsOpacityEffect(self._value_label)
            self._value_label.setGraphicsEffect(self._tip_effect)
            self._tip_effect.setOpacity(0.0)
        label = self._value_label
        label.setFont(self.font())
        label.setText(self._value_format.format(value=self.sliderPosition()))
        label.setStyleSheet(
            f"background:{theme.tokens.surface};color:{theme.tokens.text};border:1px solid {theme.tokens.border};border-radius:5px;padding:5px 9px;"
        )
        label.adjustSize()
        target = self._tip_target()
        if self._tip_requested:
            if self._tip_motion.state() != QtCore.QAbstractAnimation.State.Running:
                label.move(target)
            else:
                self._tip_motion.setEndValue(target)
            return
        self._tip_requested = True
        was_visible = label.isVisible()
        self._tip_fade.stop()
        self._tip_motion.stop()
        if not was_visible:
            self._tip_opacity = 0.0
            self._set_tip_position(target + QtCore.QPoint(0, 6))
        label.show()
        label.raise_()
        self._tip_fade.setStartValue(self._tip_opacity)
        self._tip_fade.setEndValue(1.0)
        self._tip_fade.start()
        self._tip_motion.setStartValue(label.pos())
        self._tip_motion.setEndValue(target)
        self._tip_motion.start()

    def hide_value_tip(self, *, immediate=False):
        self._tip_requested = False
        self._tip_fade.stop()
        self._tip_motion.stop()
        if self._value_label is None:
            return
        if immediate:
            self._set_tip_opacity(0.0)
            self._value_label.hide()
            return
        self._tip_fade.setStartValue(self._tip_opacity)
        self._tip_fade.setEndValue(0.0)
        self._tip_fade.start()
        self._tip_motion.setStartValue(self._value_label.pos())
        self._tip_motion.setEndValue(self._value_label.pos() + QtCore.QPoint(0, 4))
        self._tip_motion.start()

    def enterEvent(self, event):
        self.show_value_tip()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.show_value_tip()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.isSliderDown() or self.underMouse():
            self.show_value_tip()

    def leaveEvent(self, event):
        if not self.isSliderDown():
            self.hide_value_tip()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self.underMouse():
            self.hide_value_tip()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.show_value_tip()

    def focusOutEvent(self, event):
        self.hide_value_tip()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self.hide_value_tip(immediate=True)
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.EnabledChange and not self.isEnabled():
            self.hide_value_tip(immediate=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_value_label()

    def _refresh_style(self):
        super()._refresh_style()
        self._update_value_label()


class RangeSlider(Slider):
    """Ordered pair of native slider values. Handles never cross.

    Qt's rangeChanged still describes the allowed bounds; valuesChanged is the
    selected interval. Tab changes controls, Space switches the active handle.
    """

    valuesChanged = Signal(int, int)
    lowerValueChanged = Signal(int)
    upperValueChanged = Signal(int)

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        self._lower, self._upper = 25, 75
        self._display_lower, self._display_upper = 25.0, 75.0
        self._range_animation = None
        self._active_handle = "lower"
        self._syncing = False
        super().__init__(orientation, parent)
        self._range_animation = QtCore.QVariantAnimation(self)
        self._range_animation.setDuration(170)
        self._range_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._range_animation.valueChanged.connect(self._set_display_range_progress)
        self._range_start = self._range_end = (25.0, 75.0)
        self.valueChanged.connect(self._native_value_changed)
        self.sliderMoved.connect(self._position_changed)
        self.rangeChanged.connect(self._bounds_changed)
        self._sync_native()
        self.setAccessibleName("区间选择")

    def values(self):
        return self._lower, self._upper

    def lowerValue(self):
        return self._lower

    def upperValue(self):
        return self._upper

    def setValues(self, lower, upper):
        if not isinstance(lower, int) or not isinstance(upper, int):
            raise TypeError("range values must be integers")
        if not self.minimum() <= lower <= upper <= self.maximum():
            raise ValueError("values must be ordered and inside the slider bounds")
        previous = self.values()
        self._lower, self._upper = lower, upper
        self._sync_native()
        self._emit_values(previous)

    def setLowerValue(self, value):
        self.setValues(value, self._upper)

    def setUpperValue(self, value):
        self.setValues(self._lower, value)

    def activeHandle(self):
        return self._active_handle

    def setActiveHandle(self, handle):
        if handle not in ("lower", "upper"):
            raise ValueError("handle must be lower or upper")
        self._active_handle = handle
        self._sync_native()
        self.update()

    def _sync_native(self):
        self._syncing = True
        QtWidgets.QSlider.setValue(
            self, self._lower if self._active_handle == "lower" else self._upper
        )
        self._syncing = False

    def _emit_values(self, previous):
        if self.values() == previous:
            return
        if self._lower != previous[0]:
            self.lowerValueChanged.emit(self._lower)
        if self._upper != previous[1]:
            self.upperValueChanged.emit(self._upper)
        self.valuesChanged.emit(*self.values())
        self.setAccessibleDescription(f"{self._lower} – {self._upper}")
        self._sync_visual_position()
        self.update()

    def _visual_value(self):
        return self._display_lower if self._active_handle == "lower" else self._display_upper

    def _visual_range_target(self):
        lower, upper = self.values()
        if self.isSliderDown() and not self.hasTracking():
            if self._active_handle == "lower":
                lower = self.sliderPosition()
            else:
                upper = self.sliderPosition()
        return float(lower), float(upper)

    def _sync_visual_position(self, *_args):
        if self._range_animation is None:
            return
        target = self._visual_range_target()
        if (
            not self.isVisible()
            or not self.isEnabled()
            or (self.isSliderDown() and self._pointer_dragging)
        ):
            self._range_animation.stop()
            self._display_lower, self._display_upper = target
            self.update()
            return
        if (
            self._range_animation.state() == QtCore.QAbstractAnimation.State.Running
            and target == self._range_end
        ):
            return
        self._range_animation.stop()
        current = self._display_lower, self._display_upper
        if current == target:
            return
        self._range_start, self._range_end = current, target
        self._range_animation.setStartValue(0.0)
        self._range_animation.setEndValue(1.0)
        self._range_animation.start()

    def _set_display_range_progress(self, progress):
        fraction = float(progress)
        self._display_lower, self._display_upper = tuple(
            start + (end - start) * fraction
            for start, end in zip(self._range_start, self._range_end)
        )
        self.update()

    def _reset_visual_position(self, *_args):
        super()._reset_visual_position()
        if self._range_animation is not None:
            self._range_animation.stop()
        self._display_lower, self._display_upper = self._visual_range_target()
        self.update()

    def _native_value_changed(self, value):
        if self._syncing:
            return
        previous = self.values()
        self._lower = max(self.minimum(), min(self._lower, self.maximum()))
        self._upper = max(self.minimum(), min(self._upper, self.maximum()))
        if self._active_handle == "lower":
            self._lower = max(self.minimum(), min(value, self._upper))
        else:
            self._upper = min(self.maximum(), max(value, self._lower))
        self._sync_native()
        self._emit_values(previous)

    def _position_changed(self, value):
        # Tracking off retains the committed pair until release, like QSlider.
        if not self.hasTracking():
            bounded = (
                min(value, self._upper)
                if self._active_handle == "lower"
                else max(value, self._lower)
            )
            if bounded != value:
                self.setSliderPosition(bounded)
            self.update()

    def _bounds_changed(self, minimum, maximum):
        self.setValues(
            max(minimum, min(self._lower, maximum)), max(minimum, min(self._upper, maximum))
        )

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            lower, upper = (
                self._point_for_value(self._display_lower),
                self._point_for_value(self._display_upper),
            )
            dl = (event.position() - lower).manhattanLength()
            du = (event.position() - upper).manhattanLength()
            if dl != du:
                self.setActiveHandle("lower" if dl < du else "upper")
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            self._keyboard_focus = True
            self._animate_center(1.0)
            self.setActiveHandle("upper" if self._active_handle == "lower" else "lower")
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        lower, upper = self._display_lower, self._display_upper
        self._draw_track(painter, lower, upper)
        inactive, active = (upper, lower) if self._active_handle == "lower" else (lower, upper)
        self._draw_handle(painter, inactive, active=False)
        self._draw_handle(painter, active, active=True)
