from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from core.task_log import TaskLog
from core.ue_pipeline import Pipeline, Step


class TaskLogTests(unittest.TestCase):
    def test_full_history_exceeds_both_gui_limits_and_keeps_noise(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'中文完整日志',['fixture'],'test')
            log.append('JSON converters: FIRST_UNFILTERED')
            for index in range(25050):log.append(f'OUTPUT_{index:05d}')
            log.append('LAST_LINE');log.finish(0)
            target=Path(folder)/'saved.txt';log.export(target)
            raw=target.read_bytes();text=raw.decode('utf-8-sig')
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
            self.assertIn('FIRST_UNFILTERED',text);self.assertIn('LAST_LINE',text)
            self.assertEqual(text.count('OUTPUT_'),25050)
            self.assertIn('退出码 0',text)

    def test_parallel_process_stdout_stderr_and_failure_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'parallel',[],'test')
            jobs=[Step(str(i),[sys.executable,'-X','utf8','-c',
                f"import sys;print('WORKER_{i}_OUT');print('WORKER_{i}_ERR',file=sys.stderr)"]) for i in range(3)]
            pipe=Pipeline([Step('parallel',[],parallel_factory=lambda:jobs),
                           Step('failure',[],action=lambda _:(_ for _ in ()).throw(ValueError('FULL_TRACEBACK')))],
                          on_line=log.append,on_done=log.finish)
            pipe._run();target=Path(folder)/'saved.txt';log.export(target)
            text=target.read_text(encoding='utf-8-sig')
            for i in range(3):
                self.assertIn(f'WORKER_{i}_OUT',text);self.assertIn(f'WORKER_{i}_ERR',text)
            self.assertIn('Traceback (most recent call last)',text)
            self.assertIn('ValueError: FULL_TRACEBACK',text);self.assertIn('退出码 -4',text)

    def test_running_snapshot_does_not_close_or_truncate_live_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'live',[],'test');log.append('BEFORE')
            target=Path(folder)/'running.txt';log.export(target)
            log.append('AFTER');log.finish(-2)
            self.assertIn('任务仍在运行',target.read_text(encoding='utf-8-sig'))
            self.assertNotIn('AFTER',target.read_text(encoding='utf-8-sig'))
            log.export(Path(folder)/'finished.txt')
            text=Path(folder,'finished.txt').read_text(encoding='utf-8-sig')
            self.assertIn('AFTER',text);self.assertIn('已取消',text)
            self.assertNotIn('任务仍在运行',text)

    def test_cleanup_messages_and_previous_sessions_remain_available(self):
        with tempfile.TemporaryDirectory() as folder:
            first=TaskLog(folder,'same title',[],'test');first.append('FIRST_TASK');first.finish(1)
            first.append('已清理残留文件');first.close()
            second=TaskLog(folder,'same title',[],'test');second.append('SECOND_TASK');second.finish(0)
            self.assertNotEqual(first.path,second.path)
            text=first.path.read_text(encoding='utf-8-sig')
            self.assertIn('FIRST_TASK',text);self.assertIn('已清理残留文件',text)
            self.assertNotIn('SECOND_TASK',text)

    def test_concurrent_output_is_not_interleaved_or_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'threads',[],'test')
            def emit(worker):
                for i in range(1000):log.append(json.dumps(dict(worker=worker,line=i)))
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(emit,range(4)))
            log.finish(0)
            records=[json.loads(row[row.index('{'):]) for row in log.path.read_text(encoding='utf-8-sig').splitlines() if '] {' in row]
            self.assertEqual(len(records),4000)
            self.assertEqual(len({(r['worker'],r['line']) for r in records}),4000)

    def test_failed_save_preserves_existing_destination_and_cleans_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'atomic',[],'test');log.append('DATA');log.finish(0)
            target=Path(folder)/'existing.txt';target.write_text('ORIGINAL')
            with patch('core.task_log.os.replace',side_effect=OSError('save failed')):
                with self.assertRaises(OSError):log.export(target)
            self.assertEqual(target.read_text(),'ORIGINAL')
            self.assertFalse(list(Path(folder).glob('*.partial')))
            with self.assertRaises(ValueError):log.export(log.path)

    def test_recording_error_is_explicit_and_never_exported_as_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            log=TaskLog(folder,'unwritable',[],'test')
            with patch.object(log._stream,'write',side_effect=OSError('disk full')):
                self.assertFalse(log.append('not saved'))
            self.assertIn('disk full',log.error)
            log.finish(1)
            with self.assertRaises(OSError):log.export(Path(folder)/'complete.txt')
