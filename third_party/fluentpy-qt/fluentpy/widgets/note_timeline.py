"""Compact, read-only note overview, independent of music file formats."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Integral, Real

from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font


def _seconds(value: float, name: str, *, negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (result < 0 and not negative):
        raise ValueError(f"{name} must be finite" + ("" if negative else " and nonnegative"))
    return result


def _integer(value: int, name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return int(value)


@dataclass(frozen=True)
class NoteEvent:
    """A note in seconds, with a MIDI pitch and a zero-based track index."""

    start: float
    duration: float
    pitch: int
    track: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _seconds(self.start, "start"))
        object.__setattr__(self, "duration", _seconds(self.duration, "duration"))
        object.__setattr__(self, "pitch", _integer(self.pitch, "pitch", 127))
        object.__setattr__(self, "track", _integer(self.track, "track"))
        if not math.isfinite(self.start + self.duration):
            raise ValueError("note end must be finite")


class NoteTimeline(QtWidgets.QWidget):
    """Theme-aware note overview with a cached note layer and playback cursor.

    All times are seconds. This widget displays data; it does not read files,
    play sound, send input, or change playback when clicked.
    """

    positionChanged = Signal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        self._notes: tuple[NoteEvent, ...] = ()
        self._duration = 0.0
        self._position = 0.0
        self._pitch_range: tuple[int, int] | None = None
        self._auto_pitch_range = (48, 85)
        self._track_colors: tuple[QtGui.QColor, ...] | None = None
        self._empty_text = "暂无音符"
        self._background: QtGui.QPixmap | None = None
        self._background_key: tuple[int, int, float] | None = None
        self.setMinimumHeight(48)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self.setAccessibleName("音符时间轴")
        theme.subscribe(self, self._invalidate_background)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(480, 88)

    def notes(self) -> tuple[NoteEvent, ...]:
        return self._notes

    def duration(self) -> float:
        return self._duration

    def position(self) -> float:
        return self._position

    def set_notes(self, notes: Iterable[NoteEvent], *, duration: float | None = None) -> None:
        """Replace notes atomically and reset the cursor; preserve trailing silence.

        The visible duration is at least the last note's end. Copying the iterable
        prevents callers' later list edits from silently invalidating the cache.
        """
        values = tuple(notes)
        if any(not isinstance(note, NoteEvent) for note in values):
            raise TypeError("notes must contain NoteEvent instances")
        total = 0.0 if duration is None else _seconds(duration, "duration")
        total = max(total, max((note.start + note.duration for note in values), default=0.0))
        auto_range = (
            (min(note.pitch for note in values), max(note.pitch for note in values))
            if values
            else (48, 85)
        )
        self._notes = values
        self._duration = total
        self._auto_pitch_range = auto_range
        self._invalidate_background()
        self.set_position(0.0)

    def clear(self) -> None:
        """Clear notes, duration and position, keeping display preferences."""
        self.set_notes(())

    def set_position(self, seconds: float) -> None:
        position = min(self._duration, max(0.0, _seconds(seconds, "position", negative=True)))
        if position == self._position:
            return
        self._position = position
        self.update()
        self.positionChanged.emit(position)

    def set_pitch_range(self, minimum: int | None = None, maximum: int | None = None) -> None:
        """Set a fixed inclusive MIDI range; omit both limits to fit the notes."""
        if minimum is None and maximum is None:
            limits = None
        else:
            low = _integer(minimum, "minimum", 127)
            high = _integer(maximum, "maximum", 127)
            if low > high:
                raise ValueError("minimum must not exceed maximum")
            limits = (low, high)
        if limits != self._pitch_range:
            self._pitch_range = limits
            self._invalidate_background()

    def pitch_range(self) -> tuple[int, int]:
        return self._auto_pitch_range if self._pitch_range is None else self._pitch_range

    def set_track_colors(self, colors: Iterable[str | QtGui.QColor]) -> None:
        """Set a repeating track palette; copy colors to keep caller edits safe."""
        values = tuple(QtGui.QColor(color) for color in colors)
        if not values or any(not color.isValid() for color in values):
            raise ValueError("track colors must be a nonempty sequence of valid colors")
        self._track_colors = values
        self._invalidate_background()

    def set_empty_text(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("empty text must be a string")
        if text != self._empty_text:
            self._empty_text = text
            self._invalidate_background()

    def empty_text(self) -> str:
        return self._empty_text

    def _invalidate_background(self) -> None:
        self._background = None
        self._background_key = None
        self.update()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() in (QtCore.QEvent.Type.FontChange, QtCore.QEvent.Type.EnabledChange):
            self._invalidate_background()
        super().changeEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        self._invalidate_background()
        super().resizeEvent(event)

    def _make_background(self) -> QtGui.QPixmap:
        ratio = self.devicePixelRatioF()
        pixmap = QtGui.QPixmap(
            max(1, math.ceil(self.width() * ratio)), max(1, math.ceil(self.height() * ratio))
        )
        pixmap.setDevicePixelRatio(ratio)
        tokens = theme.tokens
        pixmap.fill(QtGui.QColor(tokens.surface))
        painter = QtGui.QPainter(pixmap)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setClipRect(self.rect())
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.border)))
            for row in range(1, 5):
                y = row * self.height() // 5
                painter.drawLine(0, y, self.width(), y)
            if not self._notes:
                painter.setFont(self.font())
                painter.setPen(QtGui.QColor(tokens.text_muted))
                painter.drawText(
                    self.rect().adjusted(8, 0, -8, 0),
                    QtCore.Qt.AlignmentFlag.AlignCenter,
                    self._empty_text,
                )
                return pixmap

            palette = self._track_colors or tuple(
                QtGui.QColor(color)
                for color in (
                    tokens.accent,
                    "#77bfa3",
                    "#d3a8e8",
                    "#e7bb76",
                )
            )
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            low, high = self.pitch_range()
            width, height = float(self.width()), float(self.height())
            note_height = min(4.0, height)
            vertical_span = max(0.0, height - 8.0)
            brushes: dict[int, QtGui.QColor] = {}
            for note in self._notes:
                if not low <= note.pitch <= high:
                    continue
                color_index = note.track % len(palette)
                if color_index not in brushes:
                    color = QtGui.QColor(palette[color_index])
                    color.setAlpha(round(color.alpha() * (185 / 255 if self.isEnabled() else 0.35)))
                    brushes[color_index] = color
                painter.setBrush(brushes[color_index])
                x = note.start / self._duration * width if self._duration else 0.0
                note_width = (
                    max(2.0, note.duration / self._duration * width) if self._duration else 2.0
                )
                # End-point impulses retain their minimum width inside the view.
                x = min(x, max(0.0, width - 2.0))
                note_width = min(note_width, width - x)
                y = (
                    (high - note.pitch) / (high - low) * vertical_span
                    if high != low
                    else max(0.0, (height - note_height) / 2)
                )
                painter.drawRoundedRect(QtCore.QRectF(x, y, note_width, note_height), 2, 2)
        finally:
            painter.end()
        return pixmap

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if self._background is None or self._background_key != key:
            self._background = self._make_background()
            self._background_key = key
        painter = QtGui.QPainter(self)
        try:
            painter.drawPixmap(0, 0, self._background)
            if self._notes and self._duration > 0:
                x = min(self.width() - 1, self._position / self._duration * self.width())
                painter.setPen(
                    QtGui.QPen(
                        QtGui.QColor(
                            theme.tokens.text if self.isEnabled() else theme.tokens.disabled
                        ),
                        1,
                    )
                )
                painter.drawLine(int(x), 0, int(x), self.height())
        finally:
            painter.end()
