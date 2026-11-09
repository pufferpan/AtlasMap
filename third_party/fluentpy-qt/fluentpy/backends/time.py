"""C-first time conversion and independent wheel steps, with Python fallback."""

from importlib import import_module

from . import _time_python
from ._compat import select_backend

_METHODS = (
    "time_validate_time",
    "time_display_time",
    "time_from_display",
    "time_step_time",
    "time_column_values",
)
try:
    _extension = import_module(f"{__package__.rpartition('.')[0]}._native")
except (ImportError, OSError) as error:
    _extension = None
    _native_import_error = str(error)
else:
    _native_import_error = None
    if not all(callable(getattr(_extension, name, None)) for name in _METHODS):
        _extension = None
        _native_import_error = "The installed fluentpy._native extension predates the time backend."


def native_available() -> bool:
    return _extension is not None


def native_error() -> str | None:
    return _native_import_error


def backend_name() -> str:
    return select_backend(_extension, _native_import_error, "time")


def validate_time(hour: int, minute: int) -> tuple[int, int]:
    if backend_name() == "native":
        return _extension.time_validate_time(hour, minute)
    return _time_python.validate_time(hour, minute)


def display_time(hour: int, minute: int, use_12_hour: bool = False) -> tuple[int, int, int]:
    if backend_name() == "native":
        return _extension.time_display_time(hour, minute, use_12_hour)
    return _time_python.display_time(hour, minute, use_12_hour)


def from_display(hour: int, minute: int, period: int) -> tuple[int, int]:
    if backend_name() == "native":
        return _extension.time_from_display(hour, minute, period)
    return _time_python.from_display(hour, minute, period)


def step_time(
    hour: int, minute: int, column: int, steps: int, use_12_hour: bool = False
) -> tuple[int, int]:
    if backend_name() == "native":
        return _extension.time_step_time(hour, minute, column, steps, use_12_hour)
    return _time_python.step_time(hour, minute, column, steps, use_12_hour)


def column_values(
    hour: int, minute: int, column: int, radius: int = 4, use_12_hour: bool = False
) -> tuple[int | None, ...]:
    if backend_name() == "native":
        return _extension.time_column_values(hour, minute, column, radius, use_12_hour)
    return _time_python.column_values(hour, minute, column, radius, use_12_hour)
