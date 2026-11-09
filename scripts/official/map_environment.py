"""Validate source environment bindings before sending them to native UE."""
import math
import re

KNOWN_SOURCE_SKY_MESH='deltaforce/content/materiallib/materials/scene/sky/map/sm_skymesh_a.sm_skymesh_a'


def resource_identity(reference):
    """Canonical full object identity, never the ambiguous short asset name."""
    if isinstance(reference,str):path=reference;name=''
    else:path=reference.get('ObjectPath','');name=reference.get('ObjectName','')
    path=path.replace('\\','/')
    if path.lower().startswith('/game/'):path='DeltaForce/Content/'+path[6:]
    quoted=re.search(r"'([^']+)'",name)
    if quoted:path=path.split('.')[0]+'.'+quoted[1].split(':')[-1].split('.')[-1]
    return path.lower()


def select_authored_sky_cube(environment,lights):
    """Only a unique actual SkyLight.Cubemap may drive the low-detail fallback.

    ReflectionCubemap and neighbouring reflection captures are deliberately not
    considered, even when their names are identical.
    """
    requests=set()
    for row in lights:
        if str(row.get('type',row.get('Type',''))).lower()!='sky':continue
        source=row.get('source',row.get('Source',{}))
        props=source.get('properties',{})
        kind=str(props.get('SourceType','')).split('::')[-1].lower()
        if kind and kind not in ('sls_specifiedcubemap','specifiedcubemap','1'):continue
        reference=props.get('Cubemap') or props.get('CubeMap')
        if reference:requests.add(resource_identity(reference))
    if len(requests)!=1:return None
    wanted=next(iter(requests))
    matches=[row for row in environment.get('skies',[]) if row.get('kind')=='cube'
             and resource_identity(row.get('source_texture',''))==wanted and not row.get('rgbm')]
    return matches[0] if len(matches)==1 else None


def known_source_sky_rows(scene):
    """Recognize only the audited SkyDomeMesh placeholder with full source data."""
    result=[]
    for row in scene.get('instances',[]):
        meta=row.get('dfmap') or {}
        source_id=meta.get('sourceId','')
        if not re.fullmatch(r'DFI_[0-9a-f]{24}',source_id):continue
        if resource_identity(meta.get('unrealMeshPath',''))!=KNOWN_SOURCE_SKY_MESH:continue
        if resource_identity(row.get('mesh',''))!=KNOWN_SOURCE_SKY_MESH:continue
        actor=meta.get('sourceActor','')
        if not actor.endswith(':PersistentLevel.SkyDomeMesh'):continue
        if meta.get('sourceComponent')!='StaticMeshComponent0':continue
        if meta.get('sourceComponentPath')!=actor+'.StaticMeshComponent0':continue
        if meta.get('overrideMaterials')!=[None]:continue
        visibility=meta.get('visibility') or {}
        if visibility.get('renderable') is not True:continue
        if any(visibility.get(k) is True for k in ('hiddenInGame','ownerHidden','editorOnly')):continue
        result.append(row)
    return result


def sky_actor_matches(source_id,label,metadata):
    """Accept an exact exported ID or exact preserved source-component identity."""
    if re.fullmatch(r'(?:C[0-9]+_)?'+re.escape(source_id),label):return True
    return metadata.get('sourceId')==source_id


def select_sky(document):
    candidates=[]
    for row in document.get('skies',[]):
        master=(row.get('parameters') or {}).get('MasterPath') or ''
        if (row.get('eligible') and row.get('kind') in ('cube','latlong')
                and 'billboard' not in master.lower() and not row.get('rgbm')):
            candidates.append(row)
    return candidates[0] if len(candidates)==1 else None


def reflection_catalog(document):
    result={}
    for row in document.get('captures',[]):
        guid=row.get('guid','')
        if not re.fullmatch('[0-9a-f]{32}',guid):raise ValueError('Invalid source reflection GUID')
        if guid in result and result[guid]!=row:raise ValueError('Conflicting source reflection GUID: '+guid)
        result[guid]=row
    return result


def native_intensity(payload,properties):
    average=float(payload['average_brightness'])
    mean=float(payload['decoded_mean_luminance'])
    brightness=float(properties.get('Brightness',payload.get('brightness',1)))
    if any(not math.isfinite(v) or v<0 for v in (average,mean,brightness)):
        raise ValueError('Invalid source reflection intensity')
    if mean==0:
        if average:raise ValueError('Nonzero source energy with an empty reflection cube')
        return 0.0
    return brightness*average/mean


def bind_reflections(captures,document):
    candidates=[]
    for row in document.get('captures',[]):
        matches=[c for c in captures if c['guid']==row.get('guid')]
        for capture in matches:
            reference=capture['properties'].get('LocalReflectionGroupBakeObject') or {}
            active=reference.get('ObjectPath','').split('.')[0].removeprefix('/Game/')
            source=row.get('source','').removeprefix('assets/').removesuffix('.uexp')
            if active and not (source==active or source=='DeltaForce/Content/'+active):continue
            candidates.append(row);break
    return reflection_catalog({'captures':candidates})


def ambient_weights(captures):
    """Compensate additive stock-UE ambient volumes for overlapping probes."""
    result={}
    for row in captures:
        overlap=sum(sum((a-b)**2 for a,b in zip(row['loc'],other['loc']))<=
                    max(1,float(other['properties'].get('InfluenceRadius',3000)))**2 for other in captures)
        result[row['guid']]=1/max(1,overlap)
    return result
