"""Small, license-gated failure UI smoke check; never starts a real export."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys


def run(output):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from app.export_window import ExportWindow
    from app.pages import JobPage
    from app.version import stamp
    from core.export_failure import FailureTracker
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
    tracker=FailureTracker('10/17 多 Blender 输出分块模型')
    for message in ("write('manifest.json', manifest)",'MemoryError'):
        tracker.observe('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=1,stage='模型输出 2/3',event='line',text=message)))
    report=tracker.finish(-6,'完整日志可通过下方按钮导出')
    window=ExportWindow();window.setAttribute(Qt.WA_DontShowOnScreen)
    window.begin('Brakkesh Brakkesh_Long3')
    window.feed('MemoryError');window.finish(-6,failure=report)
    window._transitioning=False;window.surfaceRect=window.rect();window._surface.show();window.show();app.processEvents()
    assert type(window.failure_notice) is W.InfoBar
    assert window.failure_notice.failure.kind=='memory'
    assert '模型输出 2/3' in window.failure_notice.detail()
    window.failure_notice.action_button.click()
    assert 'MemoryError' in app.clipboard().text()
    window.grab().save(str(out/'export-failure.png'))
    host=SimpleNamespace(export_full_log=lambda:None,stop_job=lambda:None)
    page=JobPage(host);page.setAttribute(Qt.WA_DontShowOnScreen);page.resize(1100,720)
    page.begin('Brakkesh Brakkesh_Long3',[]);page.finish(-6,report)
    page.show();app.processEvents();page.grab().save(str(out/'task-failure.png'))
    assert type(page.failure_notice) is W.InfoBar and 'MemoryError' in page.failure_notice.detail()
    result=dict(version=stamp(),frozen=bool(getattr(sys,'frozen',False)),native_controls=True,
                memory_error_visible=True,failed_chunk=2,copy_reason=True,task_page_reason=True)
    (out/'failure-ui-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    page.close();window.close()
    return 0
