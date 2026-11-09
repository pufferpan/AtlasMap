"""Compatible time-wheel policy when the optional C extension is unavailable."""

from ._compat import strict_int


def _bounded(value, name, lower, upper):
    value = strict_int(value, name)
    if not lower <= value <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _mode(use_12_hour):
    if not isinstance(use_12_hour, bool):
        raise TypeError("use_12_hour must be bool")
    return use_12_hour


def validate_time(hour, minute):
    return _bounded(hour, "hour", 0, 23), _bounded(minute, "minute", 0, 59)


def display_time(hour, minute, use_12_hour=False):
    hour, minute = validate_time(hour, minute)
    _mode(use_12_hour)
    return (hour % 12 or 12) if use_12_hour else hour, minute, int(hour >= 12)


def from_display(hour, minute, period):
    hour = _bounded(hour, "hour", 1, 12)
    minute = _bounded(minute, "minute", 0, 59)
    period = _bounded(period, "period", 0, 1)
    return hour % 12 + period * 12, minute


def step_time(hour, minute, column, steps, use_12_hour=False):
    hour, minute = validate_time(hour, minute)
    _mode(use_12_hour)
    column = _bounded(column, "column", 0, 2 if use_12_hour else 1)
    steps = strict_int(steps, "steps")
    if column == 1:
        minute = (minute + steps) % 60
    elif column == 2:
        hour = hour % 12 + max(0, min(1, int(hour >= 12) + steps)) * 12
    elif use_12_hour:
        display = ((hour % 12 or 12) - 1 + steps) % 12 + 1
        hour = display % 12 + int(hour >= 12) * 12
    else:
        hour = (hour + steps) % 24
    return hour, minute


def column_values(hour, minute, column, radius=4, use_12_hour=False):
    display, minute, period = display_time(hour, minute, use_12_hour)
    column = _bounded(column, "column", 0, 2 if use_12_hour else 1)
    radius = _bounded(radius, "radius", 0, 100)
    if column == 2:
        return tuple(
            value if 0 <= value <= 1 else None
            for value in range(period - radius, period + radius + 1)
        )
    value, lower, count = (
        (minute, 0, 60) if column == 1 else (display, 1, 12) if use_12_hour else (display, 0, 24)
    )
    return tuple((value - lower + offset) % count + lower for offset in range(-radius, radius + 1))
