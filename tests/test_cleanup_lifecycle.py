"""Exercise QApplication.exec: nested test event loops mask Qt auto-quit."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CleanupLifecycleTests(unittest.TestCase):
    def test_hidden_main_window_keeps_running_until_background_cleanup_finishes(self):
        script=r'''
import json,tempfile,time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from app.main_window import MapViewerWindow
from core.ue_pipeline import Step
from core.export_residue import ExportResidue
app=QApplication([]);win=MapViewerWindow()
temporary=tempfile.TemporaryDirectory();root=Path(temporary.name)
file=root/'mesh.fbx';existing=root/'existing.fbx';existing.write_bytes(b'keep')
plan=ExportResidue([root]);original=plan.delete
def slow_delete(**kwargs):
    time.sleep(.5)
    return original(**kwargs)
plan.delete=slow_delete
def fail(pipe):
    file.write_bytes(b'partial');pipe.stop()
overlay=win.show_export_overlay('Cleanup lifecycle',str(root),parallel_count=2)
win.run_pipeline('Cleanup lifecycle',[Step('Cancel',[],action=fail)],on_done=overlay.finish,on_line=overlay.feed,residue=plan)
clicked=False;completed=False;started=time.monotonic()
def poll():
    global clicked,completed
    dialog=getattr(win,'_cleanup_dialog',None)
    if dialog is not None and not clicked:
        clicked=True;dialog.delete_residue_button.click()
    if clicked and not getattr(win,'_cleanup_pending',False):
        completed=not file.exists() and existing.read_bytes()==b'keep'
        timer.stop();overlay.close();win.close();app.quit()
    elif time.monotonic()-started>12:
        app.quit()
timer=QTimer();timer.timeout.connect(poll);timer.start(25)
app.exec()
print('CLEANUP_COMPLETE='+str(completed),flush=True)
temporary.cleanup()
raise SystemExit(0 if completed else 2)
'''
        with tempfile.TemporaryDirectory() as profile:
            result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
                env=dict(os.environ,LOCALAPPDATA=profile,QT_QPA_PLATFORM='offscreen'),
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('CLEANUP_COMPLETE=True',result.stdout)
