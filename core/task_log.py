"""Durable, unfiltered task output, independent of bounded GUI log buffers."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid


class TaskLog:
    @classmethod
    def open_existing(cls,path):
        log=cls.__new__(cls)
        log.path=Path(path);log._lock=threading.RLock()
        log.error='';log.finished=True;log._stream=None
        log._last_flush=time.monotonic();log._readonly=True
        return log

    def __init__(self, directory, title, commands, version):
        self._lock = threading.RLock()
        self.error = ''
        self.finished = False
        self._last_flush = time.monotonic()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        label = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', title)[:48].strip(' .')
        self.path = directory / f'AtlasMap-{datetime.now():%Y%m%d-%H%M%S}-{label}-{uuid.uuid4().hex[:8]}.txt'
        self._stream = self.path.open('x', encoding='utf-8-sig', buffering=65536)
        self._stream.write('AtlasMap 完整任务日志\n')
        self._stream.write(f'版本：{version}\n任务：{title}\n开始：{datetime.now().astimezone().isoformat()}\n')
        self._stream.write('命令 / 步骤：'+json.dumps(commands, ensure_ascii=False)+'\n')
        self._stream.write('包含主流程及所有分块输出；不受界面显示行数和噪音过滤限制。\n\n')
        self._stream.flush()

    def append(self, line):
        with self._lock:
            if getattr(self,'_readonly',False):return False
            if self.error:
                return False
            try:
                # A completed task may still emit cleanup-result messages.
                if self._stream is None:
                    self._stream = self.path.open('a', encoding='utf-8', buffering=65536)
                self._stream.write(f'[{datetime.now():%H:%M:%S.%f}] {str(line).rstrip(chr(13)+chr(10))}\n')
                if time.monotonic()-self._last_flush >= .25:
                    self._stream.flush()
                    self._last_flush = time.monotonic()
                return True
            except OSError as error:
                self.error = str(error)
                return False

    def finish(self, code):
        with self._lock:
            self.append(f'[任务结束] 退出码 {code} · '+('完成' if code == 0 else '已取消' if code in (-2,130) else '失败'))
            self.finished = True
            self.close()

    def close(self):
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.close()
                except OSError as error:
                    self.error = str(error)
                self._stream = None

    def export(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError('请选择其他保存位置，自动记录的原始日志会保留。')
        partial = None
        try:
            with self._lock:
                if self.error:
                    raise OSError('日志记录过程中发生写入错误，不能作为完整日志导出：'+self.error)
                if self._stream is not None:
                    self._stream.flush()
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.atlasmap-log-', suffix='.partial', delete=False) as output:
                    partial = Path(output.name)
                    with self.path.open('rb') as source:
                        shutil.copyfileobj(source, output, length=1024*1024)
                    if not self.finished:
                        output.write(('\n[日志快照] 任务仍在运行，本文件记录到 '+datetime.now().astimezone().isoformat()+'。\n').encode('utf-8'))
            os.replace(partial, destination)
            return str(destination)
        finally:
            if partial is not None and partial.exists():
                partial.unlink()
