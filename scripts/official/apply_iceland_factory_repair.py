"""Repair the red factory's skeletal-material blend without changing geometry."""
import bpy
import hashlib
import json
import re
import time
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling')
folder=root/'out/Iceland/revised/material_refresh'
definitions=json.loads((folder/'material_refresh.json').read_text(encoding='utf-8-sig'))['materials']
needle='SM_BatchH0_IceLand_Building_FactoryRed_Destruction_56F1AADB308925FCDCF522665837E'
target=next(o for o in bpy.context.scene.objects if needle in o.name)
paths={s.material['unrealMaterialPath'] for s in target.material_slots if s.material and 'MatBlend_Structures_SK' in s.material.get('source_master','')}
if len(paths)!=3:raise RuntimeError('Unexpected factory material layout')
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D' and area.spaces.active.local_view is not None:
        with bpy.context.temp_override(area=area,region=next(r for r in area.regions if r.type=='WINDOW')):
            bpy.ops.view3d.localview(frame_selected=False)
bpy.ops.wm.save_as_mainfile(filepath=str(folder.parent/f'Iceland_before_factory_repair_{int(time.time())}.blend'),copy=True,compress=True)
affected=[]
for obj in bpy.context.scene.objects:
    if obj.type=='MESH' and any(s.material and s.material.get('unrealMaterialPath') in paths for s in obj.material_slots):
        if obj.data.uv_layers.get('UV1') is None:raise RuntimeError('Missing authored mask UV1: '+obj.name)
        affected.append(obj.name)
source=(root/'scripts/apply_iceland_texture_refresh.py').read_text(encoding='utf-8')
scope={'bpy':bpy,'Path':Path,'folder':folder,'images':{},'families':{},'re':re}
exec(source[source.index('def load_image'):source.index('\nfor path,definition in definitions.items()')],scope)
materials=[]
for path in sorted(paths):
    material=scope['build_material'](path,definitions[path])
    material['factory_repair_revision']='skeletal_UV1_two_layer_color_response'
    for old in list(bpy.data.materials):
        if old!=material and old.users and old.get('unrealMaterialPath')==path:old.user_remap(material)
    materials.append(path)
for image in scope['images'].values():
    if not image.packed_file:image.pack()
report={'target':target.name,'materials':materials,'affected_objects':affected,
        'source_master':'M_MatBlend_Structures_SK_Master','mask_uv':'UV1','base_uv':'UVMap',
        'corrections':['separate tiled base and authored blend-mask UVs','use tint alpha instead of unconditional full RGB multiplication',
                       'retain base in unpainted regions','respect disabled third layer','blend both layers normal/roughness/metalness'],
        'limitations':'Compatibility shader: cooked math expressions for exact height/tint blending are absent; weather and custom atlas data are not reconstructed.',
        'file':str(folder.parent/'Iceland_factory_materials_fixed.blend')}
(folder/'factory_repair_application.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=report['file'],compress=True)
result={'materials':len(materials),'affected_objects':len(affected),'file':report['file']}
