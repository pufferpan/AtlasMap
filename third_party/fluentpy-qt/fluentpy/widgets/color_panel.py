"""Native color editor and swatches, composed with the existing input controls."""

from __future__ import annotations

from ..backends import color as colors
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .button import Button, TextButton
from .combo_box import ComboBox
from .line_edit import LineEdit, SpinBox
from .slider import Slider


def _color(value, alpha=True):
    if not isinstance(value, (str, QtGui.QColor, QtCore.Qt.GlobalColor)):
        raise TypeError("color must be a QColor, color string or Qt.GlobalColor")
    result = QtGui.QColor(value)
    if not result.isValid():
        raise ValueError("invalid color")
    if not alpha:
        result.setAlpha(255)
    return result


def _hex(color, alpha=False):
    return colors.format_hex(*color.getRgb(), include_alpha=alpha)


def _checker(painter, rect, cell=6):
    painter.fillRect(rect, QtGui.QColor("#ffffff"))
    for x in range(int(rect.left()), int(rect.right()) + cell, cell):
        for y in range(int(rect.top()), int(rect.bottom()) + cell, cell):
            if ((x - int(rect.left())) // cell + (y - int(rect.top())) // cell) % 2:
                painter.fillRect(QtCore.QRectF(x, y, cell, cell), QtGui.QColor("#c1c5ca"))


def _paint_color(painter, rect, color, radius=4):
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(path)
    _checker(painter, rect)
    painter.fillPath(path, color)
    painter.restore()


class ColorSwatchButton(Button):
    """An actual checkable Button with an animated color selection ring."""

    colorClicked = Signal(QtGui.QColor)
    colorChanged = Signal(QtGui.QColor)
    _kind = "text"

    def __init__(self, color="#0078d4", parent=None, *, circular=True):
        super().__init__("", parent)
        self._color = _color(color)
        self._circular = bool(circular)
        self._pill = self._circular
        self._selection = 0.0
        self._selection_animation = self._make_state_animation("_selection")
        self.setFixedSize(32, 32)
        self.setCheckable(True)
        self.toggled.connect(self._selection_changed)
        self.clicked.connect(self._color_clicked)
        self._describe()

    def color(self):
        return QtGui.QColor(self._color)

    def set_color(self, color):
        value = _color(color)
        if value != self._color:
            self._color = value
            self._describe()
            self.update()
            self.colorChanged.emit(self.color())

    setColor = set_color

    def sizeHint(self):
        return QtCore.QSize(32, 32)

    def _describe(self):
        text = _hex(self._color, self._color.alpha() != 255)
        self.setAccessibleName("颜色 " + text)
        self.setToolTip(text)

    def _color_clicked(self, _checked=False):
        self.colorClicked.emit(self.color())

    def _selection_changed(self, checked):
        self._selection_animation.stop()
        if self.isVisible():
            self._animate_state(self._selection_animation, self._selection, float(checked), 150)
        else:
            self._selection = float(checked)
            self.update()

    def _draw_button_border(self, painter, rect, radius):
        pass

    def _draw_content(self, painter, rect, color):
        del color
        inset = 5 if self._circular else 3
        swatch = rect.adjusted(inset, inset, -inset, -inset)
        radius = swatch.width() / 2 if self._circular else 4
        if not self.isEnabled():
            painter.setOpacity(0.45)
        _paint_color(painter, swatch, self._color, radius)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 0.7))
        painter.drawRoundedRect(swatch, radius, radius)
        if self._selection > 0:
            ring = QtGui.QColor(theme.tokens.accent)
            ring.setAlphaF(self._selection)
            painter.setPen(QtGui.QPen(ring, 1.8))
            outer = rect.adjusted(1.5, 1.5, -1.5, -1.5)
            painter.drawRoundedRect(
                outer,
                outer.width() / 2 if self._circular else 5,
                outer.height() / 2 if self._circular else 5,
            )

    def hideEvent(self, event):
        if hasattr(self, "_selection_animation"):
            self._selection_animation.stop()
            self._selection = float(self.isChecked())
        super().hideEvent(event)


class ColorSwatchGroup(QtWidgets.QWidget):
    """An exclusive color group that wraps with a standard QGridLayout."""

    colorChanged = Signal(QtGui.QColor)

    def __init__(self, colors=None, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor()
        self._buttons = []
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(self._clicked)
        self._layout = QtWidgets.QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        self.set_colors(
            colors
            if colors is not None
            else ("#4ba6ed", "#72d4f4", "#4ca9ef", "#388fd8", "#253e72", "#c7a2ec")
        )

    def colors(self):
        return tuple(button.color() for button in self._buttons)

    def color(self):
        return QtGui.QColor(self._color)

    def set_colors(self, values):
        parsed = [_color(value) for value in values]
        if not parsed or len(parsed) > 256:
            raise ValueError("provide between 1 and 256 colors")
        for button in self._buttons:
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.hide()
            button.deleteLater()
        self._buttons = [ColorSwatchButton(value, self) for value in parsed]
        for button in self._buttons:
            self._group.addButton(button)
            button.show()
        if not self._color.isValid():
            self._color = QtGui.QColor(parsed[0])
        self._sync_checked()
        self._reflow()

    def set_color(self, color):
        value = _color(color)
        changed = value != self._color
        self._color = value
        self._sync_checked()
        if changed:
            self.colorChanged.emit(self.color())

    setColor = set_color
    setColors = set_colors

    def _sync_checked(self):
        self._group.setExclusive(False)
        matched = False
        for button in self._buttons:
            selected = not matched and button.color() == self._color
            button.setChecked(selected)
            matched |= selected
        self._group.setExclusive(True)

    def _clicked(self, button):
        self.set_color(button.color())

    def _reflow(self):
        while self._layout.count():
            self._layout.takeAt(0)
        columns = max(1, min(len(self._buttons), (self.width() + 8) // 40))
        for index, button in enumerate(self._buttons):
            self._layout.addWidget(button, index // columns, index % columns)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()


class _ColorSpectrum(QtWidgets.QWidget):
    selected = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue, self.saturation, self.value = 0.0, 1.0, 1.0
        self._marker = QtCore.QPointF(0, 0)
        self._motion = QtCore.QVariantAnimation(self)
        self._motion.setDuration(110)
        self._motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_marker)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setAccessibleName("色相与饱和度色谱")

    def sizeHint(self):
        return QtCore.QSize(240, 210)

    def set_state(self, hue, saturation, value, animated=False):
        self.hue, self.saturation, self.value = hue, saturation, value
        target = QtCore.QPointF(hue / 360, 1 - saturation)
        self._motion.stop()
        if animated and self.isVisible() and target != self._marker:
            self._motion.setStartValue(self._marker)
            self._motion.setEndValue(target)
            self._motion.start()
        else:
            self._move_marker(target)
        self.setAccessibleDescription(
            f"色相 {hue:.1f}，饱和度 {saturation * 100:.0f}%，明度 {value * 100:.0f}%"
        )
        self.update()

    def _move_marker(self, point):
        self._marker = QtCore.QPointF(point)
        self.update()

    def _pick(self, point):
        rect = self.rect().adjusted(3, 3, -3, -3)
        x = max(0.0, min(1.0, (point.x() - rect.left()) / max(1, rect.width())))
        y = max(0.0, min(1.0, (point.y() - rect.top()) / max(1, rect.height())))
        self.selected.emit(min(359.999, x * 360), 1 - y)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            self._pick(event.position())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._pick(event.position())
            event.accept()

    def keyPressEvent(self, event):
        h, s = self.hue, self.saturation
        if event.key() == QtCore.Qt.Key.Key_Left:
            h = (h - 1) % 360
        elif event.key() == QtCore.Qt.Key.Key_Right:
            h = (h + 1) % 360
        elif event.key() == QtCore.Qt.Key.Key_Up:
            s = min(1, s + 0.01)
        elif event.key() == QtCore.Qt.Key.Key_Down:
            s = max(0, s - 0.01)
        else:
            return super().keyPressEvent(event)
        self.selected.emit(h, s)
        event.accept()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(3, 3, -3, -3)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        painter.setClipPath(path)
        hue = QtGui.QLinearGradient(rect.left(), 0, rect.right(), 0)
        for index in range(7):
            hue.setColorAt(index / 6, QtGui.QColor.fromHsvF((index % 6) / 6, 1, 1))
        painter.fillPath(path, hue)
        saturation = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        saturation.setColorAt(0, QtGui.QColor(255, 255, 255, 0))
        saturation.setColorAt(1, QtGui.QColor(255, 255, 255))
        painter.fillPath(path, saturation)
        painter.fillPath(path, QtGui.QColor(0, 0, 0, round(255 * (1 - self.value))))
        painter.setClipping(False)
        point = QtCore.QPointF(
            rect.left() + self._marker.x() * rect.width(),
            rect.top() + self._marker.y() * rect.height(),
        )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 3.5))
        painter.drawEllipse(point, 6, 6)
        painter.setPen(QtGui.QPen(QtGui.QColor("#202020"), 1.5))
        painter.drawEllipse(point, 6, 6)


class _ColorPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = QtGui.QColor("#0078d4")
        self.previous = QtGui.QColor(self.current)
        self.setFixedWidth(38)
        self.setMinimumHeight(120)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        half = self.height() / 2
        _paint_color(painter, QtCore.QRectF(0, 3, self.width(), half - 4), self.current)
        _paint_color(painter, QtCore.QRectF(0, half + 1, self.width(), half - 4), self.previous)


class ColorPickerPanel(QtWidgets.QWidget):
    """Live color draft: spectrum, brightness, RGB/HSV channels and optional alpha."""

    colorChanged = Signal(QtGui.QColor)
    validationChanged = Signal(bool)

    def __init__(self, color="#0078d4", parent=None, *, enable_alpha=True):
        super().__init__(parent)
        self._alpha_enabled = bool(enable_alpha)
        self._color = _color(color, self._alpha_enabled)
        self._hue, self._saturation, self._value = 0.0, 1.0, 1.0
        self._valid = True
        self._format = "rgb"
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(260)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(8)
        upper = QtWidgets.QHBoxLayout()
        upper.setSpacing(12)
        self.spectrum = _ColorSpectrum(self)
        self.spectrum.setFixedHeight(210)
        self.preview = _ColorPreview(self)
        upper.addWidget(self.spectrum, 1)
        upper.addWidget(self.preview)
        self._layout.addLayout(upper)
        self.brightness_slider = Slider(parent=self)
        self.brightness_slider.setRange(0, 1000)
        self.brightness_slider.setAccessibleName("颜色明度")
        self._layout.addWidget(self.brightness_slider)
        format_row = QtWidgets.QHBoxLayout()
        format_row.setSpacing(10)
        self.format_combo = ComboBox(self)
        self.format_combo.addItems(["RGB", "HSV"])
        self.format_combo.setFixedWidth(88)
        self.format_combo.setAccessibleName("颜色格式")
        self.hex_input = LineEdit(parent=self)
        self.hex_input.set_clear_button_enabled(False)
        self.hex_input.setMinimumWidth(0)
        self.hex_input.setMaxLength(16)
        self.hex_input.setAccessibleName("十六进制颜色，透明度在最前")
        format_row.addWidget(self.format_combo)
        format_row.addStretch()
        format_row.addWidget(self.hex_input, 1)
        self._layout.addLayout(format_row)
        self.channel_labels, self.channel_inputs, self.channel_sliders = [], [], []
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for index, name in enumerate("RGBA"):
            label = QtWidgets.QLabel(name, self)
            entry = SpinBox(parent=self)
            entry.setRange(0, 255)
            entry.setFixedWidth(92)
            slider = Slider(parent=self)
            slider.setRange(0, 255)
            entry.valueChanged.connect(lambda value, i=index: self._channel_changed(i, value))
            slider.valueChanged.connect(lambda value, i=index: self._channel_changed(i, value))
            self.channel_labels.append(label)
            self.channel_inputs.append(entry)
            self.channel_sliders.append(slider)
            grid.addWidget(label, index, 0)
            grid.addWidget(entry, index, 1)
            grid.addWidget(slider, index, 2)
            if index == 3 and not self._alpha_enabled:
                label.hide()
                entry.hide()
                slider.hide()
        grid.setColumnStretch(2, 1)
        self._layout.addLayout(grid)
        self.error_label = QtWidgets.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self._layout.addWidget(self.error_label)
        self.spectrum.selected.connect(self._spectrum_changed)
        self.brightness_slider.valueChanged.connect(self._brightness_changed)
        self.format_combo.currentIndexChanged.connect(
            lambda index: self.set_format("hsv" if index else "rgb")
        )
        self.hex_input.textEdited.connect(self._hex_edited)
        self.hex_input.editingFinished.connect(self._finish_hex)
        self.set_previous_color(self._color)
        self._sync()
        theme.subscribe(self, self._refresh_theme)
        self._refresh_theme()

    def sizeHint(self):
        hint = self._layout.sizeHint()
        return QtCore.QSize(max(312, hint.width()), hint.height())

    def color(self):
        return QtGui.QColor(self._color)

    def set_color(self, color):
        self._assign(_color(color, self._alpha_enabled))

    def set_previous_color(self, color):
        self.preview.previous = _color(color, self._alpha_enabled)
        self.preview.update()

    def color_format(self):
        return self._format

    def set_format(self, format):
        if format not in ("rgb", "hsv"):
            raise ValueError("format must be rgb or hsv")
        self._format = format
        self._sync()

    def is_valid(self):
        return self._valid

    def validate(self):
        return self._hex_edited(self.hex_input.text())

    def acceleration_backend(self):
        return colors.backend_name()

    setColor = set_color
    setPreviousColor = set_previous_color
    setColorFormat = set_format

    def _assign(self, color, *, preserve_hue=False, from_spectrum=False, preserve_hex=False):
        changed = color != self._color
        self._color = color
        self._sync(
            preserve_hue=preserve_hue, from_spectrum=from_spectrum, preserve_hex=preserve_hex
        )
        if changed:
            self.colorChanged.emit(self.color())

    def _sync(self, *, preserve_hue=False, from_spectrum=False, preserve_hex=False):
        hue, saturation, value = colors.rgb_to_hsv(*self._color.getRgb()[:3])
        if not preserve_hue:
            if hue >= 0:
                self._hue = hue
            self._saturation, self._value = saturation, value
        self.spectrum.set_state(
            self._hue, self._saturation, self._value, animated=not from_spectrum
        )
        self.preview.current = self.color()
        self.preview.update()
        with QtCore.QSignalBlocker(self.format_combo):
            self.format_combo.setCurrentIndex(int(self._format == "hsv"))
        with QtCore.QSignalBlocker(self.brightness_slider):
            self.brightness_slider.setValue(round(self._value * 1000))
        full = QtGui.QColor(*colors.hsv_to_rgba(self._hue, self._saturation, 1))
        self.brightness_slider.set_track_gradient([(0, "#000000"), (1, full)])
        values = (
            self._color.getRgb()
            if self._format == "rgb"
            else (
                round(self._hue) % 360,
                round(self._saturation * 100),
                round(self._value * 100),
                self._color.alpha(),
            )
        )
        names = "RGBA" if self._format == "rgb" else "HSVA"
        maxima = (255, 255, 255, 255) if self._format == "rgb" else (359, 100, 100, 255)
        for index, (label, entry, slider) in enumerate(
            zip(self.channel_labels, self.channel_inputs, self.channel_sliders)
        ):
            label.setText(names[index])
            entry.setAccessibleName(names[index] + "颜色分量")
            slider.setAccessibleName(names[index] + "颜色分量")
            with QtCore.QSignalBlocker(entry), QtCore.QSignalBlocker(slider):
                entry.setRange(0, maxima[index])
                slider.setRange(0, maxima[index])
                entry.setValue(values[index])
                slider.setValue(values[index])
            stops = []
            if self._format == "hsv" and index == 0:
                stops = [(i / 6, QtGui.QColor.fromHsvF((i % 6) / 6, 1, 1)) for i in range(7)]
            else:
                for endpoint in (0, maxima[index]):
                    if index == 3:
                        color = self.color()
                        color.setAlpha(endpoint)
                    elif self._format == "rgb":
                        channels = list(self._color.getRgb())
                        channels[index] = endpoint
                        channels[3] = 255
                        color = QtGui.QColor(*channels)
                    else:
                        components = [self._hue, self._saturation, self._value]
                        components[index] = endpoint / 100
                        color = QtGui.QColor(*colors.hsv_to_rgba(*components))
                    stops.append((endpoint / maxima[index], color))
            slider.set_track_gradient(stops, checkerboard=index == 3, thickness=8)
        if not preserve_hex:
            self.hex_input.setText(_hex(self._color, self._alpha_enabled))
        self._set_valid(True)

    def _spectrum_changed(self, hue, saturation):
        self._hue, self._saturation = hue, saturation
        color = QtGui.QColor(*colors.hsv_to_rgba(hue, saturation, self._value, self._color.alpha()))
        self._assign(color, preserve_hue=True, from_spectrum=True)

    def _brightness_changed(self, value):
        self._value = value / 1000
        self._assign(
            QtGui.QColor(
                *colors.hsv_to_rgba(self._hue, self._saturation, self._value, self._color.alpha())
            ),
            preserve_hue=True,
        )

    def _channel_changed(self, index, value):
        channels = list(self._color.getRgb())
        if index == 3 or self._format == "rgb":
            channels[index] = value
            self._assign(QtGui.QColor(*channels))
        else:
            components = [self._hue, self._saturation, self._value]
            components[index] = float(value) if index == 0 else value / 100
            self._hue, self._saturation, self._value = components
            self._assign(
                QtGui.QColor(*colors.hsv_to_rgba(*components, self._color.alpha())),
                preserve_hue=True,
            )

    def _hex_edited(self, text):
        try:
            rgba = colors.parse_hex(text.strip())
        except ValueError:
            self._set_valid(False)
            return False
        color = QtGui.QColor(*rgba)
        if not self._alpha_enabled:
            color.setAlpha(255)
        self._assign(color, preserve_hex=True)
        return True

    def _finish_hex(self):
        if self._hex_edited(self.hex_input.text()):
            self.hex_input.setText(_hex(self._color, self._alpha_enabled))

    def _set_valid(self, valid):
        changed = valid != self._valid
        self._valid = valid
        self.error_label.setText("请输入 #RGB、#RRGGBB 或 #AARRGGBB。" if not valid else "")
        self.error_label.setVisible(not valid)
        self.hex_input.setAccessibleDescription(
            "" if valid else "颜色格式不完整或无效，原颜色保持不变。"
        )
        if changed:
            self.validationChanged.emit(valid)

    def _refresh_theme(self):
        self.setFont(ui_font(theme.tokens.font_size))
        for label in self.channel_labels:
            label.setStyleSheet(f"color: {theme.tokens.text}; background: transparent;")
        self.error_label.setStyleSheet(
            f"color: {'#c42b1c' if theme.mode.value == 'light' else '#ff99a4'}; background: transparent; font-size: 12px;"
        )


THEME_COLORS = (
    (
        "#ffffff",
        "#151515",
        "#e5e7eb",
        "#475569",
        "#386bc0",
        "#7659a4",
        "#a3a3a3",
        "#f5bb00",
        "#4998cf",
        "#70a641",
    ),
    (
        "#f3f4f6",
        "#808080",
        "#d1d5db",
        "#dbe2eb",
        "#dce7fa",
        "#e8dff2",
        "#ececec",
        "#fff3cd",
        "#deedf8",
        "#e1efd5",
    ),
    (
        "#dddddd",
        "#626262",
        "#acb0b8",
        "#b7c4d6",
        "#b6cbec",
        "#cebee1",
        "#d9d9d9",
        "#ffe69c",
        "#bddbf1",
        "#c6dfb1",
    ),
    (
        "#bfbfbf",
        "#454545",
        "#8b919b",
        "#879bb8",
        "#8daadd",
        "#ae95cb",
        "#bdbdbd",
        "#ffda6a",
        "#97c8e8",
        "#a8ce88",
    ),
    (
        "#9a9a9a",
        "#292929",
        "#5f6670",
        "#344155",
        "#2b5397",
        "#604487",
        "#919191",
        "#c59800",
        "#317aaa",
        "#527d2b",
    ),
    (
        "#777777",
        "#050505",
        "#363b43",
        "#202b3c",
        "#1d3765",
        "#432e61",
        "#525252",
        "#826400",
        "#1e506e",
        "#36531d",
    ),
)
STANDARD_COLORS = (
    "#c00000",
    "#ff0000",
    "#ffbd00",
    "#ffff00",
    "#92d050",
    "#00b050",
    "#00b8d4",
    "#0078d4",
    "#002060",
    "#7030a0",
)


class ColorPalette(QtWidgets.QWidget):
    """Theme and standard swatches, an automatic choice and a more-colors action."""

    colorSelected = Signal(QtGui.QColor)
    automaticSelected = Signal()
    moreColorsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons = []
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.automatic_button = TextButton("自动", self)
        self.automatic_button.setMinimumHeight(32)
        self.automatic_button.clicked.connect(lambda _checked=False: self.automaticSelected.emit())
        self._layout.addWidget(self.automatic_button)
        self._labels = []
        for title, rows in (("主题颜色", THEME_COLORS), ("标准颜色", (STANDARD_COLORS,))):
            label = QtWidgets.QLabel(title, self)
            self._labels.append(label)
            self._layout.addWidget(label)
            grid = QtWidgets.QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(3)
            for row, values in enumerate(rows):
                for column, color in enumerate(values):
                    button = ColorSwatchButton(color, self, circular=False)
                    button.setFixedSize(28, 28)
                    self._group.addButton(button)
                    self._buttons.append(button)
                    button.colorClicked.connect(self.colorSelected.emit)
                    grid.addWidget(button, row, column)
            self._layout.addLayout(grid)
        self.more_button = TextButton("更多颜色…", self)
        self.more_button.setMinimumHeight(32)
        self.more_button.clicked.connect(lambda _checked=False: self.moreColorsRequested.emit())
        self._layout.addWidget(self.more_button)
        theme.subscribe(self, self._refresh_theme)
        self._refresh_theme()

    def set_color(self, color):
        value = _color(color) if color is not None else QtGui.QColor()
        self._group.setExclusive(False)
        matched = False
        for button in self._buttons:
            selected = not matched and value == button.color()
            button.setChecked(selected)
            matched |= selected
        self._group.setExclusive(True)

    setColor = set_color

    def _refresh_theme(self):
        self.setFont(ui_font(theme.tokens.font_size))
        for label in self._labels:
            label.setStyleSheet(
                f"color: {theme.tokens.text}; background: transparent; padding: 3px 0;"
            )
