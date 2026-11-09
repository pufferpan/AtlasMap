import json
import errno
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from core.full_parallel_export import plan_levels, merge_source_states, full_parallel_steps
from core.parallel_export import write
from core.ue_pipeline import Step
from app.export_celebration import SUCCESS_MS
from app.parallel_export_windows import ParallelExportWindows, tile_rects
from app.performance_effect import show_performance_effect
from scripts.official.map_io import atomic_json,cached_blob,share_file
from core.ue_pipeline import Pipeline
from core.system_usage import ue_process_capacity
import sys


class ChunkTests(unittest.TestCase):
    def test_actual_workload_balances_geometry_instead_of_file_size(self):
        text=' 1000000 Game/Test/Lighting.umap\n 20 Game/Test/A.umap\n 10 Game/Test/B.umap\n'
        costs={'Game/Test/Lighting.umap':1,'Game/Test/A.umap':100,'Game/Test/B.umap':100}
        chunks=plan_levels(text,['Game/Test/'],[],2,costs)
        self.assertEqual(sorted(sum(costs[l] for l in c) for c in chunks),[100,101])
    def test_selection_is_complete_disjoint_stable_and_keeps_siblings(self):
        lines=['  9,000 Game/HD/Test/A_HD.umap','  20 Game/Base/Test/A.umap',
               '  8,000 Game/HD/Test/B.umap','  400 Game/HD/Test/C.umap',
               '  500 Game/HD/Test/X_Without.umap','  500 Other/Test/D.umap']
        result=plan_levels('\n'.join(lines),['Game/HD/Test/','Game/Base/Test/'],['_Without'],3)
        self.assertEqual(result,plan_levels('\n'.join(reversed(lines)),['Game/HD/Test/','Game/Base/Test/'],['_Without'],3))
        self.assertEqual(sum(map(len,result)),4)
        self.assertEqual(len(set(sum(result,[]))),4)
        self.assertTrue(any('Game/HD/Test/A_HD.umap' in c and 'Game/Base/Test/A.umap' in c for c in result))

    def test_all_expensive_phases_have_real_worker_factories(self):
        with tempfile.TemporaryDirectory() as directory:
            p=dict(root=directory+'/raw',transfer=directory+'/transfer',scripts=directory+'/scripts',
                project=directory+'/Test/Test.uproject',dest='/Game/Test',map='Test',exe='map-export.exe',config='config')
            serial=[Step(str(i),['tool','--exclude','Reflection'],env={}) for i in range(7)]
            steps=full_parallel_steps(p,serial,'current')
            factories=[s for s in steps if s.parallel_factory]
            self.assertEqual(len(factories),10)
            self.assertFalse(any(s.cmd and '-ExecutePythonScript=ue_run_headless.py' in s.cmd for s in steps))

    def test_conflicting_source_packages_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            roots=[Path(directory)/str(i) for i in range(2)]
            for i,root in enumerate(roots):
                write(root/'source-render/raw.json',[{'value':i}])
                write(root/'source-render/state-index.json',dict(complete=True,exporter={'sha256':'same'},
                    levels=[{'level':str(i)}],packages={'shared':'raw.json'},preservedAssets=[]))
            with self.assertRaisesRegex(ValueError,'不一致'):
                merge_source_states(roots,Path(directory)/'output','Test')


class CelebrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_all_real_windows_form_green_success_and_return_to_logs(self):
        group=ParallelExportWindows(None,3)
        try:
            group._targets=tile_rects(QRect(0,0,1400,900),3)
            group._phase='ready'
            for i,(w,r) in enumerate(zip(group.windows,group._targets)):
                w.begin('test',present=False);w.setGeometry(r);w.show();w.feed(f'UNIQUE_{i}')
            original=[QRect(w.geometry()) for w in group.windows]
            group.finish(0)
            self.assertEqual([w.geometry() for w in group.windows],original)
            self.assertEqual(group._success_targets,original)
            QTest.qWait(SUCCESS_MS+100)
            self.assertEqual(group._phase,'success')
            for i,(w,r) in enumerate(zip(group.windows,group._success_targets)):
                self.assertEqual(w.geometry(),r)
                self.assertEqual(w.visual_surface().geometry(),w.rect())
                self.assertIsNotNone(w._celebration)
                self.assertIn(f'UNIQUE_{i}',w.log_view.toPlainText())
            QTest.mouseClick(group.windows[1].visual_surface(),Qt.LeftButton)
            QTest.qWait(500)
            self.assertEqual(group._phase,'ready')
            self.assertTrue(all(w._celebration is None and w._surface.isVisible() for w in group.windows))
        finally:group.close()

    def test_failure_and_cancel_never_form_success(self):
        for code in (-2,3):
            group=ParallelExportWindows(None,2)
            try:
                group.begin('failure');group.finish(code)
                QTest.qWait(1100)
                self.assertFalse(group._success_pending)
                self.assertTrue(all(w._celebration is None and not w._ok for w in group.windows))
            finally:group.close()

    def test_fast_success_waits_for_the_split_and_close_cancels_it(self):
        group=ParallelExportWindows(None,2)
        try:
            group.begin('fast');group.finish(0)
            self.assertTrue(group._success_pending)
            QTest.qWait(2100)
            self.assertEqual(group._phase,'success')
            self.assertTrue(all(w._celebration is not None for w in group.windows))
        finally:group.close()
        group=ParallelExportWindows(None,2)
        group.begin('closed');group.finish(0);group.close()
        QTest.qWait(1000)
        self.assertFalse(group._success_pending)
        self.assertTrue(all(w.isHidden() for w in group.windows))

    def test_ignition_cleans_itself_up(self):
        parent=QWidget();parent.resize(1000,720);parent.show()
        try:
            effect=show_performance_effect(parent,4)
            QTest.qWait(100)
            self.assertTrue(effect.isVisible())
            self.assertGreater(effect.progress,0)
            QTest.qWait(3200)
            self.assertIsNone(parent._performance_effect)
        finally:parent.close()


class StorageTests(unittest.TestCase):
    def test_stop_returns_immediately_and_cancels_queued_jobs(self):
        jobs=[Step(str(i),[sys.executable,'-u','-c',"import time;print('STARTED',flush=True);time.sleep(30)"]) for i in range(4)]
        lines=[];pipe=Pipeline([Step('queued',[],parallel_factory=lambda:jobs,parallel_limit=lambda:1)],on_line=lines.append)
        pipe.start();deadline=time.monotonic()+5
        while not any('STARTED' in line and 'event' in line and 'text": "STARTED' in line for line in lines) and time.monotonic()<deadline:time.sleep(.01)
        import core.process_control as control
        original=control.subprocess.run
        entered=threading.Event();release=threading.Event()
        def slow(*args,**kwargs):
            entered.set();release.wait(2);return original(*args,**kwargs)
        try:
            with patch.object(control.subprocess,'run',side_effect=slow):
                started=time.monotonic();pipe.stop();elapsed=time.monotonic()-started
                self.assertLess(elapsed,.15)
                self.assertTrue(entered.wait(1))
                release.set();pipe._thread.join(8)
            self.assertFalse(pipe.running)
            self.assertEqual(pipe.code,-2)
            processes=[json.loads(line.split(' ',1)[1]) for line in lines if line.startswith('@ATLASMAP_PARALLEL ')]
            self.assertEqual(sum(event.get('event')=='process' for event in processes),1)
        finally:release.set();pipe.stop();pipe._thread.join(8)
    def test_unreal_parallelism_respects_ram_and_commit_headroom(self):
        gb=1024**3
        self.assertEqual(ue_process_capacity(8,dict(memory_available=10*gb,commit_available=14*gb)),2)
        self.assertEqual(ue_process_capacity(8,dict(memory_available=40*gb,commit_available=60*gb)),8)
        self.assertEqual(ue_process_capacity(8,dict(memory_available=2*gb,commit_available=4*gb)),1)

    def test_heavy_jobs_start_first_without_changing_worker_log_identity(self):
        lines=[]
        jobs=[Step(str(i),[sys.executable,'-c',f"print('JOB_{i}')"],priority=i) for i in range(3)]
        pipe=Pipeline([Step('limited',[],parallel_factory=lambda:jobs,parallel_limit=lambda:1)],on_line=lines.append)
        pipe._run()
        events=[json.loads(line.split(' ',1)[1]) for line in lines if line.startswith('@ATLASMAP_PARALLEL ')]
        done=[e for e in events if e.get('text','').startswith('JOB_')]
        self.assertEqual([e['worker'] for e in done],[2,1,0])
        self.assertTrue(all(e['text']=='JOB_'+str(e['worker']) for e in done))
        self.assertTrue(any(e['event']=='queued' and e['worker']==0 for e in events))
    def test_full_disk_keeps_the_original_manifest_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json';atomic_json(path,{'original':True})
            with patch.object(Path,'write_bytes',side_effect=OSError(errno.ENOSPC,'No space left on device')):
                with self.assertRaises(OSError):atomic_json(path,{'replacement':True})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'original':True})
            self.assertEqual(list(Path(directory).glob('*.partial')),[])

    def test_duplicate_images_share_bytes_and_survive_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cached_blob(root/'cache',root/'worker1/image.png',b'pixels','same')
            cached_blob(root/'cache',root/'worker2/image.png',b'pixels','same')
            self.assertTrue(os.path.samefile(root/'worker1/image.png',root/'worker2/image.png'))
            share_file(root/'worker1/image.png',root/'published/image.png')
            (root/'worker1/image.png').unlink();(root/'worker2/image.png').unlink()
            self.assertEqual((root/'published/image.png').read_bytes(),b'pixels')

    def test_native_disk_errors_stop_followup_work_with_a_clear_reason(self):
        lines=[];finished=[]
        pipeline=Pipeline([Step('native',[sys.executable,'-c',"print('OSError: [Errno 28] No space left on device')"]),
            Step('never',[],action=lambda p:finished.append(True))],on_line=lines.append)
        pipeline._run()
        self.assertEqual(pipeline.code,-5)
        self.assertEqual(finished,[])
        self.assertTrue(any('磁盘空间不足' in line for line in lines))

    def test_native_noise_stays_in_raw_log_but_progress_and_errors_reach_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'process.log'
            code="print('[2026.11.02-00.00.00:000][0]LogSavePackage: noisy')\nprint('[2026.11.02-00.00.00:000][0]LogPython: Error: real failure')\nprint('@ATLASMAP_TASK {\"event\":\"progress\",\"done\":1,\"total\":2}')"
            lines=[]
            pipe=Pipeline([Step('parallel',[],parallel_factory=lambda:[Step('worker',[sys.executable,'-c',code],log_path=str(path))])],on_line=lines.append)
            pipe._run()
            self.assertEqual(pipe.code,0)
            self.assertIn('noisy',path.read_text(encoding='utf-8'))
            events=[json.loads(line.split(' ',1)[1]) for line in lines if line.startswith('@ATLASMAP_PARALLEL ')]
            self.assertFalse(any(e.get('text','').startswith('[2026.11.02-00.00.00:000][0]LogSavePackage: noisy') for e in events))
            self.assertTrue(any(e.get('text','').startswith('[2026.11.02-00.00.00:000][0]LogPython: Error: real failure') for e in events))
            self.assertTrue(any('"event": "progress"' in line for line in lines))
