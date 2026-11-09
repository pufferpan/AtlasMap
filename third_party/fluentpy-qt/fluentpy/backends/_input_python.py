"""Compatible reference for native segmented password validation."""


def split_code(text, length, digits_only=True, truncate=False):
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(length, bool) or not isinstance(length, int):
        raise TypeError("length must be an int")
    length = int.__index__(length)
    text = str.__str__(text)
    if not 1 <= length <= 32:
        raise ValueError("length must be between 1 and 32")
    if not isinstance(digits_only, bool) or not isinstance(truncate, bool):
        raise TypeError("digits_only and truncate must be bools")
    if len(text) > length and not truncate:
        raise ValueError("code is longer than length")
    if any(not ("0" <= char <= "9") if digits_only else not char.isprintable() for char in text):
        raise ValueError("code contains an invalid character")
    return tuple(text[index : index + 1] for index in range(length))
