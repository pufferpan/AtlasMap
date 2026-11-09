"""Shared backend selection and strict integer compatibility with CPython C APIs."""

import os
import struct

_LONG_BITS = struct.calcsize("l") * 8
_LONG_MIN = -(1 << (_LONG_BITS - 1))
_LONG_MAX = (1 << (_LONG_BITS - 1)) - 1


def select_backend(extension, error, feature):
    mode = os.environ.get("FLUENTPY_BACKEND", "auto").strip().lower()
    if mode not in ("auto", "python", "native"):
        raise ValueError("FLUENTPY_BACKEND must be 'auto', 'python', or 'native'")
    if mode == "python":
        return "python"
    if extension is not None:
        return "native"
    if mode == "native":
        raise RuntimeError(
            f"FLUENTPY_BACKEND=native requires the compiled fluentpy._native {feature} backend. "
            "Rebuild with `python scripts/build_native.py` for this Python interpreter, "
            "or set FLUENTPY_BACKEND=auto (or python) to use the compatible fallback. "
            f"Import error: {error}"
        )
    return "python"


def strict_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, not bool or another type")
    # Normalize int subclasses without invoking their Python arithmetic hooks.
    return int.__index__(value)


def c_long(value, name):
    value = strict_int(value, name)
    if not _LONG_MIN <= value <= _LONG_MAX:
        raise OverflowError("Python int too large to convert to C long")
    return value
