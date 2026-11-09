"""Compact, keyboard-accessible setting cards with native Qt reveal animations."""

from __future__ import annotations

import weakref

from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from ..theme.fonts import ui_font
from .card import SimpleCardWidget


class _ExpandHeader(QtWidgets.QAbstractButton):
    def __init__(self, title: str, parent: ExpandableCardWidget):
        super().__init__(parent)
        self._progress = 0.0
        self._keyboard_focus = False
        self.setText(title)
        self.setAccessibleName(title)
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self._refresh_theme()
        theme.subscribe(self, self._refresh_theme)

    def _refresh_theme(self):
        self.setFont(ui_font(theme.tokens.font_size))
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QtCore.QSize(max(120, self.fontMetrics().horizontalAdvance(self.text()) + 72), 48)

    def minimumSizeHint(self):
        return QtCore.QSize(72, 48)

    def keyPressEvent(self, event):
        if not self.isEnabled():
            return super().keyPressEvent(event)
        self._keyboard_focus = True
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
        elif event.key() in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right):
            self.setChecked(event.key() == QtCore.Qt.Key.Key_Right)
            event.accept()
        else:
            super().keyPressEvent(event)
        self.update()

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (
            QtCore.Qt.FocusReason.TabFocusReason,
            QtCore.Qt.FocusReason.BacktabFocusReason,
            QtCore.Qt.FocusReason.ShortcutFocusReason,
        )
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        del event
        tokens = theme.tokens
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        card = self.parentWidget()
        radius = max(0, card.border_radius() - 1)
        if self.isEnabled() and (self.underMouse() or self.isDown()):
            color = QtGui.QColor(tokens.text)
            color.setAlpha(13 if self.isDown() else 6)
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(self.rect()), radius, radius)
            if self._progress > 0:
                path.addRect(QtCore.QRectF(0, self.height() - radius, self.width(), radius))
            painter.fillPath(path, color)
        color = QtGui.QColor(tokens.text if self.isEnabled() else tokens.text_muted)
        painter.setPen(color)
        text_rect = self.rect().adjusted(18, 0, -48, 0)
        text = self.fontMetrics().elidedText(
            self.text(), QtCore.Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.save()
        painter.translate(self.width() - 22, self.height() / 2)
        painter.rotate(180 * self._progress)
        painter.setPen(
            QtGui.QPen(
                color,
                1.2,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.drawPolyline(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(-3.5, -1.5),
                    QtCore.QPointF(0, 2),
                    QtCore.QPointF(3.5, -1.5),
                ]
            )
        )
        painter.restore()
        if self.hasFocus() and self._keyboard_focus:
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.accent), 1.5))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(3, 3, -3, -3), 4, 4)


class ExpandableCardWidget(SimpleCardWidget):
    """A passive content area revealed by its 48px checkable header.

    Add ordinary Qt widgets to ``body_layout`` (also named ``viewLayout``).
    Collapsing clips the content without destroying it or resetting its state.
    ``expandedChanged`` reports the requested state at the start of a transition.
    """

    expandedChanged = Signal(bool)

    def __init__(
        self,
        title: str | QtWidgets.QWidget = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        expanded: bool = False,
    ):
        if isinstance(title, QtWidgets.QWidget):
            if parent is not None:
                raise TypeError("parent was provided twice")
            parent, title = title, ""
        super().__init__(parent)
        self._expanded = bool(expanded)
        self._progress = 1.0 if expanded else 0.0
        self._natural_height = 24
        self._syncing_content = False
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self._root = QtWidgets.QVBoxLayout(self)
        self._root.setContentsMargins(1, 1, 1, 1)
        self._root.setSpacing(0)
        self.header_button = _ExpandHeader(str(title), self)
        self.header_button.setChecked(self._expanded)
        self.header_button._progress = self._progress
        self.header_button.toggled.connect(self.set_expanded)
        self._root.addWidget(self.header_button)

        # The viewport has no layout: its children's minimum sizes must not prevent
        # it from shrinking to zero. The full-size body is clipped as it slides shut.
        self._viewport = QtWidgets.QWidget(self)
        self._viewport.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self._viewport.setFixedHeight(0)
        self._root.addWidget(self._viewport)
        self.view = QtWidgets.QWidget(self._viewport)
        self.body_layout = QtWidgets.QVBoxLayout(self.view)
        self.body_layout.setContentsMargins(12, 12, 12, 12)
        self.body_layout.setSpacing(10)
        self.viewLayout = self.body_layout
        self.view.setVisible(self._expanded)
        self._viewport.setEnabled(self._expanded)

        self._layout_timer = QtCore.QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._sync_content)
        self.view.installEventFilter(self)
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_progress)
        self._animation.finished.connect(self._finish_transition)
        self._refresh_accessibility()
        self._layout_timer.start(0)

    def title(self) -> str:
        return self.header_button.text()

    def set_title(self, title: str) -> None:
        self.header_button.setText(str(title))
        self.header_button.setAccessibleName(str(title))
        self.header_button.updateGeometry()
        self.updateGeometry()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animated: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        if not changed and animated:
            return
        self._expanded = expanded
        with QtCore.QSignalBlocker(self.header_button):
            self.header_button.setChecked(expanded)
        self._refresh_accessibility()
        focus = QtWidgets.QApplication.focusWidget()
        if (
            not expanded
            and focus is not None
            and (focus is self.view or self.view.isAncestorOf(focus))
        ):
            self.header_button.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self._viewport.setEnabled(expanded)
        if expanded:
            self.view.show()
        self._sync_content()
        self._animation.stop()
        target = 1.0 if expanded else 0.0
        if animated and self.isVisible() and abs(target - self._progress) > 0.001:
            self._animation.setDuration(max(100, round(260 * abs(target - self._progress))))
            self._animation.setStartValue(self._progress)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._set_progress(target)
            self._finish_transition()
        if changed:
            self.expandedChanged.emit(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    setTitle = set_title
    setExpanded = set_expanded
    isExpanded = is_expanded

    def _refresh_accessibility(self):
        self.header_button.setAccessibleDescription(
            "展开的设置组" if self._expanded else "折叠的设置组"
        )

    def _body_height(self, width):
        layout = self.body_layout
        height = (
            layout.totalHeightForWidth(width)
            if layout.hasHeightForWidth()
            else layout.sizeHint().height()
        )
        return max(0, height, layout.minimumSize().height(), self.view.minimumHeight())

    def _sync_content(self):
        if self._syncing_content:
            return
        self._syncing_content = True
        try:
            width = max(1, self.width() - 2)
            self._natural_height = self._body_height(width)
            self.view.setGeometry(0, 0, width, self._natural_height)
            self.body_layout.activate()
            self._set_progress(self._progress)
        finally:
            self._syncing_content = False

    def _set_progress(self, value):
        self._progress = max(0.0, min(1.0, float(value)))
        height = round(self._natural_height * self._progress)
        if self._viewport.height() != height:
            self._viewport.setFixedHeight(height)
            self.updateGeometry()
        self.header_button._progress = self._progress
        self.header_button.update()
        self.update()

    def _finish_transition(self):
        if not self._expanded:
            self.view.hide()

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == QtCore.QEvent.Type.LayoutRequest:
            self._layout_timer.start(0)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "body_layout"):
            self._sync_content()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_content()

    def hideEvent(self, event):
        if hasattr(self, "_animation"):
            self._animation.stop()
            self._set_progress(1.0 if self._expanded else 0.0)
            self._finish_transition()
        super().hideEvent(event)

    def sizeHint(self):
        if not hasattr(self, "body_layout"):
            return super().sizeHint()
        width = max(self.header_button.sizeHint().width(), self.body_layout.sizeHint().width()) + 2
        return QtCore.QSize(width, 50 + round(self._natural_height * self._progress))

    def minimumSizeHint(self):
        return QtCore.QSize(74, 50)

    def paintEvent(self, event):
        super().paintEvent(event)
        if hasattr(self, "_viewport") and self._viewport.height() > 0:
            painter = QtGui.QPainter(self)
            painter.setPen(QtGui.QColor(theme.tokens.border))
            painter.drawLine(
                1,
                self.header_button.geometry().bottom() + 1,
                self.width() - 2,
                self.header_button.geometry().bottom() + 1,
            )


class _AccordionLink(QtCore.QObject):
    """Qt-owned receivers disconnect automatically when the container is deleted."""

    def __init__(self, owner, card):
        super().__init__(owner)
        self.owner_ref = weakref.ref(owner)
        self.card_ref = weakref.ref(card)
        card.expandedChanged.connect(self.expanded)
        card.destroyed.connect(self.destroyed_card)

    @Slot(bool)
    def expanded(self, expanded):
        owner, card = self.owner_ref(), self.card_ref()
        if expanded and owner is not None and card is not None:
            owner._card_expanded(card)

    @Slot()
    def destroyed_card(self):
        owner, card = self.owner_ref(), self.card_ref()
        if owner is not None and card in owner._cards:
            owner._cards.remove(card)
            owner._links.pop(card, None)
            if owner._last_expanded is card:
                owner._last_expanded = None
        self.deleteLater()


class AccordionWidget(QtWidgets.QWidget):
    """A vertical collection of expandable cards, optionally one open at a time."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, exclusive: bool = False):
        super().__init__(parent)
        self._cards: list[ExpandableCardWidget] = []
        self._links: dict[ExpandableCardWidget, _AccordionLink] = {}
        self._exclusive = bool(exclusive)
        self._last_expanded = None
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

    def add_card(self, card: ExpandableCardWidget) -> ExpandableCardWidget:
        if not isinstance(card, ExpandableCardWidget):
            raise TypeError("card must be an ExpandableCardWidget")
        if card in self._cards:
            return card
        old = card.parentWidget()
        if isinstance(old, AccordionWidget):
            old.remove_card(card)
        self._cards.append(card)
        self._links[card] = _AccordionLink(self, card)
        self._layout.addWidget(card)
        if card.is_expanded():
            self._card_expanded(card)
        card.show()
        return card

    def cards(self) -> tuple[ExpandableCardWidget, ...]:
        return tuple(self._cards)

    def remove_card(self, card: ExpandableCardWidget, delete: bool = False) -> bool:
        if card not in self._cards:
            return False
        self._cards.remove(card)
        link = self._links.pop(card)
        card.expandedChanged.disconnect(link.expanded)
        card.destroyed.disconnect(link.destroyed_card)
        link.deleteLater()
        if self._last_expanded is card:
            self._last_expanded = None
        self._layout.removeWidget(card)
        card.hide()
        if delete:
            card.deleteLater()
        else:
            card.setParent(None)
        return True

    def is_exclusive(self) -> bool:
        return self._exclusive

    def set_exclusive(self, exclusive: bool) -> None:
        self._exclusive = bool(exclusive)
        if self._exclusive:
            opened = [card for card in self._cards if card.is_expanded()]
            if opened:
                self._card_expanded(
                    self._last_expanded if self._last_expanded in opened else opened[0]
                )

    def _card_expanded(self, card):
        self._last_expanded = card
        if self._exclusive:
            for other in tuple(self._cards):
                if other is not card:
                    other.set_expanded(False)

    addCard = add_card
    removeCard = remove_card
    isExclusive = is_exclusive
    setExclusive = set_exclusive
