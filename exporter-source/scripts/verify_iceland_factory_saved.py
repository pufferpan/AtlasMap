"""Validate the saved red factory against native material tables and UV buffers."""
import bpy
import hashlib
import json
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling/out/Iceland')
application=json.loads((root/'revised/material_refresh/factory_repair_application.json').read_text())
bundle=json.loads((root/'revised/common_static_repair/repair_bundle.json').read_text())
by_asset={row['asset']:row for row in bundle['meshes']}
uvs={row['asset']:row for row in json.loads((root/'audit/floor_attributes/attributes.json').read_text())}
failures=[];checked=[];materials=set()
for name in application['affected_objects']:
    obj=bpy.data.objects.get(name)
    if obj is None:failures.append({'object':name,'reason':'object missing'});continue
    data=obj.data;asset=data.get('unrealAssetPath');entry=by_asset[asset]
    indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
    if hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest()!=entry['index_sha256']:
        failures.append({'object':name,'reason':'topology differs'})
    face_slots=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',face_slots)
    source_slots=np.array(entry['used_source_slots'])
    expected=np.fromfile(root/'revised/common_static_repair'/entry['face_material_file'],'<u2')
    if np.any(face_slots>=len(source_slots)) or not np.array_equal(source_slots[face_slots],expected):
        failures.append({'object':name,'reason':'face-material assignments differ'})
    for index,source_slot in enumerate(source_slots):
        if obj.material_slots[index].material.get('unrealMaterialPath')!=entry['materials'][source_slot]:
            failures.append({'object':name,'reason':'material reference differs','slot':index})
    if asset in uvs:
        for channel,file in enumerate(uvs[asset]['uv_files']):
            name_uv='UVMap' if channel==0 else f'UV{channel}'
            actual=np.empty(len(data.loops)*2,np.float32);data.uv_layers[name_uv].data.foreach_get('uv',actual)
            source=np.fromfile(root/'audit/floor_attributes'/file,'<f4').reshape(-1,2).copy();source[:,1]=1-source[:,1]
            if not np.array_equal(actual.reshape(-1,2),source[indices]):failures.append({'object':name,'reason':'authored UV differs','channel':channel})
    for slot in obj.material_slots:
        material=slot.material
        if not material or material.get('unrealMaterialPath') not in application['materials']:continue
        materials.add(material.name)
        nodes=material.node_tree.nodes
        mask=next(n for n in nodes if n.type=='TEX_IMAGE' and n.image and '_Mask_HD' in n.image.name)
        binding=mask.inputs['Vector'].links[0].from_node
        if binding.type!='UVMAP' or binding.uv_map!='UV1':failures.append({'material':material.name,'reason':'mask not bound to UV1'})
        shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        for socket in ['Base Color','Normal','Roughness','Metallic']:
            if not shader.inputs[socket].is_linked:failures.append({'material':material.name,'reason':'missing '+socket})
        for node in nodes:
            if node.type=='TEX_IMAGE' and node.image and not node.image.packed_file:failures.append({'material':material.name,'reason':'unpacked texture','image':node.image.name})
    checked.append({'object':obj.name,'triangles':len(data.polygons),'slots':len(obj.material_slots),'uv_channels':len(data.uv_layers)})
report={'file':bpy.data.filepath,'objects':checked,'materials_checked':len(materials),'failures':failures}
(root/'revised/material_refresh/factory_saved_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
assert not failures
result=report
