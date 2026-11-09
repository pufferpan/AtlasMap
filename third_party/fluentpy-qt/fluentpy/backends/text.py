"""JSON token spans for the editor, independent of Qt.

Positions and lengths are UTF-16 code units, as required by QTextDocument.
This is a tolerant syntax scanner, not a JSON parser or validator.  It preserves
the editor's original regular-expression token rules while optionally moving
the scan and Unicode position mapping into the CPython extension.

``FLUENTPY_BACKEND=auto`` (the default) uses the extension when importable.
``python`` selects the reference implementation; ``native`` requires the
extension and raises an actionable error when it is unavailable.  The named
implementations are also exposed for reproducible differential benchmarks.
"""

from __future__ import annotations

import re
from importlib import import_module

from ._compat import select_backend

try:
    _extension = import_module(f"{__package__.rpartition('.')[0]}._native")
except (ImportError, OSError) as error:
    _extension = None
    _native_import_error = str(error)
else:
    _native_import_error = None
    if not callable(getattr(_extension, "json_spans", None)):
        _extension = None
        _native_import_error = "The installed fluentpy._native extension has no JSON scanner."

__all__ = [
    "backend_name",
    "json_spans",
    "json_spans_native",
    "json_spans_python",
    "native_available",
    "native_error",
]

_TOKENS = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|\b(?:true|false|null)\b"
    r"|(?<![\w.])-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])"
)


def native_available() -> bool:
    """Whether this interpreter successfully loaded the compiled extension."""
    return _extension is not None


def native_error() -> str | None:
    """Return the import failure, useful when diagnosing a missing binary."""
    return _native_import_error


def backend_name() -> str:
    """Resolve the backend selection, rejecting invalid or unavailable modes."""
    return select_backend(_extension, _native_import_error, "text")


def _require_native() -> None:
    if _extension is None:
        raise RuntimeError(
            "FLUENTPY_BACKEND=native requires the compiled fluentpy._native "
            "extension. Build the native extension for this Python interpreter "
            "or set FLUENTPY_BACKEND=python to use the compatible fallback. "
            f"Import error: {_native_import_error}"
        )


def json_spans_python(text: str) -> list[tuple[int, int, int]]:
    """Reference scanner; token kinds: key=0, string=1, number=2, literal=3."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    offsets = [0]
    for character in text:
        offsets.append(offsets[-1] + (2 if ord(character) > 0xFFFF else 1))
    spans = []
    for match in _TOKENS.finditer(text):
        token = match.group()
        if token.startswith('"'):
            following = match.end()
            while following < len(text) and text[following].isspace():
                following += 1
            kind = 0 if following < len(text) and text[following] == ":" else 1
        elif token in ("true", "false", "null"):
            kind = 3
        else:
            kind = 2
        start, end = match.span()
        spans.append((offsets[start], offsets[end] - offsets[start], kind))
    return spans


def json_spans_native(text: str) -> list[tuple[int, int, int]]:
    """Call the extension explicitly, failing visibly if it is unavailable."""
    _require_native()
    return _extension.json_spans(text)


def json_spans(text: str) -> list[tuple[int, int, int]]:
    """Scan with the selected backend without changing the source text."""
    if backend_name() == "native":
        return _extension.json_spans(text)
    return json_spans_python(text)
