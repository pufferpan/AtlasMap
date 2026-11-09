"""Persistent UE project catalogue. A record always represents a whole project."""
import json
import errno
import hashlib
import os
from pathlib import Path
import shutil
import uuid
from core import exporter, mapnames


def key(path):
    return os.path.normcase(os.path.abspath(path))


def maps_in(project):
    if Path(project).suffix.lower()=='.blend':
        marker=Path(project).parent/'blender_project.json'
        data=json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else {}
        return [data['map']] if data.get('complete') and data.get('map') else []
    folder = Path(project).parent / 'Content' / 'AtlasMaps'
    return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []


def title(record):
    maps = '、'.join(mapnames.label(m) for m in record.get('maps', []))
    return record.get('name') or maps or Path(record['path']).stem


class Catalogue:
    def __init__(self, path=None):
        self.path = Path(path or Path(exporter.app_dir()) / 'projects.json')

    def records(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            raise ValueError('工程记录格式损坏，请保留 projects.json 并导出日志。')
        return data

    def update(self, change):
        # Also protects multiple running copies of the application.
        from PySide6.QtCore import QLockFile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(self.path) + '.lock')
        if not lock.tryLock(1000):
            raise OSError('其他窗口正在更新工程列表，请稍后重试。')
        temporary = self.path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            rows = self.records()
            result = change(rows)
            temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, self.path)
            return result
        finally:
            temporary.unlink(missing_ok=True)
            lock.unlock()

    def register(self, project, map_name='', export_root='', destination=''):
        project = str(Path(project).absolute())
        if not Path(project).is_file() or Path(project).suffix.lower() not in ('.uproject','.blend'):
            raise ValueError('请选择存在的 .uproject 或 .blend 工程文件。')
        def change(rows):
            record = next((r for r in rows if key(r['path']) == key(project)), None)
            if record is None:
                record = {'path': project, 'name': '', 'maps': []}
                rows.append(record)
            record['maps'] = sorted(set(record.get('maps', [])) | set(maps_in(project)) | ({map_name} if map_name else set()))
            if map_name and export_root:
                record.setdefault('exports', {})[map_name] = {'root': export_root, 'destination': destination}
            return dict(record)
        return self.update(change)

    def edit(self, project, name, note):
        if len(name.strip()) > 120 or len(note) > 2000:
            raise ValueError('名称最多 120 字，备注最多 2000 字。')
        def change(rows):
            record = next(r for r in rows if key(r['path']) == key(project))
            record.update(name=name.strip(), note=note.strip())
        self.update(change)

    def replace_path(self, old, new):
        def change(rows):
            record = next(r for r in rows if key(r['path']) == key(old))
            record['path'] = str(new)
        self.update(change)

    def forget(self, project):
        self.update(lambda rows: rows.__setitem__(slice(None), [r for r in rows if key(r['path']) != key(project)]))


def discover(settings):
    """Bounded scan of configured export locations; never walk game disks."""
    found = set()
    current = settings.get('ue_project', '')
    if current and Path(current).is_file():
        found.add(str(Path(current).absolute()))
    roots = {str(Path(p).absolute()) for p in
             (settings.get('ue_export_base'), settings.get('outdir'),
              str(Path(current).parent.parent) if current else '') if p}
    for root in roots:
        base = Path(root)
        if not base.is_dir() or base == Path(base.anchor):
            continue
        # Up to two folders below each selected export base.
        for pattern in ('*.uproject', '*/*.uproject', '*/*/*.uproject'):
            found.update(str(p) for p in base.glob(pattern) if p.is_file())
        for pattern in ('*.blend','*/*.blend','*/*/*.blend'):
            found.update(str(p) for p in base.glob(pattern) if p.is_file() and (p.parent/'blender_project.json').is_file())
    return sorted(found)


def managed_root(project):
    path = Path(project).absolute()
    root = path.parent
    blend=path.suffix.lower()=='.blend'
    marker=root/'blender_project.json'
    if blend:
        data=json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else {}
        valid=(data.get('complete') and data.get('file')==path.name and (root/'assets').is_dir()
               and len(list(root.glob('*.blend')))==1)
    else:valid=path.suffix.lower()=='.uproject' and (root/'Content').is_dir() and len(list(root.glob('*.uproject')))==1
    if (not valid or not path.is_file() or root == Path(root.anchor)
            or root == Path.home() or root == Path(exporter._src_root())
            ):
        raise ValueError('只能操作独立的 UE 工程，或带完整导出清单和 assets 的 Blender 工程目录。')
    for parent in (root, *root.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('工程路径包含链接，请先选择实际工程目录。')
    # Refuse links inside projects before moving/deleting any contents.
    def failed(error):
        raise error
    for folder, dirs, files in os.walk(_io_path(root), followlinks=False, onerror=failed):
        for name in dirs + files:
            item = Path(folder) / name
            if item.is_symlink() or item.is_junction():
                raise ValueError('工程包含目录链接，暂不支持移动或删除，请在资源管理器中处理。')
    return root


def _io_path(path):
    value = os.path.abspath(path)
    if os.name != 'nt' or value.startswith('\\\\?\\'):
        return value
    return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value


def assert_idle():
    import psutil
    for process in psutil.process_iter(['name']):
        if str(process.info.get('name') or '').lower() in ('unrealeditor.exe', 'unrealeditor-cmd.exe', 'blender.exe', 'map-export.exe', 'scene-state.exe'):
            raise ValueError('请先结束导出并关闭 Blender / UE 编辑器，再移动或删除工程。')


def move(project, destination):
    assert_idle()
    root = managed_root(project)
    parent = Path(destination).resolve(strict=True)
    target = parent / root.name
    if not parent.is_dir() or target.exists() or parent == root or root in parent.parents:
        raise ValueError('目标位置已存在同名目录，或位于当前工程内部，请换一个位置。')
    if Path(project).suffix.lower()=='.uproject' and any(ord(c) > 127 for c in str(target)):
        raise ValueError('UE 导出要求英文路径，请选择不含中文的目标目录。')
    try:
        try:
            os.rename(_io_path(root), _io_path(target))
        except OSError as error:
            if error.errno != errno.EXDEV and getattr(error, 'winerror', 0) != 17:
                raise
            # Cross-volume moves keep the source until every copied byte has
            # been verified. copytree refuses an existing destination.
            before = _fingerprint(root)
            shutil.copytree(_io_path(root), _io_path(target))
            if before != _fingerprint(target) or before != _fingerprint(root):
                raise OSError('文件在移动期间发生变化或校验不一致，原工程已保留。')
            shutil.rmtree(_io_path(root))
    except OSError as error:
        raise OSError(f'移动未完成，请保留原目录并检查目标目录中的部分文件。\n原目录：{root}\n目标：{target}\n{error}') from error
    return str(target / Path(project).name)


def _fingerprint(root):
    base = Path(_io_path(root))
    result = {}
    def failed(error):
        raise error
    for folder, dirs, files in os.walk(base, onerror=failed, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            if path.is_symlink() or path.is_junction():
                raise OSError('工程中出现链接，已停止移动。')
        for name in files:
            path = Path(folder) / name
            with path.open('rb') as stream:
                result[str(path.relative_to(base))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def recycle(project):
    assert_idle()
    root = managed_root(project)
    from send2trash import send2trash
    if os.name == 'nt' and send2trash.__module__ != 'send2trash.win.modern':
        raise OSError('回收站组件不可用，未删除工程。请导出日志后检查安装。')
    send2trash(str(root))
