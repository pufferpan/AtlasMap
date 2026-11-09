"""FluentPy exports only. No widget subclasses, custom paints, or Qt fallbacks."""
import fluentpy as _fp
from fluentpy import widgets as W, theme, ThemeMode, FluentIcon as _FluentIconEnum
from fluentpy.icons import fluent_icon as _fluent_icon
from PySide6.QtGui import QIcon

LEVEL=1
VERSION=_fp.__version__
SOURCE=f'fluentpy-qt {VERSION} (native controls)'
LEVEL_NAME='FluentPy 原生控件'
FluentWindow=W.FluentWindow
PushButton=W.Button
PrimaryPushButton=W.AccentButton
ToolButton=W.IconButton
TransparentToolButton=W.TextButton
ToggleButton=W.ToggleButton
ComboBox=W.ComboBox
CheckBox=W.CheckBox
ToggleSwitch=W.ToggleSwitch
ProgressBar=W.ProgressBar
CardWidget=W.CardWidget
SimpleCardWidget=W.SimpleCardWidget
HeaderCardWidget=W.HeaderCardWidget
TableWidget=W.TableWidget


def apply_fluent_theme(dark=True,color='#2B579A'):
    theme.set_theme('dark' if dark else 'light',accent=color)


def describe():
    return dict(level=LEVEL,level_name=LEVEL_NAME,source=SOURCE,window_class='FluentWindow')

ICON_ALIASES = {
    "library": ("DOCUMENT", "BOOK", "ARCHIVE", "FOLDER"),
    "photo": ("IMAGE", "EYE", "PHOTO", "VIEW"),
    "brush": ("EYEDROPPER", "COLOR", "EDIT", "TOOLBOX"),
    "save": ("DOCUMENT_SAVE", "ARROW_DOWNLOAD", "DOCUMENT"),
    "setting": ("SETTINGS", "TOOLBOX"),
    "folder": ("FOLDER", "FOLDER_OPEN"),
    "camera": ("CAMERA", "IMAGE"),
    "fullscreen": ("ARROW_MAXIMIZE", "GRID"),
    "search": ("DOCUMENT_SEARCH", "FILTER"),
    "delete": ("DELETE", "DISMISS"),
    "sync": ("ARROW_SYNC", "ARROW_CLOCKWISE", "ARROW_RESET"),
    "info": ("INFO", "ALERT"),
    "palette": ("COLOR", "EYEDROPPER"),
    "view": ("EYE", "GRID"),
    "export": ("ARROW_EXPORT", "ARROW_UPLOAD"),
    "open": ("FOLDER_OPEN", "DOCUMENT"),
    "app": ("APPS", "HOME"),
    "download": ("ARROW_DOWNLOAD", "ARROW_DOWN"),
    "copy": ("COPY", "DOCUMENT_COPY"),
    "play": ("GAMES", "NAVIGATION"),
    "document": ("DOCUMENT", "DOCUMENT_TEXT"),
    "help": ("INFO", "ALERT"),
    "history": ("HISTORY", "CLOCK"),
}


def icon(name: str) -> QIcon:
    """FluentPy's FluentWindow / setIcon 只要 QIcon，所以这里直接给 QIcon。"""
    key = (name or "").strip().lower()
    for cand in ICON_ALIASES.get(key, ()) + (key.upper(),):
        member = _FluentIconEnum.__members__.get(str(cand).upper())
        if member is not None:
            try:
                return _fluent_icon(member)
            except Exception:                                # noqa: BLE001
                continue
    member = _FluentIconEnum.__members__.get("INFO")
    try:
        return _fluent_icon(member) if member is not None else QIcon()
    except Exception:                                        # noqa: BLE001
        return QIcon()


def qicon(name: str) -> QIcon:
    return icon(name)
