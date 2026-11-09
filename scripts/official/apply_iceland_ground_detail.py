"""Preserve baked road colour while restoring source near-surface detail."""
import bpy
import json
import re
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling')
out=root/'out/Iceland'
folder=out/'revised/ground_detail'
source=json.loads((folder/'ground_detail_sources.json').read_text())
builder_source=(root/'scripts/apply_iceland_texture_refresh.py').read_text()
scope={'bpy':bpy,'Path':Path,'folder':folder,'images':{},'families':{},'re':re}
exec(builder_source[builder_source.index('def load_image'):builder_source.index('\nfor path,definition in definitions.items()')],scope)
terrain=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('source')=='BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD')
old=terrain.active_material
macro=next(n.image for n in old.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'rvt_layer0_mip1' in n.image.name)
projection=json.loads((out/'revised/material_refresh/road_cloth_tank_application.json').read_text())['rvt_projection']
b=scope['Builder']('Iceland ground - baked colour plus source near detail')
size=projection['size_xy'];minimum=projection['min_xy']
coordinate=b.coord((1/size[0],1/size[1]),(-minimum[0]/size[0],-minimum[1]/size[1]),world=True)
macro_node=b.nodes.new('ShaderNodeTexImage');macro_node.image=macro;macro_node.extension='EXTEND'
b.links.new(coordinate,macro_node.inputs['Vector'])

width,height=source['weight_image_size']
weights=[]
weight_uv=b.coord((1/width,1/height),(.5/width,1.5/height),world=True)
for file in source['weight_files']:
    sample=b.texture(file,True,True,weight_uv);sample.interpolation='Linear';sample.extension='EXTEND'
    channels=b.split(sample)
    weights.extend([channels['Red'],channels['Green'],channels['Blue'],sample.outputs['Alpha']])
weights=weights[:10]
total=0
for weight in weights:total=b.math('ADD',total,weight)
denominator=b.math('MAXIMUM',total,.0001)
coverage=b.math('MINIMUM',total,1)
detail=(0,0,0,1);normals=(0,0,0,1)
for layer,weight in zip(source['layers'],weights):
    uv=b.coord((layer['tiling'],layer['tiling']),world=True)
    normal=b.texture(layer['normal'],True,True,uv)
    tile=b.texture(layer['colour_detail'],True,True,uv)
    tile.label='Source colour detail layer '+str(layer['index'])
    normal.label='Source normal XY layer '+str(layer['index'])
    factor=b.math('DIVIDE',weight,denominator)
    contribution=b.mix(b.mix(tile.outputs['Color'],layer['ratio_decode_scale'],1,'MULTIPLY'),factor,1,'MULTIPLY')
    detail=b.mix(detail,contribution,1,'ADD')
    normals=b.mix(normals,b.mix(normal.outputs['Color'],factor,1,'MULTIPLY'),1,'ADD')
detail=b.mix((1,1,1,1),detail,coverage)
colour=b.mix(macro_node.outputs['Color'],detail,1,'MULTIPLY')
b.links.new(colour,b.shader.inputs['Base Color'])
normals=b.mix((.5,.5,1,1),normals,coverage)
split=b.nodes.new('ShaderNodeSeparateColor');b.links.new(normals,split.inputs['Color'])
x=b.math('SUBTRACT',b.math('MULTIPLY',split.outputs['Red'],2),1)
y=b.math('SUBTRACT',b.math('MULTIPLY',split.outputs['Green'],2),1)
length=b.math('ADD',b.math('MULTIPLY',x,x),b.math('MULTIPLY',y,y))
z=b.math('ADD',b.math('MULTIPLY',b.math('SQRT',b.math('MAXIMUM',b.math('SUBTRACT',1,length),0)),.5),.5)
encoded=b.nodes.new('ShaderNodeCombineColor')
b.links.new(split.outputs['Red'],encoded.inputs['Red'])
# UE world Y is reflected into Blender world Y, including normal-map handedness.
b.links.new(b.math('SUBTRACT',1,split.outputs['Green']),encoded.inputs['Green'])
b.links.new(z,encoded.inputs['Blue'])

data=terrain.data
if data.uv_layers.get('GroundWorldUV') is None:
    vertices=np.empty(len(data.vertices)*3,np.float32);data.vertices.foreach_get('co',vertices);vertices=vertices.reshape(-1,3)
    indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
    uv=vertices[:,:2]/4032
    layer=data.uv_layers.new(name='GroundWorldUV');layer.data.foreach_set('uv',uv[indices].ravel())
normal_map=b.nodes.new('ShaderNodeNormalMap');normal_map.uv_map='GroundWorldUV'
b.links.new(encoded.outputs[0],normal_map.inputs['Color']);b.links.new(normal_map.outputs['Normal'],b.shader.inputs['Normal'])
b.shader.inputs['Roughness'].default_value=.85
b.material['source_rvt_albedo']='LandscapeRuntimeVT_Iceland_HD_EditorSVT layer 0 mip 1'
b.material['source_ground_detail_layers']=10
b.material['ground_detail_revision']='source_normal_XY_and_high_pass_albedo_bilinear_G16_weights'
b.material['approximation']='Source colour/normal inputs restored; exact game height blends and weather remain approximations. No guessed packed roughness channel.'
terrain.data.materials[0]=b.material

road_folder=out/'revised/road_detail'
roads=json.loads((road_folder/'road_detail_sources.json').read_text())['materials']
road_changes=[]
for entry in roads:
    for material in bpy.data.materials:
        if not material.users or material.get('unrealMaterialPath')!=entry['material'] or not material.get('source_rvt_albedo'):continue
        nodes,links=material.node_tree.nodes,material.node_tree.links
        shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        old_colour=shader.inputs['Base Color'].links[0].from_socket
        uv=nodes.new('ShaderNodeUVMap');uv.uv_map='UVMap'
        texture=nodes.new('ShaderNodeTexImage');texture.image=scope['load_image'](road_folder/entry['colour_detail'],True,True)
        links.new(uv.outputs['UV'],texture.inputs['Vector'])
        decode=nodes.new('ShaderNodeMixRGB');decode.blend_type='MULTIPLY';decode.inputs[0].default_value=1;decode.inputs[2].default_value=(4,4,4,1)
        links.new(texture.outputs['Color'],decode.inputs[1])
        multiply=nodes.new('ShaderNodeMixRGB');multiply.blend_type='MULTIPLY';multiply.inputs[0].default_value=1
        links.new(old_colour,multiply.inputs[1]);links.new(decode.outputs[0],multiply.inputs[2]);links.new(multiply.outputs[0],shader.inputs['Base Color'])
        for node in nodes:
            if node.type!='TEX_IMAGE' or not node.image:continue
            name=Path(bpy.path.abspath(node.image.filepath)).name
            if name==Path(entry['original_normal_file']).name:
                node.image=scope['load_image'](road_folder/entry['normal'],True,True)
            if name==Path(entry['original_hra_file']).name:
                node.image=scope['load_image'](road_folder/entry['hra'],True,True)
        material['road_near_detail_restored']=True;road_changes.append(entry['material'])

# The remaining visible Cube is authored geometry with a component material override.
wall_folder=out/'revised/helper_wall_material'
wall_document=json.loads((wall_folder/'material_refresh.json').read_text())
wall_path,wall_definition=next(iter(wall_document['materials'].items()))
wall_scope={'bpy':bpy,'Path':Path,'folder':wall_folder,'images':{},'families':{},'re':re}
exec(builder_source[builder_source.index('def load_image'):builder_source.index('\nfor path,definition in definitions.items()')],wall_scope)
wall_material=wall_scope['build_material'](wall_path,wall_definition)
wall=bpy.data.objects.get('Engine/Content/BasicShapes/Cube.Cube.036')
if wall:
    wall.material_slots[0].link='OBJECT';wall.material_slots[0].material=wall_material
    wall['native_component_material_override']=wall_path
    wall['source_visible_wall']=True
for image in [*scope['images'].values(),*wall_scope['images'].values()]:
    if not image.packed_file:image.pack()
report={'terrain':terrain.name,'ground_material':b.material.name,'colour_layers':10,'normal_layers':10,
        'ground_effective_texels_per_metre':[l['effective_albedo_texels_per_metre'] for l in source['layers']],
        'macro_rvt_texels_per_metre':8192/4033,'weight_quantization_error':source['maximum_weight_quantization_error'],
        'road_materials':road_changes,'wall_material_override':wall_path,'wall_object':wall.name if wall else None,
        'source_ground_detail_manifest':str(folder/'ground_detail_sources.json'),
        'file':str(out/'revised/Iceland_ground_detail_helpers_fixed.blend')}
(out/'revised/material_refresh/ground_detail_application.json').write_text(json.dumps(report,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=report['file'],compress=True)
result=report
