import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from core.export_storage import GB,MB,DiskGuard,check_space,prefer_project_storage,source_budget
from core.ue_pipeline import Pipeline,Step

class StorageTests(unittest.TestCase):
 def test_documents_drive_moves_before_it_falls_below_four_gb(self):
  if os.name!='nt':self.skipTest('Windows volumes')
  free=lambda path:12*GB if str(path).lower().startswith('c:') else 40*GB
  self.assertTrue(prefer_project_storage(r'C:/Users/Other/Documents/export',r'E:/Project',free))
  self.assertFalse(prefer_project_storage(r'E:/export',r'E:/Project',free))
 def test_larger_maps_reserve_more_space_before_native_export(self):
  small=source_budget([dict(meshes=2,instances=10)])
  large=source_budget([dict(meshes=2000,instances=15000)]*6)
  self.assertGreater(large,small)
  with self.assertRaises(OSError):check_space({'C:/export':large},lambda _:small)
 def test_live_guard_stops_a_silent_process_and_reports_disk_full(self):
  # The subprocess emits no lines while disk space falls: a stdout-only check
  # cannot detect this failure until the native writer has already lost data.
  lines=[];clock=time.monotonic()
  def free(path):return GB if time.monotonic()-clock<.4 else 0
  step=Step('source extraction',[sys.executable,'-c','import time;time.sleep(30)'],storage_limits={'fixture':MB})
  with patch('core.export_storage.disk_free',side_effect=free):
   # Replace providers explicitly: function defaults bind at import time.
   import core.export_storage as storage
   original=storage.DiskGuard
   with patch.object(storage,'check_space',side_effect=lambda limits,*args:check_space(limits,free)),patch.object(storage,'DiskGuard',side_effect=lambda limits,callback:original(limits,callback,interval=.05,free=free)):
    pipe=Pipeline([step],on_line=lines.append);pipe._run()
  self.assertEqual(pipe.code,-5)
  self.assertLess(time.monotonic()-clock,8)
  self.assertTrue(any('ATLASMAP_DISK_FULL' in line for line in lines))
  self.assertFalse(pipe._cancelled)
 def test_preflight_does_not_launch_a_writer_when_reserve_is_missing(self):
  lines=[]
  with patch('core.export_storage.check_space',side_effect=OSError(28,'磁盘空间不足')):
   pipe=Pipeline([Step('extract',[sys.executable,'-c',"print('SHOULD_NOT_RUN')"],storage_limits={'x':MB})],on_line=lines.append);pipe._run()
  self.assertNotEqual(pipe.code,0)
  self.assertFalse(any('PID=' in x for x in lines))
 def test_failure_progress_stays_at_failed_step(self):
  progress=[]
  pipe=Pipeline([Step('first',[],action=lambda _:1),Step('never',[],action=lambda _:None)],on_progress=lambda *x:progress.append(x));pipe._run()
  self.assertEqual(progress[-1][0],0)
  self.assertIn('first',progress[-1][2])

 def test_out_of_memory_retries_unfinished_workers_once_at_single_concurrency(self):
  with tempfile.TemporaryDirectory() as temp:
   flag=str(Path(temp)/'attempt')
   code="import pathlib,sys;p=pathlib.Path(sys.argv[1]);first=not p.exists();p.write_text('attempt');print('Out of memory.' if first else 'RETRY_OK');sys.exit(1 if first else 0)"
   lines=[];jobs=[Step('oom',[sys.executable,'-c',code,flag]),Step('other',[sys.executable,'-c',"import time;time.sleep(.2);print('OTHER_OK')"]) ]
   pipe=Pipeline([Step('parallel',[],parallel_factory=lambda:jobs)],on_line=lines.append);pipe._run()
   self.assertEqual(pipe.code,0)
   self.assertTrue(any('RETRY_OK' in line for line in lines))
   self.assertTrue(any('自动单进程重试' in line for line in lines))
 def test_persistent_memory_failure_stops_after_one_retry(self):
  lines=[];job=Step('oom',[sys.executable,'-c',"print('Out of memory.');raise SystemExit(1)"])
  pipe=Pipeline([Step('parallel',[],parallel_factory=lambda:[job])],on_line=lines.append);pipe._run()
  self.assertEqual(pipe.code,-6)
  self.assertEqual(sum('Out of memory.' in x and '进程启动' not in x and '-c' not in x for x in lines),2)

 def test_ma1_localized_io_memory_error_retries_instead_of_aborting(self):
  with tempfile.TemporaryDirectory() as temp:
   flag=str(Path(temp)/'attempt')
   code="import pathlib,sys;p=pathlib.Path(sys.argv[1]);first=not p.exists();p.write_text('attempt');print('System.IO.IOException: 内存资源不足，无法处理此命令。' if first else 'MA1_RETRY_OK');sys.exit(1 if first else 0)"
   lines=[];job=Step('Ma1 source state',[sys.executable,'-X','utf8','-c',code,flag])
   pipe=Pipeline([Step('parallel',[],parallel_factory=lambda:[job])],on_line=lines.append);pipe._run()
   self.assertEqual(pipe.code,0)
   self.assertTrue(any('自动单进程重试' in line for line in lines))
   self.assertTrue(any('"text": "MA1_RETRY_OK"' in line for line in lines))
