"""Preserve the exact exporter's raw source properties alongside its geometry."""
from __future__ import annotations
from collections import defaultdict, deque
from copy import deepcopy
import json
import math
from pathlib import Path
try:
    from scripts.official.map_paths import io_path,display_path
except ImportError:
    from map_paths import io_path,display_path

KINDS={'PointLightComponent':'Point','SpotLightComponent':'Spot','RectLightComponent':'Rect',
       'DirectionalLightComponent':'Directional','SkyLightComponent':'Sky','ExponentialHeightFogComponent':'Fog'}


def merge(parent, child):
    result=deepcopy(parent)
    for key,value in child.items():
        result[key]=merge(result[key],value) if isinstance(value,dict) and isinstance(result.get(key),dict) else deepcopy(value)
    return result


class Sources:
    def __init__(self,folder,index):
        self.docs={}
        for key,file in index['packages'].items():
            rows=json.loads((folder/file).read_text(encoding='utf-8-sig'))
            self.docs[key]=rows
            self.docs[key.removesuffix('.umap').removesuffix('.uasset')]=rows

    def resolve(self,reference):
        path=reference.get('ObjectPath','')
        if not path or path.startswith('/Script/'):
            return None
        package,_,position=path.rpartition('.')
        rows=self.docs.get(package)
        if rows is None:
            return None
        name=reference.get('ObjectName','').split("'")[-2].split(':')[-1].split('.')[-1]
        if position.isdecimal() and int(position)<len(rows) and rows[int(position)].get('name')==name:
            return rows[int(position)]
        matches=[r for r in rows if r.get('name')==name]
        if len(matches)!=1:
            raise ValueError('Ambiguous source object: '+path)
        return matches[0]

    def props(self,obj,seen=()):
        value=obj.get('value',{})
        reference=value.get('Template',{})
        key=reference.get('ObjectPath','')
        if key in seen or len(seen)>16:
            raise ValueError('Cyclic source template: '+key)
        parent=self.resolve(reference)
        inherited=self.props(parent,(*seen,key)) if parent else {}
        return merge(inherited,value.get('Properties',{}))

    def pose(self,obj,seen=()):
        props=self.props(obj)
        location=[props.get('RelativeLocation',{}).get(k,0) for k in ('X','Y','Z')]
        rotation=props.get('RelativeRotation',{})
        pitch,yaw,roll=[math.radians(rotation.get(k,0)) for k in ('Pitch','Yaw','Roll')]
        cp,sp,cy,sy,cr,sr=math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw),math.cos(roll),math.sin(roll)
        matrix=[[cp*cy,sr*sp*cy-cr*sy,-cr*sp*cy-sr*sy],
                [cp*sy,sr*sp*sy+cr*cy,cy*sr-cr*sp*sy], [sp,-sr*cp,cr*cp]]
        parent=self.resolve(props.get('AttachParent',{}))
        identity=props.get('AttachParent',{}).get('ObjectPath','')
        if parent and identity not in seen and len(seen)<32:
            position,basis=self.pose(parent,(*seen,identity))
            scale=self.props(parent).get('RelativeScale3D',{})
            offset=[location[i]*scale.get(k,1) for i,k in enumerate(('X','Y','Z'))]
            if not props.get('bAbsoluteLocation',False):
                location=[position[i]+sum(basis[i][j]*offset[j] for j in range(3)) for i in range(3)]
            if not props.get('bAbsoluteRotation',False):
                matrix=[[sum(basis[i][k]*matrix[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        return location,matrix


def enrich(root,folder=None):
    root=io_path(root)
    folder=io_path(folder) if folder else root/'source-render'
    index=json.loads((folder/'state-index.json').read_text(encoding='utf-8-sig'))
    if not index.get('complete'):
        raise ValueError('Source scene extraction did not finish')
    source=Sources(folder,index)
    lights=[];post=[];cameras=[];reflections=[];unsupported=[]
    for level in index['levels']:
        rows=source.docs[level['level']]
        pending=defaultdict(deque)
        for obj in rows:
            kind=KINDS.get(obj.get('type'))
            if kind:
                pending[kind,obj['name']].append(obj)
        for original in level['lights']:
            key=(original['Type'],original['Name'])
            if not pending[key]:
                raise ValueError('Light identity not present in raw export: '+str(key))
            obj=pending[key].popleft()
            props=source.props(obj)
            row=deepcopy(original)
            for prop,field in (('Intensity','Intensity'),('AttenuationRadius','Radius'),
                ('InnerConeAngle','InnerCone'),('OuterConeAngle','OuterCone'),
                ('SourceWidth','SourceWidth'),('SourceHeight','SourceHeight'),('CastShadows','CastShadows')):
                if prop in props:row[field]=props[prop]
            if 'IntensityUnits' in props:
                row['IntensityUnits']=str(props['IntensityUnits']).split('::')[-1].lower()
            for prop in ('SourceRadius','SoftSourceRadius','SourceLength','IndirectLightingIntensity',
                         'VolumetricScatteringIntensity','Temperature','BarnDoorAngle','BarnDoorLength',
                         'LightFalloffExponent','ShadowBias','ShadowSlopeBias','SpecularScale',
                         'MaxDrawDistance','MaxDistanceFadeRange'):
                if prop in props:row[prop]=props[prop]
            for prop,field in (('bUseTemperature','UseTemperature'),('bUseInverseSquaredFalloff','UseInverseSquaredFalloff'),
                               ('bAffectVolumetricFogOnly','FogOnly'),('bAffectsWorld','AffectsWorld'),
                               ('bAffectTranslucentLighting','AffectTranslucentLighting'),('bVisible','Visible')):
                if prop in props:row[field]=props[prop]
            row['Source']={'level':level['level'],'object':obj['value'].get('Outer'),
                           'template':obj['value'].get('Template'),'properties':props}
            lights.append(row)
        if any(pending.values()):
            raise ValueError('Raw lights were omitted by native level extraction: '+level['level'])
        for obj in rows:
            if obj.get('type') in ('SphereReflectionCaptureComponent','BoxReflectionCaptureComponent'):
                props=source.props(obj)
                position,basis=source.pose(obj)
                reflections.append({'name':obj['name'],'level':level['level'],'type':obj['type'],
                    'loc':position,'properties':props,'source':obj.get('value',{}).get('Outer'),
                    'guid':str(props.get('LocalReflectionGroupBakeBuildID') or props.get('MapBuildDataId') or '').replace('-','').lower()})
            if obj.get('type')=='PostProcessVolume':
                props=source.props(obj)
                component=source.resolve(props.get('RootComponent',{}))
                transform=source.props(component) if component else {}
                brush=source.resolve(transform.get('Brush',{}))
                post.append({'name':obj['name'],'level':level['level'],'properties':props,
                             'transform':transform,'bounds':brush.get('value',{}).get('Bounds') if brush else None,
                             'raw':obj})
            if obj.get('type')=='CameraComponent':
                props=source.props(obj)
                position,basis=source.pose(obj)
                rotation=[math.degrees(math.atan2(-basis[2][1],basis[2][2])),
                          math.degrees(math.asin(max(-1,min(1,basis[2][0])))),
                          math.degrees(math.atan2(basis[1][0],basis[0][0]))]
                cameras.append({'name':obj['name'],'level':level['level'],'properties':props,
                    'actor':obj['value'].get('Outer',{}).get('ObjectName',''),
                    'loc':position,'rot':rotation,'fov':props.get('FieldOfView',90)})
    result={'complete':True,'schema':2,'mapRoot':index['mapRoot'],'exporter':index['exporter'],
            'lights':lights,'postprocess':post,'cameras':cameras,'reflection_captures':reflections,'unsupported':unsupported,
            'preservedAssets':index['preservedAssets'],
            'sourceDirectory':display_path(folder),'sourcePackages':len(index['packages'])}
    for file,key in (('environment.json','environment'),('reflection-cubemaps.json','reflection_cubemaps')):
        if (folder/file).is_file():result[key]=json.loads((folder/file).read_text(encoding='utf-8-sig'))
    (root/'render_state.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
