"""Losslessly factor identical material DAG structures into parameterized parents."""
import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import sys as _sys, os as _os
ROOT=Path(_os.environ.get('ATLASMAP_UE_ROOT') or Path('.').resolve())
plan=json.loads((ROOT/'material_plan.json').read_text(encoding='utf-8'))
images={i['id']:i for i in json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))['images']}
literal=re.compile(r'(?<![\w.])(?:\d+\.\d*|\d+)(?:e[+-]?\d+)?')
groups=defaultdict(list)
for row in plan['materials']:
    source=copy.deepcopy(row)
    renames={t['input']:f'Tex_{index}' for index,t in enumerate(source['textures'])}
    code=re.sub(r'\bImg_\d+\b',lambda match:renames[match.group()],source['code'])
    inverse={v:k for k,v in renames.items()}
    assert re.sub(r'\bTex_\d+\b',lambda match:inverse[match.group()],code)==row['code']
    assert set(re.findall(r'\bTex_\d+\b',code)).issubset(inverse)
    for index,texture in enumerate(source['textures']):
        texture['input']=f'Tex_{index}';texture['parameter']='Texture_'+str(index)
    source['code']=code
    blocks=[code]+[t['coordinate_code'] for t in source['textures']]
    signature=[*[literal.sub('#',b) for b in blocks],source['inputs'],source['masked'],source['two_sided'],source.get('surface_kind','opaque'),
               {k:source.get('surface',{}).get(k) for k in ('clip','absorption','scattering','thin_glass')},
               [(t['extension'],t['coordinate_inputs'],t['interpolation'],images[t['image']]['srgb']) for t in source['textures']]]
    key=json.dumps(signature,sort_keys=True)
    groups[key].append(source)
parents=[];instances=[]
print('@ATLASMAP_TASK '+json.dumps(dict(event='assigned',work={'materials':len(plan['materials'])},text=f"本块材质分组：{len(groups)} 组"),ensure_ascii=False),flush=True)
for group_index,(signature,rows) in enumerate(groups.items()):
    parent=copy.deepcopy(rows[0]);parent['id']=_os.environ.get('ATLASMAP_MATERIAL_NAMESPACE','')+'Master_'+hashlib.sha256(signature.encode()).hexdigest()[:16]
    all_blocks=[[r['code']]+[t['coordinate_code'] for t in r['textures']] for r in rows]
    new_blocks=[];parameters=[];parameter_values={r['id']:{} for r in rows}
    for block_index,first in enumerate(all_blocks[0]):
        tokens=[list(literal.finditer(b[block_index])) for b in all_blocks]
        assert all(len(t)==len(tokens[0]) for t in tokens)
        changes={}
        for token_index,match in enumerate(tokens[0]):
            values=[float(t[token_index].group()) for t in tokens]
            if max(values)!=min(values):
                name='K_'+str(len(parameters));parameters.append({'name':name,'default':values[0],'block':block_index,'token_index':token_index})
                changes[match.start()]=(match.end(),name)
                for row,value in zip(rows,values):parameter_values[row['id']][name]=value
        result=[];position=0
        for begin,(end,name) in sorted(changes.items()):result.extend([first[position:begin],name]);position=end
        result.append(first[position:]);new_blocks.append(''.join(result))
    parent['code']=new_blocks[0]
    parent['inputs']=parent['inputs']+[p['name'] for p in parameters if p['block']==0]
    for index,t in enumerate(parent['textures']):
        t['coordinate_code']=new_blocks[index+1]
        t['coordinate_inputs']=t['coordinate_inputs']+[p['name'] for p in parameters if p['block']==index+1]
    parent['scalar_defaults']={p['name']:p['default'] for p in parameters}
    parent['sha256']=hashlib.sha256(json.dumps({'blocks':new_blocks,'signature':signature}).encode()).hexdigest()
    parent['source_name']='Blender DAG parent ('+str(len(rows))+' variants)'
    parents.append(parent)
    for row in rows:
        instance={'id':row['id'],'parent':parent['id'],'source_name':row['source_name'],'source_material':row['source_material'],
                  'source_path':row['source_path'],'sha256':row['sha256'],'scalars':parameter_values[row['id']],
                  'textures':{t['parameter']:t['image'] for t in row['textures']}}
        # Reconstruct and compare numerical token streams and every source
        # texture to establish equivalence before touching engine assets.
        for block_index,block in enumerate(new_blocks):
            reconstructed=block
            for name,value in instance['scalars'].items():reconstructed=re.sub(r'\b'+name+r'\b',format(value,'.17g'),reconstructed)
            original=all_blocks[rows.index(row)][block_index]
            assert literal.sub('#',reconstructed)==literal.sub('#',original)
            assert [float(m.group()) for m in literal.finditer(reconstructed)]==[float(m.group()) for m in literal.finditer(original)]
        instances.append(instance)
    print('@ATLASMAP_TASK '+json.dumps(dict(event='progress',done=group_index+1,total=len(groups),unit='材质组',current=parent['id'])),flush=True)
report={'parents':parents,'instances':instances,'equivalence_verified':len(instances),
        'counts':{'parents':len(parents),'instances':len(instances)}}
(ROOT/'material_instance_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report['counts']))
