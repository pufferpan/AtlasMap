"""Add a separate preview-lighting rig and save the newly imported map."""
import json
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge

world=unreal.EditorLevelLibrary.get_editor_world()
if world.get_path_name().split('.')[0]!=bridge.MANIFEST['level']:raise RuntimeError('Refusing to light the wrong level')
sub=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
existing={a.get_actor_label():a for a in sub.get_all_level_actors()}
def create(cls,label,location):
    actor=existing.get(label) or sub.spawn_actor_from_class(cls,unreal.Vector(*location))
    actor.set_actor_label(label);actor.set_folder_path('Iceland/_PreviewLighting');actor.tags=[unreal.Name('IcelandPreviewLighting')]
    return actor
env_path=bridge.DEST+'/Lighting/T_BlenderForest_Environment'
env=unreal.EditorAssetLibrary.load_asset(env_path)
if env is None:
    env=bridge.import_task(bridge.ROOT/'forest_environment.hdr',bridge.DEST+'/Lighting','T_BlenderForest_Environment')
    bridge.save(env)
if not isinstance(env,unreal.TextureCube):raise RuntimeError('HDR environment did not import as TextureCube')
sky=create(unreal.SkyLight,'Iceland Preview SkyLight',(200000,-200000,50000))
component=sky.light_component
component.set_mobility(unreal.ComponentMobility.MOVABLE)
component.set_editor_property('source_type',unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
component.set_editor_property('cubemap',env)
component.set_editor_property('intensity',1.0)
component.set_editor_property('cubemap_resolution',256)
component.set_editor_property('real_time_capture',False)
sun=create(unreal.DirectionalLight,'Iceland Preview Sun',(200000,-200000,100000))
sun.set_actor_rotation(unreal.Rotator(pitch=-42,yaw=-35,roll=0),False)
sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
sun.light_component.set_intensity(3.0)
post=create(unreal.PostProcessVolume,'Iceland Preview Exposure',(200000,-200000,0))
post.set_editor_property('unbound',True)
settings=post.get_editor_property('settings')
for key,val in {'override_auto_exposure_min_brightness':True,'override_auto_exposure_max_brightness':True,
                'auto_exposure_min_brightness':1.0,'auto_exposure_max_brightness':1.0,
                'override_auto_exposure_bias':True,'auto_exposure_bias':0.0,
                'override_bloom_intensity':True,'bloom_intensity':0.0}.items():settings.set_editor_property(key,val)
post.set_editor_property('settings',settings)
unreal.EditorLevelLibrary.set_level_viewport_camera_info(unreal.Vector(200000,-120000,150000),unreal.Rotator(pitch=-48,yaw=-90,roll=0))
layers=unreal.get_editor_subsystem(unreal.LayersSubsystem)
layers.set_layer_visibility('Iceland_Blender_Hidden',False)
if not unreal.EditorLoadingAndSavingUtils.save_current_level():raise RuntimeError('Map save failed')
report={'level':bridge.MANIFEST['level'],'source_objects':len(bridge.find_actors()),'preview_lighting':[sky.get_path_name(),sun.get_path_name(),post.get_path_name()],
        'environment_source':'Blender forest.exr, converted to Radiance HDR for import',
        'note':'Separate preview lighting is added because the accepted Blender scene used material-preview lighting. Engine tonemapping and lighting are not identical.'}
(bridge.ROOT/'scene_completion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
output_data=report
