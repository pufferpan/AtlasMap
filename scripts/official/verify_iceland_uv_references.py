"""Compare every restored UV channel against independently exported FModel assets."""
import hashlib
import json
import struct
from pathlib import Path
import numpy as np
from iceland_validate import attributes,fstring

root=Path('D:/AtlasMap-tooling/out/Iceland/audit/floor_attributes')
passed=[];failures=[];unavailable=[]
for mesh in json.loads((root/'attributes.json').read_text(encoding='utf-8-sig')):
    path=Path('E:/FModelNew/Save')/(mesh['asset'].rsplit('.',1)[0]+'.uemodel')
    if not path.exists():continue
    data=path.read_bytes();_,offset=fstring(data,8);offset+=1
    _,offset=fstring(data,offset);_,offset=fstring(data,offset)
    lods=attributes(data,offset+1)['LODS'];_,offset=fstring(lods,4);lod=attributes(lods,offset)
    if hashlib.sha256(lod['INDICES'][4:]).hexdigest()!=mesh['index_sha256']:
        unavailable.append({'asset':mesh['asset'],'reason':'reference LOD topology differs'});continue
    raw=lod['TEXCOORDS'];count=struct.unpack_from('<i',raw)[0];offset=4
    if count!=len(mesh['uv_files']):
        failures.append({'asset':mesh['asset'],'reason':'UV channel count differs'});continue
    for channel in range(count):
        _,offset=fstring(raw,offset);vertices=struct.unpack_from('<i',raw,offset)[0];offset+=4
        source=np.frombuffer(raw,'<f4',vertices*2,offset);offset+=vertices*8
        decoded=np.fromfile(root/mesh['uv_files'][channel],'<f4')
        if source.shape!=decoded.shape or not np.array_equal(source,decoded):failures.append({'asset':mesh['asset'],'channel':channel})
        else:passed.append({'asset':mesh['asset'],'channel':channel})
report={'exact_FModel_channel_matches':len(passed),'meshes':len({m['asset'] for m in passed}),'failures':failures,'unsupported_references':unavailable}
(root/'independent_uv_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
assert not failures
