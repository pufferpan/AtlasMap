import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app.parallel_export_windows import (ParallelExportWindows, tile_rects,
    INTRO_MS, SPLIT_MS, SPLIT_HOLD_MS, SPLIT_STAGGER_MS)
from app.export_window import SHRINK_MS
from app.ue_page import UePage
from app.main_window import _JobBridge
from core.parallel_export import merge_blender, owns, write
from core.ue_pipeline import Pipeline, Step


class ProcessTests(unittest.TestCase):
    def test_workers_really_overlap_and_keep_their_logs_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'barrier.py'
            script.write_text("import pathlib,sys,time\nroot=pathlib.Path(sys.argv[1]);i=sys.argv[2]\n"
                "(root/i).write_text('started')\ndeadline=time.time()+5\n"
                "while not (root/str(1-int(i))).exists():\n"
                " if time.time()>deadline: raise RuntimeError('workers ran serially')\n time.sleep(.01)\n"
                "print('LOG_WORKER_'+i,flush=True)\n", encoding='utf-8')
            lines = []
            jobs = [Step(str(i), [sys.executable, str(script), directory, str(i)]) for i in range(2)]
            pipeline = Pipeline([Step('parallel', [], parallel_factory=lambda: jobs)], on_line=lines.append)
            pipeline._run()
            self.assertEqual(pipeline.code, 0)
            routed = [json.loads(line.split(' ', 1)[1]) for line in lines if line.startswith('@ATLASMAP_PARALLEL ')]
            for i in range(2):
                self.assertTrue(any(r['worker'] == i and r['text'] == 'LOG_WORKER_'+str(i) for r in routed))

    def test_failure_cancels_siblings_and_never_runs_merge(self):
        merged = []
        jobs = [Step('fail', [sys.executable, '-c', 'import time;time.sleep(.3);raise SystemExit(7)']),
                Step('long', [sys.executable, '-c', 'import time;time.sleep(30)'])]
        pipeline = Pipeline([Step('parallel', [], parallel_factory=lambda: jobs),
                             Step('merge', [], action=lambda pipe: merged.append(True))])
        started = time.monotonic()
        pipeline.start()
        pipeline._thread.join(10)
        if pipeline.running:
            pipeline.stop()
            pipeline._thread.join(5)
        self.assertFalse(pipeline.running)
        self.assertNotEqual(pipeline.code, 0)
        self.assertEqual(merged, [])
        self.assertLess(time.monotonic()-started, 10)

    def test_stop_cancels_the_entire_group(self):
        pipeline = Pipeline([Step('parallel', [], parallel_factory=lambda: [
            Step(str(i), [sys.executable, '-c', 'import time;time.sleep(30)']) for i in range(2)])])
        pipeline.start()
        try:
            deadline = time.monotonic()+4
            while time.monotonic() < deadline:
                with pipeline._children_lock:
                    ready = len(pipeline._children) == 2 and all(c._proc for c in pipeline._children)
                if ready:
                    break
                time.sleep(.01)
            self.assertTrue(ready)
        finally:
            pipeline.stop()
            pipeline._thread.join(6)
        self.assertEqual(pipeline.code, -2)
        self.assertFalse(pipeline.running)


class MergeTests(unittest.TestCase):
    def fixture(self, directory):
        roots = [Path(directory)/str(i) for i in range(2)]
        materials = [{'id':'M_'+str(i),'nodes':[]} for i in range(6)]
        meshes = [{'id':'SM_'+str(i),'fbx':f'meshes/SM_{i}.fbx'} for i in range(6)]
        for i, root in enumerate(roots):
            data = {'source_blend':'scene.blend','objects':[{'id':'scene_object'}], 'meshes':meshes,
                    'materials':[m for m in materials if owns(m['id'], i, 2)],'images':[],
                    'counts':{'objects':1,'mesh_assets':6},
                    'parallel':{'run_id':'current','index':i,'count':2,'all_material_ids':[m['id'] for m in materials]}}
            write(root/'manifest.json',data)
            write(root/'parallel_result.json',{'complete':True,'run_id':'current',
                'materials':[m['id'] for m in data['materials']],
                'meshes':[m['id'] for m in meshes if owns(m['id'], i, 2)]})
            (root/'meshes').mkdir()
            for mesh in meshes:
                if owns(mesh['id'],i,2):
                    (root/mesh['fbx']).write_bytes(b'x'*160+bytes.fromhex('f85a8c6adef5d97eece90ce3758f290b'))
        return roots

    def test_complete_merge_keeps_full_scene_and_every_owned_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.fixture(directory)
            destination = Path(directory)/'merged'
            merge_blender(roots, destination, 'current', Pipeline([]))
            manifest=json.loads((destination/'manifest.json').read_text())
            self.assertEqual(len(manifest['materials']),6)
            self.assertEqual(len(list((destination/'meshes').glob('*.fbx'))),6)
            self.assertEqual(manifest['objects'],[{'id':'scene_object'}])

    def test_stale_failed_missing_and_mismatched_shards_never_publish(self):
        for failure in ('stale','failed','missing','scene','path'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                roots=self.fixture(directory)
                destination=Path(directory)/'merged'
                write(destination/'manifest.json',{'previous':True})
                data=json.loads((roots[0]/'manifest.json').read_text())
                report=json.loads((roots[0]/'parallel_result.json').read_text())
                if failure=='stale':report['run_id']='old'
                if failure=='failed':report['complete']=False
                if failure=='missing':report['meshes']=[]
                if failure=='scene':data['objects']=[]
                if failure=='path':
                    owned_mesh=next(m for m in data['meshes'] if owns(m['id'],0,2))
                    owned_mesh['fbx']='../outside.fbx'
                write(roots[0]/'manifest.json',data)
                write(roots[0]/'parallel_result.json',report)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    merge_blender(roots,destination,'current',Pipeline([]))
                self.assertEqual(json.loads((destination/'manifest.json').read_text()),{'previous':True})


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_tiles_are_inside_the_screen_and_do_not_overlap(self):
        for area,count in ((QRect(-1920,0,1920,1040),8),(QRect(0,0,640,480),2),(QRect(0,0,1280,720),6)):
            rectangles=tile_rects(area,count)
            self.assertEqual(len(rectangles),count)
            for i,rect in enumerate(rectangles):
                self.assertTrue(area.contains(rect))
                self.assertTrue(all(not rect.intersects(other) for other in rectangles[i+1:]))

    def test_one_window_splits_into_live_worker_windows_without_losing_progress(self):
        group=ParallelExportWindows(None,2)
        try:
            area=self.app.primaryScreen().availableGeometry()
            group.begin('split',start_rect=area.adjusted(10,10,-10,-10))
            self.assertTrue(group.windows[0].isVisible())
            self.assertTrue(group.windows[1].isHidden())
            group.feed('@ATLASMAP_PARALLEL '+json.dumps({'worker':1,'stage':'UE 2/2','text':'LOG_BEFORE_SPLIT'}))
            group.set_fraction(.35)
            QTest.qWait(INTRO_MS+SPLIT_HOLD_MS+SPLIT_STAGGER_MS+SPLIT_MS//3)
            self.assertTrue(all(w.isVisible() and w._transitioning for w in group.windows))
            moving=[w.surfaceRect.translated(w.geometry().topLeft()) for w in group.windows]
            for rect,target in zip(moving,group._targets):
                self.assertNotEqual(rect,group._split_origin)
                self.assertNotEqual(rect,target)
            QTest.qWait(SPLIT_MS)
            self.assertEqual(group._phase,'ready')
            self.assertEqual([w.geometry() for w in group.windows],group._targets)
            self.assertEqual(group.windows[0]._fraction,.35)
            self.assertIsNone(group.windows[1]._fraction)
            group.windows[1]._flush_log(True)
            self.assertIn('LOG_BEFORE_SPLIT',group.windows[1].log_view.toPlainText())
        finally:
            group.finish(0)
            group.close()

    def test_closing_the_origin_cancels_later_reveals_and_early_finish_keeps_its_result(self):
        group=ParallelExportWindows(None,2)
        stopped=[]
        group.stop_requested.connect(lambda:stopped.append(True))
        group.begin('close')
        group.windows[0].close()
        QTest.qWait(SPLIT_HOLD_MS+SPLIT_STAGGER_MS+50)
        self.assertTrue(all(w.isHidden() for w in group.windows))
        self.assertEqual(stopped,[True])
        finished=ParallelExportWindows(None,2)
        try:
            finished.begin('fast result')
            finished.finish(7)
            # Include the mother-window intro and wait for the actual final
            # animation frame before inspecting controls hidden by snapshots.
            for _ in range(60):
                if finished._phase=='ready':break
                QTest.qWait(50)
            self.assertTrue(all(w.isVisible() and w._done and not w._ok for w in finished.windows))
            self.assertTrue(all(w.btn_stop.isHidden() and w.btn_close.isVisible() for w in finished.windows))
        finally:finished.close()

    def test_logs_route_to_their_worker_and_stop_is_shared(self):
        group=ParallelExportWindows(None,2)
        stopped=[]
        group.stop_requested.connect(lambda:stopped.append(True))
        try:
            group.begin('test')
            group.feed('@ATLASMAP_PARALLEL '+json.dumps({'worker':1,'stage':'UE 2/2','text':'only_second'}))
            group.feed('shared_phase')
            for window in group.windows:window._flush_log(True)
            self.assertNotIn('only_second',group.windows[0].log_view.toPlainText())
            self.assertIn('only_second',group.windows[1].log_view.toPlainText())
            self.assertIn('shared_phase',group.windows[0].log_view.toPlainText())
            self.assertNotIn('shared_phase',group.windows[1].log_view.toPlainText())
            group.windows[1].btn_stop.click()
            self.assertEqual(stopped,[True])
            self.assertTrue(all(not w.btn_stop.isEnabled() for w in group.windows))
        finally:group.close()
        self.assertEqual(stopped,[True])

    def test_opt_in_warning_and_preferences_are_independent(self):
        saved={'ue_map':'CollectionRoom'}
        with patch('core.exporter.load_settings',side_effect=lambda:dict(saved)), \
             patch('core.exporter.save_settings',side_effect=lambda data:saved.update(data)):
            shell=Mock()
            page=UePage(shell,shell)
            try:
                self.assertFalse(page.chk_parallel.isChecked())
                workers=page.sp_workers.value()
                with patch('app.ue_page.F.confirm',return_value=False) as warning:
                    page.chk_parallel.setChecked(True)
                    self.assertFalse(page.chk_parallel.isChecked())
                    self.assertIn('资源占用也会暴涨',warning.call_args.args[2])
                with patch('app.ue_page.F.confirm',return_value=True), \
                     patch('app.performance_effect.show_performance_effect') as effect:
                    page.chk_parallel.setChecked(True)
                    effect.assert_called_once_with(shell,page.sp_parallel.value())
                self.assertTrue(saved['parallel_export'])
                shell.set_parallel_theme.assert_called_with(True)
                self.assertEqual(page.sp_workers.value(),workers)
                self.assertEqual(page._paths()['parallel_export'],'1')
                page.chk_parallel.setChecked(False)
                self.assertFalse(saved['parallel_export'])
            finally:page.deleteLater()

    def test_each_worker_has_its_own_assignment_progress_and_log(self):
        group=ParallelExportWindows(None,2)
        try:
            group.begin('independent')
            group.set_stage('Blender 分块',parallel=True)
            def event(worker,**details):
                group.feed('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=worker,stage=f'Blender {worker+1}/2',**details)))
            for worker,total,done,asset in ((0,32,8,'SM_FIRST'),(1,17,10,'SM_SECOND')):
                event(worker,event='process',pid=1200+worker,text=f'PID={1200+worker}')
                event(worker,event='assigned',work={'meshes':total},text=f'本块模型 {total}')
                event(worker,event='progress',done=done,total=total,unit='模型',current=asset,text=asset)
            group.set_fraction(.8)
            group.feed('SHARED_ONLY_ON_COORDINATOR')
            group.feed('@ATLASMAP_PARALLEL '+json.dumps({'worker':1,'stage':'Blender 2/2',
                'text':'[2026.11.02][0]LogInit: COMMON_ENGINE_STARTUP'}))
            for window in group.windows:window._flush_log(True)
            self.assertAlmostEqual(group.windows[0]._fraction,8/32)
            self.assertAlmostEqual(group.windows[1]._fraction,10/17)
            self.assertIn('PID 1201',group.windows[1]._subtitle)
            self.assertIn('模型 17',group.windows[1]._subtitle)
            self.assertNotIn('SM_FIRST',group.windows[1].log_view.toPlainText())
            self.assertNotIn('SM_SECOND',group.windows[0].log_view.toPlainText())
            self.assertNotIn('SHARED_ONLY_ON_COORDINATOR',group.windows[1].log_view.toPlainText())
            self.assertNotIn('COMMON_ENGINE_STARTUP',group.windows[1].log_view.toPlainText())
        finally:
            group.finish(0)
            group.close()

    def test_log_batches_preserve_progress_order_and_finish_after_the_last_line(self):
        delivered=[]
        batches=[]
        def batch(lines):
            batches.append(len(lines))
            delivered.extend(lines)
        bridge=_JobBridge(delivered.append,lambda code:delivered.append(('done',code)),
                          lambda *values:delivered.append(('progress',values)),on_lines=batch)
        def produce():
            for i in range(2000):
                bridge.enqueue(str(i))
                if i==999:bridge.enqueue_progress(1,2,'half')
            bridge.done.emit(0)
        import threading
        thread=threading.Thread(target=produce)
        thread.start();thread.join()
        deadline=time.monotonic()+5
        while (not delivered or delivered[-1]!=('done',0)) and time.monotonic()<deadline:
            QTest.qWait(10)
        self.assertEqual(delivered[:1000],[str(i) for i in range(1000)])
        self.assertEqual(delivered[1000],('progress',(1,2,'half')))
        self.assertEqual(delivered[1001:-1],[str(i) for i in range(1000,2000)])
        self.assertEqual(delivered[-1],('done',0))
        self.assertLess(len(batches),25)
