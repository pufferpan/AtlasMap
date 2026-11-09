"""Split actions with separate primary and menu hit regions."""

from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from .action_menu import ActionMenu
from .button import AccentButton, Button
from .menu_button import _MenuButtonMixin


class _SplitPartMixin:
    """Join the painted surfaces while keeping each Qt button's input state."""

    _side = "left"

    def _paint_rect(self):
        rect = super()._paint_rect()
        return rect.adjusted(0, 0, 7, 0) if self._side == "left" else rect.adjusted(-7, 0, 0, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._side == "right":
            painter = QtGui.QPainter(self)
            color = QtGui.QColor(
                "#ffffff"
                if self._kind == "accent" and theme.mode.value == "light"
                else theme.tokens.text
            )
            color.setAlpha(60 if self._kind == "accent" else 28)
            if not self.isEnabled():
                color.setAlpha(18)
            painter.setPen(QtGui.QPen(color, 1))
            painter.drawLine(QtCore.QLineF(0.5, 8, 0.5, self.height() - 8))

    def keyPressEvent(self, event):
        if self._side == "left" and event.key() == QtCore.Qt.Key.Key_Down:
            self.parentWidget().show_menu()
            event.accept()
        else:
            super().keyPressEvent(event)


class _SplitContentMixin:
    """Measure and paint two text lines inside the primary hit region."""

    def __init__(self, text="", parent=None, *, description=""):
        super().__init__(text, parent)
        self._description = ""
        self.set_description(description)

    def description(self):
        return self._description

    def set_description(self, text):
        self._description = str(text)
        self.setAccessibleDescription(self._description)
        self._update_content_size()

    def _description_font(self):
        font = QtGui.QFont(self.font())
        font.setPixelSize(max(10, self.font().pixelSize() - 2))
        return font

    def _title_font(self):
        font = QtGui.QFont(self.font())
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        return font

    def _content_height(self):
        if not self._description:
            return 32
        return max(
            52,
            QtGui.QFontMetrics(self._title_font()).height()
            + QtGui.QFontMetrics(self._description_font()).height()
            + 18,
        )

    def _update_content_size(self):
        self.setMinimumHeight(self._content_height())
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        if not getattr(self, "_description", ""):
            return super().sizeHint()
        title = QtGui.QFontMetrics(self._title_font()).horizontalAdvance(self.text())
        description = QtGui.QFontMetrics(self._description_font()).horizontalAdvance(
            self._description
        )
        icon = self.iconSize().width() + 10 if not self.icon().isNull() else 0
        return QtCore.QSize(max(96, max(title, description) + icon + 32), self._content_height())

    def minimumSizeHint(self):
        if not getattr(self, "_description", ""):
            return super().minimumSizeHint()
        icon = self.iconSize().width() + 10 if not self.icon().isNull() else 0
        return QtCore.QSize(80 + icon, self._content_height())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.FontChange and hasattr(self, "_description"):
            self._update_content_size()

    def _draw_content(self, painter, rect, color):
        # The surface extends across the seam to remove the inner corners;
        # the text remains centered inside the actual main hit target.
        rect = rect.adjusted(0, 0, -7, 0)
        if not self._description:
            super()._draw_content(painter, rect, color)
            return
        title_font, description_font = self._title_font(), self._description_font()
        title_metrics, description_metrics = (
            QtGui.QFontMetrics(title_font),
            QtGui.QFontMetrics(description_font),
        )
        content = rect.adjusted(16, 0, -16, 0)
        icon_width = self.iconSize().width() + 10 if not self.icon().isNull() else 0
        width = max(
            0,
            min(
                content.width() - icon_width,
                max(
                    title_metrics.horizontalAdvance(self.text()),
                    description_metrics.horizontalAdvance(self._description),
                ),
            ),
        )
        left = content.center().x() - (width + icon_width) / 2
        if icon_width:
            icon_rect = QtCore.QRect(
                round(left),
                round(rect.center().y() - self.iconSize().height() / 2),
                self.iconSize().width(),
                self.iconSize().height(),
            )
            self._draw_tinted_icon(painter, icon_rect, color)
            left += icon_width
        top = rect.center().y() - (title_metrics.height() + description_metrics.height() + 2) / 2
        alignment = QtCore.Qt.AlignmentFlag.AlignCenter
        painter.setFont(title_font)
        painter.setPen(color)
        painter.drawText(
            QtCore.QRectF(left, top, width, title_metrics.height()),
            alignment,
            title_metrics.elidedText(self.text(), QtCore.Qt.TextElideMode.ElideRight, round(width)),
        )
        secondary = QtGui.QColor(
            color
            if self._kind == "accent"
            else theme.tokens.text_muted
            if self.isEnabled()
            else theme.tokens.disabled
        )
        secondary.setAlphaF(color.alphaF() * (0.82 if self._kind == "accent" else 1.0))
        painter.setFont(description_font)
        painter.setPen(secondary)
        painter.drawText(
            QtCore.QRectF(
                left, top + title_metrics.height() + 2, width, description_metrics.height()
            ),
            alignment,
            description_metrics.elidedText(
                self._description, QtCore.Qt.TextElideMode.ElideRight, round(width)
            ),
        )


class _SplitMain(_SplitContentMixin, _SplitPartMixin, Button):
    pass


class _AccentSplitMain(_SplitContentMixin, _SplitPartMixin, AccentButton):
    pass


class _SplitArrow(_SplitPartMixin, _MenuButtonMixin, Button):
    _side = "right"
    _menu_only = True


class _AccentSplitArrow(_SplitPartMixin, _MenuButtonMixin, AccentButton):
    _side = "right"
    _menu_only = True


class SplitButton(QtWidgets.QWidget):
    """Combine a primary action with an independently operated menu.

    ``clicked`` is emitted only by the primary region. ``description`` adds a
    second text line; an empty description retains the single-line layout.
    """

    clicked = Signal()
    _accent = False

    def __init__(
        self,
        text: str = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        menu: ActionMenu | None = None,
        description: str = "",
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.main_button = (_AccentSplitMain if self._accent else _SplitMain)(
            text, self, description=description
        )
        self.menu_button = (_AccentSplitArrow if self._accent else _SplitArrow)(
            parent=self, menu=menu
        )
        self.main_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.menu_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.menu_button._menu_anchor = self
        self.menu_button.setAccessibleName("更多操作")
        self.main_button.clicked.connect(self._clicked)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.main_button, 1)
        row.addWidget(self.menu_button)
        self.setFocusProxy(self.main_button)
        self.setAccessibleName(text)
        self.setAccessibleDescription(str(description))
        self._sync_parts()
        theme.subscribe(self, self._sync_parts)

    @Slot()
    def _clicked(self):
        self.clicked.emit()

    def setText(self, text: str) -> None:
        self.main_button.setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def text(self) -> str:
        return self.main_button.text()

    def setIcon(self, icon: QtGui.QIcon) -> None:
        self.main_button.setIcon(icon)
        self.updateGeometry()

    def icon(self) -> QtGui.QIcon:
        return self.main_button.icon()

    def setIconSize(self, size: QtCore.QSize) -> None:
        self.main_button.setIconSize(size)
        self.updateGeometry()

    def iconSize(self) -> QtCore.QSize:
        return self.main_button.iconSize()

    def description(self) -> str:
        """Return the secondary text line."""
        return self.main_button.description()

    def set_description(self, text: str) -> None:
        """Update the secondary line; an empty string restores one-line sizing."""
        self.main_button.set_description(text)
        self.setAccessibleDescription(self.main_button.description())
        self._sync_parts()

    def setDescription(self, text: str) -> None:
        self.set_description(text)

    def _sync_parts(self):
        self.menu_button.setFixedWidth(40 if self.description() else 32)
        self.updateGeometry()
        self.update()

    def set_menu(self, menu: ActionMenu | None) -> None:
        """Attach an ActionMenu, or detach the current menu with None."""
        self.menu_button.set_menu(menu)

    def setMenu(self, menu: ActionMenu | None) -> None:
        self.set_menu(menu)

    def menu(self) -> ActionMenu | None:
        return self.menu_button.menu()

    def show_menu(self) -> None:
        self.menu_button.show_menu()

    def sizeHint(self) -> QtCore.QSize:
        return self.main_button.sizeHint() + QtCore.QSize(self.menu_button.width(), 0)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.main_button.minimumSizeHint() + QtCore.QSize(self.menu_button.width(), 0)


class AccentSplitButton(SplitButton):
    _accent = True
