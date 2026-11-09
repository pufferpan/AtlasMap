"""Action menus displayed within an owning Qt window."""

from __future__ import annotations

import weakref

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from ..theme.fonts import ui_font
from .button import TextButton
from .scroll_bar import FluentScrollBar
from .system_tray_menu import SystemTrayMenu as SystemTrayMenu


class _MenuSurface(QtWidgets.QWidget):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(10.5, 8.5, -10.5, -11.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        painter.save()
        painter.translate(0, 2)
        for spread in range(10, 0, -1):
            painter.setPen(
                QtGui.QPen(QtGui.QColor(0, 0, 0, 1 if theme.mode.value == "light" else 2), spread)
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()
        painter.setBrush(QtGui.QColor(theme.tokens.surface))
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
        painter.drawPath(path)


class _MenuRow(TextButton):
    entered = Signal()

    def __init__(self, action, parent):
        super().__init__(action.text(), parent)
        self.action = action
        self.active = False
        self.setFixedHeight(32)
        self.setMinimumWidth(0)
        self.setEnabled(action.isEnabled())
        self.setIcon(action.icon())
        self.setAccessibleName(action.text())
        self.submenu = None
        self._selection_progress = 0.0
        self._selection_animation = QtCore.QVariantAnimation(self)
        self._selection_animation.setDuration(120)
        self._selection_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._selection_animation.valueChanged.connect(self._set_selection_progress)

    def set_active(self, active):
        active = bool(active)
        if self.active == active:
            return
        self.active = active
        self._selection_animation.stop()
        self._selection_animation.setStartValue(self._selection_progress)
        self._selection_animation.setEndValue(float(active))
        self._selection_animation.start()

    def _set_selection_progress(self, value):
        self._selection_progress = float(value)
        self.update()

    def hideEvent(self, event):
        self._selection_animation.stop()
        self._selection_progress = float(self.active)
        super().hideEvent(event)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 32)

    def _label_text(self):
        return self.action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")

    def preferred_width(self):
        self.ensurePolished()
        metrics = self.fontMetrics()
        shortcut = self.action.shortcut().toString(QtGui.QKeySequence.SequenceFormat.NativeText)
        trailing = (
            (16 if self.submenu is not None else metrics.horizontalAdvance(shortcut))
            if (self.submenu is not None or shortcut)
            else 0
        )
        # Match the painter: 10 left, 25 icon column, 12 right, optional 18
        # before a shortcut, plus the two half-pixel button boundaries.
        return (
            metrics.horizontalAdvance(self._label_text()) + 49 + trailing + (18 if shortcut else 0)
        )

    def enterEvent(self, event):
        self.entered.emit()
        QtWidgets.QPushButton.enterEvent(self, event)

    def leaveEvent(self, event):
        QtWidgets.QPushButton.leaveEvent(self, event)

    def _surface_color(self):
        color = self._surface_hover_color()
        color.setAlphaF(color.alphaF() * self._selection_progress)
        return color

    def _draw_content(self, painter, rect, color):
        painter.setPen(color)
        x = rect.left() + 10
        checked = self.action.isCheckable() and self.action.isChecked()
        group = self.action.actionGroup()
        radio = checked and group is not None and group.isExclusive()
        icon = fluent_icon(FluentIcon.CHECKMARK) if checked else self.action.icon()
        if radio:
            painter.setBrush(color)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QPointF(x + 8, rect.center().y()), 3.5, 3.5)
            painter.setPen(color)
        elif not icon.isNull():
            self._draw_tinted_icon(
                painter, QtCore.QRect(round(x), round(rect.center().y() - 8), 16, 16), color, icon
            )
        x += 25
        shortcut = self.action.shortcut().toString(QtGui.QKeySequence.SequenceFormat.NativeText)
        width = (
            16
            if self.submenu is not None
            else self.fontMetrics().horizontalAdvance(shortcut)
            if shortcut
            else 0
        )
        text_rect = QtCore.QRectF(
            x,
            rect.top(),
            max(0, rect.right() - x - 12 - width - (18 if shortcut else 0)),
            rect.height(),
        )
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            self.fontMetrics().elidedText(
                self._label_text(), QtCore.Qt.TextElideMode.ElideRight, round(text_rect.width())
            ),
        )
        if self.submenu is not None:
            cx, cy = rect.right() - 14, rect.center().y()
            painter.setPen(
                QtGui.QPen(color, 1.3, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap)
            )
            painter.drawLine(QtCore.QLineF(cx - 2, cy - 4, cx + 2, cy))
            painter.drawLine(QtCore.QLineF(cx + 2, cy, cx - 2, cy + 4))
        elif shortcut:
            painter.setPen(
                QtGui.QColor(theme.tokens.text_muted if self.isEnabled() else theme.tokens.disabled)
            )
            painter.drawText(
                QtCore.QRectF(rect.right() - 12 - width, rect.top(), width, rect.height()),
                QtCore.Qt.AlignmentFlag.AlignVCenter,
                shortcut,
            )


class _SubmenuLink(QtCore.QObject):
    """A Qt-owned receiver avoids touching a deleted submenu wrapper."""

    def __init__(self, owner, action, menu):
        super().__init__(owner)
        self.action, self.menu = action, menu
        self._owner_ref = weakref.ref(owner)
        owner.destroyed.connect(self.owner_destroyed)

    @Slot()
    def owner_destroyed(self):
        self._owner_ref = lambda: None

    @Slot()
    def menu_destroyed(self):
        owner = self._owner_ref()
        if owner is None:
            return
        owner._submenus.pop(self.action, None)
        owner._submenu_links.pop(self.action, None)
        if owner._child_menu is self.menu:
            owner._child_menu = None
        owner.remove_action(self.action)
        self.deleteLater()


class ActionMenu(QtWidgets.QWidget):
    """An action list anchored within its owning window.

    Qt actions retain their enabled, visible, checkable, icon and shortcut state.
    Submenus and inline QWidgetAction items share the same popup lifecycle.
    """

    triggered = Signal(QtGui.QAction)
    aboutToShow = Signal()
    aboutToHide = Signal()

    SHOW_DURATION = 180
    HIDE_DURATION = 120

    def __init__(self, parent=None, *, title=""):
        super().__init__(parent)
        if parent is not None:
            parent.destroyed.connect(self.deleteLater)
        self._anchor = None
        self._watched = []
        self._previous_focus = None
        self._closing = False
        self._opened = False
        self._placing = False
        self._active = -1
        self._progress = 0.0
        self._rest = QtCore.QPoint()
        self._direction = -1
        self._slide_offset = QtCore.QPoint(0, -8)
        self._items = []
        self._custom_content = None
        self._filter_installed = False
        self._batching = False
        self._title = str(title)
        self._icon = QtGui.QIcon()
        self._parent_menu = None
        self._child_menu = None
        self._submenus = {}
        self._submenu_links = {}
        self._context_position = None
        self._submenu_timer = QtCore.QTimer(self)
        self._submenu_timer.setSingleShot(True)
        self._submenu_timer.setInterval(180)
        self._submenu_timer.timeout.connect(self._open_active_submenu)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)
        self._surface = _MenuSurface(self)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self._surface)
        self._surface.setGraphicsEffect(self._opacity)
        self._scroll = QtWidgets.QScrollArea(self._surface)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBar(FluentScrollBar(parent=self._scroll))
        self._scroll.setObjectName("actionMenuScroll")
        self._content = QtWidgets.QWidget(self._scroll)
        self._content.setObjectName("actionMenuContent")
        self._layout = QtWidgets.QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._scroll.setWidget(self._content)
        self._reveal = QtCore.QVariantAnimation(self)
        self._reveal.valueChanged.connect(self._set_progress)
        self._reveal.finished.connect(self._motion_finished)
        self._dirty = False
        self._rebuild_timer = QtCore.QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._rebuild)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)
        self.hide()

    def add_action(
        self,
        text,
        *,
        icon=None,
        callback=None,
        checkable=False,
        checked=False,
        enabled=True,
        shortcut="",
    ):
        action = QtGui.QAction(str(text), self)
        if icon is not None:
            action.setIcon(fluent_icon(icon) if isinstance(icon, FluentIcon) else icon)
        action.setCheckable(checkable)
        action.setChecked(checked)
        action.setEnabled(enabled)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        if callback is not None:
            action.triggered.connect(callback)
        return self.addAction(action)

    def addAction(self, action):
        if self._custom_content is not None:
            raise ValueError("custom content and action rows cannot be mixed")
        if isinstance(action, str):
            return self.add_action(action)
        if not isinstance(action, QtGui.QAction):
            raise TypeError("ActionMenu expects a QAction or text")
        if action not in self.actions():
            action.changed.connect(self._schedule_rebuild)
            action.triggered.connect(self._forward_triggered)
            QtWidgets.QWidget.addAction(self, action)
        return action

    def addActions(self, actions):
        for action in actions:
            self.addAction(action)

    def title(self):
        return self._title

    def setTitle(self, title):
        self._title = str(title)
        if self._parent_menu is not None:
            for action, menu in self._parent_menu._submenus.items():
                if menu is self:
                    action.setText(self._title)

    def setIcon(self, icon):
        self._icon = fluent_icon(icon) if isinstance(icon, FluentIcon) else QtGui.QIcon(icon)
        if self._parent_menu is not None:
            for action, menu in self._parent_menu._submenus.items():
                if menu is self:
                    action.setIcon(self._icon)

    def add_menu(self, title, menu=None, *, icon=None):
        """Return a child ActionMenu. Children cannot be shared or cyclic."""
        if menu is None:
            menu = ActionMenu(self, title=title)
        if not isinstance(menu, ActionMenu):
            raise TypeError("submenu must be an ActionMenu")
        node = self
        while node is not None:
            if node is menu:
                raise ValueError("submenu cycles are not allowed")
            node = node._parent_menu
        if menu._parent_menu is not None:
            raise ValueError("submenu already belongs to a menu")
        action = self.add_action(title, icon=icon)
        menu._parent_menu = self
        menu._title = str(title)
        if icon is not None:
            menu._icon = action.icon()
        self._submenus[action] = menu
        menu.triggered.connect(self.triggered.emit)
        link = _SubmenuLink(self, action, menu)
        self._submenu_links[action] = link
        menu.destroyed.connect(link.menu_destroyed)
        self.destroyed.connect(menu.deleteLater)
        return menu

    def addMenu(self, menu):
        return (
            self.add_menu(menu.title(), menu, icon=menu._icon)
            if isinstance(menu, ActionMenu)
            else self.add_menu(str(menu))
        )

    def add_widget(self, widget):
        """Insert a native QWidgetAction between action rows; owns the widget."""
        if not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("menu content must be a QWidget")
        if (
            widget is self
            or widget.isAncestorOf(self)
            or widget in (self._surface, self._content, self._scroll)
        ):
            raise ValueError("cannot insert a structural widget or ancestor")
        action = QtWidgets.QWidgetAction(self)
        action.setDefaultWidget(widget)
        self.addAction(action)
        return action

    addWidget = add_widget

    def add_separator(self):
        action = QtGui.QAction(self)
        action.setSeparator(True)
        return self.addAction(action)

    def addSeparator(self):
        return self.add_separator()

    def remove_action(self, action):
        if action in self.actions():
            submenu = self._submenus.pop(action, None)
            if submenu is not None:
                submenu.dismiss(immediate=True)
                submenu._parent_menu = None
                submenu.triggered.disconnect(self.triggered.emit)
                link = self._submenu_links.pop(action)
                submenu.destroyed.disconnect(link.menu_destroyed)
                link.deleteLater()
                if self._child_menu is submenu:
                    self._child_menu = None
            action.changed.disconnect(self._schedule_rebuild)
            action.triggered.disconnect(self._forward_triggered)
            QtWidgets.QWidget.removeAction(self, action)

    def removeAction(self, action):
        self.remove_action(action)

    def clear(self):
        self._batching = True
        try:
            for action in self.actions():
                self.remove_action(action)
                if action.parent() is self and not action.associatedObjects():
                    action.deleteLater()
        finally:
            self._batching = False
        self._rebuild()

    def anchor_widget(self):
        return self._anchor

    def set_content_widget(self, widget):
        """Host custom Qt content using the same in-window popup and animations."""
        if widget is not None and not isinstance(widget, QtWidgets.QWidget):
            raise TypeError("content must be a QWidget or None")
        if self.actions():
            raise ValueError("remove actions before setting custom content")
        if widget is not None and (
            widget is self
            or widget.isAncestorOf(self)
            or widget in (self._surface, self._content, self._scroll)
        ):
            raise ValueError("content cannot be a popup's structural widget or ancestor")
        if widget is self._custom_content:
            return
        if self._opened:
            self.dismiss(immediate=True)
        old = self._custom_content
        if old is not None:
            old.destroyed.disconnect(self._custom_destroyed)
            self._layout.removeWidget(old)
            old.hide()
            old.deleteLater()
        self._custom_content = widget
        if widget is not None:
            self._layout.addWidget(widget)
            widget.destroyed.connect(self._custom_destroyed)
            widget.show()
        self._layout.activate()

    def _custom_destroyed(self):
        self._custom_content = None
        self.dismiss(immediate=True)

    setContentWidget = set_content_widget

    def actionEvent(self, event):
        super().actionEvent(event)
        if hasattr(self, "_layout"):
            if event.type() == QtCore.QEvent.Type.ActionRemoved and not self._batching:
                self._rebuild()
            else:
                self._schedule_rebuild()

    def _schedule_rebuild(self):
        self._dirty = True
        if not self._rebuild_timer.isActive():
            self._rebuild_timer.start(0)

    def _rebuild(self):
        self._dirty = False
        self._rebuild_timer.stop()
        if self._custom_content is not None:
            return
        active_action = (
            self._items[self._active].action if 0 <= self._active < len(self._items) else None
        )
        self._close_child()
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            widget.hide()
            if not widget.property("_menuInlineWidget"):
                widget.deleteLater()
        self._items = []
        for action in self.actions():
            if not action.isVisible():
                continue
            if isinstance(action, QtWidgets.QWidgetAction):
                widget = action.defaultWidget()
                if widget is not None:
                    widget.setProperty("_menuInlineWidget", True)
                    self._layout.addWidget(widget)
                    widget.show()
            elif action.isSeparator():
                line = QtWidgets.QFrame(self._content)
                line.setFixedHeight(7)
                line.setObjectName("actionMenuSeparator")
                self._layout.addWidget(line)
            else:
                row = _MenuRow(action, self._content)
                row.submenu = self._submenus.get(action)
                row.entered.connect(self._row_entered)
                row.clicked.connect(self._row_clicked)
                self._items.append(row)
                self._layout.addWidget(row)
        self._layout.activate()
        self._active = next(
            (
                i
                for i, row in enumerate(self._items)
                if row.action is active_action and row.isEnabled()
            ),
            -1,
        )
        if self._opened:
            if not self._layout.count():
                self.dismiss(immediate=True)
            else:
                self._place()
                self._select(self._active if self._active >= 0 else self._first_enabled())

    def _first_enabled(self):
        return next((i for i, row in enumerate(self._items) if row.isEnabled()), -1)

    def _select(self, index):
        self._active = index
        for i, row in enumerate(self._items):
            row.set_active(i == index)
        if 0 <= index < len(self._items):
            row = self._items[index]
            row.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
            self._scroll.ensureWidgetVisible(row, 0, 2)

    @Slot()
    def _row_entered(self):
        row = self.sender()
        if row in self._items and row.isEnabled():
            if self._child_menu is not row.submenu:
                self._close_child(immediate=False)
            self._select(self._items.index(row))
            if row.submenu is not None:
                self._submenu_timer.start()

    def _close_child(self, *, immediate=True):
        self._submenu_timer.stop()
        if self._child_menu is not None:
            child = self._child_menu
            self._child_menu = None
            child.dismiss(immediate=immediate)

    def _open_active_submenu(self):
        if not self._opened or self._closing or not 0 <= self._active < len(self._items):
            return
        row = self._items[self._active]
        if row.submenu is not None and row.isEnabled():
            if self._child_menu is row.submenu and self._child_menu._opened:
                return
            self._close_child(immediate=False)
            self._child_menu = row.submenu
            row.submenu.popup(row)

    @Slot()
    def _row_clicked(self):
        row = self.sender()
        if row in self._items:
            self._activate(row.action)

    @Slot()
    def _forward_triggered(self):
        action = self.sender()
        if action in self.actions():
            self.triggered.emit(action)

    def _activate(self, action):
        if self._closing or not action.isEnabled() or not action.isVisible():
            return
        if action in self._submenus:
            self._open_active_submenu()
            return
        root = self
        while root._parent_menu is not None:
            root = root._parent_menu
        root.dismiss()
        action.trigger()

    def popup(self, anchor):
        if not isinstance(anchor, QtWidgets.QWidget):
            raise TypeError("popup anchor must be a QWidget")
        if self._dirty:
            self._rebuild()
        if (
            not anchor.isEnabled()
            or not anchor.isVisible()
            or (not self._layout.count() and self._custom_content is None)
        ):
            return False
        context_position = self._context_position
        if self._opened:
            self.dismiss(immediate=True)
        self._context_position = context_position
        owner = anchor.window()
        root = self
        while root._parent_menu is not None:
            root = root._parent_menu
        for other in owner.findChildren(ActionMenu):
            other_root = other
            while other_root._parent_menu is not None:
                other_root = other_root._parent_menu
            if other is not self and other._opened and other_root is not root:
                other.dismiss(immediate=True)
        if self.parentWidget() is not owner:
            self.setParent(owner, QtCore.Qt.WindowType.Widget)
        self._anchor = anchor
        self._previous_focus = anchor
        node = anchor
        while node is not None:
            self._watched.append(node)
            node.installEventFilter(self)
            if node is owner:
                break
            node = node.parentWidget()
        anchor.destroyed.connect(self._anchor_destroyed)
        self._closing = False
        self._opened = True
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._progress = 0.0
        self._place()
        self._set_progress(0.0)
        app = QtWidgets.QApplication.instance()
        app.installEventFilter(self)
        self._filter_installed = True
        self.aboutToShow.emit()
        self.show()
        self.raise_()
        self.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        if self._custom_content is None:
            self._select(self._first_enabled())
        else:
            self._custom_content.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        self._animate(1.0, self.SHOW_DURATION)
        return True

    def popup_at(self, anchor, position):
        """Open at a point in anchor coordinates, e.g. a contextMenuEvent pos."""
        if not isinstance(position, QtCore.QPoint):
            raise TypeError("position must be a QPoint in anchor coordinates")
        self._context_position = QtCore.QPoint(position)
        if not self.popup(anchor):
            self._context_position = None
            return False
        return True

    def dismiss(self, *, immediate=False):
        self._close_child(immediate=immediate)
        if not self._opened:
            return
        if not self._closing:
            self._closing = True
            self._submenu_timer.stop()
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.aboutToHide.emit()
        if immediate or self._progress <= 0.001:
            self._reveal.stop()
            self._finish_hide()
        else:
            self._animate(0.0, self.HIDE_DURATION)

    def _animate(self, end, duration):
        self._reveal.stop()
        self._reveal.setDuration(duration)
        self._reveal.setEasingCurve(
            QtCore.QEasingCurve.Type.OutCubic if end else QtCore.QEasingCurve.Type.InOutCubic
        )
        self._reveal.setStartValue(self._progress)
        self._reveal.setEndValue(end)
        self._reveal.start()

    def _set_progress(self, value):
        self._progress = float(value)
        self._opacity.setOpacity(self._progress)
        self._surface.move(
            self._rest
            + QtCore.QPoint(
                round(self._slide_offset.x() * (1 - self._progress)),
                round(self._slide_offset.y() * (1 - self._progress)),
            )
        )
        if self._parent_menu is not None:
            # Only the child panel receives input; the parent's rows stay usable.
            self.setMask(QtGui.QRegion(self._surface.geometry()))

    def _motion_finished(self):
        if self._closing:
            self._finish_hide()

    def _remove_watchers(self):
        if self._filter_installed:
            QtWidgets.QApplication.instance().removeEventFilter(self)
            self._filter_installed = False
        for node in self._watched:
            try:
                node.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched.clear()
        if self._anchor is not None:
            try:
                self._anchor.destroyed.disconnect(self._anchor_destroyed)
            except (RuntimeError, TypeError):
                pass

    def _finish_hide(self):
        for child in tuple(self._submenus.values()):
            if child._opened:
                child.dismiss(immediate=True)
        self._remove_watchers()
        self._opened = False
        self._closing = False
        self.hide()
        try:
            if self._previous_focus is not None and self._previous_focus.isVisible():
                self._previous_focus.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        except RuntimeError:
            pass
        self._previous_focus = None
        self._anchor = None
        self._context_position = None
        if self._parent_menu is not None and self._parent_menu._child_menu is self:
            self._parent_menu._child_menu = None

    def _anchor_destroyed(self):
        self._anchor = None
        self.dismiss(immediate=True)

    def _place(self):
        if self._placing or self._anchor is None:
            return
        self._placing = True
        try:
            owner = self.parentWidget()
            self.setGeometry(owner.rect())
            anchor = QtCore.QRect(self._anchor.mapTo(owner, QtCore.QPoint()), self._anchor.size())
            scrollbar_space = max(0, self._scroll.verticalScrollBar().sizeHint().width())
            widths = [row.preferred_width() + 34 + scrollbar_space for row in self._items]
            anchor_width = 0 if self._context_position is not None else anchor.width() + 20
            width = max(0, min(self.width() - 8, 480, max([160, anchor_width, *widths])))
            height = max(0, min(self.height() - 8, 360, self._layout.sizeHint().height() + 32))
            if self._custom_content is not None:
                width = max(0, min(self.width() - 8, self._custom_content.sizeHint().width() + 34))
                height = max(0, min(self.height() - 8, self._layout.sizeHint().height() + 32))
            inline_widths = [
                max(
                    action.defaultWidget().sizeHint().width(),
                    action.defaultWidget().minimumSizeHint().width(),
                    action.defaultWidget().minimumWidth(),
                )
                + 34
                for action in self.actions()
                if isinstance(action, QtWidgets.QWidgetAction)
                and action.defaultWidget() is not None
            ]
            if inline_widths:
                width = min(self.width() - 8, max(width, *inline_widths))
            self._surface.resize(width, height)
            self._scroll.setGeometry(17, 15, max(0, width - 34), max(0, height - 30))
            x = anchor.left() - 10
            below = anchor.bottom() + 1 - 3
            above = anchor.top() - height + 3
            fits_below = below + height <= self.height() - 4
            y = below if fits_below or above < 4 else above
            if self._context_position is not None:
                context = self._anchor.mapTo(owner, self._context_position)
                x, y = context.x() - 10, context.y() - 8
                if y + height > self.height() - 4:
                    y = context.y() - height + 8
            if self._parent_menu is not None:
                parent_rect = self._parent_menu._surface.geometry()
                x = parent_rect.right() - 10
                if x + width > self.width() - 4:
                    x = parent_rect.left() - width + 10
                y = anchor.top() - 15
            self._direction = -1 if fits_below else 1
            if self._context_position is not None:
                self._direction = -1 if y >= context.y() - 8 else 1
            if self._parent_menu is not None:
                self._slide_offset = QtCore.QPoint(-8 if x >= parent_rect.left() else 8, 0)
            else:
                self._slide_offset = QtCore.QPoint(0, self._direction * 8)
            x = max(4, min(x, self.width() - width - 4))
            y = max(4, min(y, self.height() - height - 4))
            self._rest = QtCore.QPoint(x, y)
            self._set_progress(self._progress)
        finally:
            self._placing = False

    def eventFilter(self, watched, event):
        if not self._opened or self._closing:
            return False
        kind = event.type()
        if (
            self._parent_menu is not None
            and kind == QtCore.QEvent.Type.MouseButtonPress
            and isinstance(watched, QtWidgets.QWidget)
            and not self._surface.isAncestorOf(watched)
            and watched is not self._surface
        ):
            self.dismiss(immediate=True)
            return False
        if watched in self._watched:
            if kind in (
                QtCore.QEvent.Type.Hide,
                QtCore.QEvent.Type.Close,
                QtCore.QEvent.Type.WindowDeactivate,
            ):
                self.dismiss(immediate=True)
            elif kind == QtCore.QEvent.Type.EnabledChange and not watched.isEnabled():
                self.dismiss(immediate=True)
            elif kind in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Move) and not self._closing:
                self._place()
        if (
            self._opened
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self.window()
        ):
            if self._child_menu is not None and self._child_menu._opened:
                return False  # The deepest menu owns keyboard handling.
            inline = any(
                isinstance(action, QtWidgets.QWidgetAction)
                and action.defaultWidget() is not None
                and (
                    watched is action.defaultWidget()
                    or action.defaultWidget().isAncestorOf(watched)
                )
                for action in self.actions()
            )
            if kind == QtCore.QEvent.Type.ShortcutOverride:
                if (
                    self._custom_content is not None or inline
                ) and event.key() != QtCore.Qt.Key.Key_Escape:
                    return False
                event.accept()
                return True
            if kind == QtCore.QEvent.Type.KeyPress:
                key = event.key()
                if inline and key != QtCore.Qt.Key.Key_Escape:
                    return False
                if self._custom_content is not None:
                    if key == QtCore.Qt.Key.Key_Escape:
                        self.dismiss()
                        event.accept()
                        return True
                    if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
                        controls = [
                            control
                            for control in self._custom_content.findChildren(QtWidgets.QWidget)
                            if control.isVisible()
                            and control.isEnabled()
                            and control.focusPolicy() & QtCore.Qt.FocusPolicy.TabFocus
                        ]
                        if controls:
                            focus = QtWidgets.QApplication.focusWidget()
                            index = controls.index(focus) if focus in controls else -1
                            backwards = key == QtCore.Qt.Key.Key_Backtab or bool(
                                event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
                            )
                            controls[(index + (-1 if backwards else 1)) % len(controls)].setFocus(
                                QtCore.Qt.FocusReason.BacktabFocusReason
                                if backwards
                                else QtCore.Qt.FocusReason.TabFocusReason
                            )
                        event.accept()
                        return True
                    return False
                if key == QtCore.Qt.Key.Key_Right:
                    self._open_active_submenu()
                elif key == QtCore.Qt.Key.Key_Left and self._parent_menu is not None:
                    parent = self._parent_menu
                    self.dismiss(immediate=True)
                    parent._select(parent._active)
                elif key in (
                    QtCore.Qt.Key.Key_Escape,
                    QtCore.Qt.Key.Key_Tab,
                    QtCore.Qt.Key.Key_Backtab,
                ):
                    self.dismiss()
                elif key in (
                    QtCore.Qt.Key.Key_Down,
                    QtCore.Qt.Key.Key_Up,
                    QtCore.Qt.Key.Key_Home,
                    QtCore.Qt.Key.Key_End,
                ):
                    eligible = [i for i, row in enumerate(self._items) if row.isEnabled()]
                    if eligible:
                        current = eligible.index(self._active) if self._active in eligible else -1
                        index = (
                            0
                            if key == QtCore.Qt.Key.Key_Home
                            else len(eligible) - 1
                            if key == QtCore.Qt.Key.Key_End
                            else (current + (1 if key == QtCore.Qt.Key.Key_Down else -1))
                            % len(eligible)
                        )
                        self._select(eligible[index])
                elif key in (
                    QtCore.Qt.Key.Key_Return,
                    QtCore.Qt.Key.Key_Enter,
                    QtCore.Qt.Key.Key_Space,
                ):
                    if 0 <= self._active < len(self._items) and not event.isAutoRepeat():
                        self._activate(self._items[self._active].action)
                event.accept()
                return True
        return False

    def mousePressEvent(self, event):
        if self._custom_content is None or not self._surface.geometry().contains(
            event.position().toPoint()
        ):
            self.dismiss()
        event.accept()

    def hideEvent(self, event):
        if self._opened:
            self._close_child()
            self._reveal.stop()
            self._remove_watchers()
            self._opened = False
            self._closing = False
            self.aboutToHide.emit()
            self._anchor = None
            self._context_position = None
        super().hideEvent(event)

    def _apply_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.setStyleSheet(
            "QScrollArea#actionMenuScroll, QWidget#actionMenuContent, QScrollArea#actionMenuScroll > QWidget { background: transparent; border: none; }"
            f"QFrame#actionMenuSeparator {{ background: transparent; border: none; border-bottom: 1px solid {theme.tokens.border}; margin: 3px 8px; }}"
        )
        self._surface.update()
        if self._opened:
            self._place()
