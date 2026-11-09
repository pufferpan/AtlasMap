"""Native FluentPy failure notice with one-click diagnostic copying."""
from fluentpy import widgets as W
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLabel


def failure_notice(parent=None):
    bar=W.InfoBar('导出失败原因','',parent,tone='error',orientation='vertical',closable=False,
                  action_text='复制原因',action_callback=lambda:QApplication.clipboard().setText(bar.failure.text() if bar.failure else ''))
    bar.failure=None
    if bar.graphicsEffect() is not None:bar.graphicsEffect().setEnabled(False)
    for label in bar.findChildren(QLabel):label.setTextFormat(Qt.PlainText)
    bar.hide()
    return bar


def show_failure(bar,report,compact=False):
    bar.failure=report
    if report is not None:
        bar.set_title(report.title)
        text=report.text()
        if compact:
            text='\n'.join(text.splitlines()[:3])
            if report.evidence:text+='\n错误原文：'+report.evidence[:180]
        bar.set_detail(text)
    bar.setVisible(report is not None)
