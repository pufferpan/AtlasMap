"""Record new export files; never recursively remove a user-selected folder."""
import os
from pathlib import Path
import re
import stat
import time

from scripts.official.map_paths import io_path,display_path


def _absolute(path):
    return Path(os.path.abspath(display_path(path)))


def _safe(path, root):
    if not path.is_relative_to(root):return False
    for part in (path, *path.parents):
        try:
            value=io_path(part).lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(value.st_mode) or getattr(value,'st_file_attributes',0)&0x400:
            return False
    return True


def _stamp(path):
    value=io_path(path).stat(follow_symlinks=False)
    return value.st_size,value.st_mtime_ns,value.st_ino


class ExportResidue:
    def __init__(self, roots, exclusions=()):
        self.roots=list(dict.fromkeys(_absolute(p) for p in roots))
        self.exclusions=[_absolute(p) for p in exclusions]
        self.before={}
        self.candidates={}
        self.directories=set()
        self.warnings=[]
        self.sealed=False
        self.deleted=False

    def _scan(self, root):
        if root==Path(root.anchor) or root==Path.home() or not _safe(root,root):
            raise ValueError('不清理磁盘根目录、用户主目录或链接目录：'+str(root))
        files={};directories=set()
        def walk(path):
            # A nested scope can explicitly include an otherwise excluded
            # project branch; the broad raw-export scope cannot reach it.
            if any(path.is_relative_to(p) and not root.is_relative_to(p) for p in self.exclusions):return
            if not _safe(path,root):return
            if not io_path(path).exists():return
            directories.add(path)
            with os.scandir(io_path(path)) as entries:
                for entry in entries:
                    target=Path(display_path(entry.path))
                    if not _safe(target,root):continue
                    if entry.is_dir(follow_symlinks=False):walk(target)
                    elif entry.is_file(follow_symlinks=False):files[target]=_stamp(target)
        walk(root)
        return files,directories

    def capture(self):
        for root in self.roots:
            try:self.before[root]=self._scan(root)
            except (OSError,ValueError) as exc:self.warnings.append(str(exc))

    def seal(self):
        for root,(old_files,old_dirs) in self.before.items():
            try:
                files,directories=self._scan(root)
                for path,stamp in files.items():
                    if path not in old_files and path.suffix.lower()!='.log':
                        self.candidates[path]=(root,stamp)
                self.directories.update((root,p) for p in directories-old_dirs)
            except (OSError,ValueError) as exc:self.warnings.append(str(exc))
        self.sealed=True

    @property
    def size(self):
        return sum(stamp[0] for _,stamp in self.candidates.values())

    def delete(self,on_progress=None):
        if not self.sealed or self.deleted:raise RuntimeError('清理清单未完成或已使用')
        self.deleted=True
        removed=0;skipped=[];errors={};removed_bytes=0;last_progress=0
        total=len(self.candidates)
        # Resolve and check every target on the deleting thread immediately
        # before unlinking. A replaced folder/junction can never redirect us.
        for done,(path,(root,expected)) in enumerate(self.candidates.items(),1):
            try:
                if not _safe(path,root) or _stamp(path)!=expected:
                    skipped.append(str(path));errors[str(path)]='文件已被修改或路径不再安全'
                else:
                    io_path(path).unlink();removed+=1;removed_bytes+=expected[0]
            except FileNotFoundError:pass
            except OSError as exc:
                skipped.append(str(path));errors[str(path)]=str(exc)
            now=time.monotonic()
            if on_progress and (done==total or now-last_progress>=.25):
                on_progress(dict(done=done,total=total,removed=removed,skipped=len(skipped),
                                 removed_bytes=removed_bytes,current=str(path)))
                last_progress=now
        for root,path in sorted(self.directories,key=lambda r:len(r[1].parts),reverse=True):
            try:
                if _safe(path,root):io_path(path).rmdir()
            except OSError:pass  # Logs, changed files and existing data remain.
        return dict(removed=removed,skipped=skipped,errors=errors,removed_bytes=removed_bytes)


def for_ue_export(paths, steps):
    project=_absolute(paths['project']).parent
    roots=[paths['root'],paths['transfer']]
    dest=paths['dest'].strip('/').split('/')
    if len(dest)>1 and dest[0]=='Game' and all(re.fullmatch(r'[\w-]+',p) for p in dest[1:]):
        roots.append(project/'Content'/Path(*dest[1:]))
    run_id=next((s.env.get('ATLASMAP_UE_RUN_ID') for s in reversed(steps) if s.env.get('ATLASMAP_UE_RUN_ID')),None)
    if paths.get('parallel_export')=='1' and run_id and re.fullmatch('[0-9a-f]{32}',run_id):
        roots.append(project/'.atlasmap-parallel'/run_id)
    # If the raw export was accidentally pointed at an ancestor of the UE
    # project, exclude the entire project from that broad scan.
    roots=[p for p in roots if _absolute(p)!=project]
    return ExportResidue(roots,exclusions=[project])
