"""Compatible Gregorian policy for installations without the C accelerator."""

from ._compat import strict_int


def _bounded(value, name, minimum, maximum):
    value = strict_int(value, name)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _month_length(year, month):
    return (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1] + (
        month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    )


def days_in_month(year, month):
    return _month_length(_bounded(year, "year", 1, 9999), _bounded(month, "month", 1, 12))


def _bound(value, name):
    value = tuple(value)
    if len(value) != 3:
        raise ValueError(f"{name} must contain exactly three date integers")
    year = _bounded(value[0], "bound year", 1, 9999)
    month = _bounded(value[1], "bound month", 1, 12)
    day = _bounded(value[2], "bound day", 1, _month_length(year, month))
    return year, month, day


def _clamp(value, minimum, maximum):
    year, month, day = value
    return max(minimum, min(maximum, (year, month, min(day, _month_length(year, month)))))


def _parse(year, month, day, minimum, maximum):
    year = _bounded(year, "year", 1, 9999)
    month = _bounded(month, "month", 1, 12)
    day = max(1, min(strict_int(day, "day"), _month_length(year, month)))
    minimum, maximum = _bound(minimum, "minimum"), _bound(maximum, "maximum")
    if minimum > maximum:
        raise ValueError("minimum date must not be after maximum date")
    return _clamp((year, month, day), minimum, maximum), minimum, maximum


def clamp_date(year, month, day, minimum=(1, 1, 1), maximum=(9999, 12, 31)):
    return _parse(year, month, day, minimum, maximum)[0]


def _interval(value, minimum, maximum, column):
    year, month, _day = value
    if column == 0:
        return minimum[0], maximum[0]
    if column == 1:
        return minimum[1] if year == minimum[0] else 1, maximum[1] if year == maximum[0] else 12
    return (
        minimum[2] if (year, month) == minimum[:2] else 1,
        maximum[2] if (year, month) == maximum[:2] else _month_length(year, month),
    )


def step_date(year, month, day, column, steps, minimum=(1, 1, 1), maximum=(9999, 12, 31)):
    column = _bounded(column, "column", 0, 2)
    steps = strict_int(steps, "steps")
    value, minimum, maximum = _parse(year, month, day, minimum, maximum)
    lower, upper = _interval(value, minimum, maximum, column)
    updated = list(value)
    updated[column] = (
        max(lower, min(upper, value[column] + steps))
        if column == 0
        else lower + (value[column] - lower + steps) % (upper - lower + 1)
    )
    return _clamp(updated, minimum, maximum)


def column_values(year, month, day, column, radius=4, minimum=(1, 1, 1), maximum=(9999, 12, 31)):
    column = _bounded(column, "column", 0, 2)
    radius = _bounded(radius, "radius", 0, 100)
    value, minimum, maximum = _parse(year, month, day, minimum, maximum)
    lower, upper = _interval(value, minimum, maximum, column)
    center = value[column]
    return tuple(
        None
        if (column == 0 and not lower <= center + offset <= upper)
        or (lower == upper and offset != 0)
        else center + offset
        if column == 0
        else lower + (center - lower + offset) % (upper - lower + 1)
        for offset in range(-radius, radius + 1)
    )
