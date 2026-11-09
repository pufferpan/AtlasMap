"""Titled and grouped card containers, composed from ordinary Qt widgets."""

from __future__ import annotations

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font
from .card import SimpleCardWidget


class _CardDivider(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        theme.subscribe(self, self.update)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(theme.tokens.border))


class _GroupIcon(QtWidgets.QWidget):
    def __init__(self, source, parent):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._text = ""
        self._tint = isinstance(source, FluentIcon)
        if isinstance(source, FluentIcon):
            self._icon = fluent_icon(source)
        elif isinstance(source, QtGui.QPixmap):
            self._icon = QtGui.QIcon(source)
        elif isinstance(source, QtGui.QIcon):
            self._icon = QtGui.QIcon(source)
        elif isinstance(source, str):
            self._icon = QtGui.QIcon(source) if QtCore.QFile.exists(source) else QtGui.QIcon()
            self._text = source if self._icon.isNull() else ""
        elif source is None:
            self._icon = QtGui.QIcon()
            self.hide()
        else:
            raise TypeError("icon must be a QIcon, QPixmap, FluentIcon, string, QWidget or None")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        theme.subscribe(self, self.update)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._text:
            painter.setFont(ui_font(20, self.font()))
            painter.setPen(QtGui.QColor(theme.tokens.text))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self._text)
        elif not self._icon.isNull():
            pixmap = self._icon.pixmap(QtCore.QSize(24, 24))
            if self._tint:
                pixmap = QtGui.QPixmap(pixmap)
                tint = QtGui.QPainter(pixmap)
                tint.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
                tint.fillRect(pixmap.rect(), QtGui.QColor(theme.tokens.text))
                tint.end()
            painter.drawPixmap(self.rect(), pixmap)


class HeaderCardWidget(SimpleCardWidget):
    """A static card with a title strip and a vertical content layout.

    Add normal Qt widgets/layouts to ``body_layout`` (also ``viewLayout``).
    Header actions may be added to ``header_layout`` after the title label.
    """

    def __init__(
        self, title: str | QtWidgets.QWidget = "", parent: QtWidgets.QWidget | None = None
    ) -> None:
        if isinstance(title, QtWidgets.QWidget):
            if parent is not None:
                raise TypeError("parent was provided twice")
            parent, title = title, ""
        super().__init__(parent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred
        )
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_widget = QtWidgets.QWidget(self)
        self.header_widget.setMinimumHeight(52)
        self.header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(22, 13, 22, 13)
        self.header_layout.setSpacing(12)
        self.title_label = QtWidgets.QLabel(str(title), self.header_widget)
        self.title_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.header_layout.addWidget(self.title_label, 1)
        self._header_divider = _CardDivider(self)
        self.view = QtWidgets.QWidget(self)
        self.body_layout = QtWidgets.QVBoxLayout(self.view)
        self.body_layout.setContentsMargins(22, 18, 22, 20)
        self.body_layout.setSpacing(14)
        self.viewLayout = self.body_layout
        root.addWidget(self.header_widget)
        root.addWidget(self._header_divider)
        root.addWidget(self.view)
        self._refresh_header_theme()
        theme.subscribe(self, self._refresh_header_theme)

    def title(self) -> str:
        return self.title_label.text()

    def set_title(self, title: str) -> None:
        self.title_label.setText(str(title))
        self.updateGeometry()

    def setTitle(self, title: str) -> None:
        self.set_title(title)

    def set_header_visible(self, visible: bool) -> None:
        self.header_widget.setVisible(bool(visible))
        self._header_divider.setVisible(bool(visible))
        self.updateGeometry()

    def is_header_visible(self) -> bool:
        return not self.header_widget.isHidden()

    def _refresh_header_theme(self) -> None:
        tokens = theme.tokens
        font = ui_font(tokens.font_size + 2, self.title_label.font())
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet(
            f"color: {tokens.text}; background: transparent; border: none; "
            f"font-size: {tokens.font_size + 2}px; font-weight: 600;"
        )


class _CardGroup(QtWidgets.QWidget):
    def __init__(self, icon, title: str, content: str, control, parent):
        super().__init__(parent)
        self.control = None
        self._control_below = False
        self._relayout_pending = False
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(22, 12, 22, 12)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(10)
        self._grid.setColumnStretch(1, 1)
        self.icon_widget = icon if isinstance(icon, QtWidgets.QWidget) else _GroupIcon(icon, self)
        self._grid.addWidget(self.icon_widget, 0, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._text = QtWidgets.QWidget(self)
        labels = QtWidgets.QVBoxLayout(self._text)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(3)
        self.title_label = QtWidgets.QLabel(str(title), self._text)
        self.content_label = QtWidgets.QLabel(str(content), self._text)
        for label in (self.title_label, self.content_label):
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred
            )
            labels.addWidget(label)
        self._grid.addWidget(self._text, 0, 1)
        self._set_text(title, content)
        self._set_control(control)
        self._refresh_group_theme()
        theme.subscribe(self, self._refresh_group_theme)

    def _set_text(self, title, content):
        self.title_label.setText(str(title))
        self.content_label.setText(str(content))
        self.content_label.setVisible(bool(content))
        self.setMinimumHeight(72 if content else 60)
        self.updateGeometry()

    def _set_control(self, control):
        if control is self.control:
            return
        if control is not None and not isinstance(control, QtWidgets.QWidget):
            raise TypeError("control must be a QWidget or None")
        old = self.control
        if old is not None:
            self._grid.removeWidget(old)
            old.hide()
            old.deleteLater()
        self.control = control
        if control is not None:
            self._grid.addWidget(
                control,
                1 if self._control_below else 0,
                1 if self._control_below else 2,
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            )
            control.show()
        self._position_control()
        self.updateGeometry()

    def _position_control(self):
        if self.control is None or self._relayout_pending:
            return
        margins = self._grid.contentsMargins()
        icon_width = (
            0
            if self.icon_widget.isHidden()
            else max(self.icon_widget.minimumWidth(), self.icon_widget.sizeHint().width())
        )
        control_width = max(
            self.control.minimumWidth(),
            self.control.minimumSizeHint().width(),
            min(360, self.control.sizeHint().width()),
        )
        needed = margins.left() + margins.right() + max(0, icon_width) + control_width + 160 + 28
        below = self.width() < needed
        if below == self._control_below:
            return
        self._relayout_pending = True
        try:
            self._control_below = below
            self._grid.removeWidget(self.control)
            self._grid.addWidget(
                self.control,
                1 if below else 0,
                1 if below else 2,
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            )
            self.updateGeometry()
        finally:
            self._relayout_pending = False

    def resizeEvent(self, event):
        self._position_control()
        super().resizeEvent(event)

    def _refresh_group_theme(self):
        tokens = theme.tokens
        self.setFont(ui_font(tokens.font_size, self.font()))
        for label, size, color in (
            (self.title_label, tokens.font_size, tokens.text),
            (self.content_label, max(11, tokens.font_size - 2), tokens.text_muted),
        ):
            label.setFont(ui_font(size, label.font()))
            label.setStyleSheet(
                f"color: {color}; background: transparent; border: none; font-size: {size}px;"
            )
        self.updateGeometry()


class GroupHeaderCardWidget(HeaderCardWidget):
    """A titled card whose rows own their icon, labels and optional control.

    The content layout is available as ``body_layout`` / ``viewLayout`` /
    ``vBoxLayout``. Rows wrap their control below the text in a narrow layout.
    Removing a row or replacing its control schedules the old widget for deletion.
    """

    def __init__(
        self, title: str | QtWidgets.QWidget = "", parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(title, parent)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.vBoxLayout = self.body_layout
        self._groups = []
        self._separators = []

    def add_group(
        self, icon, title: str, content: str = "", control: QtWidgets.QWidget | None = None
    ) -> QtWidgets.QWidget:
        if control is not None and not isinstance(control, QtWidgets.QWidget):
            raise TypeError("control must be a QWidget or None")
        row = _CardGroup(icon, title, content, control, self.view)
        separator = _CardDivider(self.view) if self._groups else None
        if separator is not None:
            self.body_layout.addWidget(separator)
        self.body_layout.addWidget(row)
        self._groups.append(row)
        self._separators.append(separator)
        return row

    def addGroup(
        self, icon, title: str, content: str = "", control: QtWidgets.QWidget | None = None
    ) -> QtWidgets.QWidget:
        return self.add_group(icon, title, content, control)

    def groups(self) -> tuple[QtWidgets.QWidget, ...]:
        return tuple(self._groups)

    def remove_group(self, group: QtWidgets.QWidget) -> bool:
        if group not in self._groups:
            return False
        index = self._groups.index(group)
        separator = self._separators.pop(index)
        self._groups.pop(index)
        self.body_layout.removeWidget(group)
        group.hide()
        group.deleteLater()
        if separator is not None:
            self.body_layout.removeWidget(separator)
            separator.deleteLater()
        if index == 0 and self._separators and self._separators[0] is not None:
            first = self._separators[0]
            self.body_layout.removeWidget(first)
            first.deleteLater()
            self._separators[0] = None
        self.updateGeometry()
        return True

    def set_group_control(
        self, group: QtWidgets.QWidget, control: QtWidgets.QWidget | None
    ) -> None:
        if group not in self._groups:
            raise ValueError("group does not belong to this card")
        group._set_control(control)

    def set_group_text(self, group: QtWidgets.QWidget, title: str, content: str = "") -> None:
        if group not in self._groups:
            raise ValueError("group does not belong to this card")
        group._set_text(title, content)
