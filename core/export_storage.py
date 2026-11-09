"""Export workspace selection, conservative budgets and live disk guards."""
from pathlib import Path
import shutil
import threading

GB=1024**3
MB=1024**2


def disk_free(path):
    probe=Path(path).resolve()
    while not probe.exists():probe=probe.parent
    return shutil.disk_usage(probe).free


def prefer_project_storage(source,project,free=disk_free):
    source,project=Path(source).resolve(),Path(project).resolve()
    return source.anchor.lower()!=project.anchor.lower() and free(project)>free(source)+GB


def source_budget(rows):
    # A planning estimate, not an exact asset size: PNGs, GLBs, packed .blend,
    # FBX and native imports all coexist until final validation.
    meshes=sum(max(0,int(r.get('meshes',0))) for r in rows)
    objects=sum(max(0,int(r.get('instances',0))) for r in rows)
    return max(4*GB,meshes*MB+objects*384*1024+len(rows)*128*1024)


def check_space(limits,free=disk_free):
    for path,reserve in limits.items():
        available=free(path)
        if available<reserve:
            raise OSError(28,f'磁盘空间不足：{path}，剩余 {available/GB:.2f} GB，需要保留 {reserve/GB:.2f} GB；请换到空间充足的导出盘或工程盘')


class DiskGuard:
    def __init__(self,limits,on_full,interval=1,free=disk_free):
        self.limits=limits;self.on_full=on_full;self.interval=interval;self.free=free
        self.error=None;self.stopped=threading.Event();self.thread=None
    def start(self):
        if self.limits:
            self.thread=threading.Thread(target=self._run,name='export-disk-guard',daemon=True)
            self.thread.start()
        return self
    def _run(self):
        while not self.stopped.wait(self.interval):
            try:check_space(self.limits,self.free)
            except OSError as exc:
                self.error=str(exc);self.on_full(self.error);return
    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(2)
