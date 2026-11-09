"""Startup activation using exact native FluentPy controls."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QHBoxLayout
from app import fluent_api as F
from core import activation as licensing


def activation_dialog(machine, config, reason='', parent=None):
    dialog = F.Dialog('激活 AtlasMap', '首次使用需要激活。复制本机机器码，由软件提供者生成激活码后粘贴到下方。', parent)
    dialog.setAttribute(Qt.WA_QuitOnClose, False)
    dialog.setYesButtonText('激活并启动');dialog.setCancelButtonText('退出')
    dialog.add_content_widget(QLabel('本机机器码', dialog))
    row = QWidget(dialog);layout = QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
    machine_edit = F.LineEdit(machine,show_clear_button=False);machine_edit.setReadOnly(True)
    machine_edit.setFont(QFont('Consolas',10));machine_edit.setCursorPosition(0)
    machine_edit.setMinimumWidth(430);machine_edit.setToolTip('绑定当前 Windows 安装；重装系统后需重新激活。')
    copy = F.PushButton('复制机器码')
    copy.clicked.connect(lambda: (QApplication.clipboard().setText(machine), copy.setText('已复制')))
    layout.addWidget(machine_edit,1);layout.addWidget(copy)
    dialog.add_content_widget(row)
    website = F.PushButton('打开激活码生成网页（管理者）')
    website.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(config['issuer_url'])))
    dialog.add_content_widget(website)
    dialog.add_content_widget(QLabel('激活码', dialog))
    code = F.TextEdit();code.setPlaceholderText('粘贴完整的 DFMA1. 开头的激活码');code.setFixedHeight(108)
    dialog.add_content_widget(code)
    notice = F.WarningNotice(reason, dialog);dialog.add_content_widget(notice)
    tip = QLabel('激活后可离线使用，本机再次启动无需重复输入。', dialog);tip.setWordWrap(True)
    dialog.add_content_widget(tip)
    dialog.yes_button.clicked.disconnect()
    dialog.yes_button.setAutoDefault(False);dialog.yes_button.setDefault(False)
    def activate():
        try:
            licensing.save_license(code.toPlainText(), machine, licensing.unb64(config['public_key']))
        except (licensing.ActivationError, OSError) as exc:
            F.set_warning(notice, str(exc));dialog.adjustSize();code.setFocus();return
        dialog.accept()
    dialog.yes_button.clicked.connect(activate)
    code.textChanged.connect(lambda: dialog.yes_button.setEnabled(bool(code.toPlainText().strip())))
    dialog.yes_button.setEnabled(False)
    dialog.machine_edit=machine_edit;dialog.copy_button=copy;dialog.code_edit=code;dialog.notice=notice
    return dialog


def require_activation() -> bool:
    try:
        config=licensing.public_config();machine=licensing.machine_code()
        valid,reason=licensing.saved_license(machine,licensing.unb64(config['public_key']))
        if valid:return True
    except licensing.ActivationError as exc:
        F.message(None,'无法启动激活',str(exc),warning=True);return False
    dialog=activation_dialog(machine,config,reason)
    if dialog.exec()!=dialog.DialogCode.Accepted:return False
    return licensing.saved_license(machine,licensing.unb64(config['public_key']))[0]
