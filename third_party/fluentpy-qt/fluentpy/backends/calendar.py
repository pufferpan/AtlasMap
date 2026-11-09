"""C-first calendar, range and second-precision time policies."""

from importlib import import_module

from . import _calendar_python as fallback
from ._compat import select_backend

_METHODS = (
    "validate_rules",
    "is_selectable",
    "month_cells",
    "shift_date",
    "normalize_range",
    "clamp_datetime",
    "step_time",
    "time_values",
)
try:
    _extension = import_module(f"{__package__.rpartition('.')[0]}._native")
except (ImportError, OSError) as error:
    _extension, _native_import_error = None, str(error)
else:
    _native_import_error = None
    if not all(callable(getattr(_extension, "calendar_" + name, None)) for name in _METHODS):
        _extension = None
        _native_import_error = (
            "The installed fluentpy._native extension predates the calendar backend."
        )


def native_available() -> bool:
    return _extension is not None


def native_error() -> str | None:
    return _native_import_error


def backend_name() -> str:
    return select_backend(_extension, _native_import_error, "calendar")


def _call(name, *args, **kwargs):
    target = (
        getattr(_extension, "calendar_" + name)
        if backend_name() == "native"
        else getattr(fallback, name)
    )
    return target(*args, **kwargs)


def validate_rules(
    minimum=(1, 1, 1), maximum=(9999, 12, 31), disabled_weekdays=(), disabled_dates=()
):
    return _call("validate_rules", minimum, maximum, disabled_weekdays, disabled_dates)


def is_selectable(
    value, minimum=(1, 1, 1), maximum=(9999, 12, 31), disabled_weekdays=(), disabled_dates=()
):
    return _call("is_selectable", value, minimum, maximum, disabled_weekdays, disabled_dates)


def month_cells(
    year,
    month,
    minimum=(1, 1, 1),
    maximum=(9999, 12, 31),
    disabled_weekdays=(),
    disabled_dates=(),
    first_weekday=0,
):
    return _call(
        "month_cells",
        year,
        month,
        minimum,
        maximum,
        disabled_weekdays,
        disabled_dates,
        first_weekday,
    )


def shift_date(value, days=0, months=0):
    return _call("shift_date", value, days, months)


def normalize_range(
    start, end, minimum=(1, 1, 1), maximum=(9999, 12, 31), disabled_weekdays=(), disabled_dates=()
):
    return _call("normalize_range", start, end, minimum, maximum, disabled_weekdays, disabled_dates)


def clamp_datetime(value, minimum=(1, 1, 1, 0, 0, 0), maximum=(9999, 12, 31, 23, 59, 59)):
    return _call("clamp_datetime", value, minimum, maximum)


def step_time(hour, minute, second, column, steps):
    return _call("step_time", hour, minute, second, column, steps)


def time_values(hour, minute, second, column, radius=4):
    return _call("time_values", hour, minute, second, column, radius)
