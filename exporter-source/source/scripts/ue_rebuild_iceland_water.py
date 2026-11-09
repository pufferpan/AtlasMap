"""Native UE5.4 water compatibility rebuild from actual Iceland source data.

No claim of recovered original shader math or custom engine simulation. Source
data/parameters and every native conversion are recorded for inspection.
"""
import hashlib,json,math,time
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge

ROOT=Path('D:/AtlasMap-tooling/out/Iceland/water_rebuild/20261031')
SOURCE=ROOT/'source_data'
DEST=bridge.DEST+'/Water'
WATER_IDS={'O_1f6a67499e93c3e0e9b5':'Coast','O_130f9f54a12effd5e9c4':'Deep',
           'O_d681d86357a82093814a':'Deep','O_eb20cabb25e61ecfcc42':'Far'}
PROXY='O_ad6ca3a902cd84b6da39'

def snapshot():
    out={}
    for oid,a in bridge.find_actors().items():
        t=a.get_actor_transform();c=a.static_mesh_component if isinstance(a,unreal.StaticMeshActor) else None
        out[oid]={'label':a.get_actor_label(),'location':[t.translation.x,t.translation.y,t.translation.z],
                  'rotation':[t.rotation.x,t.rotation.y,t.rotation.z,t.rotation.w],
                  'scale':[t.scale3d.x,t.scale3d.y,t.scale3d.z],
                  'hidden_game':a.get_editor_property('hidden'),
                  'visible':c.get_editor_property('visible') if c else None,
                  'materials':[m.get_path_name() if m else None for m in c.get_materials()] if c else []}
    return out

def import_data():
    specs={
      'CoastData':('T_Water_Iceland_Data1/T_Water_Iceland_Data1.tga',True),
      'GroundData':('T_Water_Iceland_Data2/T_Water_Iceland_Data2.tga',True),
      'Height16':('Iceland_Water_Heightmap_R16/Iceland_Water_Heightmap_R16_RG8_Packed.tga',True),
      'Detail':('T_DetailWaveTexture_01/T_DetailWaveTexture_01.tga',False),
      'Foam':('T_Seafoam_03_NSH/T_Seafoam_03_NSH.tga',False),
      'Profile':('T_DefaultWaveProfile_Forard_2/T_DefaultWaveProfile_Forard_2.tga',False),
      'Volume':('T_OceanWave_VolumeTexture/T_OceanWave_VolumeTexture_BGRA8_Volume.dds',False)}
    results={};records=[]
    for name,(filename,clamp) in specs.items():
        asset_name='T_IcelandWater_'+name if name!='Volume' else 'T_OceanWave_SourceVolume'
        obj=unreal.load_asset(DEST+'/Textures/'+asset_name)
        if obj is None:obj=bridge.import_task(SOURCE/filename,DEST+'/Textures',asset_name)
        obj.set_editor_property('srgb',False)
        obj.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP if name=='Volume' else unreal.TextureCompressionSettings.TC_EDITOR_ICON)
        obj.set_editor_property('compression_no_alpha',False)
        obj.set_editor_property('never_stream',True)
        obj.set_editor_property('lod_bias',0)
        if isinstance(obj,unreal.Texture2D):
            obj.set_editor_property('address_x',unreal.TextureAddress.TA_CLAMP if clamp else unreal.TextureAddress.TA_WRAP)
            obj.set_editor_property('address_y',unreal.TextureAddress.TA_CLAMP if clamp else unreal.TextureAddress.TA_WRAP)
        bridge.metadata(obj,'WaterSourceFile',str(SOURCE/filename));bridge.metadata(obj,'WaterSourceSHA256',hashlib.sha256((SOURCE/filename).read_bytes()).hexdigest())
        bridge.save(obj);results[name]=obj
        records.append({'name':name,'asset':obj.get_path_name(),'file':filename,'class':obj.get_class().get_name()})
    (ROOT/'texture_imports.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    return results

def hlsl(variant):
    coast=variant=='Coast';far=variant=='Far'
    # Channel decode, time sampling and attenuation-distance conversion below
    # are native compatibility interpretations; cooked math was stripped.
    return f'''
float t=WaterTime;
float dist=length(Camera-WP);
float2 mapuv=(WP.xy-float2(193331.73,-121131.44))/float2(511000.0,128000.0)+0.5;
float inMap=step(0.0,mapuv.x)*step(mapuv.x,1.0)*step(0.0,mapuv.y)*step(mapuv.y,1.0);
float proximity=Texture2DSampleLevel(Ground,GroundSampler,saturate(mapuv),0).r*inMap;
float shoreBand=pow(saturate(4.0*proximity*(1.0-proximity)),6.0);
float3 uvw=float3(frac(WP.xy*0.000125+float2(0,-t*0.00375)),frac(t/12.0));
float waterMip=clamp(log2(max(dist,3000.0)/3000.0),0.0,5.0);
float4 state=Texture3DSampleLevel(Waves,WavesSampler,uvw,waterMip);
float delta=1.0/256.0;
float hx0=Texture3DSampleLevel(Waves,WavesSampler,uvw-float3(delta,0,0),waterMip).b;
float hx1=Texture3DSampleLevel(Waves,WavesSampler,uvw+float3(delta,0,0),waterMip).b;
float hy0=Texture3DSampleLevel(Waves,WavesSampler,uvw-float3(0,delta,0),waterMip).b;
float hy1=Texture3DSampleLevel(Waves,WavesSampler,uvw+float3(0,delta,0),waterMip).b;
float waveHeight=120.0;
float3 n=normalize(float3(-(hx1-hx0)*waveHeight/62.5,-(hy1-hy0)*waveHeight/62.5,1));
float4 detail=Texture2DSampleLevel(Detail,DetailSampler,frac(WP.xy/800.0+float2(t*.014,-t*.009)),waterMip);
float4 detail2=Texture2DSampleLevel(Detail,DetailSampler,frac(WP.yx/1350.0+float2(-t*.009,t*.006)),waterMip);
float detailFade=1.0-smoothstep(15000.0,80000.0,dist);
n=normalize(n+float3((detail.rg+detail2.gr-1.0)*0.22*detailFade,0));
float foam=0;
float4 foamSample=Texture2DSampleLevel(Foam,FoamSampler,frac(WP.xy*.0005+float2(t*.012,-t*.008)),0);
float profile=Texture2DSampleLevel(Profile,ProfileSampler,float2(frac(t*.12-proximity*3.202044),.5),0).r;
{'foam=saturate(shoreBand*smoothstep(.25,.8,profile)*smoothstep(.25,.72,foamSample.a)*.4);' if coast else ''}
float3 foamColor=float3(.504427,.539740,.65);
OutNormal=normalize(lerp(n,float3(0,0,1),foam*.5));
OutRoughness=clamp(.05+.035*(1-detailFade)+foam*.4,.05,.6);
OutOpacity=lerp(.15,1.0,foam);
float displaceFade=1.0-smoothstep(10000.0,30000.0,dist);
OutWPO={'float3(0,0,0)' if far else 'float3((state.rg*2.0-1.0)*125.0,(state.b-.4324)*waveHeight)*displaceFade'};
float3 viewdir=normalize(Camera-WP);
float3 reflected=reflect(-viewdir,OutNormal);
float3 env=TextureCubeSampleLevel(Environment,EnvironmentSampler,reflected,0).rgb;
float fresnel=.03+.97*pow(1.0-saturate(dot(viewdir,OutNormal)),5.0);
OutEmissive=float3(0,0,0);
OutScattering=lerp(float3(.0000287625,.0000353196,.0000359376),float3(.00008,.00016,.000146442),saturate(proximity*2.0));
OutAbsorption=lerp(1.0/float3(148.1291,269.9668,350.0),1.0/float3(75.0,100.32805,150.0),saturate(proximity*2.0));
OutPhase=.25;
OutBehind=lerp(float3(.7,.690766,.657465),float3(1,1,1),saturate(proximity*2.0));
return lerp(float3(0,0,0),foamColor,foam);
'''

def make_material(variant,textures):
    name='M_IcelandWater_'+variant+'_Compatibility';path=DEST+'/Materials/'+name
    material=unreal.load_asset(path)
    if material:
        existing=unreal.MaterialEditingLibrary.get_material_property_input_node(material,unreal.MaterialProperty.MP_BASE_COLOR)
        if isinstance(existing,unreal.MaterialExpressionCustom) and existing.get_editor_property('code')==hlsl(variant) and material.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER:
            return material
    if material is None:material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,DEST+'/Materials',unreal.Material,unreal.MaterialFactoryNew())
    else:unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
    material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER)
    material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_OPAQUE)
    material.set_editor_property('two_sided',True);material.set_editor_property('tangent_space_normal',False)
    pos=bridge.expression(material,unreal.MaterialExpressionWorldPosition,-1700,0)
    pos.set_editor_property('world_position_shader_offset',unreal.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
    camera=bridge.expression(material,unreal.MaterialExpressionCameraPositionWS,-1700,150)
    clock=bridge.expression(material,unreal.MaterialExpressionTime,-1700,300)
    offset=bridge.expression(material,unreal.MaterialExpressionScalarParameter,-1700,450)
    offset.set_editor_property('parameter_name','TimeOffset');offset.set_editor_property('default_value',0.0)
    add=bridge.expression(material,unreal.MaterialExpressionAdd,-1400,300);bridge.link(clock,'',add,'A');bridge.link(offset,'',add,'B')
    node=bridge.expression(material,unreal.MaterialExpressionCustom,-300,0)
    node.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    node.set_editor_property('description','Iceland native water compatibility; source samples preserved; formula reconstruction documented')
    node.set_editor_property('code',hlsl(variant))
    extras=[]
    for name,kind in [('OutNormal',3),('OutRoughness',1),('OutOpacity',1),('OutWPO',3),('OutEmissive',3),('OutScattering',3),('OutAbsorption',3),('OutPhase',1),('OutBehind',3)]:
        out=unreal.CustomOutput();out.set_editor_property('output_name',name)
        out.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3 if kind==3 else unreal.CustomMaterialOutputType.CMOT_FLOAT1);extras.append(out)
    node.set_editor_property('additional_outputs',extras)
    input_names=['WP','Camera','WaterTime','Waves','Ground','Detail','Foam','Profile','Environment']
    bridge.custom_inputs(node,input_names)
    bridge.link(pos,'',node,'WP');bridge.link(camera,'',node,'Camera');bridge.link(add,'',node,'WaterTime')
    texture_mapping={'Waves':textures['Volume'],'Ground':textures['GroundData'],'Detail':textures['Detail'],'Foam':textures['Foam'],'Profile':textures['Profile'],
                     'Environment':unreal.load_asset(bridge.DEST+'/Lighting/T_Iceland_SCb0_19_2_Source')}
    for i,(name,tex) in enumerate(texture_mapping.items()):
        obj=bridge.expression(material,unreal.MaterialExpressionTextureObject,-1200,700+i*140)
        obj.set_editor_property('texture',tex);obj.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        bridge.link(obj,'',node,name)
    for name,prop in [('',unreal.MaterialProperty.MP_BASE_COLOR),('OutNormal',unreal.MaterialProperty.MP_NORMAL),
                       ('OutRoughness',unreal.MaterialProperty.MP_ROUGHNESS),('OutOpacity',unreal.MaterialProperty.MP_OPACITY),
                       ('OutEmissive',unreal.MaterialProperty.MP_EMISSIVE_COLOR)]:
        bridge.output_link(node,name,prop)
    specular=bridge.expression(material,unreal.MaterialExpressionConstant,-300,-250);specular.set_editor_property('r',.375);bridge.output_link(specular,'',unreal.MaterialProperty.MP_SPECULAR)
    water=bridge.expression(material,unreal.MaterialExpressionSingleLayerWaterMaterialOutput,350,350)
    for name,pin in [('OutScattering','ScatteringCoefficients'),('OutAbsorption','AbsorptionCoefficients'),('OutPhase','PhaseG'),('OutBehind','ColorScaleBehindWater')]:bridge.link(node,name,water,pin)
    unreal.MaterialEditingLibrary.recompile_material(material)
    bridge.metadata(material,'WaterRebuildVariant',variant)
    bridge.metadata(material,'WaterWPOExpression',node.get_name())
    bridge.metadata(material,'CompatibilityWarning','Original cooked function math and custom runtime unavailable. Native wave B/normal RG, shoreline proximity and reciprocal absorption are compatibility interpretations.')
    bridge.save(material)
    (ROOT/(variant+'_compatibility.hlsl')).write_text(hlsl(variant),encoding='utf-8')
    return material

def build():
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    assert world.get_path_name().split('.')[0]==bridge.MANIFEST['level']
    ROOT.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'before_water_objects.json').exists():(ROOT/'before_water_objects.json').write_text(json.dumps(snapshot(),ensure_ascii=False),encoding='utf-8')
    textures=import_data();materials={name:make_material(name,textures) for name in ['Coast','Deep','Far']}
    output={'materials':{k:v.get_path_name() for k,v in materials.items()},'stage':'materials_ready','source_geometry_modified':False,
            'WPO_binding_note':'Python excludes the hidden WorldPositionOffset enum. For a freshly rebuilt Coast/Deep graph, read the graph and connect root.OutWPO to Material.WorldPositionOffset via material_apply_graph before applying. Existing reviewed graphs are preserved.'}
    (ROOT/'water_build_status.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    return output

def apply():
    actors=bridge.find_actors();changes=[]
    instances={}
    for variant in ['Coast','Deep','Far']:
        parent=unreal.load_asset(DEST+'/Materials/M_IcelandWater_'+variant+'_Compatibility');assert parent
        name='MI_IcelandWater_'+variant
        instance=unreal.load_asset(DEST+'/Materials/'+name)
        if instance is None:instance=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,DEST+'/Materials',unreal.MaterialInstanceConstant,unreal.MaterialInstanceConstantFactoryNew())
        unreal.MaterialEditingLibrary.set_material_instance_parent(instance,parent)
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(instance,'TimeOffset',0.0)
        unreal.MaterialEditingLibrary.update_material_instance(instance);bridge.save(instance);instances[variant]=instance
    for oid,variant in WATER_IDS.items():
        a=actors[oid];c=a.static_mesh_component
        material=instances[variant]
        c.modify();c.set_material(0,material)
        c.set_editor_property('cast_shadow',False)
        c.set_editor_property('bounds_scale',1.02)
        c.set_visibility(True,False)
        changes.append({'id':oid,'label':a.get_actor_label(),'variant':variant,'material':material.get_path_name()})
    # Source Near/Far HISM are false even after construction. Preserve the
    # existing equivalent proxy but hide it to avoid coplanar double surfaces.
    proxy=actors[PROXY];proxy.static_mesh_component.set_visibility(False,False);proxy.set_actor_hidden_in_game(True)
    proxy.set_is_temporarily_hidden_in_editor(True)
    assert unreal.EditorLoadingAndSavingUtils.save_current_level()
    output={'water_objects':changes,'retained_hidden_proxy':PROXY,'saved':True,'stage':'applied',
            'source_objects':len(actors),'formula_status':'native compatibility, not original game implementation',
            'native_render_mapping':'Coast/deep/far share native SingleLayerWater for continuous refraction/reflections; original false-switch deep/far branch is not recovered.',
            'pending_original_features':['Custom native buoyancy/Gerstner generator','Runtime interactive height/normal simulation','Exact water data channel math','Original underwater and shoreline render passes']}
    (ROOT/'water_application.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    return output
