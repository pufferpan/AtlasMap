"""Restore native UE lights from the selected map's lights.json in UE cm.

ATLASMAP_SOURCE_ROOT points to the map export; ATLASMAP_UE_LEVEL names its level.
The sidecar also carries Rect/Sky/Fog, which glTF cannot represent faithfully.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

import unreal
from map_lighting import DISTANCE_FIELDS, records as source_records, postprocess_box
from map_game_lighting import build_profile
try:
    from ue_sky_capture import prepare_sky,finalize_skies
except ModuleNotFoundError:
    from scripts.official.ue_sky_capture import prepare_sky,finalize_skies

TAG = "AtlasMapLighting_"


def _log(message):
    unreal.log("[light] " + str(message))


def _records(data):
    yield from source_records(data)


def _snake(name):
    name=re.sub(r'^b(?=[A-Z])','',name)
    name=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',name)
    return re.sub(r'([A-Z])([A-Z][a-z])',r'\1_\2',name).lower()


def _value(value,current):
    if isinstance(value,str) and '::' in value:
        token=value.split('::')[-1].upper()
        if hasattr(type(current),token):return getattr(type(current),token)
    if not isinstance(value,dict):return value
    if isinstance(current,unreal.LinearColor):
        return unreal.LinearColor(*(float(value.get(k.upper(),getattr(current,k))) for k in ('r','g','b','a')))
    if isinstance(current,unreal.Color):
        return unreal.Color(*(int(value.get(k.upper(),getattr(current,k))) for k in ('r','g','b','a')))
    if isinstance(current,unreal.Vector4):
        return unreal.Vector4(*(float(value.get(k.upper(),getattr(current,k))) for k in ('x','y','z','w')))
    if hasattr(current,'set_editor_property'):
        for key,item in value.items():
            prop=_snake(key)
            try:current.set_editor_property(prop,_value(item,current.get_editor_property(prop)))
            except Exception:pass
        return current
    raise ValueError('Unsupported source structure: '+str(type(current)))


def _assign(target,prop,value,report,source_name):
    try:
        current=target.get_editor_property(prop)
        target.set_editor_property(prop,_value(value,current))
        return True
    except Exception as exc:
        note='Source field unavailable in stock UE: '+source_name
        if note not in report['compatibility']:report['compatibility'].append(note)
        return False


def _distance_report(report):
    return report.setdefault('distance_fields', {
        'expected_fields': 0, 'applied_fields': 0, 'checked_fields': 0,
        'matched_fields': 0, 'missing_source_fields': [], 'errors': []})


def _distance_error(report, row, source_name, prop, phase, error):
    issue = {'name': row.get('name'), 'type': row.get('type'),
             'source_field': source_name, 'target_property': prop,
             'phase': phase, 'error': str(error)}
    _distance_report(report)['errors'].append(issue)
    report.setdefault('errors', []).append(issue)


def _restore_light_distances(comp, row, report):
    """Apply source distance fields through the editor API, never hasattr.

    Legacy sidecars can lack these fields. Record that gap and keep their
    existing compatibility behavior; a missing value is not guessed as zero.
    A supplied source field which cannot be applied is an import error.
    """
    state = _distance_report(report)
    for key, source_name, prop in DISTANCE_FIELDS:
        if key not in row:
            state['missing_source_fields'].append({
                'name': row.get('name'), 'type': row.get('type'),
                'source_field': source_name, 'target_property': prop})
            continue
        state['expected_fields'] += 1
        try:
            comp.get_editor_property(prop)
            comp.set_editor_property(prop, float(row[key]))
            state['applied_fields'] += 1
        except Exception as exc:
            _distance_error(report, row, source_name, prop, 'apply', exc)


def _validate_light_distances(comp, row, report):
    """Read back every supplied source field independently of the apply result.

    In particular, do not reuse a capability/hasattr filter from the importer:
    an unreadable or mismatching native property must fail the final report.
    """
    state = _distance_report(report)
    for key, source_name, prop in DISTANCE_FIELDS:
        if key not in row:
            continue
        try:
            expected = float(row[key])
            actual = float(comp.get_editor_property(prop))
            state['checked_fields'] += 1
            if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-4):
                raise ValueError('Expected source value %r, native readback %r' % (expected, actual))
            state['matched_fields'] += 1
        except Exception as exc:
            _distance_error(report, row, source_name, prop, 'readback', exc)


def _visibility_report(report):
    return report.setdefault('component_visibility', {
        'expected_fields': 0, 'applied_fields': 0, 'checked_fields': 0,
        'matched_fields': 0, 'missing_source_fields': [], 'errors': []})


def _visibility_error(report, row, phase, error):
    issue = {'name': row.get('name'), 'type': row.get('type'),
             'source_field': 'Visible', 'target_property': 'visible',
             'phase': phase, 'error': str(error)}
    _visibility_report(report)['errors'].append(issue)
    report.setdefault('errors', []).append(issue)


def _restore_component_visibility(comp, row, report):
    """Fog and light components both obey explicit source visibility.

    Missing visibility leaves the existing/default state alone. A False source
    value is meaningful and must not be replaced by a fallback True value.
    """
    state = _visibility_report(report)
    if 'visible' not in row:
        state['missing_source_fields'].append({'name': row.get('name'), 'type': row.get('type')})
        return
    state['expected_fields'] += 1
    try:
        comp.set_visibility(bool(row['visible']), False)
        state['applied_fields'] += 1
    except Exception as exc:
        _visibility_error(report, row, 'visibility_apply', exc)


def _validate_component_visibility(comp, row, report):
    """Independently read back every explicit visibility expectation."""
    if 'visible' not in row:
        return
    state = _visibility_report(report)
    try:
        expected = bool(row['visible'])
        actual = bool(comp.get_editor_property('visible'))
        state['checked_fields'] += 1
        if actual != expected:
            raise ValueError('Expected source visibility %r, native readback %r' % (expected, actual))
        state['matched_fields'] += 1
    except Exception as exc:
        _visibility_error(report, row, 'visibility_readback', exc)


def _fog(comp,props,report):
    fields=('FogDensity','FogHeightFalloff','SecondFogData','FogInscatteringColor','FogMaxOpacity',
            'StartDistance','FogCutoffDistance','DirectionalInscatteringExponent',
            'DirectionalInscatteringStartDistance','DirectionalInscatteringColor',
            'bEnableVolumetricFog','VolumetricFogScatteringDistribution','VolumetricFogAlbedo',
            'VolumetricFogEmissive','VolumetricFogExtinctionScale','VolumetricFogDistance',
            'VolumetricFogStaticLightingScatteringIntensity')
    for key in fields:
        if key in props:
            prop={'FogInscatteringColor':'fog_inscattering_luminance',
                  'DirectionalInscatteringColor':'directional_inscattering_luminance'}.get(key,_snake(key))
            _assign(comp,prop,props[key],report,key)
    report['source_fog_settings']=True


def _postprocess(eas,rows,report):
    for row in rows:
        props=row['properties']; transform=row['transform']
        position,extent=postprocess_box(row)
        rot=transform.get('RelativeRotation',{})
        from ue_actor_spawn import spawn_actor
        actor=spawn_actor(unreal,unreal.TriggerBox,
            unreal.Vector(*position),
            unreal.Rotator(pitch=rot.get('Pitch',0),yaw=rot.get('Yaw',0),roll=rot.get('Roll',0)))
        actor.tags=[unreal.Name(TAG+'post_'+hashlib.sha256((row['level']+row['name']).encode()).hexdigest()[:20])]
        actor.set_actor_label('AtlasMap Source PostProcess '+row['name'])
        actor.set_folder_path('AtlasMap/Lighting')
        box=actor.get_component_by_class(unreal.BoxComponent)
        bounds=row.get('bounds')
        if bounds:
            box.set_box_extent(unreal.Vector(*extent),False)
        box.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        subsystem=unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        handles=subsystem.k2_gather_subobject_data_for_instance(actor)
        handle,reason=subsystem.add_new_subobject(unreal.AddNewSubobjectParams(
            parent_handle=handles[0],new_class=unreal.PostProcessComponent))
        comp=unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
            unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle))
        if comp is None:raise RuntimeError('Cannot add source post-process component: '+str(reason))
        comp.attach_to_component(box, '', unreal.AttachmentRule.KEEP_RELATIVE,
            unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, False)
        if comp.get_attach_parent()!=box:
            raise RuntimeError('Source post-process component is not attached to its volume bounds')
        comp.set_editor_property('unbound',bool(props.get('bUnbound',not bool(bounds))))
        comp.set_editor_property('priority',float(props.get('Priority',0)))
        comp.set_editor_property('blend_weight',float(props.get('BlendWeight',1)))
        comp.set_editor_property('blend_radius',float(props.get('BlendRadius',100)))
        settings=comp.get_editor_property('settings')
        source=props.get('Settings',{})
        applied=[]
        for key,enabled in source.items():
            if not key.startswith('bOverride_') or not enabled:continue
            field=key[len('bOverride_'):]
            if not _assign(settings,'override_'+_snake(field),True,report,key):continue
            if field in source and not _assign(settings,_snake(field),source[field],report,field):continue
            applied.append(field)
        comp.set_editor_property('settings',settings)
        report['postprocess'].append({'name':row['name'],'settings':applied,'bounded':bool(bounds),
            'unbound':bool(comp.get_editor_property('unbound')),'center':position,'extent':extent,
            'bounds_attached':True})


def _spawn(eas, cls, key, position, rotation, old):
    actor = old.get(TAG + key)
    if actor is None:
        from ue_actor_spawn import spawn_actor
        actor = spawn_actor(unreal, cls, unreal.Vector(*position), rotation)
    if actor is None:
        raise RuntimeError(f"Failed to spawn {cls}: {key}")
    actor.set_actor_location(unreal.Vector(*position), False, True)
    actor.set_actor_rotation(rotation, True)
    actor.tags = [unreal.Name(TAG + key)]
    actor.set_folder_path("AtlasMap/Lighting")
    return actor


def camera_key(row):
    return 'camera_'+hashlib.sha256((row['level']+row.get('actor','')+row['name']).encode()).hexdigest()[:20]


def _cameras(eas, rows, old, report):
    report['source_cameras']=[]
    for row in rows:
        roll,pitch,yaw=row['rot']
        actor=_spawn(eas,unreal.CameraActor,camera_key(row),row['loc'],
                     unreal.Rotator(pitch=pitch,yaw=yaw,roll=roll),old)
        actor.set_actor_label('AtlasMap Source Camera '+row.get('actor',row['name']))
        actor.set_folder_path('AtlasMap/Cameras')
        comp=actor.camera_component
        comp.set_field_of_view(float(row['fov']))
        props=row.get('properties',{})
        settings=comp.get_editor_property('post_process_settings')
        applied=[]
        source=props.get('PostProcessSettings',{})
        for key,enabled in source.items():
            if not key.startswith('bOverride_') or not enabled:continue
            field=key[len('bOverride_'):]
            if field not in source:continue
            if _assign(settings,'override_'+_snake(field),True,report,key) and _assign(settings,_snake(field),source[field],report,field):
                applied.append(field)
        comp.set_editor_property('post_process_settings',settings)
        comp.set_editor_property('post_process_blend_weight',float(props.get('PostProcessBlendWeight',1)))
        report['source_cameras'].append({'key':camera_key(row),'actor':row.get('actor',''),'settings':applied})


def _game_profile(eas, profile, center, old, report):
    report['game_profile']=dict(profile)
    if not profile['enabled']:return
    actor=_spawn(eas,unreal.PostProcessVolume,'game_profile',center,unreal.Rotator(),old)
    actor.set_actor_label('AtlasMap Game Lighting Compatibility')
    actor.set_editor_property('unbound',True)
    actor.set_editor_property('priority',100.0 if profile.get('explicit_override_fields') else -100.0)
    settings=actor.get_editor_property('settings')
    fields={'local_exposure_highlight_contrast_scale':profile['local_highlight_contrast'],
            'local_exposure_shadow_contrast_scale':profile['local_shadow_contrast'],
            'dynamic_global_illumination_method':unreal.DynamicGlobalIlluminationMethod.LUMEN,
            'reflection_method':unreal.ReflectionMethod.LUMEN}
    if profile['exposure_bias_ev'] is not None:
        fields['auto_exposure_bias']=profile['exposure_bias_ev']
    applied={}
    for prop,value in fields.items():
        settings.set_editor_property('override_'+prop,True)
        settings.set_editor_property(prop,value)
    actor.set_editor_property('settings',settings)
    readback=actor.get_editor_property('settings')
    for prop,value in fields.items():
        actual=readback.get_editor_property(prop)
        matched=math.isclose(float(actual),value,abs_tol=1e-5) if isinstance(value,(int,float)) else actual==value
        if not readback.get_editor_property('override_'+prop) or not matched:
            raise RuntimeError('Game lighting profile readback failed: '+prop)
        applied[prop]=float(actual) if isinstance(value,(int,float)) else str(actual)
    report['game_profile']['native_readback']=applied


def _source_exposure(eas, data, root, report, plan_data=None, plan_root=None):
    """Restore a proven constant desktop range together with its source curve.

    Missing/dynamic/ambiguous source state is reported, never replaced by an
    arbitrary outdoor EV or by a mobile fixed-exposure setting.
    """
    try:
        from map_exposure import build_plan,package_path
        from ue_source_exposure import apply_to_component
    except ModuleNotFoundError:
        from scripts.official.map_exposure import build_plan,package_path
        from scripts.official.ue_source_exposure import apply_to_component
    # First establish source evidence. Legacy exports with no TOD resources
    # need no native exposure APIs and retain their existing behavior.
    evidence_data=plan_data if plan_data is not None else data
    evidence_root=plan_root if plan_root is not None else root
    plan=build_plan(evidence_data,evidence_root,False)
    state={'eligible':plan['eligible'],'source_ev_limits':plan['source_ev_limits'],
        'native_limits':plan['native_limits'],'errors':plan['errors'],
        'skipped_missing':plan['skipped_missing'],'applied':[]}
    report['source_exposure']=state
    if not plan['eligible']:return
    extended=bool(unreal.SystemLibrary.get_console_variable_int_value(
        'r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange'))
    lens=unreal.SystemLibrary.get_console_variable_float_value('r.EyeAdaptation.LensAttenuation')
    plan=build_plan(evidence_data,evidence_root,extended,lens)
    state['native_limits']=plan['native_limits']
    actors={str(tag):a for a in eas.get_all_level_actors() for tag in a.tags}
    for row in data.get('postprocess',[]):
        settings=row.get('properties',{}).get('Settings',{})
        reference=settings.get('AutoExposureBiasCurve') or {}
        if not settings.get('bOverride_AutoExposureBiasCurve'):continue
        if package_path(reference.get('ObjectPath',''))!=plan['curve']['source_package']:continue
        tag=TAG+'post_'+hashlib.sha256((row['level']+row['name']).encode()).hexdigest()[:20]
        actor=actors.get(tag)
        if actor is None:continue
        component=actor.get_component_by_class(unreal.PostProcessComponent)
        if component is None:raise RuntimeError('Source exposure postprocess component is missing')
        destination=os.environ.get('ATLASMAP_UE_DEST','/Game/AtlasMaps/Map').rstrip('/')+'/Environment'
        result=apply_to_component(unreal,component,plan,destination,
            work_directory=Path(root)/'source-render/exposure-curves')
        state['applied'].append({'actor':actor.get_path_name(),'result':result})
    coefficient=plan.get('source_ibl_coefficient')
    if state['applied'] and coefficient is not None:
        # Saved light records remain unchanged. This explicit native adapter
        # uses the source IBL coefficient alongside the physical exposure.
        state['native_ibl_unit_mapping']=[]
        for key,row in _records(data):
            if row['type']!='Sky':continue
            actor=actors.get(TAG+key)
            component=actor.get_component_by_class(unreal.SkyLightComponent) if actor else None
            if component is None:continue
            if component.get_editor_property('source_type')!=unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP:continue
            if not isinstance(component.get_editor_property('cubemap'),unreal.TextureCube):continue
            authored=float(row.get('intensity',1));native=authored*coefficient
            component.set_editor_property('intensity',native)
            actual=float(component.get_editor_property('intensity'))
            if not math.isclose(actual,native,rel_tol=1e-6,abs_tol=1e-5):raise RuntimeError('Native IBL intensity readback mismatch')
            state['native_ibl_unit_mapping'].append({'actor':actor.get_path_name(),
                'source_intensity':authored,'source_coefficient':coefficient,'native_intensity':actual,
                'basis':'Explicit native compatibility units coupled to source physical exposure'})


def main():
    level = os.environ.get("ATLASMAP_UE_LEVEL", "")
    source = os.environ.get("ATLASMAP_SOURCE_ROOT", "")
    if not level or not source:
        raise RuntimeError("ATLASMAP_UE_LEVEL and ATLASMAP_SOURCE_ROOT must name the selected map")
    root = Path(source)
    if (root/'source-render/state-index.json').is_file():
        from map_scene_state import enrich
        data=enrich(root)
    else:
        data = json.loads((root / "lights.json").read_text(encoding="utf-8-sig"))
    rows = list(_records(data))
    profile_root=Path(os.environ.get('ATLASMAP_GLOBAL_SOURCE_ROOT') or root)
    profile_data=json.loads((profile_root/'render_state.json').read_text(encoding='utf-8')) if profile_root!=root else data
    profile=build_profile(profile_data,profile_root,os.environ.get('ATLASMAP_RENDER_PROFILE','game'))
    primary_chunk=os.environ.get('ATLASMAP_UE_PRIMARY_CHUNK','1')=='1'
    report = {"level": level, "source": str(root / "lights.json"),
              "source_count": len(data.get("lights", [])), "restored": {},
              "fallback": [], "compatibility": [], "errors": [], "complete": False,
              "mode": os.environ.get("ATLASMAP_LIGHTING_MODE", "source"),
              "coordinate_system": "Original UE centimetres; roll/pitch/yaw; linear RGB"}
    report['source_state_schema']=data.get('schema',0)
    report['fog_only_lights']=0
    report['postprocess']=[]
    _distance_report(report)
    distance_targets=[]
    visibility_targets=[]
    _visibility_report(report)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world.get_path_name().split('.')[0] != level and not les.load_level(level):
        raise RuntimeError("Cannot load selected level: " + level)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()
    old = {str(tag): actor for actor in actors for tag in actor.tags if str(tag).startswith(TAG)}
    wanted = {TAG + key for key, _ in rows}
    wanted.update(TAG+camera_key(row) for row in data.get('cameras',[]))
    if profile['enabled'] and primary_chunk:wanted.add(TAG+'game_profile')
    for tag, actor in old.items():
        if tag not in wanted:
            eas.destroy_actor(actor)
    classes = {"Point": (unreal.PointLight, unreal.PointLightComponent),
               "Spot": (unreal.SpotLight, unreal.SpotLightComponent),
               "Rect": (unreal.RectLight, unreal.RectLightComponent),
               "Directional": (unreal.DirectionalLight, unreal.DirectionalLightComponent),
               "Sky": (unreal.SkyLight, unreal.SkyLightComponent),
               "Fog": (unreal.ExponentialHeightFog, unreal.ExponentialHeightFogComponent)}
    zero = unreal.Rotator(pitch=0, yaw=0, roll=0)
    for key, row in rows:
        kind = row.get("type")
        try:
            if kind not in classes:
                raise ValueError("Unsupported source light type: " + str(kind))
            cls, component_class = classes[kind]
            roll, pitch, yaw = row.get("rot") or [0, 0, 0]
            actor = _spawn(eas, cls, key, row.get("loc") or [0, 0, 0],
                           unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw), old)
            actor.set_actor_label("AtlasMap Source " + kind + " " + str(row.get("name", key)))
            comp = actor.get_component_by_class(component_class)
            comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            if kind in ('Point', 'Spot', 'Rect'):
                # Register the expectation before applying it so a failure in
                # either stage cannot make the independent audit skip it.
                distance_targets.append((comp, row))
                _restore_light_distances(comp, row, report)
            if kind == "Fog":
                props=row.get('source',{}).get('properties',{})
                if props:
                    _fog(comp,props,report)
                else:
                    report["compatibility"].append("Source fog transform restored; legacy sidecar has no fog settings")
            else:
                intensity = float(row.get("intensity", 1))
                if kind == "Sky":
                    if intensity == 5000:
                        intensity = 1.0
                        report["compatibility"].append("Sky intensity absent in cooked source; using 1.0")
                    prepare_sky(unreal,comp)
                    sky_props=row.get('source',{}).get('properties',{})
                    comp.set_editor_property("lower_hemisphere_is_black",bool(sky_props.get('bLowerHemisphereIsBlack',True)))
                    for field,prop in (('SourceCubemapAngle','source_cubemap_angle'),('SkyDistanceThreshold','sky_distance_threshold'),('LowerHemisphereColor','lower_hemisphere_color')):
                        if field in sky_props:_assign(comp,prop,sky_props[field],report,field)
                color = row.get("color") or [1, 1, 1]
                linear = unreal.LinearColor(*color[:3], 1.0)
                if kind == 'Sky':
                    # SkyLight stores FLinearColor directly; its API has no
                    # sRGB-conversion parameter (unlike LightComponent).
                    comp.set_light_color(linear)
                else:
                    comp.set_light_color(linear, True)
                if kind in ("Point", "Spot", "Rect") and "intensityunits" in row:
                    units = {"0": unreal.LightUnits.UNITLESS, "1": unreal.LightUnits.CANDELAS,
                             "2": unreal.LightUnits.LUMENS, "unitless": unreal.LightUnits.UNITLESS,
                             "candelas": unreal.LightUnits.CANDELAS, "lumens": unreal.LightUnits.LUMENS}
                    comp.set_editor_property("intensity_units", units[str(row["intensityunits"]).lower()])
                # Changing units in the editor can convert the existing value.
                # Restore source intensity only after the units have been set.
                comp.set_editor_property('intensity',intensity)
                if intensity<0:
                    report.setdefault('signed_source_intensities',[]).append(dict(name=row.get('name'),
                        requested=intensity,applied=float(comp.get_editor_property('intensity'))))
                    if float(comp.get_editor_property('intensity'))!=intensity:
                        report['compatibility'].append('Stock UE clamps signed light intensity; original value retained in render_state.json: '+str(row.get('name')))
                for key_name, prop in (("sourceradius", "source_radius"),
                                       ("softsourceradius", "soft_source_radius"),
                                       ("sourcelength", "source_length"),
                                       ("indirectlightingintensity", "indirect_lighting_intensity"),
                                       ("volumetricscatteringintensity", "volumetric_scattering_intensity"),
                                       ("temperature", "temperature"),
                                       ("barndoorangle", "barn_door_angle"),
                                       ("barndoorlength", "barn_door_length"),
                                       ("lightfalloffexponent", "light_falloff_exponent"),
                                       ("shadowbias", "shadow_bias"),
                                       ("shadowslopebias", "shadow_slope_bias"),
                                       ("specularscale", "specular_scale"),
                                       ("affecttranslucentlighting", "affect_translucent_lighting"),
                                       ("usetemperature", "use_temperature"),
                                       ("useinversesquaredfalloff", "use_inverse_squared_falloff")):
                    if key_name in row:
                        comp.set_editor_property(prop, row[key_name])
                comp.set_editor_property("cast_shadows", bool(row.get("castshadows", True)))
                if kind in ("Point", "Spot", "Rect"):
                    comp.set_editor_property("attenuation_radius", max(0.0, float(row.get("radius", 1000))))
                if kind == "Spot":
                    comp.set_editor_property("inner_cone_angle", float(row.get("innercone", 0)))
                    comp.set_editor_property("outer_cone_angle", float(row.get("outercone", 44)))
                if kind == "Rect":
                    defaults = unreal.get_default_object(unreal.RectLightComponent)
                    for prop, key_name in (("source_width", "sourcewidth"), ("source_height", "sourceheight")):
                        size = float(row.get(key_name) or 0)
                        if size <= 0:
                            size = defaults.get_editor_property(prop)
                            note = "Source rect size absent; using native UE class defaults"
                            if note not in report["compatibility"]:
                                report["compatibility"].append(note)
                        comp.set_editor_property(prop, size)
                if kind == "Directional":
                    comp.set_editor_property("atmosphere_sun_light", True)
                if row.get('fogonly',False) and kind != 'Sky':
                    comp.set_lighting_channels(False,False,False)
                    comp.set_editor_property('indirect_lighting_intensity',0.0)
                    # The game's thousands-scale scatter is masked by its
                    # custom pre-baked depth shader, unavailable in stock UE.
                    # Keep the source untouched in render_state.json; bound
                    # only this explicitly identified compatibility path.
                    scatter=float(row.get('volumetricscatteringintensity',1))
                    cap=profile['fog_only_scattering_cap'] if profile['enabled'] else 1.0
                    if scatter>cap:
                        comp.set_editor_property('volumetric_scattering_intensity',cap)
                        report.setdefault('fog_compatibility',[]).append({
                            'name':row.get('name'),'source_scattering':scatter,'preview_scattering':cap})
                    comp.set_editor_property('cast_shadows',True)
                    comp.set_editor_property('cast_volumetric_shadow',True)
                    report['fog_only_lights']+=1
                elif kind != 'Sky':
                    comp.set_lighting_channels(True,False,False)
                if 'affectsworld' in row:
                    comp.set_editor_property('affects_world',bool(row['affectsworld']))
            # Visibility belongs to all component kinds, including Fog. Keep
            # it outside the native-light-only properties branch.
            visibility_targets.append((comp, row))
            _restore_component_visibility(comp, row, report)
            report["restored"][kind] = report["restored"].get(kind, 0) + 1
        except Exception as exc:
            report["errors"].append({"type": kind, "name": row.get("name"), "error": str(exc)})
    scene = json.loads((root / "scene.json").read_text(encoding="utf-8-sig"))
    _postprocess(eas,data.get('postprocess',[]),report)
    positions = [row["loc"] for row in scene.get("instances", []) if row.get("loc")]
    center = [sum(row[i] for row in positions) / len(positions) for i in range(3)] if positions else [0, 0, 0]
    span=max((max(p[i] for p in positions)-min(p[i] for p in positions) for i in range(3)),default=1000) if positions else 1000
    if data.get('reflection_captures') or data.get('environment') or profile_data.get('environment'):
        from ue_source_environment import restore as restore_environment
        restore_environment(root,data,eas,report,center,span,primary_chunk,ambient_enabled=profile['enabled'],global_root=profile_root,global_data=profile_data)
    _cameras(eas,data.get('cameras',[]),old,report)
    if primary_chunk:_game_profile(eas,profile,center,old,report)
    _source_exposure(eas,data,root,report,plan_data=profile_data,plan_root=profile_root)
    names = {a.get_class().get_name() for a in eas.get_all_level_actors()}
    if report["mode"] == "supplemental" and primary_chunk:
        if "SkyAtmosphere" not in names:
            ground = [center[0], center[1], min((p[2] for p in positions), default=0) - 10000]
            actor = _spawn(eas, unreal.SkyAtmosphere, "atmosphere", ground, zero, {})
            actor.set_actor_label("AtlasMap Environment Atmosphere")
            report["fallback"].append("SkyAtmosphere")
        if "DirectionalLight" not in names:
            actor = _spawn(eas, unreal.DirectionalLight, "sun", center,
                           unreal.Rotator(pitch=-42, yaw=35, roll=0), {})
            actor.set_actor_label("AtlasMap Environment Sun")
            comp = actor.get_component_by_class(unreal.DirectionalLightComponent)
            comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            comp.set_editor_property("intensity", 3.0)
            comp.set_editor_property("atmosphere_sun_light", True)
            report["fallback"].append("DirectionalLight")
        if "SkyLight" not in names:
            actor = _spawn(eas, unreal.SkyLight, "sky", center, zero, {})
            actor.set_actor_label("AtlasMap Environment SkyLight")
            comp = actor.get_component_by_class(unreal.SkyLightComponent)
            comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            comp.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_CAPTURED_SCENE)
            comp.set_editor_property("real_time_capture", False)
            comp.set_editor_property("intensity", 1.0)
            comp.set_editor_property("lower_hemisphere_is_black", False)
            report["fallback"].append("SkyLight")
    if data.get('schema'):
        report['preserved_bake_files']=len(data.get('preservedAssets',[]))
        report['compatibility'].append('Original cooked bake payloads retained; custom game PRT is not loadable by stock UE')
        if report['fog_only_lights']:
            report['compatibility'].append('Game fog-only flag mapped to zero surface channels; pre-baked fog depth uses real-time shadows and bounded stock-UE scattering')
    else:
        report["compatibility"].append("Legacy lights.json omits the original scene settings; export again")
    no_render = os.environ.get("ATLASMAP_UE_NO_RENDER", "0") == "1"
    finalize_skies(unreal,eas,report,rows,no_render,tag_prefix=TAG)
    if no_render:
        report["compatibility"].append("Sky recapture deferred until the level opens with rendering enabled")
    for comp, row in distance_targets:
        _validate_light_distances(comp, row, report)
    for comp, row in visibility_targets:
        _validate_component_visibility(comp, row, report)
    report["complete"] = not report["errors"] and bool(les.save_current_level())
    report_path = root / "lighting_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"Source lights: {report['source_count']}; restored: {report['restored']}; environment: {report['fallback']}")
    _log("Lighting report: " + str(report_path))
    if report.get('source_environment'):
        environment=report['source_environment']
        _log(f"原始 HDR 环境反射：{len(environment['restored'])}/{environment['source_reflections']}；天空：{environment['sky']}")
        if environment['unsupported']:_log(f"有 {len(environment['unsupported'])} 个源环境记录暂不支持，原始文件与原因已保留在 lighting_report.json")
    if not report["complete"]:
        raise RuntimeError("Lighting restoration incomplete: " + json.dumps(report["errors"]))
    return report


if __name__ == "__main__":
    main()
