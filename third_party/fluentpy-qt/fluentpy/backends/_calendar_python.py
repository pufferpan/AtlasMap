"""Gregorian calendar policies, kept equivalent to calendar_accel.c."""

from datetime import date, timedelta

from ._compat import c_long, strict_int

MINIMUM = (1, 1, 1)
MAXIMUM = (9999, 12, 31)


def _integer(value, name, lower, upper):
    value = strict_int(value, name)
    if not lower <= value <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _parts(value, name="date", size=3):
    try:
        value = tuple(value)
    except TypeError:
        raise TypeError(f"{name} must be a sequence") from None
    if len(value) != size:
        raise ValueError(f"{name} must contain {size} parts")
    y, m, d = (
        _integer(v, n, lo, hi)
        for v, n, lo, hi in zip(value[:3], ("year", "month", "day"), (1, 1, 1), (9999, 12, 31))
    )
    date(y, m, d)
    if size == 3:
        return y, m, d
    h, minute, s = (
        _integer(v, n, 0, hi)
        for v, n, hi in zip(value[3:], ("hour", "minute", "second"), (23, 59, 59))
    )
    return y, m, d, h, minute, s


def validate_rules(minimum=MINIMUM, maximum=MAXIMUM, disabled_weekdays=(), disabled_dates=()):
    minimum, maximum = _parts(minimum, "minimum"), _parts(maximum, "maximum")
    if minimum > maximum:
        raise ValueError("minimum must not be after maximum")
    weekdays = tuple(sorted({_integer(v, "weekday", 0, 6) for v in disabled_weekdays}))
    dates = tuple(sorted({_parts(v, "disabled date") for v in disabled_dates}))
    return minimum, maximum, weekdays, dates


def _enabled(value, rules):
    low, high, weekdays, dates = rules
    return low <= value <= high and date(*value).weekday() not in weekdays and value not in dates


def is_selectable(value, minimum=MINIMUM, maximum=MAXIMUM, disabled_weekdays=(), disabled_dates=()):
    return _enabled(
        _parts(value), validate_rules(minimum, maximum, disabled_weekdays, disabled_dates)
    )


def month_cells(
    year,
    month,
    minimum=MINIMUM,
    maximum=MAXIMUM,
    disabled_weekdays=(),
    disabled_dates=(),
    first_weekday=0,
):
    year, month = _integer(year, "year", 1, 9999), _integer(month, "month", 1, 12)
    first_weekday = _integer(first_weekday, "first_weekday", 0, 6)
    rules = validate_rules(minimum, maximum, disabled_weekdays, disabled_dates)
    first = date(year, month, 1)
    start = first.toordinal() - (first.weekday() - first_weekday) % 7
    result = []
    for ordinal in range(start, start + 42):
        if not 1 <= ordinal <= date.max.toordinal():
            result.append(None)
        else:
            value = date.fromordinal(ordinal)
            parts = value.year, value.month, value.day
            result.append((*parts, _enabled(parts, rules)))
    return tuple(result)


def shift_date(value, days=0, months=0):
    y, m, d = _parts(value)
    days, months = c_long(days, "days"), c_long(months, "months")
    index = max(0, min(9999 * 12 - 1, (y - 1) * 12 + m - 1 + months))
    y, m = divmod(index, 12)
    y, m = y + 1, m + 1
    last = (date(y, m + 1, 1) - timedelta(days=1)).day if m < 12 else 31
    ordinal = date(y, m, min(d, last)).toordinal()
    result = date.fromordinal(max(1, min(date.max.toordinal(), ordinal + days)))
    return result.year, result.month, result.day


def normalize_range(
    start, end, minimum=MINIMUM, maximum=MAXIMUM, disabled_weekdays=(), disabled_dates=()
):
    rules = validate_rules(minimum, maximum, disabled_weekdays, disabled_dates)
    start, end = _parts(start, "start"), _parts(end, "end")
    if not _enabled(start, rules) or not _enabled(end, rules):
        raise ValueError("range endpoints must be selectable")
    return (start, end) if start <= end else (end, start)


def clamp_datetime(value, minimum=(1, 1, 1, 0, 0, 0), maximum=(9999, 12, 31, 23, 59, 59)):
    value, minimum, maximum = (
        _parts(value, size=6),
        _parts(minimum, "minimum", 6),
        _parts(maximum, "maximum", 6),
    )
    if minimum > maximum:
        raise ValueError("minimum must not be after maximum")
    return max(minimum, min(maximum, value))


def step_time(hour, minute, second, column, steps):
    values = [
        _integer(hour, "hour", 0, 23),
        _integer(minute, "minute", 0, 59),
        _integer(second, "second", 0, 59),
    ]
    column = _integer(column, "column", 0, 2)
    steps = strict_int(steps, "steps")
    values[column] = (values[column] + steps) % (24 if column == 0 else 60)
    return tuple(values)


def time_values(hour, minute, second, column, radius=4):
    column = _integer(column, "column", 0, 2)
    values = step_time(hour, minute, second, column, 0)
    radius = _integer(radius, "radius", 0, 100)
    return tuple(
        (values[column] + i) % (24 if column == 0 else 60) for i in range(-radius, radius + 1)
    )
