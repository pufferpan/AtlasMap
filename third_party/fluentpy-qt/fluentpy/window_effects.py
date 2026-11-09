from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys

from .qt import QtCore, QtGui, QtWidgets
from .theme import ThemeMode


class _Margins(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def _dwm_set_int(hwnd: int, attr: int, value: int) -> bool:
    data = ctypes.c_int(value)
    function = ctypes.windll.dwmapi.DwmSetWindowAttribute
    function.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    function.restype = ctypes.c_long
    return function(hwnd, attr, ctypes.byref(data), ctypes.sizeof(data)) == 0


def _apply_window_shape(widget: QtWidgets.QWidget, hwnd: int) -> bool:
    """Use square, borderless maximized bounds; restore DWM's normal frame."""
    expanded = widget.isMaximized() or widget.isFullScreen()
    rounded = _dwm_set_int(hwnd, 33, 1 if expanded else 2)
    # DWMWA_BORDER_COLOR: NONE while covering the work area, DEFAULT when
    # restored. These affect DWM's own border, not a Qt-painted replacement.
    _dwm_set_int(hwnd, 34, -2 if expanded else -1)
    return rounded


def _get_window_long_ptr(hwnd: int, index: int) -> int:
    user32 = ctypes.windll.user32
    if hasattr(user32, "GetWindowLongPtrW"):
        func = user32.GetWindowLongPtrW
        func.restype = ctypes.c_longlong
    else:
        func = user32.GetWindowLongW
        func.restype = ctypes.c_long
    func.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    return int(func(hwnd, index))


def _set_window_long_ptr(hwnd: int, index: int, value: int) -> None:
    user32 = ctypes.windll.user32
    if hasattr(user32, "SetWindowLongPtrW"):
        func = user32.SetWindowLongPtrW
        func.restype = ctypes.c_longlong
        func.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    else:
        func = user32.SetWindowLongW
        func.restype = ctypes.c_long
        func.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_long]
    func(hwnd, index, value)


def _extend_frame(hwnd: int, whole_client: bool, integrated: bool = False) -> bool:
    """Extend the DWM surface without changing the window or extended styles."""
    inset = -1 if whole_client else (1 if integrated else 0)
    margins = _Margins(inset, inset, inset, inset)
    function = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
    function.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(_Margins)]
    function.restype = ctypes.c_long
    return function(hwnd, ctypes.byref(margins)) == 0


def _high_contrast_enabled() -> bool | None:
    class _HighContrast(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.UINT),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("lpszDefaultScheme", ctypes.wintypes.LPWSTR),
        ]

    value = _HighContrast()
    value.cbSize = ctypes.sizeof(value)
    query = ctypes.windll.user32.SystemParametersInfoW
    query.argtypes = [
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
        ctypes.c_void_p,
        ctypes.wintypes.UINT,
    ]
    query.restype = ctypes.wintypes.BOOL
    if not query(0x0042, value.cbSize, ctypes.byref(value), 0):  # SPI_GETHIGHCONTRAST
        return None
    return bool(value.dwFlags & 0x00000001)  # HCF_HIGHCONTRASTON


def _transparency_effects_enabled() -> bool:
    # Read the user's switch only. Never write Personalize settings or change
    # the global Windows theme to make a material visible.
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "EnableTransparency")
    except FileNotFoundError:
        # An absent preference uses Windows' default, not a forced opt-out.
        return True
    return isinstance(value, int) and bool(value)


def _backdrop_policy_allows() -> bool:
    """Check locally readable prerequisites; DWM still owns material policy."""
    try:
        if sys.getwindowsversion().build < 22621:
            return False  # DWMWA_SYSTEMBACKDROP_TYPE's documented minimum.
        composition = ctypes.wintypes.BOOL()
        query = ctypes.windll.dwmapi.DwmIsCompositionEnabled
        query.argtypes = [ctypes.POINTER(ctypes.wintypes.BOOL)]
        query.restype = ctypes.c_long
        if query(ctypes.byref(composition)) != 0 or not composition.value:
            return False
        if _high_contrast_enabled() is not False:
            return False
        return _transparency_effects_enabled()
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return False


def apply_system_backdrop(
    widget: QtWidgets.QWidget, mode: ThemeMode, active: bool, enabled: bool = True
) -> bool:
    """Expose DWM's main-window material across a transparent Qt client.

    Both the material attribute and frame extension must succeed. The caller
    must clear its ordinary, non-layered Qt backing store with source alpha;
    opaque Qt painting still covers the system material. The return value is
    native setup status, not a promise about the wallpaper tint or a capture.
    DWM handles activation and its remaining energy/session policy itself.
    Unsupported or policy-disabled setups return False for an opaque fallback.
    """

    if sys.platform != "win32":
        return False

    hwnd = None
    integrated = getattr(widget, "_integrated_windows_frame", False) is True
    try:
        hwnd = int(widget.winId())
        _dwm_set_int(hwnd, 20, 1 if mode is ThemeMode.DARK else 0)
        # Retain the system-owned frame, resize border and DWM shadow. These
        # are hints, not a custom rounded region or a painted Qt shadow.
        _apply_window_shape(widget, hwnd)
        if enabled and _backdrop_policy_allows():
            if _dwm_set_int(hwnd, 38, 2) and _extend_frame(hwnd, True):
                return True  # DWMSBT_MAINWINDOW + whole-client DWM surface.
        # Also undo a previous successful request when policy changes or only
        # one half of native setup succeeds. Preserve the resize-frame inset.
        _dwm_set_int(hwnd, 38, 1)  # DWMSBT_NONE
        _extend_frame(hwnd, False, integrated)
        return False
    except Exception:
        # A deleted/recreated native handle must leave ordinary Qt painting
        # available. Do not add WS_EX_LAYERED or overwrite frame styles here.
        if hwnd is not None:
            try:
                _dwm_set_int(hwnd, 38, 1)
                _extend_frame(hwnd, False, integrated)
            except Exception:
                pass
        return False


def capture_window_frame(widget: QtWidgets.QWidget) -> QtGui.QImage:
    """Capture this window, including actual Windows non-client controls.

    PrintWindow reads only the supplied HWND, not neighboring desktop content.
    Its result includes the native frame but not the compositor's outer shadow.
    A Qt-only grab is used on other platforms; a failed Windows capture raises
    rather than silently presenting a client-only image as native-frame proof.
    This helper is intended for preview generation and focused UI validation.
    """
    application = QtWidgets.QApplication.instance()
    if (
        sys.platform != "win32"
        or application is None
        or application.platformName().lower() != "windows"
    ):
        return widget.grab().toImage()

    hwnd = int(widget.window().winId())
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
    user32.GetWindowRect.restype = ctypes.wintypes.BOOL
    user32.GetWindowDC.argtypes = [ctypes.wintypes.HWND]
    user32.GetWindowDC.restype = ctypes.wintypes.HDC
    user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
    user32.PrintWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC, ctypes.wintypes.UINT]
    user32.PrintWindow.restype = ctypes.wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
    gdi32.GetDIBits.argtypes = [
        ctypes.wintypes.HDC,
        ctypes.wintypes.HBITMAP,
        ctypes.wintypes.UINT,
        ctypes.wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int

    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Cannot read the window frame bounds")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("Cannot capture an empty window")

    class _BitmapHeader(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.wintypes.DWORD),
            ("width", ctypes.wintypes.LONG),
            ("height", ctypes.wintypes.LONG),
            ("planes", ctypes.wintypes.WORD),
            ("bits", ctypes.wintypes.WORD),
            ("compression", ctypes.wintypes.DWORD),
            ("image_size", ctypes.wintypes.DWORD),
            ("x_pels", ctypes.wintypes.LONG),
            ("y_pels", ctypes.wintypes.LONG),
            ("colors", ctypes.wintypes.DWORD),
            ("important", ctypes.wintypes.DWORD),
        ]

    source, memory, bitmap, previous = user32.GetWindowDC(hwnd), None, None, None
    if not source:
        raise RuntimeError("Cannot acquire the window drawing context")
    try:
        memory = gdi32.CreateCompatibleDC(source)
        bitmap = gdi32.CreateCompatibleBitmap(source, width, height)
        if not memory or not bitmap:
            raise RuntimeError("Cannot create the native capture surface")
        previous = gdi32.SelectObject(memory, bitmap)
        if not user32.PrintWindow(hwnd, memory, 2):  # PW_RENDERFULLCONTENT
            raise RuntimeError("Windows rejected the native frame capture")
        gdi32.SelectObject(memory, previous)
        previous = None
        header = _BitmapHeader(
            ctypes.sizeof(_BitmapHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0
        )
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
            raise RuntimeError("Cannot read the native frame pixels")
        # Windows' 32-bit BI_RGB has an unused alpha byte, not a transparent
        # window. Force it opaque before handing the copied pixels to Qt.
        data = bytearray(pixels.raw)
        # PrintWindow can report success for an unmapped/hidden HWND while
        # producing an entirely black bitmap. Never publish that as a capture.
        if not any(data[0::4]) and not any(data[1::4]) and not any(data[2::4]):
            raise RuntimeError("Windows returned a black frame; capture a mapped window instead")
        data[3::4] = b"\xff" * (width * height)
        return QtGui.QImage(
            bytes(data), width, height, width * 4, QtGui.QImage.Format.Format_ARGB32
        ).copy()
    finally:
        if previous and memory:
            gdi32.SelectObject(memory, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory:
            gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd, source)


def apply_integrated_window_frame(widget: QtWidgets.QWidget, mode: ThemeMode) -> bool:
    """Retain the real Windows resize frame and DWM shadow for a Qt caption.

    FluentWindow handles WM_NCCALCSIZE so these styles do not add a second
    system caption. The buttons are explicitly Qt-rendered in this mode.
    """
    application = QtWidgets.QApplication.instance()
    if (
        sys.platform != "win32"
        or application is None
        or application.platformName().lower() != "windows"
    ):
        return False
    try:
        hwnd = int(widget.winId())
        old_style = _get_window_long_ptr(hwnd, -16)
        # Keep native resizing/system commands, but remove WS_CAPTION: DWM
        # would otherwise draw an extra set of caption glyphs over the sole
        # Qt title bar when the whole client exposes Mica. Leave non-client
        # rendering enabled so the actual material and DWM shadow survive.
        style = (old_style & ~0x00C00000) | 0x00040000 | 0x00080000
        flags = widget.windowFlags()
        for hint, bit in (
            (QtCore.Qt.WindowType.WindowMinimizeButtonHint, 0x00020000),
            (QtCore.Qt.WindowType.WindowMaximizeButtonHint, 0x00010000),
        ):
            style = style | bit if flags & hint else style & ~bit
        if style != old_style:
            _set_window_long_ptr(hwnd, -16, style)
        _dwm_set_int(hwnd, 20, 1 if mode is ThemeMode.DARK else 0)
        rounded = _apply_window_shape(widget, hwnd)
        # Window calls this after apply_system_backdrop. Retain its accepted
        # whole-client extension instead of covering Mica with a 1px surface.
        _extend_frame(hwnd, getattr(widget, "_backdrop_applied", False) is True, True)
        if style != old_style:
            position = ctypes.windll.user32.SetWindowPos
            position.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.wintypes.UINT,
            ]
            position(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        return rounded
    except (AttributeError, OSError, ValueError):
        return False


def apply_frameless_window_effect(widget: QtWidgets.QWidget, mode: ThemeMode) -> bool:
    if sys.platform != "win32":
        return False

    try:
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32
        gwl_style = -16
        gwl_exstyle = -20
        ws_caption = 0x00C00000
        ws_ex_noanimation = 0x08000000
        exstyle = _get_window_long_ptr(hwnd, gwl_exstyle)
        _set_window_long_ptr(hwnd, gwl_exstyle, exstyle | ws_ex_noanimation)
        _set_window_long_ptr(hwnd, gwl_style, ws_caption)
        margins = _Margins(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20.
        _dwm_set_int(hwnd, 20, 1 if mode is ThemeMode.DARK else 0)
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2.
        _dwm_set_int(hwnd, 33, 2)
        # DWMWA_BORDER_COLOR = 34. COLORREF is 0x00bbggrr.
        _dwm_set_int(hwnd, 34, 0x00262626 if mode is ThemeMode.DARK else 0x00D9D9D9)
        swp_nomove = 0x0002
        swp_nosize = 0x0001
        swp_nozorder = 0x0004
        swp_noactivate = 0x0010
        swp_framechanged = 0x0020
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            swp_nomove | swp_nosize | swp_nozorder | swp_noactivate | swp_framechanged,
        )
        return True
    except Exception:
        return False
