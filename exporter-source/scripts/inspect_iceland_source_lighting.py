"""Extract the cooked, constant PC lighting-sequence values without UE mutation."""
import json
from pathlib import Path

ROOT=Path('D:/AtlasMap-tooling/out/Iceland/audit/environment_query')
data=json.loads((ROOT/'Iceland_HD_sequence.json').read_text(encoding='utf-8-sig'))
scene=next(x['value']['Properties'] for x in data if x['type']=='MovieScene')
binding={}
for b in scene['ObjectBindings']:
    for track in b['Tracks']:
        binding[track['ObjectName'].split("'")[1].rsplit('.',1)[-1]]=b['BindingName']
sections={}
for x in data:
    if 'Section' in x['type'] and 'Outer' in x['value']:
        owner=x['value']['Outer']['ObjectName'].split("'")[1].rsplit('.',1)[-1]
        sections.setdefault(owner,[]).append(x)
def channel(c):
    nested=c.get('StructFallback',c)
    values=nested.get('Values',[])
    if not values:
        return c['DefaultValue'] if c.get('bHasDefaultValue',False) else None
    vals=[v.get('Value',v) if isinstance(v,dict) else v for v in values]
    assert len(vals)==1 or all(v==vals[0] for v in vals), ('Time-varying channel',vals)
    return vals[0]
out=[]
for x in data:
    if not x['type'].endswith('Track'): continue
    p=x['value']['Properties']; sec=sections.get(x['name'],[])
    if not sec: continue
    assert len(sec)==1
    s=sec[0]['value']['Properties'];typ=sec[0]['type']
    if typ=='MovieSceneFloatSection':v=channel(s['FloatCurve'])
    elif typ=='MovieSceneColorSection':v=[channel(s[k+'Curve']) for k in ['Red','Green','Blue','Alpha']]
    elif typ=='MovieSceneVectorSection':v=[channel(s['Curves' if i==0 else f'Curves[{i}]']) for i in range(s['ChannelsUsed'])]
    elif typ=='MovieSceneObjectPropertySection':v=channel(s['ObjectChannel'])
    elif typ=='MovieScenePrimitiveMaterialSection':v=channel(s['MaterialChannel'])
    elif typ=='MovieSceneByteSection':v=channel(s['ByteCurve'])
    elif typ=='MovieSceneBoolSection':v=channel(s['BoolCurve'])
    else:raise ValueError(typ)
    out.append({'binding':binding.get(x['name']),'property':p.get('PropertyPath',p.get('PropertyName',x['type'])),'value':v,'track':x['name']})
(ROOT/'lighting').mkdir(exist_ok=True)
(ROOT/'lighting/pc_sequence_values.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
for x in out:print(x['binding'],x['property'],json.dumps(x['value'],ensure_ascii=False))
