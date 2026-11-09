"""Resumable UE 5.4 import of the accepted Blender scene and material graph plan."""
import json
import re
import time
import traceback
from pathlib import Path
import unreal
from map_geometry import expected_triangles as source_triangle_count

import os as _os
ROOT=Path(_os.environ.get('ATLASMAP_UE_ROOT') or 'D:/AtlasMap-tooling/out/Iceland/ue_transfer/20261031')
MANIFEST=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
PLAN=json.loads((ROOT/'material_plan.json').read_text(encoding='utf-8'))
INSTANCE_PLAN=json.loads((ROOT/'material_instance_plan.json').read_text(encoding='utf-8'))
DEST=MANIFEST['ue_root']
IMAGES={r['id']:r for r in MANIFEST['images']}
MESHES={r['id']:r for r in MANIFEST['meshes']}
MATERIALS={r['id']:r for r in PLAN['materials']}
_handle=None
_state={}
_assets={}
_actors={}
_busy=False
_scalar_defaults={}
_pending_saves={}
_last_persist=0.0
INPUT_HASHES={}
BATCH_SAVE=_os.environ.get('ATLASMAP_UE_BATCH_SAVE','0')=='1'

def package(kind,identifier):return DEST+'/'+kind+'/'+identifier
def asset(kind,identifier):
    path=package(kind,identifier)
    if path not in _assets:
        obj=unreal.load_asset(path)
        if not obj:raise RuntimeError('Missing asset '+path)
        _assets[path]=obj
    return _assets[path]
def metadata(obj,key,value):unreal.EditorAssetLibrary.set_metadata_tag(obj,key,str(value))
def save(obj):
    if BATCH_SAVE:
        _pending_saves[obj.get_path_name()]=obj
        if len(_pending_saves)>=32:flush_saves()
        return
    if not unreal.EditorAssetLibrary.save_loaded_asset(obj,only_if_is_dirty=True):raise RuntimeError('Save failed '+obj.get_path_name())

def flush_saves():
    if not _pending_saves:return
    objects=list(_pending_saves.values())
    if not unreal.EditorAssetLibrary.save_loaded_assets(objects,only_if_is_dirty=True):
        raise RuntimeError('Batch save failed: '+', '.join(obj.get_path_name() for obj in objects[:3]))
    _pending_saves.clear()

def persist(force=False):
    global _last_persist
    if not force and time.monotonic()-_last_persist<.5:return
    _last_persist=time.monotonic()
    _state['updated']=time.time()
    temporary=ROOT/'ue_pipeline_status.tmp'
    temporary.write_text(json.dumps(_state,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(ROOT/'ue_pipeline_status.json')
def import_task(filename,destination,name,options=None,factory=None):
    task=unreal.AssetImportTask();task.filename=str(filename);task.destination_path=destination;task.destination_name=name
    task.automated=True;task.replace_existing=True;task.save=False
    if options is not None:task.options=options
    if factory is not None:task.factory=factory
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths=list(task.imported_object_paths)
    if not paths:raise RuntimeError('No imported object for '+str(filename))
    return unreal.load_asset(paths[0])

def fbx_options():
    options=unreal.FbxImportUI();options.automated_import_should_detect_type=False
    options.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH
    options.import_as_skeletal=False;options.import_materials=False;options.import_textures=False
    data=options.static_mesh_import_data
    for key,val in {'combine_meshes':True,'auto_generate_collision':False,'generate_lightmap_u_vs':False,
        'remove_degenerates':False,'convert_scene':False,'convert_scene_unit':False,'force_front_x_axis':False,
        'transform_vertex_to_absolute':True,'reorder_material_to_fbx_order':True,
        'vertex_color_import_option':unreal.VertexColorImportOption.REPLACE,
        'normal_import_method':unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS}.items():
        data.set_editor_property(key,val)
    return options

def cached_texture(row):
    path=package('Textures',row['id'])
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        obj=unreal.load_asset(path)
        if unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderSHA256')==row['sha256']:
            _assets[path]=obj;return obj
    return None

def finish_texture(row,obj):
    path=package('Textures',row['id'])
    properties={'compression_settings':unreal.TextureCompressionSettings.TC_EDITOR_ICON,
        'srgb':row['srgb'],'compression_no_alpha':False,
        'mip_gen_settings':unreal.TextureMipGenSettings.TMGS_SIMPLE_AVERAGE,
        'lod_group':unreal.TextureGroup.TEXTUREGROUP_CINEMATIC,'lod_bias':0,
        'max_texture_size':max(row['size']),'filter':unreal.TextureFilter.TF_BILINEAR}
    if max(row['size'])>=4034:properties['never_stream']=True
    obj.set_editor_properties(properties)
    if bool(obj.get_editor_property('srgb'))!=row['srgb']:raise RuntimeError('Texture colour space rejected '+path)
    metadata(obj,'BlenderImage',row['source_name']);metadata(obj,'BlenderSHA256',row['sha256']);metadata(obj,'BlenderSRGB',int(row['srgb']))
    save(obj);_assets[path]=obj
    return {'path':path,'srgb':row['srgb']}

def import_texture(row):
    if cached_texture(row):return {'skipped':True}
    factory=unreal.TextureFactory();factory.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_EDITOR_ICON)
    factory.set_editor_property('defer_compression',False);factory.set_editor_property('no_alpha',False)
    obj=import_task(ROOT/row['file'],DEST+'/Textures',row['id'],factory=factory)
    return finish_texture(row,obj)

def cached_mesh(row):
    path=package('Meshes',row['id'])
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        obj=unreal.load_asset(path)
        expected=INPUT_HASHES.get('Meshes/'+row['id'],{}).get('sha256')
        matching=not expected or unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderMeshSHA256')==expected
        matching = matching and (not row.get('ue_topology_revision') or unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderTopologyRevision')==row['ue_topology_revision'])
        if matching and unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderMeshId')==row['id'] and (len(row['materials'])<=1 or unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderFaceSlotRevision')=='preserve_face_slots_v2'):
            _assets[path]=obj;return obj
    return None

def finish_mesh(row,obj):
    path=package('Meshes',row['id'])
    desc=obj.get_static_mesh_description(0)
    expected_triangles=source_triangle_count(row)
    if desc.get_triangle_count()!=expected_triangles:raise RuntimeError(f'Triangle count differs {path}: {desc.get_triangle_count()} vs {expected_triangles}')
    actual_uv=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_num_uv_channels(obj,0)
    if actual_uv!=len(row['uv_layers']):raise RuntimeError('UV channel count differs '+path)
    metadata(obj,'BlenderMeshId',row['id']);metadata(obj,'BlenderMesh',row['source_name'])
    metadata(obj,'BlenderMeshSHA256',INPUT_HASHES.get('Meshes/'+row['id'],{}).get('sha256',''))
    metadata(obj,'BlenderFaceSlotRevision','preserve_face_slots_v2')
    metadata(obj,'BlenderTopologyRevision',row.get('ue_topology_revision','legacy'))
    metadata(obj,'BlenderRepeatedIndexTriangles',row.get('repeated_index_triangles',0))
    metadata(obj,'BlenderSourceAsset',row.get('source_asset') or '')
    save(obj);_assets[path]=obj
    return {'path':path,'triangles':desc.get_triangle_count(),'uv_channels':actual_uv}

def import_mesh(row):
    if cached_mesh(row):return {'skipped':True}
    filename=ROOT/row['fbx']
    if not filename.is_file():raise RuntimeError('FBX not yet exported '+str(filename))
    obj=import_task(filename,DEST+'/Meshes',row['id'],options=fbx_options())
    return finish_mesh(row,obj)

def run_import_batches(stage,start_index=0,progress=None):
    """Submit independent imports together; all UObject access stays on the game thread."""
    global _state
    rows=MANIFEST['images'] if stage=='textures' else MANIFEST['meshes']
    kind='Textures' if stage=='textures' else 'Meshes'
    cached=cached_texture if stage=='textures' else cached_mesh
    finish=finish_texture if stage=='textures' else finish_mesh
    batch_size=max(1,min(32,int(_os.environ.get('ATLASMAP_UE_BATCH_SIZE','16'))))
    if stage=='meshes':batch_size=min(8,batch_size)
    _state={'phase':stage,'cursor':start_index,'total':len(rows),'running':True,'complete':False,'started':time.time()}
    persist(True)
    counts={'imported':0,'skipped':0,'batches':0}
    for offset in range(start_index,len(rows),batch_size):
        chunk=rows[offset:offset+batch_size];pending=[]
        for row in chunk:
            if cached(row):counts['skipped']+=1;continue
            task=unreal.AssetImportTask();task.filename=str(ROOT/row['file' if stage=='textures' else 'fbx'])
            task.destination_path=DEST+'/'+kind;task.destination_name=row['id']
            task.automated=True;task.replace_existing=True;task.save=False;task.async_=True
            if stage=='meshes':task.options=fbx_options()
            pending.append((row,task))
        if pending:
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task for _,task in pending])
            for row,task in pending:
                objects=list(task.get_objects())
                expected=package(kind,row['id'])
                obj=next((obj for obj in objects if obj.get_path_name().split('.')[0]==expected),None)
                if obj is None:raise RuntimeError('Import did not produce expected asset '+expected)
                finish(row,obj);counts['imported']+=1
            flush_saves();counts['batches']+=1
        _state['cursor']=offset+len(chunk);_state['current']=chunk[-1]['id'];_state['last_result']=dict(counts)
        persist(True)
        if progress:progress(_state['cursor'],len(rows),dict(counts))
    _state['running']=False;_state['complete']=True;persist(True)
    return counts

def expression(material,kind,x=0,y=0):
    node=unreal.MaterialEditingLibrary.create_material_expression(material,kind,x,y)
    if not node:raise RuntimeError('Cannot create '+str(kind))
    return node
def link(source,output,target,input_name):
    if input_name=='Coordinates':input_name='UVs'
    if not unreal.MaterialEditingLibrary.connect_material_expressions(source,output,target,input_name):
        raise RuntimeError('Material connection failed '+output+' -> '+input_name)
def output_link(source,output,prop):
    if not unreal.MaterialEditingLibrary.connect_material_property(source,output,prop):raise RuntimeError('Material output connection failed '+output)
def custom_inputs(node,names):
    values=[]
    for name in names:
        item=unreal.CustomInput();item.set_editor_property('input_name',name);values.append(item)
    node.set_editor_property('inputs',values)
def global_input(material,name,cache):
    if name in cache:return cache[name]
    if name in _scalar_defaults:
        node=expression(material,unreal.MaterialExpressionScalarParameter,-1800,-1000-len(cache)*80)
        node.set_editor_property('parameter_name',name);node.set_editor_property('default_value',_scalar_defaults[name]);output=''
    elif name=='TIME':node=expression(material,unreal.MaterialExpressionTime,-1800,-850);output=''
    elif name=='WP':node=expression(material,unreal.MaterialExpressionWorldPosition,-1800,-700);output=''
    elif name=='VC':
        node=expression(material,unreal.MaterialExpressionVertexColor,-1800,-500)
        alpha=expression(material,unreal.MaterialExpressionAppendVector,-1500,-500)
        link(node,'',alpha,'A');link(node,'A',alpha,'B');node=alpha;output=''
    elif name.startswith('UV'):
        node=expression(material,unreal.MaterialExpressionTextureCoordinate,-1800,-300+int(name[2:])*160)
        node.set_editor_property('coordinate_index',int(name[2:]));output=''
    else:raise RuntimeError('Unknown shader global '+name)
    cache[name]=(node,output);return cache[name]

def _frosted_glass(material,surface):
    """Sample the rendered background, rather than adding a grey diffuse pane."""
    material.set_editor_property('translucency_pass',unreal.MaterialTranslucencyPass.MTP_BEFORE_DOF)
    blur=expression(material,unreal.MaterialExpressionCustom,300,750)
    blur.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    radius=float(surface.get('frosted_blur_radius',.004))
    offsets=[(0,0,4),(-1,0,2),(1,0,2),(0,-1,2),(0,1,2),(-1,-1,1),(-1,1,1),(1,-1,1),(1,1,1)]
    names=['S'+str(i) for i in range(len(offsets))]
    custom_inputs(blur,names)
    for i,(x,y,weight) in enumerate(offsets):
        sample=expression(material,unreal.MaterialExpressionSceneColor,-300,800+i*140)
        sample.set_editor_property('input_mode',unreal.MaterialSceneAttributeInputMode.OFFSET_FRACTION)
        sample.set_editor_property('const_input',unreal.Vector2D(x*radius,y*radius))
        link(sample,'',blur,names[i])
    tint=surface.get('transmittance_color',[1,1,1])
    blur.set_editor_property('code','return ('+'+'.join(f'{names[i]}*{weight}.0' for i,(_,_,weight) in enumerate(offsets))+
        ')/16.0*float3('+','.join(str(float(v)) for v in tint)+');')
    output_link(blur,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)


def import_material(row):
    global _scalar_defaults
    _scalar_defaults=row.get('scalar_defaults',{})
    path=package('Materials',row['id'])
    material=unreal.EditorAssetLibrary.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    if material and unreal.EditorAssetLibrary.get_metadata_tag(material,'BlenderGraphSHA256')==row['sha256'] and unreal.EditorAssetLibrary.get_metadata_tag(material,'AtlasMapSurfaceRevision')=='7':
        _assets[path]=material;return {'skipped':True}
    if not material:
        material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(row['id'],DEST+'/Materials',unreal.Material,unreal.MaterialFactoryNew())
    unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
    material.set_editor_property('two_sided',row['two_sided']);material.set_editor_property('tangent_space_normal',False)
    kind=row.get('surface_kind','masked' if row['masked'] else 'opaque')
    material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT if kind=='translucent' else unreal.BlendMode.BLEND_MASKED if row['masked'] else unreal.BlendMode.BLEND_OPAQUE)
    material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    if kind=='translucent':
        material.set_editor_property('translucency_lighting_mode',unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        material.set_editor_property('refraction_method',unreal.RefractionMode.RM_PIXEL_NORMAL_OFFSET if row.get('surface',{}).get('thin_glass') else unreal.RefractionMode.RM_INDEX_OF_REFRACTION)
        material.set_editor_property('screen_space_reflections',True)
        material.set_editor_property('refraction_depth_bias',row.get('surface',{}).get('refraction_depth_bias',0))
        native_blend=str(row.get('surface',{}).get('blend_mode','')).lower()
        if 'alphacomposite' in native_blend:material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_ALPHA_COMPOSITE)
        elif 'additive' in native_blend:material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_ADDITIVE)

    material.set_editor_property('opacity_mask_clip_value',row.get('surface',{}).get('clip',.333))
    material.set_editor_property('use_material_attributes',False)
    globals_cache={};samples=[]
    for index,texture in enumerate(row['textures']):
        coordinate=expression(material,unreal.MaterialExpressionCustom,-1200,index*230)
        coordinate.set_editor_property('description','Blender coordinate '+str(texture['node']))
        coordinate.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT2)
        coordinate.set_editor_property('code',texture['coordinate_code']);custom_inputs(coordinate,texture['coordinate_inputs'])
        for name in texture['coordinate_inputs']:
            node,output=global_input(material,name,globals_cache);link(node,output,coordinate,name)
        image=asset('Textures',texture['image']);record=IMAGES[texture['image']]
        sampler=expression(material,unreal.MaterialExpressionTextureSampleParameter2D if texture.get('parameter') else unreal.MaterialExpressionTextureSample,-850,index*230)
        if texture.get('parameter'):sampler.set_editor_property('parameter_name',texture['parameter'])
        sampler.set_editor_property('texture',image)
        sampler.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if record['srgb'] else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        sampler.set_editor_property('sampler_source',unreal.SamplerSourceMode.SSM_CLAMP_WORLD_GROUP_SETTINGS if texture['extension']=='EXTEND' else unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        sampler.set_editor_property('automatic_view_mip_bias',False)
        link(coordinate,'',sampler,'Coordinates')
        rgba=expression(material,unreal.MaterialExpressionAppendVector,-620,index*230)
        link(sampler,'',rgba,'A');link(sampler,'A',rgba,'B')
        samples.append((texture['input'],rgba))
    node=expression(material,unreal.MaterialExpressionCustom,-400,0)
    node.set_editor_property('description','Blender source '+row['source_name'])
    node.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    additional=[]
    for name,output_kind in [('OutNormal',unreal.CustomMaterialOutputType.CMOT_FLOAT3),('OutRoughness',unreal.CustomMaterialOutputType.CMOT_FLOAT1),('OutMetallic',unreal.CustomMaterialOutputType.CMOT_FLOAT1),('OutAlpha',unreal.CustomMaterialOutputType.CMOT_FLOAT1),('OutIOR',unreal.CustomMaterialOutputType.CMOT_FLOAT1),('OutSpecular',unreal.CustomMaterialOutputType.CMOT_FLOAT1)]:
        out=unreal.CustomOutput();out.set_editor_property('output_name',name);out.set_editor_property('output_type',output_kind);additional.append(out)
    node.set_editor_property('additional_outputs',additional);node.set_editor_property('code',row['code'])
    custom_inputs(node,row['inputs']+[name for name,_ in samples])
    for name in row['inputs']:
        source,output=global_input(material,name,globals_cache);link(source,output,node,name)
    for name,sample in samples:link(sample,'',node,name)
    for name,prop in [('',unreal.MaterialProperty.MP_BASE_COLOR),('OutNormal',unreal.MaterialProperty.MP_NORMAL),('OutRoughness',unreal.MaterialProperty.MP_ROUGHNESS),('OutMetallic',unreal.MaterialProperty.MP_METALLIC)]:output_link(node,name,prop)
    output_link(node,'OutSpecular',unreal.MaterialProperty.MP_SPECULAR)
    if kind in ('translucent','water'):
        output_link(node,'OutAlpha',unreal.MaterialProperty.MP_OPACITY)
    if kind=='translucent':output_link(node,'OutIOR',unreal.MaterialProperty.MP_REFRACTION)
    if kind=='translucent' and row.get('surface',{}).get('thin_glass'):
        frosted=row.get('surface',{}).get('frosted_glass',False)
        thin=None if frosted else expression(material,unreal.MaterialExpressionThinTranslucentMaterialOutput,200,450)
        tint=row.get('surface',{}).get('transmittance_color')
        if not frosted and tint is not None:
            transmission=expression(material,unreal.MaterialExpressionConstant3Vector,0,450)
            transmission.set_editor_property('constant',unreal.LinearColor(*tint,1))
            link(transmission,'',thin,'TransmittanceColor')
        elif not frosted:link(node,'',thin,'TransmittanceColor')
        # Clear glass transmits the source tint; a diffuse white base adds a
        # milky veil on top of it, especially on two-sided source panes.
        clear=expression(material,unreal.MaterialExpressionConstant3Vector,0,250)
        clear.set_editor_property('constant',unreal.LinearColor(0,0,0,1))
        output_link(clear,'',unreal.MaterialProperty.MP_BASE_COLOR)
        if frosted:_frosted_glass(material,row['surface'])
        else:material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT)
    if kind=='water':
        water=expression(material,unreal.MaterialExpressionSingleLayerWaterMaterialOutput,200,600)
        for name,values in [('AbsorptionCoefficients',row.get('surface',{}).get('absorption',[.003,.0015,.0007])),
                            ('ScatteringCoefficients',row.get('surface',{}).get('scattering',[.0001,.0002,.0003]))]:
            coefficient=expression(material,unreal.MaterialExpressionConstant3Vector,-50,600 if name.startswith('Absorption') else 750)
            coefficient.set_editor_property('constant',unreal.LinearColor(*values,1))
            link(coefficient,'',water,name)
        material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER)
    if row['masked']:
        function=unreal.load_asset('/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA')
        if not function:raise RuntimeError('Engine DitherTemporalAA function missing')
        dither=expression(material,unreal.MaterialExpressionMaterialFunctionCall,0,500)
        if not dither.set_material_function(function):raise RuntimeError('Cannot set dither function')
        names=list(unreal.MaterialEditingLibrary.get_material_expression_input_names(dither))
        alpha=next(n for n in names if 'alpha' in n.lower())
        link(node,'OutAlpha',dither,alpha);output_link(dither,'',unreal.MaterialProperty.MP_OPACITY_MASK)
    unreal.MaterialEditingLibrary.recompile_material(material)
    metadata(material,'BlenderGraphSHA256',row['sha256']);metadata(material,'BlenderMaterial',row['source_name'])
    metadata(material,'AtlasMapSurfaceKind',kind);metadata(material,'AtlasMapSurfaceRevision','7')
    metadata(material,'BlenderMaterialId',row['source_material']);metadata(material,'BlenderSourceMaterialPath',row.get('source_path') or '')
    metadata(material,'BlenderUVBindings',json.dumps(row['bindings'],sort_keys=True))
    save(material);_assets[path]=material
    return {'path':path,'texture_nodes':len(samples),'masked':row['masked']}

def import_instance(row):
    path=package('Materials',row['id']);obj=unreal.EditorAssetLibrary.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    # Preserve explicitly reviewed follow-up shader repairs on a resumed import.
    repair_path=ROOT/'container_detail_compatibility_repair.json'
    repaired=json.loads(repair_path.read_text(encoding='utf-8')) if repair_path.exists() else {}
    desired_parent=(unreal.load_asset(repaired['parent']) if row['id'] in repaired.get('instances',[]) else asset('Materials',row['parent']))
    if desired_parent is None:raise RuntimeError('Missing reviewed material parent '+row['id'])
    if obj and not isinstance(obj,unreal.MaterialInstanceConstant):
        backup=package('Validation/InitialGraphs',row['id'])
        if unreal.EditorAssetLibrary.does_asset_exist(backup):raise RuntimeError('Conflicting legacy graph backup '+backup)
        if not unreal.EditorAssetLibrary.rename_asset(path,backup):raise RuntimeError('Cannot preserve initial graph '+path)
        save(obj);obj=None
    if obj and unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderGraphSHA256')==row['sha256'] and obj.get_editor_property('parent')==desired_parent:
        _assets[path]=obj;return {'skipped':True}
    if not obj:obj=unreal.AssetToolsHelpers.get_asset_tools().create_asset(row['id'],DEST+'/Materials',unreal.MaterialInstanceConstant,unreal.MaterialInstanceConstantFactoryNew())
    unreal.MaterialEditingLibrary.set_material_instance_parent(obj,desired_parent)
    for name,value in row['scalars'].items():
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(obj,name,value)
        actual=unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(obj,name)
        if abs(actual-value)>max(1e-6,abs(value)*1e-6):raise RuntimeError('Scalar parameter readback differs '+path+' '+name)
    for name,image in row['textures'].items():
        expected=asset('Textures',image)
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(obj,name,expected)
        if unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(obj,name)!=expected:raise RuntimeError('Texture parameter readback differs '+path+' '+name)
    unreal.MaterialEditingLibrary.update_material_instance(obj)
    metadata(obj,'BlenderGraphSHA256',row['sha256']);metadata(obj,'BlenderMaterial',row['source_name'])
    metadata(obj,'BlenderSourceMaterialPath',row.get('source_path') or '')
    metadata(obj,'BlenderMaterialId',row['source_material']);metadata(obj,'BlenderParameterizedParent',row['parent'])
    save(obj);_assets[path]=obj
    return {'path':path,'parent':row['parent']}

def mesh_slot_map(mesh):
    result={}
    dropped=[]
    for index,slot in enumerate(mesh.static_materials):
        name=str(slot.material_slot_name)
        match=re.search(r'DF_SLOT_(\d+)',name)
        if not match:
            # FBX 导进来的默认槽（WorldGridMaterial / 空名）：不认就丢掉，
            # 后面 bind_mesh 会按 PLAN 的槽位重新补，不该整批中断
            dropped.append(name)
            continue
        source=int(match.group(1))
        if source in result:
            dropped.append(name)
            continue
        result[source]=index
    if dropped:
        unreal.log_warning('[bridge] %s 忽略了 %d 个非 DF_SLOT 槽：%s' % (mesh.get_name(), len(dropped), ','.join(dropped[:4])))
    return result

def bind_mesh(row):
    mesh=asset('Meshes',row['id']);mapping=mesh_slot_map(mesh)
    defaults=PLAN['mesh_materials'][row['id']]
    # 只保留 DF_SLOT 槽，其余（WorldGridMaterial 之类）直接剔掉，避免重复占位
    keep=[slots_i for slots_i in mesh.static_materials if re.search(r'DF_SLOT_(\d+)',str(slots_i.material_slot_name))]
    slots=list(keep)
    for source_index,mid in enumerate(defaults):
        if not mid:raise RuntimeError('Missing source material slot')
        if source_index not in mapping:
            material=unreal.StaticMaterial();material.material_slot_name='DF_SLOT_'+str(source_index).zfill(4)
            slots.append(material);mapping[source_index]=len(slots)-1
        slots[mapping[source_index]].material_interface=asset('Materials',mid)
    mesh.set_editor_property('static_materials',slots);metadata(mesh,'BlenderSlotMap',json.dumps(mapping,sort_keys=True));save(mesh)
    return {'slots':len(slots)}

def make_transform(row):
    transform=unreal.Transform()
    transform.set_editor_property('translation',unreal.Vector(*row['location_cm']))
    transform.set_editor_property('rotation',unreal.Quat(*row['rotation_xyzw']))
    transform.set_editor_property('scale3d',unreal.Vector(*row['scale']))
    return transform
def find_actors():
    result={}
    for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        for tag in actor.tags:
            text=str(tag)
            if text.startswith('IcelandBlenderId_'):result[text[len('IcelandBlenderId_'):]]=actor
    return result

def apply_actor_visibility(actor,row):
    actor.set_actor_hidden_in_game(row['hidden_render'])
    if row['hidden_editor']:
        layer=unreal.get_editor_subsystem(unreal.LayersSubsystem)
        layer.add_actor_to_layer(actor,'Iceland_Blender_Hidden')
        layer.set_layer_visibility('Iceland_Blender_Hidden',False)
        if row['type']=='MESH':actor.static_mesh_component.set_visibility(False,False)
    if row.get('map_lod_policy'):
        metadata(actor,'AtlasMapLodPolicy',row['map_lod_policy'])


def create_actor(row):
    world=unreal.EditorLevelLibrary.get_editor_world()
    if world.get_path_name().split('.')[0]!=MANIFEST['level']:raise RuntimeError('Wrong destination level: '+world.get_path_name())
    if row['id'] in _actors:
        apply_actor_visibility(_actors[row['id']],row)
        return {'skipped':True}
    cls={'MESH':unreal.StaticMeshActor,'CAMERA':unreal.CameraActor,'EMPTY':unreal.TargetPoint}.get(row['type'])
    if not cls:raise RuntimeError('Unsupported object type '+row['type'])
    from ue_actor_spawn import spawn_actor
    actor=spawn_actor(unreal,cls,unreal.Vector(*row['location_cm']),transform=make_transform(row))
    if not actor:raise RuntimeError('Actor creation failed '+row['name'])
    actor.set_actor_label(row['name'].rsplit('/',1)[-1])
    actor.tags=[unreal.Name('IcelandBlenderId_'+row['id']),unreal.Name('BlenderType_'+row['type'])]
    actor.set_actor_transform(make_transform(row),False,True)
    apply_actor_visibility(actor,row)
    collection=row['collections'][0] if row['collections'] else 'Scene'
    folder='Iceland/'+collection
    if row['hidden_editor']:folder='Iceland/_Hidden/'+collection
    actor.set_folder_path(folder)
    if row['type']=='MESH':
        mesh=asset('Meshes',row['mesh']);component=actor.static_mesh_component;component.set_static_mesh(mesh)
        mapping=mesh_slot_map(mesh)
        for index,mid in enumerate(PLAN['object_materials'][row['id']]):component.set_material(mapping[index],asset('Materials',mid))
    elif row['type']=='CAMERA':
        component=actor.camera_component;camera=row['camera'];component.set_field_of_view(camera['horizontal_fov_degrees']);component.set_aspect_ratio(MANIFEST['render_aspect'])
        if camera['projection']=='ORTHO':component.set_projection_mode(unreal.CameraProjectionMode.ORTHOGRAPHIC);component.set_ortho_width(camera['ortho_width_cm'])
    elif row['type']=='EMPTY':
        actor.get_editor_property('root_component').set_mobility(unreal.ComponentMobility.STATIC)
    if row['hidden_editor'] and row['type']=='MESH':
        # Set again after assigning the mesh: this state must survive reloads.
        actor.static_mesh_component.set_visibility(False,False)
    metadata(actor,'BlenderObject',row['name']);metadata(actor,'BlenderObjectId',row['id'])
    _actors[row['id']]=actor
    return {'actor':actor.get_path_name()}

def attach_actor(row):
    if row['parent']:
        actor=_actors[row['id']];parent=_actors[row['parent']]
        if not actor.attach_to_actor(parent,unreal.Name('None'),unreal.AttachmentRule.KEEP_WORLD,unreal.AttachmentRule.KEEP_WORLD,unreal.AttachmentRule.KEEP_WORLD,False):
            raise RuntimeError('Parent attachment failed '+row['name'])
    return {}

PHASES={'textures':(MANIFEST['images'],import_texture),'meshes':(MANIFEST['meshes'],import_mesh),
        'materials':(PLAN['materials'],import_material),'bindings':(MANIFEST['meshes'],bind_mesh),
        'masters':(INSTANCE_PLAN['parents'],import_material),'instances':(INSTANCE_PLAN['instances'],import_instance),
        'actors':(MANIFEST['objects'],create_actor),'parents':([r for r in MANIFEST['objects'] if r['parent']],attach_actor)}
def _tick(delta):
    global _handle,_busy
    if _busy or not _state.get('running'):return
    _busy=True
    rows,func=PHASES[_state['phase']]
    start=time.time()
    try:
        while _state['cursor']<len(rows) and time.time()-start<.18:
            row=rows[_state['cursor']];_state['current']=row.get('id','');persist()
            result=func(row);_state['cursor']+=1;_state['last_result']=result;persist()
        if _state['cursor']>=len(rows):
            flush_saves()
            _state['running']=False;_state['complete']=True;persist(True)
            unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    except Exception:
        _state['running']=False;_state['error']=traceback.format_exc();persist(True)
        unreal.log_error(_state['error'])
        if _handle:unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    finally:
        _busy=False

def start(phase,start_index=0):
    global _state,_handle,_actors
    if _state.get('running'):raise RuntimeError('Pipeline already running')
    if phase not in PHASES:raise ValueError(phase)
    if phase in ['actors','parents']:_actors=find_actors()
    _state={'phase':phase,'cursor':start_index,'total':len(PHASES[phase][0]),'running':True,'complete':False,'started':time.time()}
    persist(True);_handle=unreal.register_slate_post_tick_callback(_tick)
    return dict(_state)
def status():return dict(_state)
def pause():
    global _handle
    _state['running']=False;persist()
    if _handle:unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    return dict(_state)
