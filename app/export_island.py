"""Keep exports running behind a compact, clickable desktop progress pill."""
from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from app import fluent_api as F
from PySide6.QtWidgets import QLabel, QWidget

from app.transitions import SurfaceWindow


class _Snapshot(QWidget):
    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self.pixmap = pixmap
        # Compute the blurred texture once, at native pixel ratio. Animation
        # frames only blend two cached images, even with eight flying windows.
        self.blurred = pixmap.scaled(max(1, pixmap.width()//28), max(1, pixmap.height()//28),
                                     Qt.IgnoreAspectRatio, Qt.SmoothTransformation).scaled(
                                     pixmap.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.blurred.setDevicePixelRatio(pixmap.devicePixelRatio())
        self.blur = 0.0
        self.opacity = 1.0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(self.opacity)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.setOpacity(self.opacity*self.blur)
        painter.drawPixmap(self.rect(), self.blurred)


class _Flight(SurfaceWindow):
    def __init__(self, pixmap, start, target, done, restoring=False, progress=None):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.image = _Snapshot(self, pixmap)
        self.image.blur = 1.0 if restoring else 0.0
        bounds = start.united(target)
        self.setGeometry(bounds)
        self.surfaceRect = start.translated(-bounds.topLeft())
        self.show()
        self.animate_surface(target.translated(-bounds.topLeft()), 520, done)
        def frame(_):
            t = self._surface_anim.easingCurve().valueForProgress(
                self._surface_anim.currentTime()/self._surface_anim.duration())
            amount = 1-t if restoring else t
            self.image.blur = min(1.0, amount*1.6)
            self.image.opacity = 1-max(0.0, (amount-.72)/.28)
            self.image.update()
            if progress is not None:progress(amount)
        self._surface_anim.valueChanged.connect(frame)
        frame(None)

    def _layout_surface(self):
        self.image.setGeometry(self.surfaceRect)


class ExportIsland(QObject):
    def __init__(self, parent, windows, fraction=None):
        super().__init__(parent)
        self.windows = windows
        self.fraction = fraction or (lambda: windows[0]._fraction)
        self.state = 'expanded'
        self.rects = []
        self.flights = []
        self.pill=F.CardWidget()
        self.pill.setWindowFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus)
        self.pill.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip('单击恢复导出窗口')
        self.pill.installEventFilter(self)
        self.pill.title=QLabel(self.pill);self.pill.title.setGeometry(16,5,188,22)
        self.pill.detail=QLabel(self.pill);self.pill.detail.setGeometry(16,28,266,18)
        self.pill.progress=F.ProgressBar(self.pill)
        self.pill.progress.setTextVisible(False);self.pill.progress.setGeometry(210,16,68,6)
        self.pill.stop=F.PushButton('■',self.pill)
        self.pill.stop.setGeometry(294,10,32,32);self.pill.stop.setToolTip('终止导出')
        self.pill.stop.clicked.connect(self.stop)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)

    def eventFilter(self,watched,event):
        if watched is self.pill and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            self.restore()
            return True
        return False

    def refresh(self):
        first = self.windows[0]
        self.pill.stop.setVisible(not all(w._done for w in self.windows))
        self.pill.stop.setEnabled(first.btn_stop.isEnabled())
        title=first._title if first._done else first._phase
        self.pill.title.setText(self.pill.title.fontMetrics().elidedText(title,Qt.ElideMiddle,188))
        fraction=self.fraction()
        self.pill.progress.setRange(0,0 if fraction is None and not first._done else 1000)
        if fraction is not None:self.pill.progress.setValue(round(fraction*1000))
        minutes,seconds=divmod(int(max(w._elapsed for w in self.windows)),60)
        percent=f'{fraction:.0%}' if fraction is not None else '处理中'
        count=f' · {len(self.windows)} 分块' if len(self.windows)>1 else ''
        self.pill.detail.setText(f'{percent} · {minutes:02d}:{seconds:02d}{count}')
        self.pill.update()

    def collapse(self):
        if self.state != 'expanded' or any(w._transitioning or not w.isVisible() for w in self.windows):
            return
        self.rects = [QRect(w.geometry()) for w in self.windows]
        screen = QGuiApplication.screenAt(self.rects[0].center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.pill.setGeometry(area.center().x()-170, area.top()+10, 340, 52)
        self.state = 'collapsing'
        self.timer.start()
        self._fly(False)

    def restore(self):
        if self.state != 'collapsed':
            return
        self.state = 'restoring'
        self.pill.hide()
        self._fly(True)

    def _fly(self, restoring):
        self._remaining = len(self.windows)
        self.refresh()
        self.pill.setWindowOpacity(1.0 if restoring else 0.0)
        self.pill.show()
        for index, (window, rect) in enumerate(zip(self.windows, self.rects)):
            snapshot = window.visual_surface().grab()
            window.hide()
            start, target = (self.pill.geometry(), rect) if restoring else (rect, self.pill.geometry())
            def blend(amount):
                self.pill.setWindowOpacity(max(0.0, min(1.0, (amount-.65)/.35)))
            flight = _Flight(snapshot, start, target, lambda: self._arrived(restoring),
                             restoring, blend if index==0 else None)
            self.flights.append(flight)

    def _arrived(self, restoring):
        self._remaining -= 1
        if self._remaining:
            return
        self._clear_flights()
        if restoring:
            self.state = 'expanded'
            self.timer.stop()
            self.pill.hide()
            for window in self.windows:
                window.show()
                window.raise_()
        else:
            self.state = 'collapsed'
            self.refresh()
            self.pill.setWindowOpacity(1.0)
            self.pill.show()
            self.pill.raise_()

    def stop(self):
        first = self.windows[0]
        if not first._done and first.btn_stop.isEnabled():
            first.btn_stop.click()
            self.refresh()

    def _clear_flights(self):
        for flight in self.flights:
            if flight._surface_anim is not None:
                flight._surface_anim.stop()
            flight.close()
            flight.deleteLater()
        self.flights.clear()

    def close(self):
        self.state = 'closed'
        self.timer.stop()
        self._clear_flights()
        self.pill.close()

