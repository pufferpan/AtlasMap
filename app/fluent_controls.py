"""Configure actual FluentPy instances; no replacement controls or widget subclasses."""
from PySide6.QtCore import QObject,QEvent,Qt,QTimer
from PySide6.QtWidgets import QApplication,QScrollArea,QFrame,QWidget
from fluentpy import widgets as W


def text_menu(widget, extra=()):
    widget.setContextMenuPolicy(Qt.CustomContextMenu)
    def show(position):
        previous=getattr(widget,'_fluent_menu',None)
        if previous is not None:
            previous.dismiss(immediate=True)
            previous.deleteLater()
        menu=W.ActionMenu(widget.window())
        widget._fluent_menu=menu
        multiline=hasattr(widget,'toPlainText')
        text=widget.toPlainText() if multiline else widget.text()
        selected=widget.textCursor().hasSelection() if multiline else bool(widget.selectedText())
        writable=not widget.isReadOnly()
        if writable:
            document=widget.document() if multiline else widget
            menu.add_action('撤销',callback=widget.undo,enabled=document.isUndoAvailable())
            menu.add_action('重做',callback=widget.redo,enabled=document.isRedoAvailable())
            menu.add_separator()
            menu.add_action('剪切',callback=widget.cut,enabled=selected)
        menu.add_action('复制',callback=widget.copy,enabled=selected)
        menu.add_action('复制全部',callback=lambda:QApplication.clipboard().setText(text),enabled=bool(text))
        if writable:
            mime=QApplication.clipboard().mimeData()
            menu.add_action('粘贴',callback=widget.paste,enabled=bool(mime and mime.hasText()))
            menu.add_action('清空内容',callback=widget.clear,enabled=bool(text))
        menu.add_separator()
        menu.add_action('全选',callback=widget.selectAll,enabled=bool(text))
        for label,callback in extra:
            menu.add_separator()
            menu.add_action(label,callback=callback)
        if multiline:position=widget.viewport().mapTo(widget,position)
        menu.popup_at(widget,position)
    widget.customContextMenuRequested.connect(show)



def LineEdit(text='',parent=None,**kwargs):
    if isinstance(text,QWidget):parent,text=text,''
    widget=W.LineEdit(parent=parent,**kwargs)
    widget.setText(text)
    text_menu(widget)
    return widget


def TextEdit(text='',parent=None):
    if isinstance(text,QWidget):parent,text=text,''
    widget=W.TextEdit(parent)
    widget.setAcceptRichText(False);widget.setPlainText(text)
    text_menu(widget)
    return widget


def CodeEditor(text='',parent=None,*,language='plain'):
    if isinstance(text,QWidget):parent,text=text,''
    widget=W.CodeEdit(parent,language=language)
    widget.set_code(text)
    widget.task_context_actions=[]
    text_menu(widget.text_edit,widget.task_context_actions)
    return widget


def add_context_action(editor,label,callback):
    editor.task_context_actions.append((label,callback))


def EditableComboBox(parent=None):
    widget=W.EditableComboBox(parent)
    text_menu(widget.lineEdit())
    # Application map names are editable, but typing must not change the catalog.
    widget.lineEdit().returnPressed.disconnect(widget._commit_text)
    widget.lineEdit().returnPressed.connect(lambda:widget.setEditText(widget.currentText()))
    return widget


def WarningNotice(text='',parent=None):
    bar=W.InfoBar('请留意',text,parent,tone='warning',closable=False,orientation='vertical')
    # Embedded bars don't animate opacity. Qt nested effects conflict with dialog shadows.
    if bar.graphicsEffect() is not None:bar.graphicsEffect().setEnabled(False)
    bar.setVisible(bool(text))
    return bar


def set_warning(bar,text):
    if bar.detail()!=text:bar.set_detail(text)
    bar.setVisible(bool(text))


def Dialog(title='',content='',parent=None):
    dialog=W.FramelessDialog(title,content,parent)
    dialog.setWindowTitle(title)
    return dialog


def ChoiceDialog(title,content,parent=None,*,yes='确认',no='取消',warning=''):
    dialog=Dialog(title,content,parent)
    dialog.setYesButtonText(yes);dialog.setCancelButtonText(no)
    dialog.yes_button.setAutoDefault(False);dialog.yes_button.setDefault(False)
    dialog.cancel_button.setAutoDefault(False);dialog.cancel_button.setDefault(True)
    if warning:dialog.add_content_widget(WarningNotice(warning,dialog))
    return dialog


def set_details(dialog,text):
    details=CodeEditor(text,dialog)
    details.setReadOnly(True);details.setFixedHeight(180);details.hide()
    button=W.Button('查看详细信息',dialog)
    button.setCheckable(True)
    def toggle(checked):
        details.setVisible(checked)
        button.setText('收起详细信息' if checked else '查看详细信息')
        dialog.adjustSize()
    button.toggled.connect(toggle)
    dialog.add_content_widget(button);dialog.add_content_widget(details)
    dialog.details_editor=details


def message(parent,title,content,*,warning=False):
    dialog=Dialog(title,'' if warning else content,parent)
    dialog.setYesButtonText('知道了');dialog.cancel_button.hide()
    if warning:dialog.add_content_widget(WarningNotice(content,dialog))
    dialog.exec()


def confirm(parent,title,content):
    dialog=ChoiceDialog(title,'确认后将使用多个独立进程处理地图分块。',parent,
                        yes='开启性能模式',no='暂不开启',warning=content)
    return dialog.exec()==W.FramelessDialog.DialogCode.Accepted


class _SpinLayoutEvents(QObject):
    """Application event binding for the library's one-pixel Qt value-area bug."""
    def __init__(self,widget):
        super().__init__(widget)
        self.widget=widget
        widget.installEventFilter(self)

    def layout_value(self):
        widget=self.widget
        widget.lineEdit().setGeometry(10,2,max(1,widget.width()-48),max(1,widget.height()-4))

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Resize,QEvent.Show,QEvent.StyleChange):
            self.layout_value()
            QTimer.singleShot(0,self,self.layout_value)
        return False


def _spin(widget,width):
    widget.setMinimumWidth(width)
    widget.value_layout_events=_SpinLayoutEvents(widget)
    text_menu(widget.lineEdit())
    return widget


def SpinBox(parent=None):return _spin(W.SpinBox(parent),100)
def DoubleSpinBox(parent=None):return _spin(W.DoubleSpinBox(parent),110)


def scroll_area(parent=None):
    # FluentPy provides scroll bars, but has no scroll-area/container widget.
    widget=QScrollArea(parent)
    widget.setVerticalScrollBar(W.FluentScrollBar(Qt.Vertical,widget))
    widget.setHorizontalScrollBar(W.FluentScrollBar(Qt.Horizontal,widget))
    return widget
