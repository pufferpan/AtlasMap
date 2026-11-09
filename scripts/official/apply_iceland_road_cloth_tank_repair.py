"""Restore source RVT road colour, vertex masks and reported cloth/tank materials."""
import bpy
import hashlib
import json
import re
import time
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling')
out=root/'out/Iceland'
folder=out/'revised/material_refresh'
definitions=json.loads((folder/'material_refresh.json').read_text(encoding='utf-8-sig'))['materials']
attributes=json.loads((out/'audit/material_attributes/attributes.json').read_text())
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D' and area.spaces.active.local_view is not None:
        with bpy.context.temp_override(area=area,region=next(r for r in area.regions if r.type=='WINDOW')):
            bpy.ops.view3d.localview(frame_selected=False)
bpy.ops.wm.save_as_mainfile(filepath=str(folder.parent/f'Iceland_before_road_cloth_tank_repair_{int(time.time())}.blend'),copy=True,compress=True)
report={'uv_meshes':[],'authored_vertex_colour_meshes':[],'default_vertex_colour_meshes':[],
        'materials':[],'rvt_proxy_objects':[],'failures':[]}
by_asset={}
for obj in bpy.context.scene.objects:
    if obj.type=='MESH' and obj.data.get('unrealAssetPath'):
        by_asset.setdefault(obj.data['unrealAssetPath'],{})[obj.data.name]=obj.data
for entry in attributes:
    for data in by_asset.get(entry['asset'],{}).values():
        indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
        if len(data.vertices)!=entry['vertices'] or hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest()!=entry['index_sha256']:
            report['failures'].append({'asset':entry['asset'],'reason':'live topology differs'});continue
        for channel,file in enumerate(entry['uv_files']):
            source=np.fromfile(out/'audit/material_attributes'/file,'<f4').reshape(-1,2).copy();source[:,1]=1-source[:,1]
            name='UVMap' if channel==0 else f'UV{channel}'
            layer=data.uv_layers.get(name) or data.uv_layers.new(name=name)
            layer.data.foreach_set('uv',source[indices].ravel())
        data.uv_layers.active_index=0
        report['uv_meshes'].append(entry['asset'])
        if entry['color_file']:
            colors=np.fromfile(out/'audit/material_attributes'/entry['color_file'],'u1').reshape(-1,4).astype(np.float32)/255
            report['authored_vertex_colour_meshes'].append(entry['asset'])
        elif entry['color_buffer_state']=='default_white':
            colors=np.ones((len(data.vertices),4),np.float32)
            report['default_vertex_colour_meshes'].append(entry['asset'])
        else:
            report['failures'].append({'asset':entry['asset'],'reason':'source vertex colour buffer unavailable'});continue
        layer=data.color_attributes.get('UEVertexColor') or data.color_attributes.new(name='UEVertexColor',type='FLOAT_COLOR',domain='CORNER')
        layer.data.foreach_set('color',colors[indices].ravel())
        data['source_vertex_color_state']=entry['color_buffer_state']

source=(root/'scripts/apply_iceland_texture_refresh.py').read_text(encoding='utf-8')
scope={'bpy':bpy,'Path':Path,'folder':folder,'images':{},'families':{},'re':re}
exec(source[source.index('def load_image'):source.index('\nfor path,definition in definitions.items()')],scope)
rvt_folder=out/'audit/road_rvt'
rvt_file='rvt_layer0_mip1.png'
if not (rvt_folder/rvt_file).exists():raise RuntimeError('Source RVT colour layer is missing')
volume=json.loads((out/'audit/road_rvt_volume.json').read_text(encoding='utf-8-sig'))
component=next(o['value']['Properties'] for o in volume if o['type']=='RuntimeVirtualTextureComponent')
position=component['RelativeLocation'];scale=component['RelativeScale3D']
if component.get('RelativeRotation'):raise RuntimeError('Rotated source RVT volume requires an explicit basis')
width,height=scale['X']/100,scale['Y']/100
min_x=position['X']/100-width/2
min_y=-position['Y']/100-height/2
def source_rvt(builder):
    coordinate=builder.coord((1/width,1/height),(-min_x/width,-min_y/height),world=True)
    sample=builder.texture(rvt_file,packed=True,coordinate=coordinate,base=rvt_folder)
    sample.extension='EXTEND'
    builder.links.new(sample.outputs['Color'],builder.shader.inputs['Base Color'])
    builder.material['source_rvt_albedo']='LandscapeRuntimeVT_Iceland_HD_EditorSVT layer 0 mip 1'
    builder.material['rvt_world_bounds_blender']=[min_x,min_y,min_x+width,min_y+height]
    return sample

replacements={};road_paths=set()
for path,definition in definitions.items():
    master=definition.get('MasterPath') or ''
    road='M_Road_2layerDetail_HD' in master
    cloth='WeatherCloth' in path and 'TwoLayerDiffuse' in master
    tank='IndustrialTtorageTanks_01' in path and 'MatBlend_Structures' in master
    if not (road or cloth or tank):continue
    material=scope['build_material'](path,definition)
    material['road_cloth_tank_revision']='source_RVT_vertex_masks_structure_UV1_cloth_detail'
    if road:
        # Attach the same coordinate projection to the newly built shader.
        class Existing:pass
        builder=Existing();builder.material=material;builder.nodes=material.node_tree.nodes;builder.links=material.node_tree.links
        builder.shader=next(n for n in builder.nodes if n.type=='BSDF_PRINCIPLED');builder.uv=None;builder.first_color=None
        for name in ['coord','texture']:setattr(builder,name,getattr(scope['Builder'],name).__get__(builder))
        source_rvt(builder);road_paths.add(path)
    replacements[path]=material
    report['materials'].append({'path':path,'category':'road' if road else 'cloth' if cloth else 'tank'})
for old in list(bpy.data.materials):
    path=old.get('unrealMaterialPath')
    if path in replacements and old!=replacements[path] and old.users:old.user_remap(replacements[path])

# Houdini placeholder materials are not invented lane paint: use the actual
# baked colour at each world position, retaining the original geometry.
proxy=scope['Builder']('SOURCE_RVT_Iceland_generated_road_proxy')
proxy.material['unrealMaterialPath']='/HoudiniEngine/houdini_default_material.houdini_default_material'
proxy.material['compatibility_rvt_proxy']=True
proxy.material['source_placeholder_replaced_with_baked_rvt']=True
source_rvt(proxy)
for obj in bpy.context.scene.objects:
    if obj.type!='MESH' or '/PCG/Iceland/Road/' not in obj.data.get('unrealAssetPath',''):continue
    for slot in obj.material_slots:
        if slot.material and slot.material.get('unrealMaterialPath')=='/HoudiniEngine/houdini_default_material.houdini_default_material':
            slot.link='OBJECT';slot.material=proxy.material;report['rvt_proxy_objects'].append(obj.name)

terrain=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('source')=='BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD')
ground=terrain.active_material
builder=scope['Builder']('SOURCE_RVT_Iceland_terrain_colour')
source_rvt(builder)
builder.shader.inputs['Roughness'].default_value=.85
builder.material['original_terrain_material']=ground.name if ground else ''
terrain.data.materials.clear();terrain.data.materials.append(builder.material)
for image in scope['images'].values():
    if not image.packed_file:image.pack()
report['rvt_projection']={'source_volume':component,'min_xy':[min_x,min_y],'size_xy':[width,height],
                          'colour_file':str(rvt_folder/rvt_file),'resolution':[8192,8192]}
report['terrain_object']=terrain.name
report['affected_objects']=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and any(s.material and s.material.get('unrealMaterialPath') in replacements for s in o.material_slots)]
report['limitations']='Source baked base colour restored. Exact dynamic RVT composition, water/weather, height/tint equations and normal layering remain compatibility approximations.'
report['file']=str(folder.parent/'Iceland_road_cloth_tank_fixed.blend')
(folder/'road_cloth_tank_application.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if report['failures']:raise RuntimeError('Source attributes could not be applied safely; see application report')
bpy.ops.wm.save_as_mainfile(filepath=report['file'],compress=True)
result={k:len(report[k]) for k in ['uv_meshes','authored_vertex_colour_meshes','default_vertex_colour_meshes','materials','rvt_proxy_objects','affected_objects','failures']}
result['file']=report['file']
