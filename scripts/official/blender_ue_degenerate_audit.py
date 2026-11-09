import bpy,json,numpy as np
from pathlib import Path
root=Path('D:/AtlasMap-tooling/out/Iceland/ue_transfer/20261031')
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
rows=[]
for row in manifest['meshes']:
    data=bpy.data.meshes[row['source_name']]
    vertices=np.empty(len(data.vertices)*3,np.float32);data.vertices.foreach_get('co',vertices);vertices=vertices.reshape(-1,3)
    indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices);indices=indices.reshape(-1,3)
    faces=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',faces)
    positions=vertices[indices].astype(np.float64)
    cross=np.cross(positions[:,1]-positions[:,0],positions[:,2]-positions[:,0])
    area=np.linalg.norm(cross,axis=1)
    exact=area==0
    if exact.any():
        row['zero_area_triangles']=int(exact.sum())
        row['zero_area_face_slot_counts']={str(i):int(np.count_nonzero(exact&(faces==i))) for i in sorted(set(faces[exact]))}
        rows.append({'mesh':row['id'],'name':row['source_name'],'exact_zero':int(exact.sum()),'tiny_counts':{str(t):int(np.count_nonzero(area<t)) for t in [1e-15,1e-12,1e-10,1e-8]},'per_slot':row['zero_area_face_slot_counts']})
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(root/'validation/degenerate_source_audit.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2),flush=True)
