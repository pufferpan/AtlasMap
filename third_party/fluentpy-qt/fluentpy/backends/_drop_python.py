"""File selection policy with the same order and rejection reasons as C."""

from ._compat import c_long


def normalize_extensions(extensions):
    if isinstance(extensions, (str, bytes)):
        raise TypeError("extensions must be a sequence of strings, not a string")
    items = list(extensions)
    result, seen, unrestricted = [], set(), False
    for value in items:
        if not isinstance(value, str):
            raise TypeError("every extension must be str")
        suffix = value.strip().casefold()
        if suffix in ("*", "*.*"):
            unrestricted = True
            continue
        if suffix.startswith("*."):
            suffix = suffix[1:]
        if not suffix:
            raise ValueError("extensions cannot contain empty strings")
        if not suffix.startswith("."):
            suffix = "." + suffix
        if len(suffix) < 2 or any(c in "/\\*?\0" or c.isspace() for c in suffix[1:]):
            raise ValueError("extensions must be suffixes such as .png or .tar.gz")
        if suffix not in seen:
            seen.add(suffix)
            result.append(suffix)
    return () if unrestricted else tuple(result)


def filter_paths(
    candidates, extensions, allow_files=True, allow_folders=True, multiple=True, case_sensitive=True
):
    allow_files, allow_folders, multiple, case_sensitive = map(
        bool, (allow_files, allow_folders, multiple, case_sensitive)
    )
    if isinstance(candidates, (str, bytes)):
        raise TypeError("candidates must be a sequence of (path, kind) pairs")
    items = list(candidates)
    suffixes = normalize_extensions(extensions)
    accepted, rejected, seen = [], [], set()
    for item in items:
        pair = tuple(item)
        if len(pair) != 2:
            raise ValueError("candidate must have exactly two items")
        path, kind = pair
        if not isinstance(path, str):
            raise TypeError("candidate path must be str and kind must be int")
        kind = c_long(kind, "kind")
        if not 0 <= kind <= 3:
            raise ValueError("kind must be missing=0, file=1, folder=2 or other=3")
        reason = None
        if not path or "\0" in path:
            reason = "invalid"
        elif kind == 0:
            reason = "missing"
        elif (kind == 1 and not allow_files) or (kind == 2 and not allow_folders) or kind == 3:
            reason = "type"
        elif kind == 1 and suffixes and not path.casefold().endswith(suffixes):
            reason = "extension"
        if reason is None:
            key = path if case_sensitive else path.casefold()
            if key in seen:
                reason = "duplicate"
            elif not multiple and accepted:
                reason = "multiple"
            else:
                seen.add(key)
        if reason is None:
            accepted.append((path, kind))
        else:
            rejected.append((path, reason))
    return accepted, rejected
