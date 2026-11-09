from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font


class Card(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setObjectName("fluentCard")
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(22)
        self._shadow.setOffset(0, 8)
        self.setGraphicsEffect(self._shadow)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        theme.subscribe(self, self._apply_theme)
        self._apply_card_theme()

    def _apply_theme(self) -> None:
        self._apply_card_theme()

    def _apply_card_theme(self) -> None:
        tokens = theme.tokens
        acrylic = tokens.acrylic if theme.active else tokens.acrylic_inactive
        self._shadow.setColor(QtGui.QColor(tokens.shadow))
        self.setStyleSheet(
            f"""
QFrame#fluentCard {{
    background: {acrylic};
    border: 1px solid {tokens.border};
    border-radius: {tokens.radius}px;
}}
"""
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        tokens = theme.tokens
        acrylic = tokens.acrylic if theme.active else tokens.acrylic_inactive
        highlight = tokens.acrylic_highlight if theme.active else tokens.acrylic_highlight_inactive
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, _color(highlight))
        gradient.setColorAt(0.42, QtGui.QColor(255, 255, 255, 0))
        gradient.setColorAt(1.0, _color(acrylic))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, tokens.radius, tokens.radius)

        noise = QtGui.QColor("#ffffff" if tokens.mode.value == "dark" else "#000000")
        noise.setAlpha(8 if tokens.mode.value == "dark" else 5)
        painter.setPen(QtGui.QPen(noise, 1))
        step = 7
        for x in range(3, self.width(), step):
            y = (x * 17) % max(1, self.height())
            painter.drawPoint(x, y)

        sheen = QtGui.QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        sheen.setColorAt(0.0, QtGui.QColor(255, 255, 255, 0))
        sheen.setColorAt(
            0.38, QtGui.QColor(255, 255, 255, 18 if tokens.mode.value == "dark" else 30)
        )
        sheen.setColorAt(0.52, QtGui.QColor(255, 255, 255, 0))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(sheen)
        painter.drawRoundedRect(rect, tokens.radius, tokens.radius)


class ExamplePanel(Card):
    def __init__(
        self,
        title: str,
        source_label: str = "Source",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self.preview = QtWidgets.QWidget()
        self.preview.setObjectName("examplePreview")
        self.source = QtWidgets.QWidget()
        self.source.setObjectName("exampleSource")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        preview_layout = QtWidgets.QVBoxLayout(self.preview)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(10)
        self.preview_layout = preview_layout

        source_layout = QtWidgets.QHBoxLayout(self.source)
        source_layout.setContentsMargins(16, 10, 16, 10)
        source_layout.setSpacing(8)
        label = QtWidgets.QLabel(source_label)
        label.setObjectName("muted")
        source_layout.addWidget(label)
        source_layout.addStretch(1)
        open_button = _SourceOpenButton(fluent_icon(FluentIcon.OPEN))
        source_layout.addWidget(open_button)
        self.source_layout = source_layout

        root.addWidget(self.preview, 1)
        root.addWidget(self.source)
        self._apply_theme()

    def add_centered_row(self, *widgets: QtWidgets.QWidget) -> None:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addStretch(1)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        self.preview_layout.addLayout(row)

    def add_centered_layout(self, layout: QtWidgets.QLayout) -> None:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addLayout(layout)
        row.addStretch(1)
        self.preview_layout.addLayout(row)

    def _apply_theme(self) -> None:
        self._apply_card_theme()
        tokens = theme.tokens
        self.preview.setStyleSheet(
            f"""
QWidget#examplePreview {{
    background: {tokens.surface_high_rgba};
    border-top-left-radius: {tokens.radius}px;
    border-top-right-radius: {tokens.radius}px;
}}
QWidget#examplePreview QWidget {{
    background: transparent;
}}
"""
        )
        self.source.setStyleSheet(
            f"""
QWidget#exampleSource {{
    background: {tokens.surface_low_rgba};
    border-bottom-left-radius: {tokens.radius}px;
    border-bottom-right-radius: {tokens.radius}px;
}}
"""
        )


def _color(value: str) -> QtGui.QColor:
    if value.startswith("rgba(") and value.endswith(")"):
        parts = [int(part.strip()) for part in value[5:-1].split(",")]
        return QtGui.QColor(*parts)
    return QtGui.QColor(value)


class _SourceOpenButton(QtWidgets.QAbstractButton):
    def __init__(self, icon: QtGui.QIcon, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._hover = False
        self.setFixedSize(28, 28)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setToolTip("打开源码")
        theme.subscribe(self, self.update)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._hover:
            fill = QtGui.QColor("#ffffff" if theme.tokens.mode.value == "dark" else "#000000")
            fill.setAlpha(18 if theme.tokens.mode.value == "dark" else 10)
            painter.setBrush(fill)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2),
                theme.tokens.radius,
                theme.tokens.radius,
            )

        rect = QtCore.QRect(6, 6, 16, 16)
        pixmap = QtGui.QPixmap(rect.size())
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        icon_painter = QtGui.QPainter(pixmap)
        self._icon.paint(icon_painter, QtCore.QRect(QtCore.QPoint(0, 0), rect.size()))
        icon_painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        color = QtGui.QColor(theme.tokens.text)
        color.setAlpha(210)
        icon_painter.fillRect(pixmap.rect(), color)
        icon_painter.end()
        painter.drawPixmap(rect, pixmap)
