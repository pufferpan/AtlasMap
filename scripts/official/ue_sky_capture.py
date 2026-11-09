"""Guard native SkyLight capture against missing sky providers.

Only actual editor-readable render state qualifies. This module never creates
an atmosphere, changes a light's energy, or marks arbitrary materials IsSky.
"""
from __future__ import annotations


def _read(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _path(obj):
    try:
        return obj.get_path_name()
    except Exception:
        return str(type(obj).__name__)


def _visible(actor, component):
    # Fail closed: an unavailable API is not proof that a provider is rendered.
    if _read(actor, 'hidden', True) or not _read(component, 'visible', False):
        return False
    try:
        if actor.is_hidden_ed():
            return False
    except Exception:
        return False
    return True


def sky_providers(ue, actors):
    """Return visible native sky components or explicitly tagged sky materials."""
    result=[]
    kinds=[('SkyAtmosphere',getattr(ue,'SkyAtmosphereComponent',None)),
           ('VolumetricCloud',getattr(ue,'VolumetricCloudComponent',None))]
    primitive=getattr(ue,'MeshComponent',None)
    for actor in actors:
        for name,cls in kinds:
            if cls is None:continue
            try:components=actor.get_components_by_class(cls)
            except Exception:components=[]
            for component in components:
                if _visible(actor,component):
                    result.append({'kind':name,'component':_path(component)})
        if primitive is None:continue
        try:components=actor.get_components_by_class(primitive)
        except Exception:components=[]
        for component in components:
            if not _visible(actor,component):continue
            if not _read(component,'visible_in_real_time_sky_captures',False):continue
            try:materials=component.get_materials()
            except Exception:materials=[]
            for material in materials:
                if material is None:continue
                try:base=material.get_base_material()
                except Exception:continue
                if _read(base,'is_sky',False):
                    result.append({'kind':'IsSkyMesh','component':_path(component),
                                   'material':_path(base)})
                    break
    return result


def _specified(ue,component):
    return component.get_editor_property('source_type')==ue.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP


def prepare_sky(ue,component):
    """Defer realtime until provider audit; retain a valid specified cube."""
    component.set_editor_property('real_time_capture',False)
    texture=component.get_editor_property('cubemap')
    cube_class=getattr(ue,'TextureCube',None)
    valid_cube=cube_class is not None and isinstance(texture,cube_class)
    if _specified(ue,component) and valid_cube:
        return
    component.set_editor_property('source_type',ue.SkyLightSourceType.SLS_CAPTURED_SCENE)


def _source_requests_cube(row):
    props=row.get('source',{}).get('properties',{})
    # Records may contain a nullable Cubemap while using CapturedScene. The
    # authored SourceType is authoritative when it is available.
    source_type=str(props.get('SourceType','')).split('::')[-1].lower()
    if source_type:
        return source_type in ('sls_specifiedcubemap','specifiedcubemap','1')
    return bool(props.get('Cubemap') or props.get('CubeMap'))


def finalize_skies(ue,eas,report,rows=(),no_render=False,tag_prefix='AtlasMapLighting_'):
    """Apply and read back a safe mode after authored environment restoration.

    Missing authored environment is reported separately from geometry import
    completion. Disabling realtime alone is not represented as restored light.
    """
    actors=list(eas.get_all_level_actors())
    expected={tag_prefix+key:row for key,row in rows if row.get('type')=='Sky'}
    targets=[]
    for actor in actors:
        tags=[str(tag) for tag in actor.tags if str(tag).startswith(tag_prefix)]
        if not tags:continue
        component=actor.get_component_by_class(ue.SkyLightComponent)
        if component is not None:
            targets.append((actor,component,next((expected[tag] for tag in tags if tag in expected),{})))
    if not targets:
        return
    providers=sky_providers(ue,actors)
    state={'providers':providers,'lights':[],'environment_complete':True,
           'inspection':'Visible editor components/materials; not renderer capture pixel verification'}
    report['sky_capture']=state
    report.setdefault('environment_complete',True)
    for actor,component,row in targets:
        item={'actor':_path(actor),'requested_specified_cube':_source_requests_cube(row)}
        try:
            texture=component.get_editor_property('cubemap')
            cube_class=getattr(ue,'TextureCube',None)
            valid_cube=cube_class is not None and isinstance(texture,cube_class)
            specified=_specified(ue,component)
            if specified and valid_cube:
                realtime=False
                component.set_editor_property('real_time_capture',False)
                item.update(mode='specified_cubemap',cubemap=_path(texture),environment_complete=True)
            else:
                # Keep an unresolved authored-cube request explicit instead of
                # silently enabling an unrelated capture as if it were restored.
                unresolved=item['requested_specified_cube'] or (specified and not valid_cube)
                realtime=bool(providers) and not unresolved
                component.set_editor_property('source_type',ue.SkyLightSourceType.SLS_CAPTURED_SCENE)
                component.set_editor_property('real_time_capture',realtime)
                complete=bool(providers) and not unresolved
                item.update(mode='captured_scene',environment_complete=complete,
                            missing_authored_cubemap=unresolved)
                if not complete:
                    state['environment_complete']=False
                    report['environment_complete']=False
                    note=('Authored SkyLight cubemap is unavailable; realtime capture is disabled'
                          if unresolved else
                          'No rendered SkyAtmosphere, VolumetricCloud or IsSky mesh; realtime capture is disabled. Static scene capture may still be dark')
                    if note not in report.setdefault('compatibility',[]):report['compatibility'].append(note)
                elif not no_render:
                    component.recapture_sky()
            actual=bool(component.get_editor_property('real_time_capture'))
            if actual!=realtime:raise RuntimeError('SkyLight realtime flag did not persist')
            if item['mode']=='specified_cubemap':
                if not _specified(ue,component) or component.get_editor_property('cubemap')!=texture:
                    raise RuntimeError('SkyLight specified cubemap did not persist')
            item.update(real_time_capture=actual,recapture_deferred=bool(no_render and realtime))
        except Exception as exc:
            item.update(error=str(exc),environment_complete=False)
            state['environment_complete']=False;report['environment_complete']=False
            report.setdefault('errors',[]).append({'type':'Sky','name':row.get('name'),
                                                  'phase':'sky_capture_readback','error':str(exc)})
        state['lights'].append(item)
