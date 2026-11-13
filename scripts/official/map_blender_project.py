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
    """把源渲染状态里的灯搬进 Blender。

    强度单位按光度学换算（见 map_light_photometry）：以前点光乘 0.01、平行光原样搬，
    室内一片发白、室外又偏灰。这里同时补上衰减半径、天光颜色、太阳视角和色彩管理，
    让导出的工程一打开就接近游戏里的明暗关系。
    """
    from mathutils import Vector
    from map_lighting import records
    import map_light_photometry as photometry
    state=json.loads(Path(path).read_text(encoding='utf-8'))
    scene=bpy.context.scene
    world=bpy.data.worlds.new('AtlasMap source environment');world.use_nodes=True;scene.world=world
    # 节点名会随界面语言变化（中文版叫「背景」），按类型找，颜色/强度按插槽序号取
    tree=world.node_tree
    background=next((node for node in tree.nodes if node.type=='BACKGROUND'),None)
    if background is None:
        background=tree.nodes.new('ShaderNodeBackground')
        output=next((node for node in tree.nodes if node.type=='OUTPUT_WORLD'),None)
        if output is not None:tree.links.new(background.outputs[0],output.inputs['Surface'])
    world_color=background.inputs[0]
    world_strength=background.inputs[1]
    world_color.default_value=(.12,.15,.19,1)
    world_strength.default_value=.3
    created=0;unsupported=[]
    sun=0.0;sky_intensity=0.0;lamp_total=0.0;lamp_peak=0.0
    for identity,row in records(state):
        kind={'Point':'POINT','Spot':'SPOT','Rect':'AREA','Directional':'SUN'}.get(row['type'])
        if row['type']=='Sky':
            sky_intensity=max(0.0,float(row.get('intensity',0) or 0))
            color=[max(0.0,min(1.0,float(c))) for c in (row.get('color') or [1,1,1])]
            world_color.default_value=(color[0],color[1],color[2],1.0)
            world_strength.default_value=photometry.sky_strength(sky_intensity)
            continue
        if not kind:unsupported.append(row);continue
        light=bpy.data.lights.new(row.get('name') or identity,kind)
        light.color=row['color']
        intensity=max(0.0,float(row.get('intensity',1) or 0))
        if kind=='SUN':
            light.energy=photometry.sun_strength(intensity)
            # 平行光也带视直径：太小会出现刀切一样的硬阴影
            light.angle=photometry.sun_angle_radians(float(row.get('sourceangle',0.53) or 0))
            sun=max(sun,light.energy)
        else:
            light.energy=photometry.lamp_watts(intensity)
            lamp_total+=light.energy;lamp_peak=max(lamp_peak,light.energy)
        light.use_shadow=bool(row.get('castshadows',True))
        radius=photometry.cutoff_meters(float(row.get('radius',0) or 0))
        if kind in ('POINT','SPOT','AREA') and radius>.05:
            # UE 的衰减半径在 Blender 里对应自定义距离，不设的话远处的灯会照到不该照的地方
            light.use_custom_distance=True;light.cutoff_distance=radius
        if kind in ('POINT','SPOT'):light.shadow_soft_size=max(.01,float(row.get('sourceradius',0) or 0)/100)
        if kind=='SPOT':
            outer=float(row.get('outercone',44) or 44);inner=float(row.get('innercone',0) or 0)
            light.spot_size=math.radians(max(.1,min(179,outer*2)))
            light.spot_blend=1-min(1,inner/max(outer,.1))
        if kind=='AREA':
            light.shape='RECTANGLE';light.size=max(.01,float(row.get('sourcewidth',64) or 64)/100)
            light.size_y=max(.01,float(row.get('sourceheight',64) or 64)/100)
        obj=bpy.data.objects.new('AtlasMapLight_'+identity,light);scene.collection.objects.link(obj)
        obj.location=(row['loc'][0]/100,-row['loc'][1]/100,row['loc'][2]/100)
        pitch,yaw,_=map(math.radians,row['rot'])
        direction=Vector((math.cos(pitch)*math.cos(yaw),-math.cos(pitch)*math.sin(yaw),math.sin(pitch)))
        obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()
        obj['map_source_light']=json.dumps(row,ensure_ascii=False);created+=1
    # 色彩管理：AgX 保住高光的颜色，曝光按主光强度回落，避免一打开全是白的
    try:
        scene.view_settings.view_transform='AgX'
    except TypeError:
        pass
    for look in ('AgX - Medium High Contrast','AgX - Punchy'):
        try:
            scene.view_settings.look=look
            break
        except TypeError:
            continue
    exposure=0.0 if sun<=0 else max(-3.0,min(2.0,-math.log2(max(sun,0.01)/3.0)))
    scene.view_settings.exposure=exposure
    return dict(created=created,unsupported=unsupported,
        photometric_compatibility='Lumens/lux → watts via 683 lm/W; original UE values kept on each object',
        sun_strength=sun,sky_strength=photometry.sky_strength(sky_intensity),
        lamp_peak_watt=lamp_peak,lamp_total_watt=lamp_total,exposure_ev=exposure,
        cutoff_applied=True,colour_management='AgX · Medium High Contrast')
