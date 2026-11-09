"""Window-owned corner stacks shared by Toast and ProgressToast."""

import weakref

from ..qt import QtCore, QtWidgets


def _notification_rect(owner):
    """Return notification bounds in the owner's coordinates, below its chrome."""
    if isinstance(owner, QtWidgets.QMainWindow):
        layout = owner.layout()
        if layout is not None:
            layout.activate()
        content = owner.centralWidget()
        if content is not None:
            return QtCore.QRect(content.mapTo(owner, QtCore.QPoint()), content.size()).intersected(
                owner.rect()
            )
    return owner.rect()


class _ToastStack(QtCore.QObject):
    MARGIN = 18
    # Share only the empty shadow allowance: painted cards stay 19px apart.
    SHADOW_OVERLAP = 14

    def __init__(self, parent, placement):
        super().__init__(parent)
        self.placement = placement
        self._members = []
        self._laying_out = False

    @classmethod
    def for_toast(cls, toast, placement):
        owner = toast.parentWidget() or QtWidgets.QApplication.instance()
        key = (
            placement
            if toast.parentWidget() is not None
            else (toast.screen().name() if toast.screen() else "", placement)
        )
        if not hasattr(owner, "_fluentpy_toast_stacks"):
            owner._fluentpy_toast_stacks = {}
        if key not in owner._fluentpy_toast_stacks:
            owner._fluentpy_toast_stacks[key] = cls(owner, placement)
        return owner._fluentpy_toast_stacks[key]

    def members(self):
        result = []
        for reference in self._members:
            toast = reference()
            try:
                if toast is not None and toast._stack is self:
                    toast.width()
                    result.append(toast)
            except RuntimeError:
                pass
        self._members = [weakref.ref(toast) for toast in result]
        return result

    def add(self, toast):
        if toast._stack is self:
            return
        if toast._stack is not None:
            toast._stack.remove(toast)
        toast._stack = self
        self._members.append(weakref.ref(toast))
        toast.destroyed.connect(self._destroyed)
        self.reflow()

    def remove(self, toast):
        if toast._stack is not self:
            return
        toast._stack = None
        self._members = [reference for reference in self._members if reference() is not toast]
        try:
            toast.destroyed.disconnect(self._destroyed)
        except (RuntimeError, TypeError):
            pass
        self.reflow()

    def _destroyed(self):
        self.reflow()

    def reflow(self, *, animated=True):
        if self._laying_out:
            return
        self._laying_out = True
        try:
            items = self.members()
            if not items:
                return
            owner = self.parent()
            base = (
                _notification_rect(owner)
                if isinstance(owner, QtWidgets.QWidget)
                else items[-1]._base_rect
            )
            for toast in items:
                width = min(max(0, base.width()), toast.sizeHint().width())
                toast.resize(width, min(max(0, base.height()), toast.heightForWidth(width)))
                toast.layout().activate()
            available = max(1, base.height() - 2 * self.MARGIN)

            def needed():
                return (
                    sum(max(1, t.height() - self.SHADOW_OVERLAP) for t in items[:-1])
                    + items[-1].height()
                )

            while len(items) > 1 and needed() > available:
                oldest = items.pop(0)
                oldest._allow_close = True
                oldest.close()
                if oldest._stack is self:
                    self.remove(oldest)
            cursor = (
                base.bottom() + 1 - self.MARGIN
                if self.placement.startswith("bottom")
                else base.top() + self.MARGIN
            )
            for toast in reversed(items):
                x = (
                    (base.width() - toast.width()) // 2 + base.left()
                    if self.placement.endswith("center")
                    else base.right() + 1 - toast.width() - self.MARGIN
                    if self.placement.endswith("right")
                    else base.left() + self.MARGIN
                )
                y = cursor - toast.height() if self.placement.startswith("bottom") else cursor
                x = max(base.left(), min(x, base.right() + 1 - toast.width()))
                y = max(base.top(), min(y, base.bottom() + 1 - toast.height()))
                toast._base_rect = QtCore.QRect(base)
                toast._set_stack_target(
                    QtCore.QPoint(x, y), animated=animated and toast.isVisible()
                )
                step = max(1, toast.height() - self.SHADOW_OVERLAP)
                cursor += -step if self.placement.startswith("bottom") else step
        finally:
            self._laying_out = False
