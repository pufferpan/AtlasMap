"""C-first color policy with compatible Python fallback, including old binaries."""

from importlib import import_module

from . import _color_python
from ._compat import select_backend

_METHODS = ("color_parse_hex", "color_format_hex", "color_rgb_to_hsv", "color_hsv_to_rgba")
try:
    _extension = import_module(f"{__package__.rpartition('.')[0]}._native")
except (ImportError, OSError) as error:
    _extension = None
    _native_import_error = str(error)
else:
    _native_import_error = None
    if not all(callable(getattr(_extension, name, None)) for name in _METHODS):
        _extension = None
        _native_import_error = (
            "The installed fluentpy._native extension predates the color backend."
        )


def native_available():
    return _extension is not None


def native_error():
    return _native_import_error


def backend_name():
    return select_backend(_extension, _native_import_error, "color")


def parse_hex(text):
    return (
        _extension.color_parse_hex(text)
        if backend_name() == "native"
        else _color_python.parse_hex(text)
    )


def format_hex(red, green, blue, alpha=255, include_alpha=False):
    if backend_name() == "native":
        return _extension.color_format_hex(red, green, blue, alpha, include_alpha)
    return _color_python.format_hex(red, green, blue, alpha, include_alpha)


def rgb_to_hsv(red, green, blue):
    return (
        _extension.color_rgb_to_hsv(red, green, blue)
        if backend_name() == "native"
        else _color_python.rgb_to_hsv(red, green, blue)
    )


def hsv_to_rgba(hue, saturation, value, alpha=255):
    return (
        _extension.color_hsv_to_rgba(hue, saturation, value, alpha)
        if backend_name() == "native"
        else _color_python.hsv_to_rgba(hue, saturation, value, alpha)
    )
