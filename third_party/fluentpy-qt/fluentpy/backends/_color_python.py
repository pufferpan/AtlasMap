"""Reference color parsing and HSV conversion, independent of Qt."""

import math

from ._compat import strict_int


def _channel(value, name):
    value = strict_int(value, name)
    if not 0 <= value <= 255:
        raise ValueError(f"{name} must be between 0 and 255")
    return value


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        value = float(value)
    except OverflowError:
        raise ValueError(f"{name} is outside its valid range") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} is outside its valid range")
    return value


def parse_hex(text):
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    digits = text[1:] if text.startswith("#") else text
    if len(digits) not in (3, 6, 8) or any(char not in "0123456789abcdefABCDEF" for char in digits):
        raise ValueError("expected #RGB, #RRGGBB or #AARRGGBB")
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    value = int(digits, 16)
    return (
        value >> 16 & 255,
        value >> 8 & 255,
        value & 255,
        value >> 24 if len(digits) == 8 else 255,
    )


def format_hex(red, green, blue, alpha=255, include_alpha=False):
    red, green, blue, alpha = (
        _channel(value, name)
        for value, name in zip((red, green, blue, alpha), ("red", "green", "blue", "alpha"))
    )
    if not isinstance(include_alpha, bool):
        raise TypeError("include_alpha must be a bool")
    return (
        f"#{alpha:02x}{red:02x}{green:02x}{blue:02x}"
        if include_alpha
        else f"#{red:02x}{green:02x}{blue:02x}"
    )


def rgb_to_hsv(red, green, blue):
    r, g, b = (
        _channel(value, name) / 255
        for value, name in zip((red, green, blue), ("red", "green", "blue"))
    )
    maximum, minimum = max(r, g, b), min(r, g, b)
    delta = maximum - minimum
    if delta == 0:
        hue = -1.0
    elif maximum == r:
        hue = ((g - b) / delta) % 6 * 60
    elif maximum == g:
        hue = ((b - r) / delta + 2) * 60
    else:
        hue = ((r - g) / delta + 4) * 60
    return hue, delta / maximum if maximum else 0.0, maximum


def hsv_to_rgba(hue, saturation, value, alpha=255):
    h = _number(hue, "hue", 0, 360) / 60
    s = _number(saturation, "saturation", 0, 1)
    v = _number(value, "value", 0, 1)
    a = _channel(alpha, "alpha")
    c = v * s
    x = c * (1 - abs(h % 2 - 1))
    m = v - c
    candidates = ((c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x))
    components = candidates[int(h) % 6]
    return tuple(math.floor((component + m) * 255 + 0.5) for component in components) + (a,)
