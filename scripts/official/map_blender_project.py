"""Portable Blender project helpers shared by save and reopen validation."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def signature(objects):
    rows=[]
    for obj in sorted(objects,key=lambda o:o.name):
        if obj.type!='MESH':continue
        mesh=obj.data
        vertices=np.empty(len(mesh.vertices)*3,np.float32);mesh.vertices.foreach_get('co',vertices)
        loops=np.empty(len(mesh.loops),np.int32);mesh.loops.foreach_get('vertex_index',loops)
        rows.append(dict(name=obj.name,mesh=mesh.name,vertices=hashlib.sha256(vertices.tobytes()).hexdigest(),
            topology=hashlib.sha256(loops.tobytes()).hexdigest(),matrix=[round(float(v),7) for row in obj.matrix_world for v in row],
            materials=[slot.material.name if slot.material else None for slot in obj.material_slots],
            hidden=bool(obj.hide_render),parent=obj.parent.name if obj.parent else None))
    return dict(mesh_objects=len(rows),sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest())


def suppress_hlod(bpy,source):
    from map_lod import covered_proxies
    file=Path(source)/'scene.json'
    if not file.is_file():return 0
    covered=covered_proxies(json.loads(file.read_text(encoding='utf-8-sig')).get('instances',[]))
    count=0
    for obj in bpy.context.scene.objects:
        meta=json.loads(obj.get('map_source','{}'))
        if meta.get('sourceId') in covered:
            obj.hide_render=True;obj.hide_set(True);count+=1
    return count


def inspection_view(bpy):
    from mathutils import Vector
    corners=[]
    for obj in bpy.context.scene.objects:
        if obj.type=='MESH' and not obj.hide_render:
            values=np.asarray(obj.bound_box)@np.asarray(obj.matrix_world)[:3,:3].T+np.asarray(obj.matrix_world)[:3,3]
            if np.isfinite(values).all() and np.ptp(values,axis=0).max()<30000:corners.extend(values)
    if not corners:raise ValueError('Blender project has no visible geometry')
    lo,hi=np.min(corners,axis=0),np.max(corners,axis=0)
    target=(lo+hi)/2;distance=max(float(np.linalg.norm(hi-lo)),2)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                space=area.spaces.active
                space.clip_start=.05;space.clip_end=max(100000,distance*20)
                space.region_3d.view_location=Vector(target)
                space.region_3d.view_distance=distance
                space.region_3d.view_rotation=Vector((1,-1,1)).to_track_quat('Z','Y')
                space.shading.type='SOLID';space.shading.color_type='MATERIAL'
    return dict(min=lo.tolist(),max=hi.tolist())


def source_lighting(bpy,path):
    from mathutils import Vector
    from map_lighting import records
    state=json.loads(Path(path).read_text(encoding='utf-8'))
    scene=bpy.context.scene
    world=bpy.data.worlds.new('AtlasMap source environment');world.use_nodes=True;scene.world=world
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(.12,.15,.19,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=.3
    created=0;unsupported=[]
    for identity,row in records(state):
        kind={'Point':'POINT','Spot':'SPOT','Rect':'AREA','Directional':'SUN'}.get(row['type'])
        if row['type']=='Sky':
            world.node_tree.nodes['Background'].inputs['Strength'].default_value=max(0,float(row.get('intensity',1)))
            continue
        if not kind:unsupported.append(row);continue
        light=bpy.data.lights.new(row.get('name') or identity,kind)
        light.color=row['color']
        intensity=max(0,float(row.get('intensity',1)))
        # Keep the exact UE record on the object; photometric engine units differ.
        light.energy=intensity if kind=='SUN' else intensity*.01
        if kind in ('POINT','SPOT'):light.shadow_soft_size=max(.01,float(row.get('sourceradius',0))/100)
        if kind=='SPOT':
            outer=float(row.get('outercone',44));inner=float(row.get('innercone',0))
            light.spot_size=math.radians(max(.1,min(179,outer*2)))
            light.spot_blend=1-min(1,inner/max(outer,.1))
        if kind=='AREA':
            light.shape='RECTANGLE';light.size=max(.01,float(row.get('sourcewidth',64))/100)
            light.size_y=max(.01,float(row.get('sourceheight',64))/100)
        obj=bpy.data.objects.new('AtlasMapLight_'+identity,light);scene.collection.objects.link(obj)
        obj.location=(row['loc'][0]/100,-row['loc'][1]/100,row['loc'][2]/100)
        pitch,yaw,_=map(math.radians,row['rot'])
        direction=Vector((math.cos(pitch)*math.cos(yaw),-math.cos(pitch)*math.sin(yaw),math.sin(pitch)))
        obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()
        obj['map_source_light']=json.dumps(row,ensure_ascii=False);created+=1
    return dict(created=created,unsupported=unsupported,photometric_compatibility='Blender energy approximation; original UE values preserved')
