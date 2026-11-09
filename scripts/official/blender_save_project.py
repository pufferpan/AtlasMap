"""Save a self-contained chunk and actually reopen its saved geometry."""
import json,sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).parent))
from map_io import atomic_json
from map_blender_project import signature,suppress_hlod,inspection_view
from blender_live_preview import LivePreview
options=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'))
target=Path(options['output']);receipt=target.with_suffix('.json')
atomic_json(receipt,dict(complete=False,run_id=options['run_id']))
suppressed=suppress_hlod(bpy,options['source'])
for image in bpy.data.images:
    if image.source=='FILE' and not image.packed_file:image.pack()
images=sum(image.source=='FILE' for image in bpy.data.images)
if any(image.source=='FILE' and not image.packed_file for image in bpy.data.images):
    raise ValueError('Cannot save a portable project with external textures')
collection=bpy.data.collections.new(options['collection'])
bpy.context.scene.collection.children.link(collection)
for obj in list(bpy.context.scene.objects):
    for previous in list(obj.users_collection):previous.objects.unlink(obj)
    collection.objects.link(obj)
before=signature(collection.all_objects)
if before['mesh_objects']:inspection_view(bpy)
LivePreview().add(bpy.context.scene.objects,force=True,replace=True,complete=True)
target.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(target),compress=True)
bpy.ops.wm.open_mainfile(filepath=str(target))
actual=signature(bpy.data.collections[options['collection']].all_objects)
if actual!=before:raise ValueError('Saved Blender geometry, transforms or materials changed')
if any(image.source=='FILE' and not image.packed_file for image in bpy.data.images):
    raise ValueError('Saved Blender project lost packed textures')
atomic_json(receipt,dict(complete=True,run_id=options['run_id'],index=options['index'],
    collection=options['collection'],signature=actual,packed_images=images,suppressed_hlod=suppressed))
print('ATLASMAP_BLEND_SAVED '+json.dumps(actual),flush=True)
