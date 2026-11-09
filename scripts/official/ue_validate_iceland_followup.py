"""Read-back validation for the explicit visibility/material/lighting repairs."""
import json,math
import unreal
import ue_iceland_bridge as bridge

ROOT=bridge.ROOT
errors=[]
def check(ok,reason,**detail):
    if not ok:errors.append({'reason':reason,**detail})

world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
assert world.get_path_name().split('.')[0]==bridge.MANIFEST['level']
actors=bridge.find_actors()
baseline=json.loads((ROOT/'followup_live_baseline.json').read_text(encoding='utf-8'))
check(set(actors)==set(baseline),'source object ID set changed')
sky_id='O_ca64216549857f97184c'
sky_path=bridge.DEST+'/Lighting/M_Iceland_SourceCapturedSky'
hidden_count=0
for oid,a in actors.items():
    old=baseline[oid];t=a.get_actor_transform()
    for key,values in [('translation',[t.translation.x,t.translation.y,t.translation.z]),
                       ('rotation',[t.rotation.x,t.rotation.y,t.rotation.z,t.rotation.w]),
                       ('scale',[t.scale3d.x,t.scale3d.y,t.scale3d.z])]:
        check(max(abs(x-y) for x,y in zip(old[key],values))<1e-5,'user transform changed',id=oid,property=key)
    check(a.get_actor_label()==old['label'],'user label changed',id=oid)
    check(a.get_editor_property('hidden')==old['hidden_game'],'game hidden flag changed',id=oid)
    if isinstance(a,unreal.StaticMeshActor):
        c=a.static_mesh_component
        check(c.get_editor_property('visible')==old['visible'],'helper component visibility changed',id=oid)
        hidden_count+=not c.get_editor_property('visible')
        expected=old['materials'] if oid!=sky_id else [sky_path+'.'+sky_path.rsplit('/',1)[-1]]
        check([m.get_path_name() if m else None for m in c.get_materials()]==expected,'object material binding changed unexpectedly',id=oid)

repair=json.loads((ROOT/'container_detail_compatibility_repair.json').read_text(encoding='utf-8'))
fixed=set(repair['instances']);parent=unreal.load_asset(repair['parent'])
root=unreal.MaterialEditingLibrary.get_material_property_input_node(parent,unreal.MaterialProperty.MP_BASE_COLOR)
check(root.get_editor_property('code')==repair['shader_code'],'container shader code differs')
for prop in [unreal.MaterialProperty.MP_BASE_COLOR,unreal.MaterialProperty.MP_NORMAL,
             unreal.MaterialProperty.MP_ROUGHNESS,unreal.MaterialProperty.MP_METALLIC]:
    check(unreal.MaterialEditingLibrary.get_material_property_input_node(parent,prop)==root,'container output disconnected',property=str(prop))
for row in bridge.INSTANCE_PLAN['instances']:
    obj=bridge.asset('Materials',row['id'])
    expected=parent if row['id'] in fixed else bridge.asset('Materials',row['parent'])
    check(obj.get_editor_property('parent')==expected,'material parent differs',id=row['id'])
    for name,value in row['scalars'].items():
        check(abs(unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(obj,name)-value)<max(1e-5,abs(value)*1e-6),'source tint/numeric value changed',id=row['id'],parameter=name)
    for name,value in row['textures'].items():
        check(unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(obj,name)==bridge.asset('Textures',value),'source texture changed',id=row['id'],parameter=name)

sky_actor=actors[sky_id];c=sky_actor.static_mesh_component
check(not c.get_editor_property('cast_shadow'),'sky shadow flag regressed')
check(not c.get_editor_property('visible_in_ray_tracing'),'sky raytracing flag regressed')
sky_mat=unreal.load_asset(sky_path)
check(sky_mat.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_UNLIT,'sky is not unlit')
check(sky_mat.get_editor_property('is_sky'),'sky flag missing')
check(unreal.MaterialEditingLibrary.get_material_property_input_node(sky_mat,unreal.MaterialProperty.MP_EMISSIVE_COLOR) is not None,'sky emission disconnected')
bylabel={a.get_actor_label():a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()}
sun=bylabel['Iceland Source Sun'];rot=sun.get_actor_rotation()
for name,value in [('pitch',-28.244196),('yaw',16.426135),('roll',-4.159392)]:
    check(abs(getattr(rot,name)-value)<1e-4,'source sun rotation differs',axis=name)
check(abs(sun.light_component.get_editor_property('intensity')-2000)<.01,'sun intensity differs')
sky=bylabel['Iceland Source SkyLight'].light_component
cube=unreal.load_asset(bridge.DEST+'/Lighting/T_Iceland_SCb0_19_2_Source')
check(sky.get_editor_property('cubemap')==cube,'source HDR cube not bound')
check(not cube.get_editor_property('srgb'),'HDR cube was gamma corrected')
check(cube.get_editor_property('compression_settings')==unreal.TextureCompressionSettings.TC_HDR,'HDR cube recompressed')
check(abs(sky.get_editor_property('intensity')-900)<.01,'native IBL intensity differs')
fog=bylabel['Iceland Source HeightFog'].component
check(abs(fog.get_editor_property('fog_density')-.03)<1e-6,'source fog density differs')
check(abs(fog.get_editor_property('fog_cutoff_distance')-2000000)<1,'baked sky was fogged again')
post=bylabel['Iceland Source Exposure'].get_editor_property('settings')
ev=math.log2(post.depth_of_field_fstop**2*post.camera_shutter_speed*100/post.camera_iso)
check(abs(ev-8.8)<1e-5,'native exposure differs')
check(post.auto_exposure_method==unreal.AutoExposureMethod.AEM_MANUAL,'manual exposure changed')
output_data={'source_objects':len(actors),'hidden_mesh_components':hidden_count,
             'checked_material_instances':len(bridge.INSTANCE_PLAN['instances']),
             'repaired_container_instances':len(fixed),'exposure_ev100':ev,
             'source_sun_lux':sun.light_component.get_editor_property('intensity'),
             'errors':errors,'complete':True}
(ROOT/'followup_final_validation.json').write_text(json.dumps(output_data,ensure_ascii=False,indent=2),encoding='utf-8')
