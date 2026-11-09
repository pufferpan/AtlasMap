"""Screen sampling starts explicitly, captures once, and always releases its overlays."""

from __future__ import annotations

from functools import partial

from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme.fonts import ui_font
from .button import Button
from .color_panel import _color, _hex, _paint_color


def _dispose_overlays(overlays, cursor_owned):
    # External receiver still runs when the picker itself is being destroyed.
    for overlay in overlays:
        overlay.hide()
        overlay.deleteLater()
    overlays.clear()
    if cursor_owned[0]:
        QtWidgets.QApplication.restoreOverrideCursor()
        cursor_owned[0] = False


class _ScreenOverlay(QtWidgets.QWidget):
    def __init__(self, picker, geometry, snapshot):
        super().__init__(
            None,
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.NoDropShadowWindowHint,
        )
        self.picker = picker
        self.snapshot = snapshot
        self.setGeometry(geometry)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def mouseMoveEvent(self, event):
        self.picker._move(event.globalPosition().toPoint())

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.picker._choose(event.globalPosition().toPoint())
        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            self.picker.cancel()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.picker.cancel()
        elif event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Space,
        ):
            self.picker._choose(self.picker._point)
        elif event.key() in (
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.Key.Key_Right,
            QtCore.Qt.Key.Key_Up,
            QtCore.Qt.Key.Key_Down,
        ):
            dx = int(event.key() == QtCore.Qt.Key.Key_Right) - int(
                event.key() == QtCore.Qt.Key.Key_Left
            )
            dy = int(event.key() == QtCore.Qt.Key.Key_Down) - int(
                event.key() == QtCore.Qt.Key.Key_Up
            )
            point = self.picker._point + QtCore.QPoint(dx, dy)
            if self.picker.sample_color(point).isValid():
                QtGui.QCursor.setPos(point)
                self.picker._move(point)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.drawImage(self.rect(), self.snapshot)
        point = self.mapFromGlobal(self.picker._point)
        if not self.rect().contains(point):
            return
        value = self.picker.sample_color(self.picker._point)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 3))
        painter.drawEllipse(point, 5, 5)
        painter.setPen(QtGui.QPen(QtGui.QColor("#141414"), 1))
        painter.drawEllipse(point, 5, 5)
        width, height = 156, 64
        x = min(max(8, point.x() + 22), max(8, self.width() - width - 8))
        y = min(max(8, point.y() + 22), max(8, self.height() - height - 8))
        box = QtCore.QRectF(x, y, width, height)
        painter.setPen(QtGui.QPen(QtGui.QColor("#d7d9dc"), 1))
        painter.setBrush(QtGui.QColor("#ffffff"))
        painter.drawRoundedRect(box, 7, 7)
        # Magnify a pixel-aligned region of the frozen screen, never the overlay itself.
        scale_x = self.snapshot.width() / self.width()
        scale_y = self.snapshot.height() / self.height()
        source = QtCore.QRectF(point.x() * scale_x - 4, point.y() * scale_y - 4, 9, 9)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(QtCore.QRectF(x + 8, y + 8, 48, 48), self.snapshot, source)
        painter.setFont(ui_font(12, self.font()))
        painter.setPen(QtGui.QColor("#202020"))
        painter.drawText(
            QtCore.QRectF(x + 65, y + 7, 86, 23), QtCore.Qt.AlignmentFlag.AlignVCenter, _hex(value)
        )
        painter.setFont(ui_font(10, self.font()))
        painter.setPen(QtGui.QColor("#666666"))
        painter.drawText(
            QtCore.QRectF(x + 65, y + 31, 86, 24),
            QtCore.Qt.AlignmentFlag.AlignVCenter,
            "单击选取 · Esc取消",
        )


class ScreenColorPicker(QtCore.QObject):
    """Explicit desktop eyedropper, with logical-coordinate and mixed-DPI mapping."""

    colorSelected = Signal(QtGui.QColor)
    colorPreviewed = Signal(QtGui.QColor)
    canceled = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames = []
        self._overlays = []
        self._active = False
        self._cursor_owned = [False]
        self._point = QtCore.QPoint()
        self._last_preview = QtGui.QColor()
        self._owner = parent.window() if isinstance(parent, QtWidgets.QWidget) else None
        if self._owner is not None:
            self._owner.installEventFilter(self)
        # A Qt-owned child cannot be relied upon to run a Python destructor.
        if parent is not None:
            parent.destroyed.connect(self.cancel)
        self.destroyed.connect(partial(_dispose_overlays, self._overlays, self._cursor_owned))
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.cancel)

    def is_active(self):
        return self._active

    def _capture_screens(self):
        frames = []
        for screen in QtGui.QGuiApplication.screens():
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("当前系统不允许读取屏幕颜色")
            frames.append((QtCore.QRect(screen.geometry()), pixmap.toImage()))
        return frames

    def start(self):
        if self._active:
            return False
        try:
            frames = self._capture_screens()
            if not frames or any(rect.isEmpty() or image.isNull() for rect, image in frames):
                raise RuntimeError("没有可取色的屏幕")
            self._frames = [(QtCore.QRect(rect), QtGui.QImage(image)) for rect, image in frames]
            self._active = True
            self._point = QtGui.QCursor.pos()
            self._last_preview = QtGui.QColor()
            for rect, image in self._frames:
                self._overlays.append(_ScreenOverlay(self, rect, image))
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.CrossCursor)
            self._cursor_owned[0] = True
            for overlay in self._overlays:
                overlay.show()
                overlay.raise_()
            target = next(
                (overlay for overlay in self._overlays if overlay.geometry().contains(self._point)),
                self._overlays[0],
            )
            target.activateWindow()
            target.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            QtWidgets.QApplication.instance().applicationStateChanged.connect(
                self._application_state
            )
            self._move(self._point)
            return True
        except Exception as error:
            self._cleanup()
            self.failed.emit(str(error))
            return False

    def sample_color(self, global_point):
        """Sample a logical desktop point from the active, unmodified snapshot."""
        for rect, image in self._frames:
            if rect.contains(global_point):
                x = min(
                    image.width() - 1,
                    int((global_point.x() - rect.left()) * image.width() / rect.width()),
                )
                y = min(
                    image.height() - 1,
                    int((global_point.y() - rect.top()) * image.height() / rect.height()),
                )
                color = image.pixelColor(x, y)
                color.setAlpha(255)
                return color
        return QtGui.QColor()

    def _move(self, point):
        self._point = QtCore.QPoint(point)
        color = self.sample_color(point)
        if color.isValid() and color != self._last_preview:
            self._last_preview = color
            self.colorPreviewed.emit(QtGui.QColor(color))
        for overlay in self._overlays:
            overlay.update()

    def _choose(self, point):
        if not self._active:
            return
        value = self.sample_color(point)
        if value.isValid():
            self._cleanup()
            self.colorSelected.emit(value)

    def cancel(self):
        if self._active:
            self._cleanup()
            self.canceled.emit()

    def _cleanup(self):
        was_active = self._active
        self._active = False
        if was_active:
            try:
                QtWidgets.QApplication.instance().applicationStateChanged.disconnect(
                    self._application_state
                )
            except (RuntimeError, TypeError):
                pass
        _dispose_overlays(self._overlays, self._cursor_owned)
        self._frames.clear()

    def _application_state(self, state):
        if state != QtCore.Qt.ApplicationState.ApplicationActive:
            self.cancel()

    def eventFilter(self, watched, event):
        if watched is self._owner and event.type() in (
            QtCore.QEvent.Type.Hide,
            QtCore.QEvent.Type.Close,
        ):
            self.cancel()
        return super().eventFilter(watched, event)


class EyeDropperButton(Button):
    """Native Button with an official Fluent eyedropper icon and a current color chip."""

    colorChanged = Signal(QtGui.QColor)
    colorPreviewed = Signal(QtGui.QColor)
    failed = Signal(str)

    def __init__(self, color="#0078d4", parent=None):
        super().__init__("", parent)
        self._color = _color(color, False)
        self.setFixedSize(68, 34)
        self.setAccessibleName("从屏幕取色")
        self.picker = ScreenColorPicker(self)
        self.clicked.connect(self.picker.start)
        self.picker.colorSelected.connect(self.set_color)
        self.picker.colorPreviewed.connect(self.colorPreviewed)
        self.picker.failed.connect(self.failed)
        self._describe()

    def color(self):
        return QtGui.QColor(self._color)

    def set_color(self, color):
        value = _color(color, False)
        if value != self._color:
            self._color = value
            self.update()
            self._describe()
            self.colorChanged.emit(self.color())

    setColor = set_color

    def _describe(self):
        self.setToolTip("从屏幕取色 · " + _hex(self._color))

    def _draw_content(self, painter, rect, color):
        _paint_color(
            painter, QtCore.QRectF(rect.left() + 6, rect.center().y() - 11, 22, 22), self._color
        )
        self._draw_tinted_icon(
            painter,
            QtCore.QRect(round(rect.right() - 22), round(rect.center().y() - 9), 18, 18),
            color,
            fluent_icon(FluentIcon.EYEDROPPER),
        )

    def hideEvent(self, event):
        self.picker.cancel()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.EnabledChange and not self.isEnabled():
            self.picker.cancel()
        super().changeEvent(event)
