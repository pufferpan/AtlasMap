"""Reopen checks for authored UVs, transparent tracks and hidden collision helpers."""
import bpy
import hashlib
import json
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling/out/Iceland')
bundle=json.loads((root/'revised/common_static_repair/repair_bundle.json').read_text(encoding='utf-8-sig'))
by_asset={m['asset']:m for m in bundle['meshes']}
failures=[];channels=0;meshes=0
for entry in json.loads((root/'audit/floor_attributes/attributes.json').read_text(encoding='utf-8-sig')):
    data=bpy.data.meshes.get(by_asset[entry['asset']]['data_name'])
    if data is None:failures.append({'asset':entry['asset'],'reason':'mesh missing'});continue
    indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
    if hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest()!=entry['index_sha256']:
        failures.append({'asset':entry['asset'],'reason':'topology differs'});continue
    for index,file in enumerate(entry['uv_files']):
        name='UVMap' if index==0 else f'UV{index}'
        layer=data.uv_layers.get(name)
        if layer is None:failures.append({'asset':entry['asset'],'reason':'missing '+name});continue
        expected=np.fromfile(root/'audit/floor_attributes'/file,'<f4').reshape(-1,2).copy();expected[:,1]=1-expected[:,1]
        actual=np.empty(len(data.loops)*2,np.float32);layer.data.foreach_get('uv',actual)
        if not np.array_equal(actual.reshape(-1,2),expected[indices]):failures.append({'asset':entry['asset'],'reason':'UV data differs '+name})
        else:channels+=1
    meshes+=1
application=json.loads((root/'revised/material_refresh/floor_repair_application.json').read_text())
for entry in application['hidden_helpers']:
    obj=bpy.data.objects.get(entry['name'])
    if obj is None or not obj.hide_render or not obj.hide_get():failures.append({'object':entry['name'],'reason':'source-hidden helper became visible'})
tracks=[];roads=[]
for material in bpy.data.materials:
    if not material.users or not material.get('floor_repair_revision'):continue
    path=material.get('unrealMaterialPath','')
    shader=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    if 'MI_GEN_Decal_Track_' in path:
        ok=shader.inputs['Base Color'].is_linked and shader.inputs['Alpha'].is_linked
        tracks.append({'material':path,'color_and_alpha_connected':ok})
        if not ok:failures.append({'material':path,'reason':'track binding missing'})
    if 'MI_H_IceLand_Terrain_AsphaltS2_01_HD' in path:
        mask=next(n for n in material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'AsphaltS2_01_Mask' in n.image.name)
        link=mask.inputs['Vector'].links[0]
        ok=link.from_node.type=='UVMAP' and link.from_node.uv_map=='UV2'
        roads.append({'material':path,'mask_uses_UV2':ok})
        if not ok:failures.append({'material':path,'reason':'road mask UV differs'})
report={'file':bpy.data.filepath,'meshes_checked':meshes,'exact_uv_channels':channels,
        'source_hidden_helpers_checked':len(application['hidden_helpers']),'tracks':tracks,'roads':roads,'failures':failures}
(root/'revised/material_refresh/floor_saved_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
assert not failures
result=report
