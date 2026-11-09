"""C-first segmented input validation, with per-feature fallback for old binaries."""

from importlib import import_module

from . import _input_python
from ._compat import select_backend

try:
    _extension = import_module(f"{__package__.rpartition('.')[0]}._native")
except (ImportError, OSError) as error:
    _extension = None
    _native_import_error = str(error)
else:
    _native_import_error = None
    if not callable(getattr(_extension, "input_split_code", None)):
        _extension = None
        _native_import_error = "The installed fluentpy._native extension predates segmented input."


def native_available():
    return _extension is not None


def native_error():
    return _native_import_error


def backend_name():
    return select_backend(_extension, _native_import_error, "segmented input")


def split_code(text, length, digits_only=True, truncate=False):
    return (
        _extension.input_split_code(text, length, digits_only, truncate)
        if backend_name() == "native"
        else _input_python.split_code(text, length, digits_only, truncate)
    )
