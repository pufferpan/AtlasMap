"""Package the verified release directory; never consume a previous ZIP."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'dist/releases/source-lighting/AtlasMap'
OUT=BASE/'work/map-render-20261101'
report=json.loads((OUT/'frozen-ui-check.json').read_text(encoding='utf-8'))
assert report['complete'] and report['manual_lighting_mode']
assert report['version']=='1.0+2026-11-01.source-lighting'
native=json.loads((OUT/'ProofSource/native_light_checks.json').read_text())
assert native['complete'] and native['actor_count']==7
for name in ('ue_ensure_lighting.py','ue_render_preview.py','map_lighting.py'):
    source=BASE/'scripts/official'/name
    bundled=ROOT/'scripts/official'/name
    assert source.read_bytes()==bundled.read_bytes(),name
manifest=json.loads((ROOT/'runtime/reference-exporter.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    assert hashlib.sha256((ROOT/'runtime'/item['file']).read_bytes()).hexdigest()==item['sha256']
shutil.copy2(BASE/'docs/NOTES-source-lighting.md',ROOT/'更新说明.md')
archive=BASE/'AtlasMap-1.0+2026-11-01.source-lighting-win64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(ROOT.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            z.write(file,str(file.relative_to(ROOT.parent)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    count=len(z.infolist())
result={'archive':str(archive),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_files':count,
        'executable':str(ROOT/'AtlasMap.exe'),'reference_files':len(manifest['files']),
        'frozen_check':report,'native_light_checks':native}
(OUT/'delivery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
