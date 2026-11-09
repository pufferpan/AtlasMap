"""Import source HDR probes and restore their authored spatial influence."""
import hashlib
import json
import math
import os
import re
import struct
from pathlib import Path

import unreal
from map_environment import (ambient_weights,bind_reflections,native_intensity,select_sky,
    select_authored_sky_cube,known_source_sky_rows,sky_actor_matches)
from map_lighting import records as light_records

TAG='AtlasMapEnvironment_'


def _import(root,relative,destination,source):
    base=root.resolve();file=(base/relative).resolve()
    if not file.is_relative_to(base) or not file.is_file():raise ValueError('Invalid environment texture: '+relative)
    digest=hashlib.sha256(file.read_bytes()).hexdigest()
    name='T_Source_'+hashlib.sha256((relative+source).encode()).hexdigest()[:20]
    path=destination+'/'+name
    texture=unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if texture is None or unreal.EditorAssetLibrary.get_metadata_tag(texture,'AtlasMapEnvironmentSHA256')!=digest:
        task=unreal.AssetImportTask();task.filename=str(file);task.destination_path=destination
        task.destination_name=name;task.automated=True;task.replace_existing=True;task.save=True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        texture=next((obj for obj in task.get_objects() if obj.get_path_name().split('.')[0]==path),None)
        if texture is None:raise RuntimeError('Failed to import source environment: '+str(file))
        unreal.EditorAssetLibrary.set_metadata_tag(texture,'AtlasMapEnvironmentSHA256',digest)
        unreal.EditorAssetLibrary.set_metadata_tag(texture,'AtlasMapSourceEnvironment',source)
    if isinstance(texture,unreal.TextureCube):
        texture.set_editor_property('srgb',False)
        texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_HDR)
        with file.open('rb') as reader:header=reader.read(128)
        if header[:4]==b'DDS ' and len(header)>=32 and struct.unpack_from('<I',header,28)[0]>1:
            texture.set_editor_property('mip_gen_settings',unreal.TextureMipGenSettings.TMGS_LEAVE_EXISTING_MIPS)
    texture.set_editor_property('never_stream',True)
    if not unreal.EditorAssetLibrary.save_loaded_asset(texture):raise RuntimeError('Cannot save '+path)
    return texture


def _spawn(eas,old,cls,key,location):
    tag=TAG+key;actor=old.get(tag)
    if actor is None:
        from ue_actor_spawn import spawn_actor
        actor=spawn_actor(unreal,cls,unreal.Vector(*location))
    if actor is None:raise RuntimeError('Cannot create source environment actor: '+key)
    actor.tags=[unreal.Name(tag)];actor.set_folder_path('AtlasMap/SourceEnvironment')
    actor.set_actor_location(unreal.Vector(*location),False,True)
    return actor


def _post_component(actor,shape):
    component=actor.get_component_by_class(unreal.PostProcessComponent)
    if component is None:
        system=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        handles=system.k2_gather_subobject_data_for_instance(actor)
        handle,reason=system.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=handles[0],new_class=unreal.PostProcessComponent))
        component=unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle))
        if component is None:raise RuntimeError('Cannot create source ambient volume: '+str(reason))
    component.attach_to_component(shape,'',unreal.AttachmentRule.KEEP_RELATIVE,unreal.AttachmentRule.KEEP_RELATIVE,unreal.AttachmentRule.KEEP_RELATIVE,False)
    component.set_editor_property('unbound',False)
    component.set_editor_property('priority',-90.0)
    return component


def _sky_material(texture,descriptor,destination):
    name='M_SourceSky_'+hashlib.sha256(descriptor['source_texture'].encode()).hexdigest()[:16]
    path=destination+'/'+name
    material=unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if material is None:material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,destination,unreal.Material,unreal.MaterialFactoryNew())
    lib=unreal.MaterialEditingLibrary;lib.delete_all_material_expressions(material)
    material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property('two_sided',True);material.set_editor_property('is_sky',True)
    camera=lib.create_material_expression(material,unreal.MaterialExpressionCameraVectorWS,-900,0)
    uv=lib.create_material_expression(material,unreal.MaterialExpressionCustom,-650,0)
    entry=unreal.CustomInput();entry.set_editor_property('input_name','D');uv.set_editor_property('inputs',[entry])
    cube=isinstance(texture,unreal.TextureCube)
    uv.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3 if cube else unreal.CustomMaterialOutputType.CMOT_FLOAT2)
    uv.set_editor_property('code','return normalize(-D);' if cube else 'float3 d=normalize(-D);return float2(atan2(d.y,d.x)/6.28318530718+0.5,acos(clamp(d.z,-1.0,1.0))/3.14159265359);')
    lib.connect_material_expressions(camera,'',uv,'D')
    sample=lib.create_material_expression(material,unreal.MaterialExpressionTextureSample,-400,0)
    sample.set_editor_property('texture',texture)
    sample.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR if cube or not descriptor.get('srgb',True) else unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    lib.connect_material_expressions(uv,'',sample,'UVs')
    brightness=descriptor.get('parameters',{}).get('ScalarParameters',{}).get('Brightness (S)',1)
    brightness*=float(descriptor.get('native_display_unit_coefficient',1))
    multiply=lib.create_material_expression(material,unreal.MaterialExpressionMultiply,-150,0)
    multiply.set_editor_property('const_b',float(brightness))
    if not lib.connect_material_expressions(sample,'',multiply,'A'):raise RuntimeError('Source sky texture RGB connection failed')
    if not lib.connect_material_property(multiply,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR):raise RuntimeError('Source sky emissive connection failed')
    lib.recompile_material(material);unreal.EditorAssetLibrary.save_loaded_asset(material)
    return material


def _configure_sky_component(component,material):
    component.set_material(0,material);component.set_editor_property('cast_shadow',False)
    component.set_editor_property('affect_distance_field_lighting',False)
    component.set_editor_property('visible_in_ray_tracing',False)
    component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    if component.get_material(0)!=material:raise RuntimeError('Source sky material readback differs')
    for field in ('cast_shadow','affect_distance_field_lighting','visible_in_ray_tracing'):
        if component.get_editor_property(field):raise RuntimeError('Source sky visibility readback differs: '+field)


def _sky(eas,old,texture,descriptor,destination,center,span):
    material=_sky_material(texture,descriptor,destination)
    actor=_spawn(eas,old,unreal.StaticMeshActor,'sky',center)
    component=actor.static_mesh_component;component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Sphere'))
    _configure_sky_component(component,material)
    scale=max(span*4,1000000)/50;actor.set_actor_scale3d(unreal.Vector(scale,scale,scale))
    actor.set_actor_label('AtlasMap Source Sky · '+descriptor['source_texture'].split('/')[-1])


def _existing_sky_fallback(root,data,global_data,environment,eas,sky_source,destination):
    """Replace only an audited existing sky placeholder; no spawned geometry."""
    state={'kind':'source_cubemap_display_fallback','applied':[],
           'high_resolution_sky_restored':False,'warnings':[]}
    descriptor=select_authored_sky_cube(environment,(global_data or data).get('lights',[]))
    if descriptor is None:
        state['warnings'].append('No unique exact SkyLight.Cubemap descriptor; existing geometry not changed')
        return state
    # Keep a source HDR ambient cube in the same native display units as the
    # restored physical exposure. This is an explicit compatibility mapping.
    try:
        from map_exposure import build_plan
    except ModuleNotFoundError:
        from scripts.official.map_exposure import build_plan
    exposure=build_plan(global_data or data,Path(sky_source).parent,False)
    coefficient=exposure.get('source_ibl_coefficient') if exposure.get('eligible') else None
    if coefficient is not None:
        descriptor={**descriptor,'native_display_unit_coefficient':coefficient}
        state['native_display_unit_coefficient']=coefficient
    scene_path=Path(root)/'scene.json'
    if not scene_path.is_file():
        state['warnings'].append('Source scene identity unavailable; existing geometry not changed')
        return state
    rows=known_source_sky_rows(json.loads(scene_path.read_text(encoding='utf-8-sig')))
    actors=list(eas.get_all_level_actors())
    for row in rows:
        source_id=row['dfmap']['sourceId'];matches=[]
        for actor in actors:
            # The import pipeline names each object with its exact source ID,
            # optionally prefixed by its chunk ID. Do not match name fragments.
            if sky_actor_matches(source_id,actor.get_actor_label(),{}):matches.append(actor)
        if len(matches)!=1:
            state['warnings'].append('Audited sky source ID has no unique actor: '+source_id)
            continue
        actor=matches[0]
        if not isinstance(actor,unreal.StaticMeshActor):
            state['warnings'].append('Audited sky actor is not a static mesh: '+source_id);continue
        component=actor.static_mesh_component
        if not component.get_editor_property('visible') or actor.get_editor_property('hidden'):
            state['warnings'].append('Audited sky actor is hidden; source visibility retained: '+source_id);continue
        transform=actor.get_actor_transform()
        texture=_import(sky_source,descriptor['texture']['RelativePath'],destination,descriptor['source_texture'])
        if not isinstance(texture,unreal.TextureCube):raise RuntimeError('Fallback sky input is not a cube')
        material=_sky_material(texture,descriptor,destination)
        _configure_sky_component(component,material)
        if actor.get_actor_transform()!=transform:raise RuntimeError('Sky fallback changed the source transform')
        state['applied'].append({'source_id':source_id,'actor':actor.get_path_name(),
            'source_cube':descriptor['source_texture'],'material':material.get_path_name(),
            'resolution':[descriptor['texture']['Width'],descriptor['texture']['Height']],
            'transform_and_source_tags_preserved':True})
    if state['applied']:
        state['warnings'].append('Native HDR cubemap display fallback; not the high-resolution visible sky')
    elif not rows:state['warnings'].append('No strictly identified source SkyDomeMesh placeholder in this chunk')
    return state


def restore(root,data,eas,report,center,span,primary=True,ambient_enabled=True,global_root=None,global_data=None):
    source=root/'source-render'
    sky_source=Path(global_root or root)/'source-render'
    environment=(global_data or data).get('environment',{})
    destination=os.environ.get('ATLASMAP_UE_DEST','/Game/AtlasMaps/Map').rstrip('/')+'/Environment'
    old={str(tag):a for a in eas.get_all_level_actors() for tag in a.tags if str(tag).startswith(TAG)}
    state={'source_reflections':len(data.get('reflection_captures',[])),'restored':[],
           'sky':None,'unsupported':[],'ambient_mapping':'Source capture average brightness normalized to native local ambient cubemap; custom PRT visibility is retained, not reconstructed.'}
    rows=bind_reflections(data.get('reflection_captures',[]),data.get('reflection_cubemaps',{}))
    weights=ambient_weights(data.get('reflection_captures',[]))
    wanted=set()
    for capture in data.get('reflection_captures',[]):
        guid=capture['guid'];props=capture['properties'];payload=rows.get(guid)
        if capture['type']!='SphereReflectionCaptureComponent':
            state['unsupported'].append({'guid':guid,'reason':'Source box reflection bounds require a dedicated mapping'})
            continue
        if payload is None:
            state['unsupported'].append({'guid':guid,'reason':'Source reflection cube is unavailable; cooked data retained'})
            continue
        texture=_import(source,payload['texture'],destination,payload['source']+'#'+guid)
        if not isinstance(texture,unreal.TextureCube):raise RuntimeError('Source reflection was not imported as TextureCube')
        brightness=native_intensity(payload,props)
        key='reflection_'+guid;wanted.add(TAG+key)
        sphere=_spawn(eas,old,unreal.SphereReflectionCapture,key,capture['loc'])
        comp=sphere.get_component_by_class(unreal.SphereReflectionCaptureComponent)
        comp.set_editor_property('reflection_source_type',unreal.ReflectionSourceType.SPECIFIED_CUBEMAP)
        comp.set_editor_property('cubemap',texture)
        comp.set_editor_property('brightness',brightness)
        radius=max(1,float(props.get('InfluenceRadius',3000)))
        comp.set_editor_property('influence_radius',radius)
        sphere.set_actor_label('AtlasMap Source Reflection '+guid[:8])
        if ambient_enabled:
            ambient_key='ambient_'+guid;wanted.add(TAG+ambient_key)
            ambient=_spawn(eas,old,unreal.TriggerSphere,ambient_key,capture['loc'])
            shape=ambient.get_component_by_class(unreal.SphereComponent);shape.set_sphere_radius(radius,False)
            shape.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            pp=_post_component(ambient,shape)
            pp.set_editor_property('blend_radius',min(radius*.25,500))
            pp.set_editor_property('blend_weight',weights[guid])
            settings=pp.get_editor_property('settings')
            settings.set_editor_property('ambient_cubemap',texture)
            settings.set_editor_property('override_ambient_cubemap_intensity',True)
            settings.set_editor_property('ambient_cubemap_intensity',brightness)
            pp.set_editor_property('settings',settings)
            ambient.set_actor_label('AtlasMap Source Ambient '+guid[:8])
            if pp.get_attach_parent()!=shape:raise RuntimeError('Source ambient bounds readback differs')
        if comp.get_editor_property('cubemap')!=texture:raise RuntimeError('Source environment readback differs')
        state['restored'].append({'guid':guid,'texture':texture.get_path_name(),'radius':radius,
            'source_average_brightness':payload['average_brightness'],'native_intensity':brightness,
            'ambient_overlap_weight':weights[guid] if ambient_enabled else 0})
    # Each chunk binds its own sky light to the exact referenced source cube.
    # The one shared backdrop uses the merged catalogue, including resources
    # discovered in other chunks.
    actors_by_tag={str(t):a for a in eas.get_all_level_actors() for t in a.tags}
    def reference_path(reference):
        path=reference.get('ObjectPath','');name=reference.get('ObjectName','')
        quoted=re.search(r"'([^']+)'",name)
        if quoted:path=path.split('.')[0]+'.'+quoted[1].split(':')[-1].split('.')[-1]
        return path.removeprefix('/Game/').lower()
    for key,light in light_records(data):
        if light['type']!='Sky':continue
        props=light.get('source',{}).get('properties',{})
        reference=props.get('Cubemap') or props.get('CubeMap') or {}
        if not reference:continue
        wanted_texture=reference_path(reference)
        matches=[r for r in environment.get('skies',[]) if r.get('kind')=='cube' and
            (r.get('source_texture','').removeprefix('/Game/').lower()==wanted_texture or
             r.get('source_texture','').lower()=='deltaforce/content/'+wanted_texture)]
        actor=actors_by_tag.get('AtlasMapLighting_'+key)
        if len(matches)==1 and actor is not None:
            cube=_import(sky_source,matches[0]['texture']['RelativePath'],destination,matches[0]['source_texture'])
            comp=actor.get_component_by_class(unreal.SkyLightComponent)
            comp.set_editor_property('source_type',unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
            comp.set_editor_property('cubemap',cube);comp.set_editor_property('real_time_capture',False)
        else:state['unsupported'].append({'sky_light':light.get('name'),'reason':'Authored cubemap is unavailable or ambiguous'})
    descriptor=select_sky(environment)
    low_detail_cube=descriptor is not None and descriptor.get('kind')=='cube' and descriptor.get('texture',{}).get('Width',0)<=128
    if descriptor is None or low_detail_cube:
        # This runs for every chunk: the audited source dome may belong to a
        # later chunk than the primary environment. No extra sphere is spawned.
        fallback=_existing_sky_fallback(root,data,global_data,environment,eas,sky_source,destination)
        state['sky_display_fallback']=fallback
        if fallback['applied']:state['sky']=fallback
        elif primary:state['sky']='No unique high-resolution sky or auditable source dome; existing geometry retained'
    elif primary:
        texture=_import(sky_source,descriptor['texture']['RelativePath'],destination,descriptor['source_texture'])
        if not isinstance(texture,unreal.TextureCube):
            texture.set_editor_property('srgb',bool(descriptor.get('srgb',True)))
            texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_EDITOR_ICON)
            unreal.EditorAssetLibrary.save_loaded_asset(texture)
        _sky(eas,old,texture,descriptor,destination,center,span)
        wanted.add(TAG+'sky');state['sky']={'source':descriptor['source_texture'],'basis':descriptor['selection_basis']}
    for tag,actor in old.items():
        if tag not in wanted and (primary or tag!=TAG+'sky'):eas.destroy_actor(actor)
    report['source_environment']=state
