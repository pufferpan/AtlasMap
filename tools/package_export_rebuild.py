"""Package only the audited map exporter; retain all earlier releases."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'dist/releases/export-rebuild/AtlasMap'
OUT=BASE/'work/export-rebuild-20261101'
check=json.loads((OUT/'frozen-ui.json').read_text(encoding='utf-8'))
assert check['complete'] and check['exporter_pinned'] and check['state_helper']
assert check['splash_gradient'] and check['splash_flow']
assert check['version']=='1.0+2026-11-02.export-rebuild'
assert (OUT/'frozen-ui.json').stat().st_mtime >= (ROOT/'AtlasMap.exe').stat().st_mtime
manifest=json.loads((ROOT/'runtime/reference-exporter.json').read_text(encoding='utf-8'))
assert 'Export3' in manifest['reference']
for item in manifest['files']:
    assert hashlib.sha256((ROOT/'runtime'/item['file']).read_bytes()).hexdigest()==item['sha256']
for filename in ('map_scene_state.py','ue_ensure_lighting.py','ue_render_preview.py','blender_iceland.py'):
    assert (ROOT/'scripts/official'/filename).read_bytes()==(BASE/'scripts/official'/filename).read_bytes(),filename
assert (ROOT/'scripts/tools/scene-state/scene-state.dll').read_bytes()==(BASE/'scripts/tools/scene-state/scene-state.dll').read_bytes()
state=json.loads((OUT/'CollectionRoom/render_state.json').read_text(encoding='utf-8'))
assert len(state['lights'])==130 and len(state['preservedAssets'])==126
for item in state['preservedAssets']:
    file=OUT/'CollectionRoom/source-render/assets'/item['path']
    assert hashlib.sha256(file.read_bytes()).hexdigest()==item['sha256']
imported=json.loads((OUT/'CollectionRoom_ue/ue_import_result.json').read_text(encoding='utf-8'))
rendered=json.loads((OUT/'CollectionRoom/render_report.json').read_text(encoding='utf-8'))
assert imported['complete'] and rendered['complete'] and 'source game camera:' in rendered['camera']
shutil.copy2(BASE/'docs/NOTES-export-rebuild.md',ROOT/'更新说明-导出重做.md')
shutil.copy2(BASE/'docs/NOTES-export-rebuild.md',ROOT/'_internal/docs/NOTES-export-rebuild.md')
archive=BASE/'AtlasMap-1.0+2026-11-02.export-rebuild-win64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(ROOT.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            z.write(file,str(file.relative_to(ROOT.parent)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    count=len(z.infolist())
result={'archive':str(archive),'bytes':archive.stat().st_size,
    'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_files':count,
    'executable':str(ROOT/'AtlasMap.exe'),'reference':manifest['reference'],
    'reference_files':len(manifest['files']),'frozen_check':check,
    'source_lights':130,'fog_only':49,'bake_payloads':126,
    'source_bake_bytes':sum(x['bytes'] for x in state['preservedAssets']),
    'render':rendered}
(OUT/'delivery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
