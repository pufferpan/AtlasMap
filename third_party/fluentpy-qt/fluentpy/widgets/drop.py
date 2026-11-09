"""Qt local-file selection with optional C policy acceleration."""

from __future__ import annotations

import os

from ..backends import drop as selection
from ..qt import QtCore, QtGui, QtWidgets, Signal, Slot
from ..theme import theme
from ..theme.fonts import ui_font
from .button import TextButton


def _paths(values):
    if isinstance(values, (str, bytes)):
        raise TypeError("paths must be an iterable of local paths")
    result = tuple(os.fspath(value) for value in values)
    if any(not isinstance(value, str) for value in result):
        raise TypeError("local paths must be strings, not bytes")
    return result


def _candidates(paths):
    """Bridge Qt's native filesystem metadata to the selected policy backend."""
    result = []
    for path in paths:
        if not path or "\0" in path:
            result.append((path, 0))
            continue
        info = QtCore.QFileInfo(path)
        kind = 0 if not info.exists() else 1 if info.isFile() else 2 if info.isDir() else 3
        result.append((info.canonicalFilePath() or info.absoluteFilePath(), kind))
    return result


class _SelectionSignals(QtCore.QObject):
    finished = Signal(int, object, object)


class _SelectionJob(QtCore.QRunnable):
    def __init__(self, request, paths, extensions, options):
        super().__init__()
        self.signals = _SelectionSignals()
        self.request, self.paths, self.extensions, self.options = (
            request,
            paths,
            extensions,
            options,
        )

    def run(self):
        try:
            result = selection.filter_paths(
                _candidates(self.paths), self.extensions, **self.options
            )
            self.signals.finished.emit(self.request, result, None)
        except Exception as error:
            self.signals.finished.emit(self.request, None, str(error))


class _BrowseButton(TextButton):
    _h_padding = 6

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(0)
        self.setFixedHeight(30)

    def sizeHint(self):
        return QtCore.QSize(self.fontMetrics().horizontalAdvance(self.text()) + 12, 30)

    def _draw_content(self, painter, rect, color):
        accent = QtGui.QColor(theme.tokens.accent if self.isEnabled() else theme.tokens.disabled)
        accent.setAlphaF(1.0 - 0.28 * self._press_progress)
        super()._draw_content(painter, rect, accent)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus() and self.isEnabled():
            painter = QtGui.QPainter(self)
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.tokens.accent), 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 3, 3)


class DropArea(QtWidgets.QFrame):
    """Select local paths without copying, moving, uploading or reading contents.

    Browsing and drops validate asynchronously. ``accept_paths`` is a synchronous
    integration entry point. Folders are returned as paths without recursion.
    Selection and rejection signals are always delivered on the GUI thread.
    """

    pathsSelected = Signal(list)
    filesSelected = Signal(list)
    folderSelected = Signal(str)
    selectionChanged = Signal(list)
    pathsRejected = Signal(list)
    busyChanged = Signal(bool)
    errorOccurred = Signal(str)

    def acceleration_backend(self) -> str:
        return selection.backend_name()

    def __init__(
        self, parent=None, *, extensions=(), allow_files=True, allow_folders=True, multiple=True
    ):
        normalized = selection.normalize_extensions(extensions)
        if not allow_files and not allow_folders:
            raise ValueError("at least one path kind must be allowed")
        super().__init__(parent)
        self._extensions = normalized
        self._allow_files, self._allow_folders, self._multiple = (
            bool(allow_files),
            bool(allow_folders),
            bool(multiple),
        )
        self._selected = []
        self._request = 0
        self._busy = False
        self._drag_active = False
        self._drag_progress = 0.0
        self._custom_text = None
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_drag_progress)
        self.setAcceptDrops(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self.setMinimumSize(210, 144)
        self.setAccessibleName("拖放文件区域" if allow_files else "拖放文件夹区域")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(5)
        layout.addStretch()
        self.hint_label = QtWidgets.QLabel(self)
        self.hint_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.hint_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setMinimumWidth(0)
        layout.addWidget(self.hint_label)
        self.or_label = QtWidgets.QLabel("或者", self)
        self.or_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.or_label)
        links = QtWidgets.QHBoxLayout()
        links.setSpacing(6)
        links.addStretch()
        self.browse_files_button = _BrowseButton("浏览文件", self)
        self.browse_files_button.setVisible(self._allow_files)
        self.browse_files_button.clicked.connect(self.browse_files)
        links.addWidget(self.browse_files_button)
        self.separator_label = QtWidgets.QLabel("/", self)
        self.separator_label.setVisible(self._allow_files and self._allow_folders)
        links.addWidget(self.separator_label)
        self.browse_folder_button = _BrowseButton("浏览文件夹", self)
        self.browse_folder_button.setVisible(self._allow_folders)
        self.browse_folder_button.clicked.connect(self.browse_folder)
        links.addWidget(self.browse_folder_button)
        links.addStretch()
        layout.addLayout(links)
        layout.addStretch()
        self._refresh_theme()
        theme.subscribe(self, self._refresh_theme)

    def sizeHint(self):
        return QtCore.QSize(300 if self._allow_files else 246, 144)

    def file_extensions(self) -> tuple[str, ...]:
        return self._extensions

    def set_file_extensions(self, extensions) -> None:
        normalized = selection.normalize_extensions(extensions)
        self._cancel_pending()
        self._extensions = normalized
        self._refresh_hint()

    def setFileExtensions(self, extensions) -> None:
        self.set_file_extensions(extensions)

    def fileExtensions(self) -> tuple[str, ...]:
        return self.file_extensions()

    def is_multiple(self) -> bool:
        return self._multiple

    def set_multiple(self, multiple: bool) -> None:
        self._cancel_pending()
        self._multiple = bool(multiple)

    def selected_paths(self) -> list[str]:
        return list(self._selected)

    def text(self) -> str:
        return self.hint_label.text() if not self._busy else self._default_text()

    def set_text(self, text: str | None) -> None:
        self._custom_text = None if text is None else str(text)
        self._refresh_hint()

    def setText(self, text: str | None) -> None:
        self.set_text(text)

    def is_busy(self) -> bool:
        return self._busy

    def clear(self) -> None:
        self._cancel_pending()
        if self._selected:
            self._selected = []
            self.selectionChanged.emit([])

    def _options(self):
        return dict(
            allow_files=self._allow_files,
            allow_folders=self._allow_folders,
            multiple=self._multiple,
            case_sensitive=os.name != "nt",
        )

    def accept_paths(self, paths) -> list[str]:
        """Synchronously validate one selection; invalid items preserve prior selection."""
        values = _paths(paths)
        self._cancel_pending()
        accepted, rejected = selection.filter_paths(
            _candidates(values), self._extensions, **self._options()
        )
        self._commit(accepted, rejected)
        return [path for path, _kind in accepted]

    def submit_paths(self, paths) -> None:
        """Validate paths in a worker, replacing any older pending request."""
        values = _paths(paths)
        selection.backend_name()
        self._request += 1
        if not values:
            self._set_busy(False)
            return
        self._set_drag_active(False)
        self._set_busy(True)
        job = _SelectionJob(self._request, values, self._extensions, self._options())
        job.signals.finished.connect(self._on_finished, QtCore.Qt.ConnectionType.QueuedConnection)
        QtCore.QThreadPool.globalInstance().start(job)

    @Slot(int, object, object)
    def _on_finished(self, request, result, error):
        if request != self._request:
            return
        self._set_busy(False)
        if error is not None:
            self.errorOccurred.emit(error)
        else:
            self._commit(*result)

    def _commit(self, accepted, rejected):
        if accepted:
            paths = [path for path, _kind in accepted]
            if paths != self._selected:
                self._selected = paths
                self.selectionChanged.emit(list(paths))
            self.pathsSelected.emit(list(paths))
            files = [path for path, kind in accepted if kind == 1]
            if files:
                self.filesSelected.emit(files)
            for path, kind in accepted:
                if kind == 2:
                    self.folderSelected.emit(path)
        if rejected:
            self.pathsRejected.emit(list(rejected))

    def browse_files(self) -> None:
        if not self.isEnabled() or self._busy or not self._allow_files:
            return
        pattern = " ".join("*" + extension for extension in self._extensions) or "*"
        file_filter = f"支持的文件 ({pattern})"
        if self._multiple:
            paths, _selected = QtWidgets.QFileDialog.getOpenFileNames(
                self, "选择文件", "", file_filter
            )
        else:
            path, _selected = QtWidgets.QFileDialog.getOpenFileName(
                self, "选择文件", "", file_filter
            )
            paths = [path] if path else []
        if paths:
            self.submit_paths(paths)

    def browse_folder(self) -> None:
        if not self.isEnabled() or self._busy or not self._allow_folders:
            return
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self.submit_paths([path])

    def _default_text(self):
        if self._custom_text is not None:
            return self._custom_text
        if not self._allow_files:
            return "拖拽任意一个文件夹到框内"
        types = "、".join(extension.lstrip(".").upper() for extension in self._extensions)
        return f"拖拽任意 {types} 文件到框内" if types else "拖拽任意文件到框内"

    def _refresh_hint(self):
        self.hint_label.setText("正在检查所选路径…" if self._busy else self._default_text())

    def _set_busy(self, value):
        changed = bool(value) != self._busy
        self._busy = bool(value)
        self.browse_files_button.setEnabled(not self._busy)
        self.browse_folder_button.setEnabled(not self._busy)
        self.setAcceptDrops(not self._busy and self.isEnabled())
        self._refresh_hint()
        if changed:
            self.busyChanged.emit(self._busy)
        self.update()

    def _cancel_pending(self):
        self._request += 1
        self._set_busy(False)

    def _set_drag_progress(self, value):
        self._drag_progress = float(value)
        self.update()

    def _set_drag_active(self, active):
        self._drag_active = bool(active)
        self._animation.stop()
        self._animation.setStartValue(self._drag_progress)
        self._animation.setEndValue(1.0 if active else 0.0)
        self._animation.start()

    def _can_drop(self, event):
        urls = event.mimeData().urls()
        return (
            self.isEnabled()
            and not self._busy
            and bool(urls)
            and all(url.isLocalFile() for url in urls)
            and bool(event.possibleActions() & QtCore.Qt.DropAction.CopyAction)
        )

    def dragEnterEvent(self, event):
        if self._can_drop(event):
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._can_drop(event):
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()
            self._set_drag_active(False)

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event):
        self._set_drag_active(False)
        if not self._can_drop(event):
            event.ignore()
            return
        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()
        self.submit_paths([url.toLocalFile() for url in event.mimeData().urls()])

    def keyPressEvent(self, event):
        if event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Space,
        ):
            self.browse_files() if self._allow_files else self.browse_folder()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self._cancel_pending()
        self._animation.stop()
        self._drag_active, self._drag_progress = False, 0.0
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.EnabledChange and hasattr(self, "_busy"):
            if not self.isEnabled():
                self._cancel_pending()
                self._animation.stop()
                self._drag_active, self._drag_progress = False, 0.0
            self.setAcceptDrops(self.isEnabled() and not self._busy)
            self._refresh_theme()
        super().changeEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def _refresh_theme(self):
        self.setFont(ui_font(theme.tokens.font_size, self.font()))
        color = theme.tokens.text if self.isEnabled() else theme.tokens.disabled
        for label in (self.hint_label, self.or_label, self.separator_label):
            label.setFont(ui_font(theme.tokens.font_size, label.font()))
            label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        self._refresh_hint()
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        accent = QtGui.QColor(theme.tokens.accent)
        idle = QtGui.QColor("#96999f" if theme.mode.value == "light" else "#858b98")
        amount = self._drag_progress if self.isEnabled() else 0.0
        border = QtGui.QColor.fromRgbF(
            *(a + (b - a) * amount for a, b in zip(idle.getRgbF(), accent.getRgbF()))
        )
        if not self.isEnabled():
            border.setAlpha(105)
        pen = QtGui.QPen(border, 1.5)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        fill = QtGui.QColor(accent)
        fill.setAlpha(round((14 if theme.mode.value == "light" else 23) * amount))
        painter.setBrush(fill)
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        if self.hasFocus() and self.isEnabled():
            painter.setPen(QtGui.QPen(accent, 1))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 2, 2)


class FileDropWidget(DropArea):
    """A multi-file area with file and folder browsing; image suffixes by default."""

    def __init__(
        self, parent=None, *, extensions=(".jpg", ".png", ".gif"), multiple=True, allow_folders=True
    ):
        super().__init__(
            parent,
            extensions=extensions,
            allow_files=True,
            allow_folders=allow_folders,
            multiple=multiple,
        )


class FolderDropWidget(DropArea):
    """A single-folder area; file drops are rejected and no directory is scanned."""

    def __init__(self, parent=None, *, multiple=False):
        super().__init__(parent, allow_files=False, allow_folders=True, multiple=multiple)
