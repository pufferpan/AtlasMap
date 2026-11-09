"""Package the export-window release after the frozen UI and source checks."""
import hashlib
import json
import argparse
from pathlib import Path
import shutil
import sys
import zipfile

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from app.version import stamp

parser=argparse.ArgumentParser()
parser.add_argument('--release',default='export-ui')
parser.add_argument('--check',type=Path,default=BASE/'work/github-sync/frozen-export-ui.json')
parser.add_argument('--note',type=Path,default=BASE/'docs/NOTES-export-ui.md')
args=parser.parse_args()
ROOT=BASE/'dist/releases'/args.release/'AtlasMap'
OUT=args.check.resolve().parent
check=json.loads(args.check.read_text(encoding='utf-8'))
assert check['complete'] and check['version']==stamp()
for key in ('export_shrink_animation','export_compact','export_debug_hidden','export_cpu_memory',
            'splash_gradient','splash_flow','state_helper','exporter_pinned'):
    assert check[key],key
assert args.check.stat().st_mtime >= (ROOT/'AtlasMap.exe').stat().st_mtime
if args.release=='game-lighting':
    assert check['game_lighting_default']
    native=json.loads((OUT/'native-game-validation.json').read_text(encoding='utf-8'))
    saved=json.loads((OUT/'saved-project-validation.json').read_text(encoding='utf-8'))
    assert native['complete'] and saved['complete']
    assert native['distance_fields']['matched_fields']==110 and saved['saved_cameras']==27
if args.release in ('parallel-export','window-split','chunk-progress'):
    for key in ('parallel_tiling','parallel_log_routing','parallel_red_theme'):
        assert check[key],key
    if args.release in ('window-split','chunk-progress'):
        for key in ('parallel_single_origin','parallel_split_motion','parallel_split_finished'):
            assert check[key],key
    if args.release=='chunk-progress':
        assert check['parallel_independent_progress'] and check['parallel_common_log_not_duplicated']
        routing=json.loads((OUT/'native-worker-routing.json').read_text(encoding='utf-8'))
        assert routing['complete'] and routing['distinct_worker_progress'] and routing['disjoint_ue_resources']
    native=json.loads((OUT/'native-validation.json').read_text(encoding='utf-8'))
    assert native['complete']
    for key in ('objects_identical','meshes_identical','materials_identical','images_identical'):
        assert native[key],key
    saved=json.loads((OUT/'saved-project-validation.json').read_text(encoding='utf-8'))
    assert saved['complete'] and saved['saved_objects']==865 and saved['saved_mesh_objects']==847
    assert saved['saved_images']==532 and saved['saved_cameras']==27 and saved['saved_material_slots']==1185
reference=json.loads((ROOT/'runtime/reference-exporter.json').read_text(encoding='utf-8'))
for row in reference['files']:
    assert hashlib.sha256((ROOT/'runtime'/row['file']).read_bytes()).hexdigest()==row['sha256'],row['file']
for file in (BASE/'scripts').rglob('*'):
    if file.is_file() and '__pycache__' not in file.parts:
        assert file.read_bytes()==(ROOT/'scripts'/file.relative_to(BASE/'scripts')).read_bytes(),file
shutil.copy2(args.note,ROOT/('更新说明-并行导出.md' if args.release in ('parallel-export','window-split','chunk-progress') else
                          '更新说明-游戏光照.md' if args.release=='game-lighting' else '更新说明-导出窗口.md'))
archive=BASE/f'AtlasMap-{stamp()}-win64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(ROOT.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            z.write(file,(Path('AtlasMap')/file.relative_to(ROOT)).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    count=len(z.infolist())
result={'archive':str(archive),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_files':count,
        'executable':str(ROOT/'AtlasMap.exe'),'frozen_ui':check,'zip_crc':'passed'}
(OUT/'export-ui-delivery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
archive.with_suffix('.zip.sha256').write_text(result['sha256']+'  '+archive.name+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
