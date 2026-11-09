"""Validate emitted glTF colour accessor counts and values against source buffers."""
import json
import struct
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling/out/Iceland/audit/material_attributes')
raw=(root/'uv_smoke.glb').read_bytes();length=struct.unpack_from('<I',raw,12)[0]
document=json.loads(raw[20:20+length]);binary=raw[28+length:]
sources={m['asset']:m for m in json.loads((root/'attributes.json').read_text())}
rows=[]
for mesh in document['meshes']:
    source=sources[mesh['name']];attrs=mesh['primitives'][0]['attributes']
    state=mesh['extras']['unrealVertexColorState']
    if source['color_file']:
        accessor=document['accessors'][attrs['COLOR_0']];view=document['bufferViews'][accessor['bufferView']]
        assert accessor['type']=='VEC4' and accessor['count']==source['vertices']
        assert accessor['count']*16<=view['byteLength']
        actual=np.frombuffer(binary,'<f4',accessor['count']*4,view.get('byteOffset',0)+accessor.get('byteOffset',0))
        expected=np.fromfile(root/source['color_file'],'u1').astype(np.float32)/255
        assert np.allclose(actual,expected,rtol=0,atol=1e-7)
        error=float(np.max(np.abs(actual-expected)))
    else:
        assert state=='default_white' and 'COLOR_0' not in attrs
        error=0
    rows.append({'asset':mesh['name'],'state':state,'maximum_channel_error':error})
report={'meshes':rows,'failures':[]}
(root/'color_glb_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
