"""Calendar fields with owner-window flyouts; no native popup windows."""

from ..backends import calendar as policy
from ..icons import FluentIcon, fluent_icon
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..theme import theme
from ..theme.fonts import ui_font
from .button import Button, TextButton, TransparentIconButton
from .date_picker import _DateAction
from .time_picker import _TimeFlyout, _TimeWheel


def _date(value):
    if not isinstance(value, QtCore.QDate):
        raise TypeError("date must be a QDate")
    if not value.isValid() or not 1 <= value.year() <= 9999:
        raise ValueError("date must be valid, with year between 1 and 9999")
    return value.year(), value.month(), value.day()


def _datetime(value):
    if not isinstance(value, QtCore.QDateTime):
        raise TypeError("date time must be a QDateTime")
    if not value.isValid():
        raise ValueError("date time must be valid")
    value = value.toLocalTime()
    return (*_date(value.date()), value.time().hour(), value.time().minute(), value.time().second())


def _qdatetime(parts):
    return QtCore.QDateTime(QtCore.QDate(*parts[:3]), QtCore.QTime(*parts[3:]))


class _CalendarGrid(QtWidgets.QWidget):
    def __init__(self, calendar):
        super().__init__(calendar)
        self.calendar = calendar
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("日历日期网格")
        self._hover = -1
        self._pressed = -1
        self._wheel_remainder = 0
        self._previous = QtGui.QPixmap()
        self._progress = 1.0
        self._direction = 1
        self._range_state = (0.0, 0.0, 0.0)
        self._range_from = self._range_state
        self._range_to = self._range_state
        self._range_page = None
        self.range_motion = QtCore.QVariantAnimation(self)
        self.range_motion.setDuration(190)
        self.range_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.range_motion.valueChanged.connect(self._range_frame)
        self._hover_state = (0.0, 0.0, 0.0)
        self._hover_from = self._hover_to = self._hover_state
        self.hover_motion = QtCore.QVariantAnimation(self)
        self.hover_motion.setDuration(140)
        self.hover_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.hover_motion.valueChanged.connect(self._hover_frame)
        self._pulse_value = None
        self._pulse = 1.0
        self.selection_motion = QtCore.QVariantAnimation(self)
        self.selection_motion.setDuration(200)
        self.selection_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.selection_motion.valueChanged.connect(self._selection_frame)
        self.motion = QtCore.QVariantAnimation(self)
        self.motion.setDuration(180)
        self.motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self._frame)
        self.motion.finished.connect(self._finish)

    def _frame(self, value):
        self._progress = float(value)
        self.update()

    def _range_frame(self, value):
        self._range_state = tuple(
            a + (b - a) * float(value) for a, b in zip(self._range_from, self._range_to)
        )
        self.update()

    def _hover_frame(self, value):
        self._hover_state = tuple(
            a + (b - a) * float(value) for a, b in zip(self._hover_from, self._hover_to)
        )
        self.update()

    def _selection_frame(self, value):
        self._pulse = float(value)
        self.update()

    def pulse(self, value):
        self._pulse_value = value
        self.selection_motion.stop()
        self.selection_motion.setStartValue(0.0)
        self.selection_motion.setEndValue(1.0)
        self.selection_motion.start()

    def reset_visuals(self):
        for animation in (self.motion, self.range_motion, self.hover_motion, self.selection_motion):
            animation.stop()
        self._hover = self._pressed = -1
        self._hover_state = (0.0, 0.0, 0.0)
        self._range_page = None
        self._pulse_value = None
        self._finish()

    def sync_range(self, *, animate=True):
        cal = self.calendar
        if self._range_page != cal.month:
            self._hover = -1
            self.hover_motion.stop()
            self._hover_state = (0.0, 0.0, 0.0)
        if not cal.range_mode or not cal.start:
            target = (*self._range_state[:2], 0.0)
        else:
            start, end = cal.start, cal.end or cal.start
            if cal.end is None and 0 <= self._hover < len(cal.cells):
                cell = cal.cells[self._hover]
                if cell and cell[3]:
                    start, end = policy.normalize_range(start, cell[:3], *cal.rules)

            def position(value):
                visible = [(i, cell[:3]) for i, cell in enumerate(cal.cells) if cell]
                return float(
                    next(
                        (i for i, date in visible if date == value),
                        -1 if value < visible[0][1] else 42,
                    )
                )

            target = (position(start), position(end), 1.0)
        if self._range_page != cal.month or not animate:
            self.range_motion.stop()
            self._range_state = self._range_from = self._range_to = target
            self._range_page = cal.month
            return
        if target == self._range_to:
            return
        self.range_motion.stop()
        self._range_from, self._range_to = self._range_state, target
        if self._range_state[2] < 0.01:
            self._range_from = (target[0], target[0], 0.0)
        self.range_motion.setStartValue(0.0)
        self.range_motion.setEndValue(1.0)
        self.range_motion.start()

    def range_path(self):
        """One continuous row band with circular caps at the actual endpoints."""
        start, end, _ = self._range_state
        path = QtGui.QPainterPath()
        for row in range(6):
            first, last = row * 7, row * 7 + 6
            if start > last + 0.5 or end < first - 0.5:
                continue
            cell = self._cell(first)
            radius = min(36.0, cell.width() - 6, cell.height() - 5) / 2
            top = cell.center().y() - radius
            left_cap, right_cap = start >= first - 0.5, end <= last + 0.5
            left = (start - first + 0.5) * cell.width() if left_cap else 0.0
            right = (end - first + 0.5) * cell.width() if right_cap else float(self.width())
            segment = QtGui.QPainterPath()
            if left_cap and right_cap:
                segment.addRoundedRect(
                    QtCore.QRectF(left - radius, top, right - left + 2 * radius, 2 * radius),
                    radius,
                    radius,
                )
            else:
                segment.addRect(QtCore.QRectF(left, top, max(0.0, right - left), 2 * radius))
                if left_cap:
                    segment.addEllipse(QtCore.QRectF(left - radius, top, 2 * radius, 2 * radius))
                if right_cap:
                    segment.addEllipse(QtCore.QRectF(right - radius, top, 2 * radius, 2 * radius))
            # Union before filling: overlaps must not cancel under OddEvenFill.
            segment.setFillRule(QtCore.Qt.FillRule.WindingFill)
            path = path.united(segment)
        return path

    def _set_hover(self, index):
        if index == self._hover:
            return
        self._hover = index
        enabled = index >= 0
        if enabled and self.calendar.level == "days":
            cell = self.calendar.cells[index]
            enabled = bool(cell and cell[3])
        target = (*self._hover_state[:2], 0.0)
        if enabled:
            center = self._cell(index).center()
            target = (center.x(), center.y(), 1.0)
        self.hover_motion.stop()
        self._hover_from = self._hover_state
        if self._hover_state[2] < 0.01:
            self._hover_from = (*target[:2], 0.0)
        self._hover_to = target
        self.hover_motion.setStartValue(0.0)
        self.hover_motion.setEndValue(1.0)
        self.hover_motion.start()
        self.sync_range()
        self.update()

    def _finish(self):
        self._previous = QtGui.QPixmap()
        self.update()

    def snapshot(self, direction):
        self.motion.stop()
        self._previous = self.grab() if self.isVisible() else QtGui.QPixmap()
        self._direction = direction

    def animate(self):
        self._set_hover(-1)
        self._pressed = -1
        if not self._previous.isNull():
            self.motion.setStartValue(0.0)
            self.motion.setEndValue(1.0)
            self.motion.start()
        self.update()

    def _cell(self, index):
        if self.calendar.level == "days":
            row, col = divmod(index, 7)
            h = max(1, (self.height() - 32) / 6)
            return QtCore.QRectF(col * self.width() / 7, 32 + row * h, self.width() / 7, h)
        row, col = divmod(index, 4)
        return QtCore.QRectF(
            col * self.width() / 4, row * self.height() / 3, self.width() / 4, self.height() / 3
        )

    def _index_at(self, pos):
        count = 42 if self.calendar.level == "days" else 12
        return next((i for i in range(count) if self._cell(i).contains(pos)), -1)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if not self._previous.isNull() and self._progress < 1:
            p.setOpacity(1 - self._progress)
            p.drawPixmap(round(-self._direction * self._progress * 22), 0, self._previous)
            p.setOpacity(self._progress)
            p.translate(self._direction * (1 - self._progress) * 22, 0)
        self._draw(p)

    def _draw(self, p):
        cal, tokens = self.calendar, theme.tokens
        p.setFont(ui_font(tokens.font_size, self.font()))
        accent = QtGui.QColor(tokens.accent)
        today = _date(QtCore.QDate.currentDate())
        if cal.level != "days":
            for i, (value, label, enabled) in enumerate(cal.zoom_cells()):
                rect = self._cell(i).adjusted(4, 10, -4, -10)
                active = value == (cal.focused[1] if cal.level == "months" else cal.focused[0])
                if active or i == self._hover:
                    fill = QtGui.QColor(tokens.accent if active else tokens.surface_hover)
                    p.setBrush(fill)
                    p.setPen(QtCore.Qt.PenStyle.NoPen)
                    p.drawRoundedRect(rect, 5, 5)
                p.setPen(
                    QtGui.QColor("white")
                    if active and accent.lightness() < 170
                    else QtGui.QColor(tokens.text if enabled else tokens.disabled)
                )
                p.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)
            return
        names = (
            ("一", "二", "三", "四", "五", "六", "日")
            if cal.locale.language() == QtCore.QLocale.Language.Chinese
            else tuple(
                cal.locale.standaloneDayName(i, QtCore.QLocale.FormatType.ShortFormat)
                for i in range(1, 8)
            )
        )
        p.setPen(QtGui.QColor(tokens.text))
        for col in range(7):
            p.drawText(
                QtCore.QRectF(col * self.width() / 7, 0, self.width() / 7, 32),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                names[(col + cal.first_weekday) % 7],
            )
        start, end = cal.start, cal.end
        if cal.range_mode and self._range_state[2] > 0.001:
            fill = QtGui.QColor(tokens.text)
            fill.setAlpha(round(15 * self._range_state[2]))
            p.fillPath(self.range_path(), fill)
        hx, hy, opacity = self._hover_state
        if opacity > 0.001:
            cell = self._cell(0)
            diameter = min(36.0, cell.width() - 6, cell.height() - 5)
            hover = QtCore.QRectF(hx - diameter / 2, hy - diameter / 2, diameter, diameter)
            fill = QtGui.QColor(tokens.accent)
            fill.setAlpha(round(18 * opacity))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawEllipse(hover)
        for i, cell in enumerate(cal.cells):
            if cell is None:
                continue
            value, enabled = cell[:3], cell[3]
            rect = self._cell(i)
            diameter = min(36.0, rect.width() - 6, rect.height() - 5)
            circle = QtCore.QRectF(0, 0, diameter, diameter)
            circle.moveCenter(rect.center())
            endpoint = value in (start, end) if cal.range_mode else value == cal.selected
            is_today = value == today
            if is_today:
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(accent)
                p.drawEllipse(circle)
            if endpoint:
                ring_color = QtGui.QColor(accent)
                ring_width = 1.4
                if value == self._pulse_value:
                    ring_color.setAlphaF(0.45 + 0.55 * self._pulse)
                    ring_width = 0.9 + 0.5 * self._pulse
                p.setPen(QtGui.QPen(ring_color, ring_width))
                p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                p.drawEllipse(circle)
            color = tokens.text if value[1] == cal.month[1] else tokens.text_muted
            if not enabled:
                color = tokens.disabled
            if is_today and enabled:
                color = "#ffffff" if accent.lightness() < 170 else "#101010"
            p.setPen(QtGui.QColor(color))
            font = ui_font(tokens.font_size, self.font())
            font.setStrikeOut(not enabled and value[1] == cal.month[1])
            p.setFont(font)
            p.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, str(value[2]))

    def mouseMoveEvent(self, event):
        self._set_hover(self._index_at(event.position()))

    def leaveEvent(self, event):
        self._set_hover(-1)
        self._pressed = -1

    def hideEvent(self, event):
        self.reset_visuals()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            self._pressed = self._index_at(event.position())
            event.accept()

    def mouseReleaseEvent(self, event):
        index = self._index_at(event.position())
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and index >= 0
            and index == self._pressed
        ):
            self.calendar.activate(index)
        self._pressed = -1
        event.accept()

    def wheelEvent(self, event):
        self._wheel_remainder += event.angleDelta().y() or event.pixelDelta().y() * 3
        if abs(self._wheel_remainder) >= 120:
            count = int(self._wheel_remainder / 120)
            self._wheel_remainder -= count * 120
            self.calendar.navigate(-count)
        event.accept()

    def keyPressEvent(self, event):
        cal, key = self.calendar, event.key()
        keys = QtCore.Qt.Key
        if cal.level != "days":
            if key in (keys.Key_Return, keys.Key_Enter, keys.Key_Space):
                target = cal.focused[1] if cal.level == "months" else cal.focused[0]
                index = next((i for i, cell in enumerate(cal.zoom_cells()) if cell[0] == target), 0)
                cal.activate(index)
            elif key in (keys.Key_Left, keys.Key_Right, keys.Key_Up, keys.Key_Down):
                amount = {keys.Key_Left: -1, keys.Key_Right: 1, keys.Key_Up: -4, keys.Key_Down: 4}[
                    key
                ]
                value = policy.shift_date(
                    cal.focused, months=amount * (12 if cal.level == "years" else 1)
                )
                value = max(cal.rules[0], min(cal.rules[1], value))
                cal.focused = value
                if (
                    cal.level == "months"
                    and value[0] != cal.month[0]
                    or cal.level == "years"
                    and not cal.year_start <= value[0] < cal.year_start + 12
                ):
                    cal.set_page(*value[:2])
                cal.refresh()
            elif key in (keys.Key_PageUp, keys.Key_PageDown):
                cal.navigate(-1 if key == keys.Key_PageUp else 1)
            else:
                super().keyPressEvent(event)
                return
        elif key in (keys.Key_Return, keys.Key_Enter, keys.Key_Space):
            cal.choose(cal.focused)
        elif key in (keys.Key_Left, keys.Key_Right, keys.Key_Up, keys.Key_Down):
            cal.move_focus(
                days={keys.Key_Left: -1, keys.Key_Right: 1, keys.Key_Up: -7, keys.Key_Down: 7}[key]
            )
        elif key in (keys.Key_PageUp, keys.Key_PageDown):
            cal.move_focus(
                months=(-1 if key == keys.Key_PageUp else 1)
                * (12 if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier else 1)
            )
        elif key == keys.Key_Home:
            value = _date(QtCore.QDate.currentDate())
            if not event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                qdate = QtCore.QDate(*cal.focused)
                value = policy.shift_date(
                    cal.focused, days=-((qdate.dayOfWeek() - 1 - cal.first_weekday) % 7)
                )
            cal.move_focus(value=value)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class _CalendarView(QtWidgets.QWidget):
    dateSelected = Signal(QtCore.QDate)
    rangeSelected = Signal(QtCore.QDate, QtCore.QDate)

    def __init__(self, parent=None, *, range_mode=False):
        super().__init__(parent)
        self.range_mode = range_mode
        self.rules = policy.validate_rules()
        self.locale = QtCore.QLocale("zh_CN")
        self.first_weekday = 0
        self.selected = self.start = self.end = None
        self.focused = _date(QtCore.QDate.currentDate())
        self.month = self.focused[:2]
        self.level = "days"
        self.year_start = max(1, min(9988, self.month[0] // 10 * 10))
        self.cells = ()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 6)
        self.heading = TextButton("", self)
        self.heading.setAccessibleName("切换月份和年份视图")
        self.heading.setToolTip("点击选择月份，再次点击选择年份")
        self.heading.clicked.connect(self.zoom_out)
        self.previous_button = TransparentIconButton(FluentIcon.CHEVRON_UP, self)
        self.next_button = TransparentIconButton(FluentIcon.CHEVRON_DOWN, self)
        for button, text in ((self.previous_button, "上一页"), (self.next_button, "下一页")):
            button.setAccessibleName(text)
            button.setToolTip(text)
            button.setFixedSize(32, 32)
        self.previous_button.clicked.connect(lambda: self.navigate(-1))
        self.next_button.clicked.connect(lambda: self.navigate(1))
        header.addWidget(self.heading)
        header.addStretch()
        header.addWidget(self.previous_button)
        header.addWidget(self.next_button)
        layout.addLayout(header)
        self.grid = _CalendarGrid(self)
        layout.addWidget(self.grid, 1)
        self.setFocusProxy(self.grid)
        self._animations = [self.grid.motion]
        self._drag_origin = None
        theme.subscribe(self, self.refresh)
        self.refresh()

    def refresh(self):
        self.cells = policy.month_cells(*self.month, *self.rules, self.first_weekday)
        y, m = self.month
        if self.level == "days":
            title = f"{self.locale.monthName(m)} {y}"
            self.previous_button.setEnabled((y, m) > self.rules[0][:2])
            self.next_button.setEnabled((y, m) < self.rules[1][:2])
        elif self.level == "months":
            title = str(y)
            self.previous_button.setEnabled(y > self.rules[0][0])
            self.next_button.setEnabled(y < self.rules[1][0])
        else:
            self.year_start = max(1, min(9988, y // 10 * 10))
            title = f"{self.year_start} – {self.year_start + 11}"
            self.previous_button.setEnabled(self.year_start > self.rules[0][0])
            self.next_button.setEnabled(self.year_start + 11 < self.rules[1][0])
        self.heading.setText(title)
        self.grid.setFont(ui_font(theme.tokens.font_size, self.font()))
        self.grid.setAccessibleDescription(
            f"{title}。当前焦点 {self.focused[0]}-{self.focused[1]:02d}-{self.focused[2]:02d}。方向键移动，翻页键切换月份，Enter选择。"
        )
        self.grid.sync_range()
        self.grid.update()

    def zoom_cells(self):
        if self.level == "months":
            y = self.month[0]
            return tuple(
                (
                    m,
                    self.locale.monthName(m, QtCore.QLocale.FormatType.ShortFormat),
                    self.rules[0][:2] <= (y, m) <= self.rules[1][:2],
                )
                for m in range(1, 13)
            )
        return tuple(
            (y, str(y), self.rules[0][0] <= y <= self.rules[1][0])
            for y in range(self.year_start, self.year_start + 12)
        )

    def set_page(self, year, month, *, animate=True):
        target = max(self.rules[0][:2], min(self.rules[1][:2], (year, month)))
        if target == self.month:
            self.refresh()
            return
        if animate:
            self.grid.snapshot(1 if target > self.month else -1)
        self.month = target
        self.refresh()
        if animate:
            self.grid.animate()

    def reset(self, picker, selected=None, end=None):
        self.rules, self.locale, self.first_weekday = (
            picker._rules,
            QtCore.QLocale(picker._locale),
            picker._first_weekday,
        )
        self.selected = self.start = selected
        self.end = end
        self.focused = selected or max(
            self.rules[0], min(self.rules[1], _date(QtCore.QDate.currentDate()))
        )
        self.level = "days"
        self.month = self.focused[:2]
        self.grid.reset_visuals()
        self.grid._wheel_remainder = 0
        self.refresh()

    def zoom_out(self):
        self.grid.snapshot(1)
        self.level = "months" if self.level == "days" else "years"
        self.refresh()
        self.grid.animate()

    def navigate(self, count):
        if not count:
            return
        factor = 1 if self.level == "days" else 12 if self.level == "months" else 120
        value = policy.shift_date(
            (*self.month, 1), months=max(-120000, min(120000, count * factor))
        )
        self.set_page(*value[:2])

    def move_focus(self, *, days=0, months=0, value=None):
        value = value or policy.shift_date(self.focused, days, months)
        self.focused = max(self.rules[0], min(self.rules[1], value))
        self.set_page(*self.focused[:2])

    def activate(self, index):
        if self.level == "days":
            cell = self.cells[index]
            if cell and cell[3]:
                self.choose(cell[:3])
            return
        value, _, enabled = self.zoom_cells()[index]
        if not enabled:
            return
        self.grid.snapshot(-1)
        if self.level == "years":
            self.level = "months"
            self.month = (value, self.month[1])
        else:
            self.level = "days"
            self.month = (self.month[0], value)
        self.month = max(self.rules[0][:2], min(self.rules[1][:2], self.month))
        self.focused = policy.shift_date(
            self.focused,
            months=(self.month[0] - self.focused[0]) * 12 + self.month[1] - self.focused[1],
        )
        self.refresh()
        self.grid.animate()

    def choose(self, value):
        if not policy.is_selectable(value, *self.rules):
            return
        self.focused = value
        self.grid.pulse(value)
        if self.range_mode:
            if self.start is None or self.end is not None:
                self.start, self.end = value, None
            else:
                self.start, self.end = policy.normalize_range(self.start, value, *self.rules)
                self.grid.sync_range()
                self.rangeSelected.emit(QtCore.QDate(*self.start), QtCore.QDate(*self.end))
        else:
            self.selected = value
            self.dateSelected.emit(QtCore.QDate(*value))
        self.set_page(*value[:2])


class _SecondsWheel(_TimeWheel):
    valueChanged = Signal()

    def _column_count(self):
        return 3

    def _format_value(self, column, value):
        return f"{value:02d}"

    def set_value(self, value, use_12_hour=False, column=0):
        self.value = policy.step_time(*value, 0, 0)
        for animation in self._animations:
            animation.stop()
        self._offsets, self._wheel_remainders = [0.0, 0.0, 0.0], [0, 0, 0]
        self._wheel_mode = self._drag_origin = None
        self._drag_pixels = 0.0
        self.column = max(0, min(2, column))
        self._refresh_values()

    def _refresh_values(self):
        self._values = tuple(
            policy.time_values(*self.value, col, self.RADIUS + 1) for col in range(3)
        )
        self.setAccessibleName("时间滚轮：小时、分钟、秒")
        self.setAccessibleDescription(
            ":".join(f"{v:02d}" for v in self.value) + "。左右切换列，上下选择，Enter确认。"
        )
        self.update()

    def step(self, column, steps, *, animate=True):
        previous = self.value
        self.value = policy.step_time(*self.value, column, steps)
        self.column = column
        self._refresh_values()
        if animate and self.value != previous:
            motion = self._animations[column]
            motion.stop()
            offset = self._offsets[column] + (self.ROW_HEIGHT if steps > 0 else -self.ROW_HEIGHT)
            motion.setStartValue(float(max(-88, min(88, offset))))
            motion.setEndValue(0.0)
            motion.start()
        if self.value != previous:
            self.valueChanged.emit()


class _CalendarSurface(QtWidgets.QWidget):
    def __init__(self, parent, footer=False):
        super().__init__(parent)
        self.footer = footer

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(10.5, 8.5, -10.5, -12.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.save()
        p.translate(0, 2)
        for spread in range(10, 0, -1):
            p.setPen(
                QtGui.QPen(QtGui.QColor(0, 0, 0, 1 if theme.mode.value == "light" else 2), spread)
            )
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.restore()
        p.setBrush(QtGui.QColor(theme.tokens.surface))
        p.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.border), 1))
        p.drawPath(path)
        if self.footer:
            p.drawLine(
                QtCore.QPointF(rect.left(), self.height() - 60),
                QtCore.QPointF(rect.right(), self.height() - 60),
            )


class _CalendarFlyout(_TimeFlyout):
    """Reuse the owner-window animation/lifetime manager from TimePicker."""

    def __init__(self, anchor, *, range_mode=False, date_time=False):
        super().__init__(anchor)
        old = self.surface
        self.date_time = date_time
        self.surface = _CalendarSurface(self, footer=date_time)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self.surface)
        self.surface.setGraphicsEffect(self._opacity)
        self._layout = QtWidgets.QVBoxLayout(self.surface)
        self._layout.setContentsMargins(20, 18, 20, 14)
        self._layout.setSpacing(0)
        self.body = QtWidgets.QWidget(self.surface)
        self._body_layout = QtWidgets.QBoxLayout(
            QtWidgets.QBoxLayout.Direction.LeftToRight, self.body
        )
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(20)
        self.calendar = _CalendarView(self.body, range_mode=range_mode)
        self.wheel = self.calendar
        self._body_layout.addWidget(self.calendar, 1)
        self._layout.addWidget(self.body, 1)
        self.seconds = None
        self.confirm_button = self.cancel_button = None
        if date_time:
            self.seconds = _SecondsWheel(self.body)
            self.seconds.set_value((0, 0, 0))
            self._body_layout.addWidget(self.seconds, 1)
            footer = QtWidgets.QHBoxLayout()
            footer.setSpacing(0)
            self.confirm_button, self.cancel_button = (
                _DateAction(True, self.surface),
                _DateAction(False, self.surface),
            )
            for button, label in (
                (self.confirm_button, "确认日期时间"),
                (self.cancel_button, "取消日期时间选择"),
            ):
                button.setAccessibleName(label)
                button.setToolTip(label)
            footer.addWidget(self.confirm_button)
            footer.addWidget(self.cancel_button)
            self._layout.addLayout(footer)
            self.confirm_button.clicked.connect(self._accept)
            self.cancel_button.clicked.connect(self.dismiss)
            self.seconds.acceptRequested.connect(self._accept)
            self.seconds.cancelRequested.connect(self.dismiss)
            self.calendar.dateSelected.connect(self._adjust_datetime)
            self.seconds.valueChanged.connect(self._adjust_datetime)
        old.hide()
        old.deleteLater()
        self.setObjectName("fluentCalendarFlyout")
        self.setAccessibleName(
            "日期时间选择器" if date_time else "日期区间选择器" if range_mode else "日历日期选择器"
        )

    def _refresh_theme(self):
        if hasattr(self, "calendar"):
            self.calendar.refresh()
            if self.seconds:
                self.seconds.update()
        self.surface.update()
        if self.confirm_button:
            self.confirm_button.update()
            self.cancel_button.update()

    def _adjust_datetime(self, *_):
        value = (*self.calendar.selected, *self.seconds.value)
        result = policy.clamp_datetime(value, self._anchor._minimum_dt, self._anchor._maximum_dt)
        if result[:3] != self.calendar.selected:
            self.calendar.selected = self.calendar.focused = result[:3]
            self.calendar.set_page(*result[:2])
        if result[3:] != self.seconds.value:
            self.seconds.set_value(result[3:], column=self.seconds.column)
        self.confirm_button.setEnabled(policy.is_selectable(result[:3], *self.calendar.rules))

    def dismiss(self, _checked=False, *, immediate=False):
        if self.seconds:
            for animation in self.seconds._animations:
                animation.stop()
            self.seconds._drag_origin = None
        super().dismiss(_checked, immediate=immediate)

    def _place(self):
        if self._placing or not self._opened:
            return
        self._placing = True
        try:
            owner = self.parentWidget()
            self.setGeometry(owner.rect())
            anchor = QtCore.QRect(self._anchor.mapTo(owner, QtCore.QPoint()), self._anchor.size())
            clipped = anchor
            node = self._anchor.parentWidget()
            while node is not None and node is not owner:
                clipped = clipped.intersected(
                    QtCore.QRect(node.mapTo(owner, QtCore.QPoint()), node.size())
                )
                node = node.parentWidget()
            if (
                clipped.isEmpty()
                or owner.width() < 280
                or owner.height() < (350 if self.date_time else 250)
            ):
                self.dismiss(immediate=True)
                return
            narrow = self.date_time and owner.width() < 600
            self._body_layout.setDirection(
                QtWidgets.QBoxLayout.Direction.TopToBottom
                if narrow
                else QtWidgets.QBoxLayout.Direction.LeftToRight
            )
            width = min(680 if self.date_time and not narrow else 360, owner.width() - 8)
            height = min(650 if narrow else 470 if self.date_time else 410, owner.height() - 8)
            footer = 48 if self.date_time else 0
            self.calendar.setMinimumSize(0, 0)
            if self.seconds:
                available = (height - 32 - footer - 20) // 2 if narrow else height - 32 - footer
                rows = max(1, min(9, available // 44))
                rows -= (rows + 1) % 2
                radius = (rows - 1) // 2
                self.seconds.RADIUS = radius
                self.seconds.setFixedHeight(rows * 44)
                self.seconds._refresh_values()
            self.surface.resize(width, height)
            self.surface.layout().activate()
            self.body.layout().activate()
            x = max(4, min(anchor.left() - 10, owner.width() - width - 4))
            below = anchor.bottom() + 4
            above = anchor.top() - height - 4
            y = (
                below
                if below + height <= owner.height() - 4
                else above
                if above >= 4
                else max(4, min(below, owner.height() - height - 4))
            )
            self._rest = QtCore.QPoint(x, y)
            self._set_progress(self._progress)
        finally:
            self._placing = False

    def eventFilter(self, watched, event):
        kind = event.type()
        if (
            self._opened
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self.window()
        ):
            if (
                kind == QtCore.QEvent.Type.ShortcutOverride
                and event.key() == QtCore.Qt.Key.Key_Home
            ):
                event.accept()
                return True
            if kind == QtCore.QEvent.Type.KeyPress and event.key() in (
                QtCore.Qt.Key.Key_Tab,
                QtCore.Qt.Key.Key_Backtab,
            ):
                if self._closing:
                    return True
                widgets = [
                    self.calendar.grid,
                    self.calendar.heading,
                    self.calendar.previous_button,
                    self.calendar.next_button,
                ]
                if self.seconds:
                    widgets += [self.seconds, self.confirm_button, self.cancel_button]
                widgets = [
                    widget for widget in widgets if widget.isEnabled() and widget.isVisible()
                ]
                focus = QtWidgets.QApplication.focusWidget()
                index = widgets.index(focus) if focus in widgets else 0
                backwards = event.key() == QtCore.Qt.Key.Key_Backtab or bool(
                    event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
                )
                widgets[(index + (-1 if backwards else 1)) % len(widgets)].setFocus(
                    QtCore.Qt.FocusReason.TabFocusReason
                )
                return True
        return super().eventFilter(watched, event)


class _CalendarField(Button):
    def __init__(self, parent=None):
        policy.backend_name()
        super().__init__("", parent)
        self._rules = policy.validate_rules()
        self._locale = QtCore.QLocale("zh_CN")
        self._first_weekday = 0
        self._popup = None
        self._placeholder = "选择日期"
        self.setIcon(fluent_icon(FluentIcon.CALENDAR_LTR))
        self.setMinimumHeight(36)
        self.clicked.connect(self.show_popup)

    def sizeHint(self):
        return QtCore.QSize(max(156, self.fontMetrics().horizontalAdvance(self.text()) + 56), 36)

    def minimumSizeHint(self):
        return QtCore.QSize(136, 34)

    def _draw_content(self, painter, rect, color):
        painter.setPen(color)
        text_rect = rect.adjusted(12, 0, -38, 0)
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
            self.fontMetrics().elidedText(
                self.text(), QtCore.Qt.TextElideMode.ElideRight, int(text_rect.width())
            ),
        )
        icon_rect = QtCore.QRect(int(rect.right() - 28), int(rect.center().y() - 8), 16, 16)
        self._draw_tinted_icon(painter, icon_rect, color)

    def acceleration_backend(self) -> str:
        return policy.backend_name()

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder = str(text)
        self._update_text()

    def set_locale(self, locale: QtCore.QLocale | str) -> None:
        """Set calendar headings and weekday labels without changing the value."""
        self._locale = QtCore.QLocale(locale)
        self._discard_draft()

    def set_first_weekday(self, weekday: int) -> None:
        """Use 0 for Monday through 6 for Sunday."""
        policy.month_cells(2024, 1, first_weekday=weekday)
        self._first_weekday = weekday
        self._discard_draft()

    def set_date_bounds(self, minimum: QtCore.QDate, maximum: QtCore.QDate) -> None:
        """Set inclusive bounds. Invalid existing selections are cleared."""
        self._set_rules(_date(minimum), _date(maximum), *self._rules[2:])

    def set_disabled_weekdays(self, weekdays) -> None:
        """Disable endpoints on weekdays 0 (Monday) through 6 (Sunday)."""
        self._set_rules(*self._rules[:2], weekdays, self._rules[3])

    def set_disabled_dates(self, dates) -> None:
        self._set_rules(*self._rules[:3], tuple(_date(value) for value in dates))

    def _set_rules(self, *rules):
        result = policy.validate_rules(*rules)
        self._rules = result
        self._discard_draft()
        self._check_selection()

    def _discard_draft(self):
        if self._popup is not None:
            self._popup.dismiss(immediate=True)

    def hideEvent(self, event):
        self._discard_draft()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.EnabledChange and not self.isEnabled():
            self._discard_draft()
        super().changeEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_F4):
            self.show_popup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _prepare_popup(self, *, range_mode=False, date_time=False):
        if not self.isVisible() or not self.isEnabled():
            return False
        if self._popup is not None:
            try:
                self._popup.parentWidget()
            except RuntimeError:
                self._popup = None
        if self._popup is None:
            self._popup = _CalendarFlyout(self, range_mode=range_mode, date_time=date_time)
            if date_time:
                self._popup.accepted.connect(self._accept_datetime)
            elif range_mode:
                self._popup.calendar.rangeSelected.connect(self._accept_range)
            else:
                self._popup.calendar.dateSelected.connect(self._accept_date)
        elif self._popup._opened:
            self._popup.dismiss(immediate=True)
        return True


class CalendarPicker(_CalendarField):
    """Single-date calendar field. Clicking an enabled day commits the QDate."""

    dateChanged = Signal(QtCore.QDate)
    dateAccepted = Signal(QtCore.QDate)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._date = QtCore.QDate()
        self.setAccessibleName("日历日期")
        self._update_text()

    def date(self) -> QtCore.QDate:
        return QtCore.QDate(self._date)

    def set_date(self, value: QtCore.QDate) -> None:
        if not isinstance(value, QtCore.QDate):
            raise TypeError("date must be a QDate")
        if not value.isValid():
            self.clear()
            return
        if not policy.is_selectable(_date(value), *self._rules):
            raise ValueError("date must be selectable")
        self._discard_draft()
        if value != self._date:
            self._date = QtCore.QDate(value)
            self._update_text()
            self.dateChanged.emit(self.date())

    def setDate(self, value: QtCore.QDate) -> None:
        self.set_date(value)

    def clear(self) -> None:
        self._discard_draft()
        if self._date.isValid():
            self._date = QtCore.QDate()
            self._update_text()
            self.dateChanged.emit(self.date())

    def _check_selection(self):
        if self._date.isValid() and not policy.is_selectable(_date(self._date), *self._rules):
            self.clear()

    def _update_text(self):
        self.setText(
            self._date.toString("yyyy-MM-dd") if self._date.isValid() else self._placeholder
        )
        self.setAccessibleDescription(self.text())
        self.updateGeometry()

    def show_popup(self) -> None:
        if not self._prepare_popup():
            return
        self._popup.calendar.reset(self, _date(self._date) if self._date.isValid() else None)
        self._popup.open()

    def _accept_date(self, value):
        self._popup.dismiss()
        # Commit without cutting short the closing animation.
        if value != self._date:
            self._date = QtCore.QDate(value)
            self._update_text()
            self.dateChanged.emit(self.date())
        self.dateAccepted.emit(self.date())


class DateRangePicker(_CalendarField):
    """Two-click inclusive date interval; disabled dates cannot be endpoints."""

    rangeChanged = Signal(QtCore.QDate, QtCore.QDate)
    rangeAccepted = Signal(QtCore.QDate, QtCore.QDate)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._start = self._end = QtCore.QDate()
        self._placeholder = "选择日期区间"
        self.setAccessibleName("日期区间")
        self._update_text()

    def start_date(self) -> QtCore.QDate:
        return QtCore.QDate(self._start)

    def end_date(self) -> QtCore.QDate:
        return QtCore.QDate(self._end)

    def set_range(self, start: QtCore.QDate, end: QtCore.QDate) -> None:
        """Normalize reversed endpoints; two invalid QDates clear the range."""
        if not isinstance(start, QtCore.QDate) or not isinstance(end, QtCore.QDate):
            raise TypeError("endpoints must be QDates")
        if not start.isValid() and not end.isValid():
            self.clear()
            return
        result = policy.normalize_range(_date(start), _date(end), *self._rules)
        self._discard_draft()
        self._commit(*result)

    def _commit(self, start, end):
        start, end = QtCore.QDate(*start), QtCore.QDate(*end)
        if (start, end) != (self._start, self._end):
            self._start, self._end = start, end
            self._update_text()
            self.rangeChanged.emit(self.start_date(), self.end_date())

    def clear(self) -> None:
        self._discard_draft()
        if self._start.isValid():
            self._start, self._end = QtCore.QDate(), QtCore.QDate()
            self._update_text()
            self.rangeChanged.emit(self.start_date(), self.end_date())

    def _check_selection(self):
        if self._start.isValid() and not all(
            policy.is_selectable(_date(value), *self._rules) for value in (self._start, self._end)
        ):
            self.clear()

    def _update_text(self):
        self.setText(
            f"{self._start.toString('yyyy-MM-dd')} – {self._end.toString('yyyy-MM-dd')}"
            if self._start.isValid()
            else self._placeholder
        )
        self.setAccessibleDescription(self.text())
        self.updateGeometry()

    def show_popup(self) -> None:
        if not self._prepare_popup(range_mode=True):
            return
        self._popup.calendar.reset(
            self,
            _date(self._start) if self._start.isValid() else None,
            _date(self._end) if self._end.isValid() else None,
        )
        self._popup.open()

    def _accept_range(self, start, end):
        self._popup.dismiss()
        self._commit(_date(start), _date(end))
        self.rangeAccepted.emit(self.start_date(), self.end_date())


class DateTimePicker(_CalendarField):
    """Local date/time calendar with independent hour/minute/second wheels."""

    dateTimeChanged = Signal(QtCore.QDateTime)
    dateTimeAccepted = Signal(QtCore.QDateTime)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._value = QtCore.QDateTime()
        self._minimum_dt, self._maximum_dt = (1, 1, 1, 0, 0, 0), (9999, 12, 31, 23, 59, 59)
        self._placeholder = "选择日期与时间"
        self.setAccessibleName("日期时间")
        self._update_text()

    def date_time(self) -> QtCore.QDateTime:
        return QtCore.QDateTime(self._value)

    def dateTime(self) -> QtCore.QDateTime:
        return self.date_time()

    def set_date_time(self, value: QtCore.QDateTime) -> None:
        """Convert to local time, drop milliseconds, and clamp to inclusive bounds."""
        if not isinstance(value, QtCore.QDateTime):
            raise TypeError("date time must be a QDateTime")
        if not value.isValid():
            self.clear()
            return
        result = policy.clamp_datetime(_datetime(value), self._minimum_dt, self._maximum_dt)
        if not policy.is_selectable(result[:3], *self._rules):
            raise ValueError("date must be selectable")
        self._discard_draft()
        self._commit(result)

    def setDateTime(self, value: QtCore.QDateTime) -> None:
        self.set_date_time(value)

    def set_date_time_bounds(self, minimum: QtCore.QDateTime, maximum: QtCore.QDateTime) -> None:
        low, high = _datetime(minimum), _datetime(maximum)
        policy.clamp_datetime(low, low, high)
        rules = policy.validate_rules(low[:3], high[:3], *self._rules[2:])
        current = (
            policy.clamp_datetime(_datetime(self._value), low, high)
            if self._value.isValid()
            else None
        )
        self._minimum_dt, self._maximum_dt = low, high
        self._rules = rules
        self._discard_draft()
        if current:
            if policy.is_selectable(current[:3], *rules):
                self._commit(current)
            else:
                self.clear()

    def set_date_bounds(self, minimum: QtCore.QDate, maximum: QtCore.QDate) -> None:
        self.set_date_time_bounds(
            QtCore.QDateTime(minimum, QtCore.QTime(0, 0)),
            QtCore.QDateTime(maximum, QtCore.QTime(23, 59, 59)),
        )

    def _commit(self, parts):
        value = _qdatetime(parts)
        if not value.isValid():
            raise ValueError("date time does not exist in the local time zone")
        if value != self._value:
            self._value = value
            self._update_text()
            self.dateTimeChanged.emit(self.date_time())

    def clear(self) -> None:
        self._discard_draft()
        if self._value.isValid():
            self._value = QtCore.QDateTime()
            self._update_text()
            self.dateTimeChanged.emit(self.date_time())

    def _check_selection(self):
        if self._value.isValid() and not policy.is_selectable(
            _date(self._value.date()), *self._rules
        ):
            self.clear()

    def _update_text(self):
        self.setText(
            self._value.toString("yyyy-MM-dd HH:mm:ss")
            if self._value.isValid()
            else self._placeholder
        )
        self.setAccessibleDescription(self.text())
        self.updateGeometry()

    def show_popup(self) -> None:
        if not self._prepare_popup(date_time=True):
            return
        parts = policy.clamp_datetime(
            _datetime(self._value if self._value.isValid() else QtCore.QDateTime.currentDateTime()),
            self._minimum_dt,
            self._maximum_dt,
        )
        self._popup.calendar.reset(self, parts[:3])
        self._popup.seconds.set_value(parts[3:])
        self._popup.confirm_button.setEnabled(policy.is_selectable(parts[:3], *self._rules))
        self._popup.open()

    def _accept_datetime(self):
        parts = policy.clamp_datetime(
            (*self._popup.calendar.selected, *self._popup.seconds.value),
            self._minimum_dt,
            self._maximum_dt,
        )
        if not policy.is_selectable(parts[:3], *self._rules):
            return
        self._popup.dismiss()
        self._commit(parts)
        self.dateTimeAccepted.emit(self.date_time())
