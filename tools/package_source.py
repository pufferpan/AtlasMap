"""Archive project sources and the pinned reference toolchain without build caches."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import sys
import zipfile

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from app.version import stamp

SKIP = {'__pycache__', 'bin', 'obj', '.git', '.venv', '.pytest_cache', 'node_modules', '.cache'}
PRIVATE_NAMES = {'license.json', 'activation.json', 'settings.json'}


def _rel(path):
    """清单里只写包内相对路径，避免泄漏构建机器的绝对路径。"""
    try:
        return path.resolve().relative_to(BASE.resolve()).as_posix()
    except ValueError:
        return path.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=BASE/'exporter-source')
    parser.add_argument('--reference', type=Path, default=BASE/'runtime')
    parser.add_argument('--output', type=Path, default=BASE/f'AtlasMap-{stamp()}-full-source.zip')
    args = parser.parse_args()
    files = {}

    def add(source, target):
        if target in files:
            raise ValueError('Duplicate archive entry: ' + target)
        files[target] = source

    def tree(source, target):
        if not source.is_dir():
            raise FileNotFoundError(source)
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            if path.is_file() and not SKIP.intersection(relative.parts) and path.suffix.lower() not in {'.pyc', '.pyo', '.pem', '.key', '.pfx', '.p12', '.partial'}:
                if path.name.lower() in PRIVATE_NAMES or path.name.lower().startswith('.env'):continue
                if 'aeskey' in path.name.lower() and path.suffix.lower()=='.json':continue
                add(path, (Path(target)/relative).as_posix())

    for name in ('app', 'assets', 'core', 'docs', 'scripts', 'site', 'tests', 'tools'):
        tree(BASE/name, name)
    for name in ('run.py', 'AtlasMap.spec', 'requirements.txt', 'requirements-build.txt', 'README-source.md', 'README.md', '.gitignore', 'build-source.ps1'):
        add(BASE/name, name)
    reference = args.reference.resolve()
    expected = {
        'map-export.exe': '32cfc2d98630eba7c8513027d8b5a72cc30da86c7fffb0283f45a6e4f18b548c',
        'dfmap.dll': 'f5a909824c021b27ff5a76d94e1b5a3f01db85b09d84568e9b990d327cbc6ac7',
    }
    for name, digest in expected.items():
        assert hashlib.sha256((reference/name).read_bytes()).hexdigest() == digest, name
    tree(reference, 'runtime')
    for name in ('source', 'docs', 'presets', 'scripts', 'research_helpers'):
        tree(args.original/name, 'exporter-source/'+name)
    vendor=BASE/'third_party/fluentpy-qt'
    if vendor.is_dir():
        tree(vendor,'third_party/fluentpy-qt')
    else:
        fluent = importlib.util.find_spec('fluentpy')
        tree(Path(fluent.origin).parent, 'third_party/fluentpy-qt/fluentpy')
        metadata = importlib.metadata.distribution('fluentpy-qt')
        assert metadata.version == '0.7.3'
        tree(Path(metadata._path), 'third_party/fluentpy-qt/'+Path(metadata._path).name)

    root = 'AtlasMap-source/'
    entries = []
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix+'.partial')
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for target, source in sorted(files.items()):
            data = source.read_bytes()
            if re.search(rb'-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\r?\n[A-Za-z0-9+/=]{32,}', data):
                raise ValueError('Unexpected private key material: '+target)
            entries.append({'file': target, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            archive.writestr(root+target, data)
        manifest = {
            'version': stamp(),
            'date': stamp().split('+', 1)[1].split('.', 1)[0],
            'packaged_at': datetime.now(timezone.utc).isoformat(),
            'project': BASE.name, 'original_source': _rel(args.original.resolve()),
            'reference_toolchain': _rel(reference), 'pinned_hashes': expected,
            'file_count': len(entries), 'total_bytes': sum(item['bytes'] for item in entries),
            'files': entries,
        }
        archive.writestr(root+'SOURCE-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(partial) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(entries)+1
        for entry in entries:
            data = archive.read(root+entry['file'])
            assert len(data) == entry['bytes']
            assert hashlib.sha256(data).hexdigest() == entry['sha256']
            assert data == files[entry['file']].read_bytes(), entry['file']
        required = ('app/splash.py', 'app/wizard.py', 'core/ue_pipeline.py',
                    'scripts/official/ue_ensure_lighting.py', 'tools/scene_state/Program.cs',
                    'exporter-source/source/dfmap/Program.cs', 'exporter-source/source/dfmap/dfmap.csproj',
                    'runtime/dfmap.dll', 'build-source.ps1', 'app/export_quality.py',
                    'core/export_quality.py', 'core/export_failure.py', 'app/failure_notice.py',
                    'scripts/official/map_json.py')
        for name in required:
            assert root+name in archive.namelist(), name
    partial.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n', encoding='utf-8')
    print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size,
                      'files': len(entries)+1, 'source_bytes': manifest['total_bytes'],
                      'sha256': digest, 'zip_crc': 'passed', 'content_hashes': 'passed'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
