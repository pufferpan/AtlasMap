"""Create a relocatable map project from independently verified .blend assets."""
import json,sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).parent))
from map_io import atomic_json
from map_blender_project import signature,inspection_view,source_lighting
options=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'))
project=Path(options['project']);receipt=project.parent/'blender_project.json'
atomic_json(receipt,dict(complete=False,run_id=options['run_id']))
bpy.ops.wm.read_factory_settings(use_empty=True)
reports=[]
for row in options['chunks']:
    file=Path(row['output']);report=json.loads(file.with_suffix('.json').read_text(encoding='utf-8'))
    if not report.get('complete') or report['run_id']!=options['run_id']:raise ValueError('Chunk belongs to a different export')
    with bpy.data.libraries.load(str(file),link=True) as (source,target):
        if row['collection'] not in source.collections:raise ValueError('Saved Blender collection is missing')
        target.collections=[row['collection']]
    bpy.context.scene.collection.children.link(target.collections[0])
    bpy.context.view_layer.update()
    if signature(target.collections[0].all_objects)!=report['signature']:raise ValueError('Linked Blender chunk changed')
    reports.append(report)
for library in bpy.data.libraries:
    library.filepath='//'+str(Path(library.filepath).relative_to(project.parent)).replace('\\','/')
lighting=source_lighting(bpy,options['lighting']) if Path(options['lighting']).is_file() else dict(created=0,unsupported=[])
scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
scene.render.engine='CYCLES';scene.view_settings.view_transform='AgX'
bounds=inspection_view(bpy)
bpy.ops.wm.save_as_mainfile(filepath=str(project),compress=True)
bpy.ops.wm.open_mainfile(filepath=str(project))
for row,report in zip(options['chunks'],reports):
    collection=bpy.data.collections.get(row['collection'])
    if collection is None or signature(collection.all_objects)!=report['signature']:
        raise ValueError('Reopened master project differs from verified Blender chunks')
for library in bpy.data.libraries:
    if not library.filepath.startswith('//') or not Path(bpy.path.abspath(library.filepath)).is_file():
        raise ValueError('Master Blender project has a missing or absolute library path')
atomic_json(receipt,dict(complete=True,run_id=options['run_id'],map=options['map'],file=project.name,
    chunks=len(reports),mesh_objects=sum(r['signature']['mesh_objects'] for r in reports),
    packed_images=sum(r['packed_images'] for r in reports),lighting=lighting,bounds=bounds))
print('ATLASMAP_BLEND_PROJECT '+str(project),flush=True)
