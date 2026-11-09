"""Source-backed Iceland lighting reconstruction; import then call apply().

Does not execute on import. Keeps all source actors. Native UE conversions are
explicit parameters because the cooked game's NZSkyBox/PRT engine is unavailable.
"""
import json,math
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge

SOURCE=Path('D:/AtlasMap-tooling/out/Iceland/audit/environment_query/lighting')
DEST=bridge.DEST+'/Lighting'

def image_asset():
    name='T_Iceland_Skybox_PC_RGBM_Source'
    obj=unreal.load_asset(DEST+'/'+name)
    if not obj:
        obj=bridge.import_task(SOURCE/'Iceland_Skybox_PC_RGBM.png',DEST,name)
    obj.set_editor_property('srgb',False)
    obj.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_EDITOR_ICON)
    obj.set_editor_property('never_stream',True)
    bridge.save(obj)
    return obj

def sky_material(energy_scale,rotation_turns,rgbm_range):
    tex=image_asset();name='M_Iceland_SourceSky_RGBM'
    mat=unreal.load_asset(DEST+'/'+name)
    if not mat:
        mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,DEST,unreal.Material,unreal.MaterialFactoryNew())
    else:
        unreal.MaterialEditingLibrary.delete_all_material_expressions(mat)
    mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property('two_sided',True)
    mat.set_editor_property('is_sky',True)
    mat.set_editor_property('blend_mode',unreal.BlendMode.BLEND_OPAQUE)
    cam=bridge.expression(mat,unreal.MaterialExpressionCameraVectorWS,-1200,0)
    uv=bridge.expression(mat,unreal.MaterialExpressionCustom,-1000,0)
    uv.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT2)
    # Rotation unit is an explicit compatibility interpretation: source Rotate=1.2.
    uv.set_editor_property('code',f'float3 d=normalize(-D); return float2(frac(atan2(d.y,d.x)/6.28318530718+0.5+{rotation_turns:.9f}),acos(clamp(d.z,-1.0,1.0))/3.14159265359);')
    bridge.custom_inputs(uv,['D']);bridge.link(cam,'',uv,'D')
    sample=bridge.expression(mat,unreal.MaterialExpressionTextureSample,-700,0)
    sample.set_editor_property('texture',tex)
    sample.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    bridge.link(uv,'',sample,'UVs')
    rgba=bridge.expression(mat,unreal.MaterialExpressionAppendVector,-500,0)
    bridge.link(sample,'',rgba,'A');bridge.link(sample,'A',rgba,'B')
    decode=bridge.expression(mat,unreal.MaterialExpressionCustom,-200,0)
    decode.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    decode.set_editor_property('description','TC_HDR_RGBM compatibility decode; source HDRScale 0.7')
    decode.set_editor_property('code',f'float h=normalize(-D).z; float3 clouds=C.rgb*(C.a*{rgbm_range:.9f})*0.7; float3 underground=float3(0.00241,0.00294,0.00326); return lerp(underground,clouds,smoothstep(-0.05,0.0,h))*{energy_scale:.9f};')
    bridge.custom_inputs(decode,['C','D']);bridge.link(rgba,'',decode,'C');bridge.link(cam,'',decode,'D')
    bridge.output_link(decode,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.recompile_material(mat)
    bridge.metadata(mat,'SourceMaterial','/Game/Environment/Sky/IceLandTOD_Sky/HDRI_Sky_01/Sky_Iceland_PC')
    bridge.metadata(mat,'CompatibilityAdaptation',json.dumps({'rgbm_range':rgbm_range,'sky_energy_scale':energy_scale,'rotation_turns':rotation_turns,'source_HDRScale':.7}))
    bridge.save(mat)
    return mat

def captured_sky_material(energy_scale):
    """Use the game's baked sky capture, including its prepared horizon.

    This avoids inventing the stripped RGBM material's horizon composition,
    rotation units and decode range. The original capture is only 128px/face.
    """
    cube=unreal.load_asset(DEST+'/T_Iceland_SCb0_19_2_Source')
    name='M_Iceland_SourceCapturedSky'
    mat=unreal.load_asset(DEST+'/'+name)
    if mat and unreal.EditorAssetLibrary.get_metadata_tag(mat,'NativeEnergyScale')==str(energy_scale):
        return mat
    if not mat:
        mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,DEST,unreal.Material,unreal.MaterialFactoryNew())
    else:unreal.MaterialEditingLibrary.delete_all_material_expressions(mat)
    mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property('two_sided',True);mat.set_editor_property('is_sky',True)
    camera=bridge.expression(mat,unreal.MaterialExpressionCameraVectorWS,-1000,0)
    direction=bridge.expression(mat,unreal.MaterialExpressionCustom,-800,0)
    direction.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    direction.set_editor_property('code','return normalize(-D);')
    bridge.custom_inputs(direction,['D']);bridge.link(camera,'',direction,'D')
    sample=bridge.expression(mat,unreal.MaterialExpressionTextureSample,-600,0)
    sample.set_editor_property('texture',cube)
    sample.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    bridge.link(direction,'',sample,'UVs')
    scale=bridge.expression(mat,unreal.MaterialExpressionCustom,-300,0)
    scale.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    scale.set_editor_property('code',f'return C*{energy_scale:.9f};')
    bridge.custom_inputs(scale,['C']);bridge.link(sample,'',scale,'C')
    bridge.output_link(scale,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.recompile_material(mat)
    bridge.metadata(mat,'SourceCapture','/Game/Maps/Iceland/ClientConfig/Lighting/ReflectionCubes_HD/IceLand_TODLight_245/SCb0_19_2')
    bridge.metadata(mat,'NativeEnergyScale',str(energy_scale));bridge.save(mat)
    return mat

def apply(ibl_coefficient=500.0,sky_energy_scale=500.0,manual_ev100=8.8,
          sky_rotation_turns=1.2,rgbm_range=64.0,enable_volumetric_fog=True,use_baked_capture=True,
          fog_energy_scale=500.0,static_gi_fill=2.0):
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    assert world.get_path_name().split('.')[0]==bridge.MANIFEST['level']
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    bylabel={a.get_actor_label():a for a in actors.get_all_level_actors()}
    sun=bylabel.get('Iceland Source Sun') or bylabel['Iceland Preview Sun']
    sky=bylabel.get('Iceland Source SkyLight') or bylabel['Iceland Preview SkyLight']
    post=bylabel.get('Iceland Source Exposure') or bylabel['Iceland Preview Exposure']
    for actor,label in [(sun,'Iceland Source Sun'),(sky,'Iceland Source SkyLight'),(post,'Iceland Source Exposure')]:
        actor.set_actor_label(label);actor.set_folder_path('Iceland/_SourceLighting')
        actor.tags=[unreal.Name('IcelandSourceLighting')]
    # Saved component orientation composed with NZSkyBoxComponent's -114.999985 yaw.
    sun.set_actor_rotation(unreal.Rotator(pitch=-28.244196,yaw=16.426135,roll=-4.159392),False)
    sun.light_component.set_intensity(2000.0)
    sun.light_component.set_editor_property('light_source_angle',2.35)
    sun.light_component.set_editor_property('shadow_bias',.2)
    sun.light_component.set_editor_property('volumetric_scattering_intensity',1.0)
    cube=unreal.load_asset(DEST+'/T_Iceland_SCb0_19_2_Source')
    assert isinstance(cube,unreal.TextureCube),'Import SCb0_19_2_RGBA16F.dds first'
    c=sky.light_component
    c.set_editor_property('source_type',unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
    c.set_editor_property('cubemap',cube)
    # Native ambient fill substitutes for unavailable custom GI2D/PRT. The
    # source GiAdjust.PrtMult is 2, but this is not its original algorithm.
    c.set_intensity(.9*ibl_coefficient*static_gi_fill)
    c.set_editor_property('light_color',unreal.Color(r=128,g=128,b=128,a=255))
    c.set_editor_property('lower_hemisphere_is_black',False)
    c.set_editor_property('lower_hemisphere_color',unreal.LinearColor(.48,.48,.48,1))
    c.set_editor_property('volumetric_scattering_intensity',2.0)
    # Source sky mesh exists in the imported manifest: change its object override only.
    sky_actor=bridge.find_actors()['O_ca64216549857f97184c']
    sky_actor.static_mesh_component.set_material(0,captured_sky_material(sky_energy_scale) if use_baked_capture else sky_material(sky_energy_scale,sky_rotation_turns,rgbm_range))
    sky_actor.static_mesh_component.set_editor_property('cast_shadow',False)
    sky_actor.static_mesh_component.set_editor_property('visible_in_ray_tracing',False)
    fog=bylabel.get('Iceland Source HeightFog')
    if not fog:
        fog=actors.spawn_actor_from_class(unreal.ExponentialHeightFog,unreal.Vector(195410,-159770,-23508.266))
        fog.set_actor_label('Iceland Source HeightFog')
        fog.set_folder_path('Iceland/_SourceLighting')
        fog.tags=[unreal.Name('IcelandSourceLighting')]
    fc=fog.component
    props={'fog_density':.03,'fog_height_falloff':.039076,'fog_max_opacity':1.0,'start_distance':5000.0,
           'fog_cutoff_distance':2000000.0,
           'fog_inscattering_luminance':unreal.LinearColor(.018786*fog_energy_scale,.034763*fog_energy_scale,.034763*fog_energy_scale,1),
           'directional_inscattering_luminance':unreal.LinearColor(.019097*fog_energy_scale,.012803*fog_energy_scale,.009636*fog_energy_scale,1),
           'directional_inscattering_exponent':3.180953,'directional_inscattering_start_distance':131.63925,
           'enable_volumetric_fog':enable_volumetric_fog,'volumetric_fog_scattering_distribution':.6,
           'volumetric_fog_extinction_scale':.5,'volumetric_fog_distance':6000.0}
    for key,value in props.items():fc.set_editor_property(key,value)
    post.set_editor_property('unbound',True)
    s=post.get_editor_property('settings')
    source_pp={'white_temp':6500.0,'bloom_intensity':.05,'bloom_threshold':-.7,'bloom_size_scale':2.0,
               'blue_correction':0.0,'expand_gamut':0.0,'ambient_occlusion_intensity':.9,
               'ambient_occlusion_radius':141.26158,'ambient_occlusion_bias':3.0,'ambient_occlusion_power':2.0,
               'ambient_occlusion_quality':50.0,'local_exposure_shadow_contrast_scale':.9,
               'local_exposure_blurred_luminance_blend':.3,'local_exposure_detail_strength':1.1,
               'color_correction_shadows_max':.09,'color_correction_highlights_min':.5}
    for key,value in source_pp.items():
        s.set_editor_property('override_'+key,True);s.set_editor_property(key,value)
    # Project uses old exposure brightness units. Manual camera EV avoids mixing units.
    # EV100 = log2(N^2 * shutter_speed * 100 / ISO).
    exposure={'auto_exposure_method':unreal.AutoExposureMethod.AEM_MANUAL,
              'auto_exposure_apply_physical_camera_exposure':True,'camera_iso':100.0,
              'depth_of_field_fstop':4.0,'camera_shutter_speed':2**manual_ev100/16,
              'auto_exposure_bias':0.0}
    for key,value in exposure.items():
        s.set_editor_property('override_'+key,True);s.set_editor_property(key,value)
    post.set_editor_property('settings',s)
    c.recapture_sky()
    assert unreal.EditorLoadingAndSavingUtils.save_current_level()
    report={'source_sequence':'/Game/Environment/SequencerTOD/Battlefield/Iceland_HD/Iceland_HD',
            'source_weather_id':8001,'source_sun_intensity':2000,'source_sun_world_rotation':[-28.244196,16.426135,-4.159392],
            'source_skylight_intensity':.9,'source_skylight_srgb_color':[128,128,128],
            'source_HDRScale':.7,'source_RGBM_texture':'Iceland_Skybox_PC_RGBM.png','source_cube':'SCb0_19_2_RGBA16F.dds',
            'source_parameters_applied':source_pp,'source_TOD_exposure_EV_bounds':[8.8,15.0],
            'compatibility':{'ibl_coefficient':ibl_coefficient,'sky_energy_scale':sky_energy_scale,'manual_ev100':manual_ev100,
                             'fog_energy_scale':fog_energy_scale,
                             'static_gi_fill':static_gi_fill,
                             'sky_background':'source_baked_capture_128px_faces' if use_baked_capture else 'RGBM_reconstruction',
                             'rgbm_range':None if use_baked_capture else rgbm_range,'sky_rotation_turns':None if use_baked_capture else sky_rotation_turns},
            'limitations':['Original NZSkyBox exposure and irradiance normalization code unavailable',
                           'Original GI2D/PRT, cloud shadow light function and custom fog map are not reconstructed',
                           'Baked source sky capture substitutes for stripped source sky shader; capture resolution is 128px per face',
                           'Verify shader compilation, source override changes and saved map reopen before delivery']}
    (bridge.ROOT/'source_lighting_application.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
