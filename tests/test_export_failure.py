import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.export_failure import FailureTracker,ExportFailure,latest_failure
from core.ue_pipeline import Pipeline,Step


class FailureTests(unittest.TestCase):
    def test_real_blender_memory_errors_and_cancelled_siblings(self):
        for error in ('MemoryError','Malloc returns null: len=1554772 in packFile, total 2969333956'):
            tracker=FailureTracker('map')
            for line in ('Traceback (most recent call last):','write(\'manifest.json\', manifest)',error):
                tracker.observe('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=1,stage='模型输出 2/3',event='line',text=line)))
            tracker.observe('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=2,stage='模型输出 3/3',event='finished',code=-2,text='分块 3 退出，状态 -2')))
            report=tracker.finish(1,'task.txt')
            self.assertEqual((report.kind,report.worker,report.stage),('memory',2,'模型输出 2/3'))
            self.assertIn(error,report.text());self.assertIn('task.txt',report.text())

    def test_disk_permission_missing_validation_dependency_and_unknown(self):
        cases=[('[Errno 28] No space left on device','disk'),('PermissionError: Access is denied','permission'),
               ('FileNotFoundError: missing.blend','missing'),('[输出校验失败] missing manifest','validation'),
               ('ImportError: DLL load failed','dependency'),('ValueError: custom shader mismatch','process')]
        for line,kind in cases:
            tracker=FailureTracker('test');tracker.observe(line)
            report=tracker.finish(1)
            self.assertEqual(report.kind,kind);self.assertIn(line,report.evidence)
            self.assertTrue(report.advice)

    def test_failed_process_produces_report_and_success_or_cancel_does_not(self):
        lines=[]
        pipeline=Pipeline([Step('模型输出 2/3',[sys.executable,'-c',"print('MemoryError');raise SystemExit(1)"])],on_line=lines.append)
        pipeline._run()
        self.assertEqual(pipeline.code,-6)
        self.assertEqual(pipeline.failure.kind,'memory')
        self.assertTrue(any(line.startswith('@ATLASMAP_FAILURE ') for line in lines))
        successful=Pipeline([Step('handled warning',[sys.executable,'-c',"print('MemoryError handled successfully')"])])
        successful._run();self.assertEqual(successful.code,0);self.assertIsNone(successful.failure)
        tracker=FailureTracker();tracker.observe('MemoryError')
        for code in (0,-2,130):self.assertIsNone(tracker.finish(code))

    def test_parallel_retry_keeps_true_failure_or_clears_recovered_failure(self):
        pipeline=Pipeline([Step('输出',[],parallel_factory=lambda:[
            Step('模型输出 1/2',[sys.executable,'-c',"print('MemoryError');raise SystemExit(1)"]),
            Step('模型输出 2/2',[sys.executable,'-c',"print('ok')"])],parallel_limit=lambda:1)])
        pipeline._run();self.assertEqual(pipeline.code,-6)
        self.assertEqual((pipeline.failure.kind,pipeline.failure.worker,pipeline.failure.stage),('memory',1,'模型输出 1/2'))
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'retried'
            script="from pathlib import Path;p=Path("+repr(str(marker))+");first=not p.exists();p.touch();print('MemoryError' if first else 'ok');raise SystemExit(1 if first else 0)"
            recovered=Pipeline([Step('retry',[],parallel_factory=lambda:[Step('worker',[sys.executable,'-c',script])])])
            recovered._run();self.assertEqual(recovered.code,0);self.assertIsNone(recovered.failure)

    def test_startup_and_validation_errors_have_a_visible_cause(self):
        missing=Pipeline([Step('start',['Z:\\definitely-absent\\blender.exe'])]);missing._run()
        self.assertIsNotNone(missing.failure)
        failed=Pipeline([Step('check',[sys.executable,'-c','pass'],validate=lambda _:(_ for _ in ()).throw(ValueError('bad manifest')))])
        failed._run();self.assertEqual(failed.failure.kind,'validation')
        self.assertIn('bad manifest',failed.failure.text())

    def test_error_after_ui_log_limit_is_not_lost(self):
        tracker=FailureTracker()
        for i in range(25000):tracker.observe('normal '+str(i))
        tracker.observe('MemoryError')
        report=tracker.finish(1)
        self.assertEqual(report.kind,'memory');self.assertEqual(len(tracker._tail),12)
        replay=FailureTracker();replay.observe(report.event())
        self.assertEqual(replay.finish(1).kind,'memory')

    def test_reopens_old_release_failure_but_not_success_or_running_task(self):
        from core.task_log import TaskLog
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'AtlasMap-old.txt'
            line='[12:42:59.000000] @ATLASMAP_PARALLEL '+json.dumps(dict(worker=1,stage='模型输出 2/3',text='MemoryError'))
            path.write_text(line+'\n[12:44:43.000000] [任务结束] 退出码 1 · 失败',encoding='utf-8')
            report=latest_failure(directory)
            self.assertEqual((report.kind,report.worker),('memory',2))
            log=TaskLog.open_existing(path)
            target=Path(directory)/'copied.txt';log.export(target)
            self.assertEqual(target.read_bytes(),path.read_bytes())
            self.assertFalse(log.append('not allowed'));log.close()
            path.write_text('[任务结束] 退出码 0 · 完成',encoding='utf-8')
            self.assertIsNone(latest_failure(directory))
            path.write_text('MemoryError but still running',encoding='utf-8')
            self.assertIsNone(latest_failure(directory))


class StreamJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'scripts/official/map_json.py'
        previous=list(sys.path);sys.path.insert(0,str(path.parent))
        cls.addClassCleanup(lambda:sys.path.__setitem__(slice(None),previous))
        spec=importlib.util.spec_from_file_location('tested_map_json',path)
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def test_large_unicode_manifest_does_not_materialize_json_string(self):
        data={'objects':[{'name':'中文物体','matrix':list(range(16))}]*5000,'materials':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json'
            with patch.object(self.module.json,'dumps',side_effect=MemoryError('full-string serialization forbidden')):
                self.module.write_json(path,data)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),data)

    def test_failed_save_preserves_existing_manifest_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json';path.write_text('{"previous":true}')
            with patch.object(self.module.json,'dump',side_effect=MemoryError('failed write')):
                with self.assertRaises(MemoryError):self.module.write_json(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'previous':True})
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
class FailureUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_native_failure_notice_copy_and_reset(self):
        from fluentpy import widgets as W
        from app.export_window import ExportWindow
        window=ExportWindow()
        self.addCleanup(window.close)
        window.begin('export')
        for i in range(4100):window.feed('noise '+str(i))
        window.feed('MemoryError');window.finish(1)
        self.app.processEvents()
        self.assertIs(type(window.failure_notice),W.InfoBar)
        self.assertEqual(window.failure_notice.failure.kind,'memory')
        self.assertFalse(window.failure_notice.isHidden())
        self.assertIn('原因',window.failure_notice.detail())
        window.failure_notice.action_button.click()
        self.assertIn('MemoryError',self.app.clipboard().text())
        self.assertTrue(window._surface.rect().contains(window.failure_notice.geometry()))
        window.begin('new');window.finish(0)
        self.assertIsNone(window.failure_notice.failure);self.assertTrue(window.failure_notice.isHidden())

    def test_current_task_capture_does_not_reuse_previous_job_failure(self):
        from types import SimpleNamespace
        from core.task_log import TaskLog
        from app.main_window import MapViewerWindow
        old=ExportFailure('disk','old disk failure','old','old')
        host=SimpleNamespace(job=SimpleNamespace(failure=old),job_page=SimpleNamespace(title=SimpleNamespace(text=lambda:'new task')))
        bridge=SimpleNamespace(enqueue=lambda _:None,done=SimpleNamespace(emit=lambda _:None))
        with tempfile.TemporaryDirectory() as directory:
            log=TaskLog(directory,'new task',[],'test')
            output,finish=MapViewerWindow._log_callbacks(host,log,bridge)
            for i in range(21000):output('normal '+str(i))
            output('FileNotFoundError: missing Blender');finish(-1)
            self.assertEqual(host._failure_report.kind,'missing')
            self.assertIn('missing Blender',log.path.read_text(encoding='utf-8-sig'))
            self.assertIn('[失败原因]',log.path.read_text(encoding='utf-8-sig'))


if __name__=='__main__':unittest.main()
