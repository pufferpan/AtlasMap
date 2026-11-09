"""Read unambiguous source exposure limits and source compensation curves.

Dynamic TOD evaluation is deliberately not guessed. Only constant single-key
limits from the selected map's TODLight package qualify for automatic use.
"""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path


def package_path(path):
    path=str(path).replace('\\','/').split('.')[0]
    if path.lower().startswith('/game/'):path='DeltaForce/Content/'+path[6:]
    return path.lower()


def constant_curve(value, name):
    keys=value.get('EditorCurveData',{}).get('Keys',[])
    if len(keys)!=1:raise ValueError(name+' is not a proven single-key constant')
    v=float(keys[0]['Value'])
    if not math.isfinite(v):raise ValueError(name+' is not finite')
    return v


def validate_keys(keys):
    result=sorted(keys,key=lambda k:float(k['Time']))
    if not result:raise ValueError('Source compensation curve has no keys')
    for i,k in enumerate(result):
        if not all(math.isfinite(float(k.get(p,0))) for p in ('Time','Value','ArriveTangent','LeaveTangent')):
            raise ValueError('Source compensation curve contains nonfinite values')
        if k.get('TangentWeightMode','RCTWM_WeightedNone')!='RCTWM_WeightedNone':
            raise ValueError('Weighted source curve tangents are not supported')
        if k.get('InterpMode') not in ('RCIM_Linear','RCIM_Constant','RCIM_Cubic'):
            raise ValueError('Unsupported source curve interpolation')
        if i and float(result[i-1]['Time'])>=float(k['Time']):raise ValueError('Duplicate source curve key time')
    return result


def evaluate_curve(keys,time):
    keys=validate_keys(keys);time=float(time)
    if time<=float(keys[0]['Time']):return float(keys[0]['Value'])
    if time>=float(keys[-1]['Time']):return float(keys[-1]['Value'])
    # A constant interval owns its open right endpoint. At a stored key time,
    # the source curve evaluates that key's value, not the preceding step.
    for stored in keys:
        if time==float(stored['Time']):return float(stored['Value'])
    for a,b in zip(keys,keys[1:]):
        if float(a['Time'])<=time<=float(b['Time']):
            dt=float(b['Time'])-float(a['Time']);t=(time-float(a['Time']))/dt
            if a['InterpMode']=='RCIM_Constant':return float(a['Value'])
            if a['InterpMode']=='RCIM_Linear':return float(a['Value'])+t*(float(b['Value'])-float(a['Value']))
            return ((2*t**3-3*t*t+1)*float(a['Value'])+(t**3-2*t*t+t)*dt*float(a.get('LeaveTangent',0))
                +(-2*t**3+3*t*t)*float(b['Value'])+(t**3-t*t)*dt*float(b.get('ArriveTangent',0)))
    raise AssertionError('Curve interval missing')


def curve_samples(keys,step=.005):
    keys=validate_keys(keys)
    start=min(-20.,float(keys[0]['Time']));end=max(20.,float(keys[-1]['Time']))
    times={float(k['Time']) for k in keys}
    times.update(round(start+i*step,8) for i in range(math.ceil((end-start)/step)+1))
    return [(t,evaluate_curve(keys,t)) for t in sorted(times)]


def native_limits(min_ev,max_ev,extended,lens_attenuation=.78):
    if not all(math.isfinite(float(x)) for x in (min_ev,max_ev,lens_attenuation)) or min_ev>max_ev:
        raise ValueError('Invalid source exposure limits')
    # RenderUtils.h EV100ToLuminance = Lmax * 2^EV. Non-extended rendering
    # hardcodes Lmax=1 (PostProcessEyeAdaptation.cpp); no arbitrary -3 shift.
    return [float(min_ev),float(max_ev)] if extended else [2.**float(min_ev),2.**float(max_ev)]


def _source_docs(root):
    folder=Path(root)/'source-render';index=folder/'state-index.json'
    if not index.is_file():return []
    entries=json.loads(index.read_text(encoding='utf-8-sig')).get('packages',{})
    result=[];seen=set()
    for package,filename in entries.items():
        key=package_path(package)
        if key in seen:continue
        seen.add(key)
        file=folder/filename
        if file.is_file():result.append((key,json.loads(file.read_text(encoding='utf-8-sig')),str(file)))
    return result


def build_plan(data,root,extended,lens_attenuation=.78,curve_files=None):
    root=Path(root);docs=_source_docs(root)
    result={'eligible':False,'source_ev_limits':None,'native_limits':None,'bias_ev':None,
        'extended_luminance_range':bool(extended),'lens_attenuation':float(lens_attenuation),
        'curve':None,'errors':[],'skipped_missing':[],'basis':'Selected map constant source TOD limits and authored exposure curve'}
    selected_root=package_path(data.get('mapRoot','').split(' + ')[-1]).rstrip('/')
    candidates=[];ibl_coefficients=set()
    for package,rows,file in docs:
        if not package.startswith(selected_root+'/') or 'todlight' not in package:continue
        for row in rows:
            if row.get('type')!='NZSkyBoxComponent':continue
            props=row.get('value',{}).get('Properties',{}).get('TodExposure')
            if not props:continue
            try:
                limits=[constant_curve(props.get(k,{}),k) for k in ('MinBrightnessCrv_Wtx','MaxBrightnessCrv_Wtx')]
                bias=constant_curve(props.get('CompensationCurve_Wtx',{}),'CompensationCurve_Wtx')
                candidates.append((limits,bias,file))
                if 'IBLCoef' in props:
                    coef=float(props['IBLCoef'])
                    if not math.isfinite(coef) or not 0<coef<=10000:raise ValueError('Invalid source IBL coefficient')
                    ibl_coefficients.add(coef)
            except (KeyError,TypeError,ValueError) as exc:result['errors'].append(str(exc))
    unique={(tuple(limits),bias) for limits,bias,_ in candidates}
    if result['errors']:return result
    if len(unique)!=1:
        result['errors'].append('Missing or ambiguous source TOD exposure limits');return result
    limits,bias=next(iter(unique));result['source_ev_limits']=list(limits);result['bias_ev']=bias
    result['source_files']=sorted({file for _,_,file in candidates})
    result['native_limits']=native_limits(*limits,extended,lens_attenuation)
    result['source_ibl_coefficient']=next(iter(ibl_coefficients)) if len(ibl_coefficients)==1 else None
    volumes=sorted(data.get('postprocess',[]),key=lambda r:float(r.get('properties',{}).get('Priority',0)),reverse=True)
    source_curve=None
    for volume in volumes:
        settings=volume.get('properties',{}).get('Settings',{})
        if settings.get('bOverride_AutoExposureBiasCurve'):
            ref=settings.get('AutoExposureBiasCurve') or {}
            source_curve=package_path(ref.get('ObjectPath',''));break
    if not source_curve:
        result['skipped_missing'].append('No authored compensation curve reference');return result
    available={package_path(k):Path(v) for k,v in (curve_files or {}).items()}
    index=root/'source-render/exposure-resources.json'
    if index.is_file():
        resources=json.loads(index.read_text(encoding='utf-8-sig')).get('resources',{})
        entries=resources.items() if isinstance(resources,dict) else ((r['source_path'],r['raw']) for r in resources if r.get('raw'))
        for package,relative in entries:
            path=(index.parent/relative).resolve()
            if not path.is_relative_to(index.parent.resolve()):raise ValueError('Invalid exposure resource path')
            available.setdefault(package_path(package),path)
    for package,rows,file in docs:
        if package==source_curve:available.setdefault(package,Path(file))
    if source_curve not in available or not available[source_curve].is_file():
        result['skipped_missing'].append('Authored compensation curve JSON unavailable: '+source_curve);return result
    file=available[source_curve]
    rows=json.loads(file.read_text(encoding='utf-8-sig'))
    matches=[row for row in rows if row.get('type')=='CurveFloat' and package_path(row.get('value',{}).get('Package',''))==source_curve]
    if len(matches)!=1:
        result['errors'].append('Authored compensation curve resource identity mismatch');return result
    try:keys=validate_keys(matches[0]['value']['Properties']['FloatCurve']['Keys'])
    except (KeyError,TypeError,ValueError) as exc:
        result['errors'].append(str(exc));return result
    result['curve']={'source_package':source_curve,'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'keys':keys}
    result['meter_mask']=None
    for volume in volumes:
        settings=volume.get('properties',{}).get('Settings',{})
        if not settings.get('bOverride_AutoExposureMeterMask'):continue
        reference=package_path((settings.get('AutoExposureMeterMask') or {}).get('ObjectPath',''))
        if index.is_file():
            resources=json.loads(index.read_text(encoding='utf-8-sig')).get('resources',[])
            if isinstance(resources,list):
                found=[r for r in resources if package_path(r.get('source_path',''))==reference and r.get('texture')]
                if len(found)==1:
                    result['meter_mask']={'source_package':reference,'texture':found[0]['texture'],
                        'properties':found[0].get('properties',{}),'base_directory':str(index.parent)}
        if result['meter_mask'] is None:result['skipped_missing'].append('Authored exposure meter texture unavailable; existing meter retained')
        break
    result['eligible']=True
    return result
