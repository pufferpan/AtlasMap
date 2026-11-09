"""C file-selection acceleration with compatible Python fallback."""

from importlib import import_module

from . import _drop_python
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
        for name in ("drop_filter_paths", "drop_normalize_extensions")
    ):
        _extension = None
        _import_error = "The installed native extension predates the drop selection backend."


def require_native():
    if _extension is None:
        raise RuntimeError(
            "DropArea requires the compiled fluentpy._native drop backend. Rebuild with "
            "`python scripts/build_native.py` (or pass --zig), then restart the application. "
            f"Import error: {_import_error}"
        )
    return _extension


def native_available() -> bool:
    return _extension is not None


def native_error() -> str | None:
    return _import_error


def backend_name() -> str:
    return select_backend(_extension, _import_error, "drop")


def normalize_extensions(extensions) -> tuple[str, ...]:
    if backend_name() == "native":
        return _extension.drop_normalize_extensions(extensions)
    return _drop_python.normalize_extensions(extensions)


def filter_paths(
    candidates,
    extensions,
    *,
    allow_files=True,
    allow_folders=True,
    multiple=True,
    case_sensitive=True,
):
    if backend_name() == "native":
        return _extension.drop_filter_paths(
            candidates, extensions, allow_files, allow_folders, multiple, case_sensitive
        )
    return _drop_python.filter_paths(
        candidates, extensions, allow_files, allow_folders, multiple, case_sensitive
    )
