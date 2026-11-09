"""Animate child surfaces inside one fixed translucent native window."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRect, Qt
from PySide6.QtWidgets import QWidget


class SurfaceWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._surface_rect = QRect()
        self._surface_anim = None

    def _get_surface(self):
        return QRect(self._surface_rect)

    def _set_surface(self, rect):
        self._surface_rect = QRect(rect)
        self._layout_surface()

    surfaceRect = Property(QRect, _get_surface, _set_surface)

    def _layout_surface(self):
        raise NotImplementedError

    def animate_surface(self, target, duration, done=None,
                        easing=QEasingCurve.InOutCubic):
        if self._surface_anim is not None:
            self._surface_anim.stop()
            self._surface_anim.deleteLater()
        anim = QPropertyAnimation(self, b"surfaceRect", self)
        anim.setDuration(duration)
        anim.setStartValue(self.surfaceRect)
        anim.setEndValue(QRect(target))
        anim.setEasingCurve(easing)
        if done is not None:
            anim.finished.connect(done)
        self._surface_anim = anim
        anim.start()
