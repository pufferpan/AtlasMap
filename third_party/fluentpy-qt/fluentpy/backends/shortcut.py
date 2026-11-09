"""Prefer C shortcut policy, falling back to Python; Qt converts key strings."""

from importlib import import_module

from . import _shortcut_python
from ._compat import select_backend

try:
    _extension = import_module("fluentpy._native")
except (ImportError, OSError) as error:
    _extension = None
    _import_error = str(error)
else:
    _import_error = None
    if not all(
        callable(getattr(_extension, name, None))
        for name in ("shortcut_normalize", "shortcut_modifier_labels", "shortcut_conflicts")
    ):
        _extension = None
        _import_error = "The installed C extension predates the shortcut backend."


def require_native():
    if _extension is None:
        raise RuntimeError(
            "ShortcutPicker requires the compiled fluentpy._native shortcut backend. "
            "Rebuild with `python scripts/build_native.py` (or pass --zig), then restart. "
            f"Import error: {_import_error}"
        )
    return _extension


def native_available():
    return _extension is not None


def native_error():
    return _import_error


def backend_name():
    return select_backend(_extension, _import_error, "shortcut")


def normalize(key, modifiers):
    if backend_name() == "native":
        return _extension.shortcut_normalize(key, modifiers)
    return _shortcut_python.normalize(key, modifiers)


def modifier_labels(modifiers):
    if backend_name() == "native":
        return _extension.shortcut_modifier_labels(modifiers)
    return _shortcut_python.modifier_labels(modifiers)


def conflicts(key, modifiers, reserved):
    if backend_name() == "native":
        return _extension.shortcut_conflicts(key, modifiers, reserved)
    return _shortcut_python.conflicts(key, modifiers, reserved)
