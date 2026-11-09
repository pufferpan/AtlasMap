"""Repair authored mask UVs, decal bindings and source-hidden helpers in-place."""
import bpy
import hashlib
import json
import time
from pathlib import Path

import numpy as np

root=Path('D:/AtlasMap-tooling')
out=root/'out/Iceland'
folder=out/'revised/material_refresh'
definitions=json.loads((folder/'material_refresh.json').read_text(encoding='utf-8-sig'))['materials']
bundle=json.loads((out/'revised/common_static_repair/repair_bundle.json').read_text(encoding='utf-8-sig'))
attributes=json.loads((out/'audit/floor_attributes/attributes.json').read_text(encoding='utf-8-sig'))
source_meshes={m['asset']:m for m in bundle['meshes']}
asset_for_data={m['data_name']:m['asset'] for m in bundle['meshes']}
bpy.ops.wm.save_as_mainfile(filepath=str(out/'revised'/f'Iceland_before_floor_repair_{int(time.time())}.blend'),copy=True,compress=True)
report={'uv_meshes':[],'materials':[],'hidden_helpers':[],'failures':[]}
for entry in attributes:
    original=source_meshes.get(entry['asset'])
    data=bpy.data.meshes.get(original['data_name']) if original else None
    if data is None:continue
    indices=np.empty(len(data.loops),np.uint32)
    data.loops.foreach_get('vertex_index',indices)
    if len(data.vertices)!=entry['vertices'] or hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest()!=entry['index_sha256']:
        report['failures'].append({'asset':entry['asset'],'reason':'topology differs; retained UVs'});continue
    for channel,file in enumerate(entry['uv_files']):
        source=np.fromfile(out/'audit/floor_attributes'/file,'<f4').reshape(-1,2).copy()
        source[:,1]=1-source[:,1]
        name='UVMap' if channel==0 else f'UV{channel}'
        layer=data.uv_layers.get(name) or data.uv_layers.new(name=name)
        layer.data.foreach_set('uv',source[indices].ravel())
    data.uv_layers.active_index=0
    data['authored_uv_channel_count']=len(entry['uv_files'])
    report['uv_meshes'].append({'asset':entry['asset'],'channels':len(entry['uv_files'])})

# Load the shared builders without running the full-scene refresh or its saves.
source=(root/'scripts/apply_iceland_texture_refresh.py').read_text(encoding='utf-8')
scope={'bpy':bpy,'Path':Path,'folder':folder,'images':{},'families':{},'re':__import__('re')}
exec(source[source.index('def load_image'):source.index('\nfor path,definition in definitions.items()')],scope)
replacements={}
for path,definition in definitions.items():
    parameters=definition.get('texture_parameters',{})
    if 'MatBlend_Ground' in (definition.get('MasterPath') or '') or 'DecalTexture' in parameters or 'BAMap' in parameters:
        material=scope['build_material'](path,definition)
        material['floor_repair_revision']='authored_UV2_mask_and_decal_RGBA'
        replacements[path]=material
        report['materials'].append(path)
for material in list(bpy.data.materials):
    path=material.get('unrealMaterialPath')
    if path in replacements and material!=replacements[path] and material.users:
        material.user_remap(replacements[path])

visibility=json.loads((out/'audit/all_common_visibility/visibility_audit.json').read_text(encoding='utf-8-sig'))
hidden={};visible={}
for row in visibility:
    if not row.get('loc'):continue
    target=visible if row['renderable'] else hidden
    target.setdefault(row['asset'],[]).append(row['loc'])
hidden={k:np.asarray(v,dtype=np.float64)*[.01,-.01,.01] for k,v in hidden.items()}
visible={k:np.asarray(v,dtype=np.float64)*[.01,-.01,.01] for k,v in visible.items()}
for obj in bpy.context.scene.objects:
    if obj.type!='MESH':continue
    asset=asset_for_data.get(obj.data.name) or obj.get('source_asset')
    if asset not in hidden:continue
    position=np.asarray(obj.matrix_world.translation,dtype=np.float64)
    error=float(np.min(np.linalg.norm(hidden[asset]-position,axis=1)))
    if error>.025:continue
    # A visible source instance at the same position takes precedence.
    if asset in visible and float(np.min(np.linalg.norm(visible[asset]-position,axis=1)))<=.025:continue
    obj['source_hidden_in_game']=True
    obj.hide_render=True
    obj.hide_set(True)
    report['hidden_helpers'].append({'name':obj.name,'asset':asset,'position_error_m':error})
for image in scope['images'].values():
    if not image.packed_file:image.pack()
report['file']=str(out/'revised/Iceland_floors_fixed.blend')
(folder/'floor_repair_application.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=report['file'],compress=True)
result={k:len(report[k]) for k in ['uv_meshes','materials','hidden_helpers','failures']}
result['file']=report['file']
