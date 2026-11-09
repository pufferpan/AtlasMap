"""Single-chord validation and conflict compatibility without the C binary."""

from ._compat import c_long

SHIFT, CTRL, ALT, META, NUM = 0x02000000, 0x04000000, 0x08000000, 0x10000000, 0x20000000
MODIFIERS = SHIFT | CTRL | ALT | META | NUM


def _modifiers(value):
    value = c_long(value, "modifiers")
    if value < 0 or value & ~MODIFIERS:
        raise ValueError("unsupported shortcut modifier bits")
    return value


def normalize(key, modifiers):
    key = c_long(key, "key")
    modifiers = _modifiers(modifiers)
    if key == 0 and modifiers == 0:
        return 0, 0
    if not (
        (0x20 <= key <= 0x10FFFF and not 0xD800 <= key <= 0xDFFF) or 0x01000000 <= key < 0x01020000
    ):
        raise ValueError("shortcut requires one valid non-modifier Qt key")
    if 0x01000020 <= key <= 0x01000026:
        raise ValueError("a modifier or lock key alone is not a shortcut")
    if ord("a") <= key <= ord("z"):
        key -= ord("a") - ord("A")
    return key, modifiers


def modifier_labels(modifiers):
    modifiers = _modifiers(modifiers)
    return tuple(
        name
        for flag, name in (
            (CTRL, "Ctrl"),
            (ALT, "Alt"),
            (SHIFT, "Shift"),
            (META, "Meta"),
            (NUM, "Num"),
        )
        if modifiers & flag
    )


def conflicts(key, modifiers, reserved):
    chord = normalize(key, modifiers)
    if isinstance(reserved, (str, bytes)):
        raise TypeError("reserved shortcuts must be pairs, not text")
    found = False
    for item in list(reserved):
        pair = tuple(item)
        if len(pair) != 2:
            raise ValueError("reserved shortcut must contain key and modifiers")
        other = normalize(*pair)
        found |= chord[0] != 0 and chord == other
    return bool(found)
