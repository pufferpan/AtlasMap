from __future__ import annotations

from ..qt import QtCore, QtGui, QtWidgets
from ..theme import theme
from ..theme.fonts import ui_font
from .toast_stack import _notification_rect, _ToastStack


class _SuccessIcon(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setAccessibleName("成功")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 24, self.height() / 24)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#0f7b0f" if theme.mode.value == "light" else "#6ccb5f"))
        painter.drawEllipse(QtCore.QRectF(0, 0, 24, 24))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor("white" if theme.mode.value == "light" else "#102810"),
                1.8,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        path = QtGui.QPainterPath(QtCore.QPointF(7, 12))
        path.lineTo(10.5, 15.5)
        path.lineTo(17, 9)
        painter.drawPath(path)


class _CloseButton(QtWidgets.QAbstractButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("关闭提示")

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 24, self.height() / 24)
        if self.underMouse() or self.hasFocus():
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(theme.tokens.surface_high))
            painter.drawRoundedRect(QtCore.QRectF(0, 0, 24, 24), 4, 4)
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(theme.tokens.text),
                1.1,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(QtCore.QPointF(7, 7), QtCore.QPointF(17, 17))
        painter.drawLine(QtCore.QPointF(17, 7), QtCore.QPointF(7, 17))


class Toast(QtWidgets.QFrame):
    """A closeable message card; an optional target adds a pointing arrow.

    With a parent/target this is an ordinary child painted inside the window.
    Existing corner placements remain available without a target.
    """

    SHOW_DURATION = 280
    HIDE_DURATION = 180
    PLACEMENTS = (
        "top-left",
        "top-center",
        "top-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    )

    def __init__(
        self,
        title: str,
        detail: str = "",
        parent: QtWidgets.QWidget | None = None,
        *,
        target: QtWidgets.QWidget | None = None,
    ) -> None:
        if target is not None:
            parent = target.window()
        flags = (
            QtCore.Qt.WindowType.Widget
            if parent is not None
            else (
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.ToolTip
                | QtCore.Qt.WindowType.NoDropShadowWindowHint
            )
        )
        super().__init__(parent, flags)
        self.setObjectName("fluentToast")
        self._placement: str | None = None
        self._stack = None
        self._stack_target = QtCore.QPoint()
        self._stack_motion = QtCore.QVariantAnimation(self)
        self._stack_motion.setDuration(240)
        self._stack_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._stack_motion.valueChanged.connect(self._set_stack_position)
        self._compact = not bool(detail)
        self._target = target
        self._arrow_edge: str | None = None
        self._arrow_x = 0.0
        self._positioning = False
        self._position_host = None
        self._closing = False
        self._allow_close = False
        self._reveal_progress = 1.0
        self._rest_pos = QtCore.QPoint()
        self._base_rect = QtCore.QRect()
        self._motion = QtCore.QPoint(0, 1)
        self._slide_distance = 12 if self._compact else 6
        if parent is None:
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        elif parent.window().testAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen):
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)

        # Assign parents before any visibility change: showing an orphan QLabel
        # briefly creates a decorated top-level window on Windows.
        layout = QtWidgets.QHBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        margins = (28, 22, 24, 28) if self._compact else (32, 28, 30, 36)
        layout.setContentsMargins(*margins)
        layout.setSpacing(10 if self._compact else 14)
        self._icon = _SuccessIcon(self)
        if self._compact:
            self._icon.setFixedSize(20, 20)
        layout.addWidget(self._icon, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)
        self._title = QtWidgets.QLabel(title, self)
        self._detail = QtWidgets.QLabel(detail, self)
        self._title.setObjectName("toastTitle")
        self._detail.setObjectName("toastDetail")
        for label in (self._title, self._detail):
            label.setWordWrap(True)
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setMinimumSize(0, 0)
            label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred
            )
        text.addWidget(self._title)
        text.addWidget(self._detail)
        self._detail.setVisible(bool(detail))
        layout.addLayout(text, 1)
        self.close_button = _CloseButton(self)
        if self._compact:
            self.close_button.setFixedSize(20, 20)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(
            self.close_button,
            0,
            QtCore.Qt.AlignmentFlag.AlignVCenter
            if self._compact
            else QtCore.Qt.AlignmentFlag.AlignTop,
        )

        watched = target or parent
        while watched is not None:
            watched.installEventFilter(self)
            if watched is parent:
                break
            watched = watched.parentWidget()
        if target is not None:
            target.destroyed.connect(self._target_destroyed)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._reveal = QtCore.QVariantAnimation(self)
        self._reveal.valueChanged.connect(self._set_reveal_progress)
        self._reveal.finished.connect(self._reveal_finished)
        self._apply_theme()
        theme.subscribe(self, self._apply_theme)

    @classmethod
    def success(
        cls,
        title: str,
        *,
        detail: str = "",
        placement: str = "top-right",
        timeout_ms: int = 2000,
        parent: QtWidgets.QWidget | None = None,
        target: QtWidgets.QWidget | None = None,
    ) -> "Toast":
        toast = cls(title, detail, parent or QtWidgets.QApplication.activeWindow(), target=target)
        toast.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.show_at(placement)
        timer = QtCore.QTimer(toast)
        timer.setSingleShot(True)
        timer.timeout.connect(toast.close)
        if timeout_ms > 0:
            timer.start(timeout_ms)
        return toast

    def sizeHint(self) -> QtCore.QSize:
        metrics = self._title.fontMetrics()
        text_width = max(
            metrics.horizontalAdvance(self._title.text()),
            self._detail.fontMetrics().horizontalAdvance(self._detail.text()),
        )
        width = min(
            640, max(220 if self._compact else 300, text_width + (112 if self._compact else 138))
        )
        return QtCore.QSize(width, self.heightForWidth(width))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        text_width = max(1, width - (112 if self._compact else 138))
        title_height = max(
            self._title.fontMetrics().height(), self._title.heightForWidth(text_width)
        )
        detail_height = (
            max(self._detail.fontMetrics().height(), self._detail.heightForWidth(text_width))
            if self._detail.text()
            else 0
        )
        return max(
            80 if self._compact else 112,
            (50 if self._compact else 64)
            + title_height
            + (2 + detail_height if detail_height else 0),
        )

    def show_at(self, placement: str = "top-right") -> None:
        if placement not in self.PLACEMENTS:
            raise ValueError(f"placement must be one of {self.PLACEMENTS}")
        was_visible = self.isVisible() and not self._closing
        self._reveal.stop()
        self._closing = False
        self._allow_close = False
        self._reveal_progress = 1.0 if was_visible else 0.0
        self._placement = placement
        if self._stack is not None and self._stack.placement != placement:
            self._stack.remove(self)
        self._position()
        if self._target is None:
            _ToastStack.for_toast(self, placement).add(self)
        self._set_reveal_progress(self._reveal_progress)
        self.show()
        self.raise_()
        if not was_visible:
            self._animate_reveal(1.0, self.SHOW_DURATION)

    def _position(self) -> None:
        if self._positioning:
            return
        self._positioning = True
        try:
            parent = self.parentWidget()
            screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
            base = (
                _notification_rect(parent)
                if parent is not None
                else (
                    screen.availableGeometry()
                    if screen is not None
                    else QtCore.QRect(0, 0, 1280, 800)
                )
            )
            content = parent.centralWidget() if isinstance(parent, QtWidgets.QMainWindow) else None
            if content is not self._position_host:
                if self._position_host is not None:
                    try:
                        self._position_host.removeEventFilter(self)
                    except RuntimeError:
                        pass  # A replaced central widget may already be deleted.
                self._position_host = content
                if content is not None:
                    content.installEventFilter(self)
            self.ensurePolished()
            width = min(max(0, base.width()), self.sizeHint().width())
            self.resize(width, min(max(0, base.height()), self.heightForWidth(width)))
            self._arrow_edge = None
            if self._target is not None:
                anchor = QtCore.QRect(
                    self._target.mapTo(parent, QtCore.QPoint()), self._target.size()
                )
                x = anchor.center().x() - self.width() // 2
                above = anchor.top() - 6 - (self.height() - 12)
                below = anchor.bottom() + 2
                if above >= base.top() or below + self.height() > base.bottom() + 1:
                    y, self._arrow_edge = above, "bottom"
                else:
                    y, self._arrow_edge = below, "top"
            else:
                placement = self._placement or "top-right"
                x = (
                    (base.width() - self.width()) // 2 + base.left()
                    if placement.endswith("center")
                    else base.right() + 1 - self.width() - 18
                    if placement.endswith("right")
                    else base.left() + 18
                )
                y = (
                    base.bottom() + 1 - self.height() - 18
                    if placement.startswith("bottom")
                    else base.top() + 18
                )
            x = max(base.left(), min(x, base.right() + 1 - self.width()))
            y = max(base.top(), min(y, base.bottom() + 1 - self.height()))
            self._base_rect = QtCore.QRect(base)
            if self._target is not None:
                self._motion = QtCore.QPoint(0, -1 if self._arrow_edge == "top" else 1)
            elif (self._placement or "top-right").endswith("center"):
                self._motion = QtCore.QPoint(0, -1 if self._placement.startswith("top") else 1)
            else:
                self._motion = QtCore.QPoint(
                    1 if (self._placement or "top-right").endswith("right") else -1, 0
                )
            if self._target is not None:
                self._arrow_x = max(34, min(anchor.center().x() - x, self.width() - 34))
            self.layout().activate()
            if self._stack is not None:
                self._stack.reflow(animated=False)
            else:
                self._rest_pos = QtCore.QPoint(x, y)
                self._stack_target = QtCore.QPoint(x, y)
            self._set_reveal_progress(self._reveal_progress)
            self.update()
        finally:
            self._positioning = False

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if self._placement is not None:
            if event.type() in (
                QtCore.QEvent.Type.Resize,
                QtCore.QEvent.Type.Move,
                QtCore.QEvent.Type.LayoutRequest,
                QtCore.QEvent.Type.Show,
            ):
                self._position()
            elif event.type() == QtCore.QEvent.Type.Hide and watched is not self._position_host:
                self._allow_close = True
                self.close()
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        self._placement = None
        if self._allow_close or not self.isVisible() or self._reveal_progress <= 0.001:
            self._reveal.stop()
            self._closing = False
            super().closeEvent(event)
            return
        event.ignore()
        if not self._closing:
            self._closing = True
            self._animate_reveal(0.0, self.HIDE_DURATION)

    def hideEvent(self, event) -> None:
        self._stack_motion.stop()
        if self._stack is not None:
            self._stack.remove(self)
        self._placement = None
        super().hideEvent(event)

    def _set_stack_target(self, position, *, animated=True):
        if position == self._stack_target and animated:
            return
        self._stack_motion.stop()
        self._stack_target = QtCore.QPoint(position)
        if animated and self._rest_pos != position:
            self._stack_motion.setStartValue(self._rest_pos)
            self._stack_motion.setEndValue(position)
            self._stack_motion.start()
        else:
            self._set_stack_position(position)

    def _set_stack_position(self, position):
        self._rest_pos = QtCore.QPoint(position)
        self._set_reveal_progress(self._reveal_progress)

    def _target_destroyed(self) -> None:
        self._target = None
        self._allow_close = True
        self.close()

    def _animate_reveal(self, end: float, duration: int) -> None:
        self._reveal.stop()
        self._reveal.setDuration(duration)
        self._reveal.setStartValue(self._reveal_progress)
        self._reveal.setEndValue(end)
        self._reveal.setEasingCurve(
            QtCore.QEasingCurve.Type.OutCubic if end else QtCore.QEasingCurve.Type.InCubic
        )
        self._reveal.start()

    def _set_reveal_progress(self, value: float) -> None:
        self._reveal_progress = max(0.0, min(1.0, float(value)))
        self._opacity.setOpacity(self._reveal_progress)
        offset = round(self._slide_distance * (1.0 - self._reveal_progress))
        x = self._rest_pos.x() + self._motion.x() * offset
        x = max(self._base_rect.left(), min(x, self._base_rect.right() + 1 - self.width()))
        y = self._rest_pos.y() + self._motion.y() * offset
        y = max(self._base_rect.top(), min(y, self._base_rect.bottom() + 1 - self.height()))
        self.move(x, y)

    def _reveal_finished(self) -> None:
        if self._closing:
            self._allow_close = True
            self.close()

    def _card_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(16.5, 12.5, max(0, self.width() - 33), max(0, self.height() - 33))

    def _card_path(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        rect = self._card_rect()
        path.addRoundedRect(rect, 10, 10)
        if self._arrow_edge is not None and rect.width() > 36:
            triangle = QtGui.QPainterPath()
            y = rect.bottom() if self._arrow_edge == "bottom" else rect.top()
            direction = 1 if self._arrow_edge == "bottom" else -1
            triangle.moveTo(self._arrow_x - 9, y - direction)
            triangle.lineTo(self._arrow_x, y + direction * 8)
            triangle.lineTo(self._arrow_x + 9, y - direction)
            triangle.closeSubpath()
            path = path.united(triangle)
        return path

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        path = self._card_path()
        # The soft shadow and arrow are painted in the same child surface.
        painter.save()
        painter.translate(0, 2)
        for spread in range(12, 0, -1):
            painter.setPen(
                QtGui.QPen(QtGui.QColor(0, 0, 0, 1 if theme.mode.value == "light" else 2), spread)
            )
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()
        painter.setPen(
            QtGui.QPen(QtGui.QColor("#e2e2e2" if theme.mode.value == "light" else "#454545"), 1)
        )
        painter.setBrush(QtGui.QColor("#f8f8f8" if theme.mode.value == "light" else "#2b2b2b"))
        painter.drawPath(path)

    def _apply_theme(self) -> None:
        tokens = theme.tokens
        size = tokens.font_size if self._compact else tokens.font_size + 2
        self.setFont(ui_font(size, self.font()))
        self.setStyleSheet(f"""
QFrame#fluentToast {{ background: transparent; border: none; }}
QLabel#toastTitle, QLabel#toastDetail {{ color: {tokens.text}; background: transparent; border: none; font-size: {size}px; }}
QLabel#toastTitle {{ font-weight: 600; }}
""")
        self._title.setFont(ui_font(size, self._title.font()))
        bold = self._title.font()
        bold.setWeight(QtGui.QFont.Weight.DemiBold)
        self._title.setFont(bold)
        self._detail.setFont(ui_font(size, self._detail.font()))
        self._icon.update()
        self.close_button.update()
        if self._placement is not None:
            self._position()
        self.update()
