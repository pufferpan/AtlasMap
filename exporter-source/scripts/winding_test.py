"""Check triangle winding in an exported GLB using the signed-volume test.

For a closed mesh, triangles wound counter-clockwise as seen from outside (the glTF front-face
convention) enclose a POSITIVE signed volume. A negative volume means every face is inside-out.
That is independent of position, so it isolates a winding bug from a mirroring bug.

Also reports, for the same meshes, whether the exported vertex normals point away from the
centre of mass, which is the same question asked of the NORMAL attribute Blender actually shades
with.
"""
import json
import struct
import sys

import numpy as np

glb = sys.argv[1]
b = open(glb, 'rb').read()
_, _, total = struct.unpack_from('<III', b, 0)
off, js, bc = 12, None, None
while off < total:
    clen, ctype = struct.unpack_from('<II', b, off)
    body = b[off + 8: off + 8 + clen]
    if ctype == 0x4E4F534A:
        js = json.loads(body.decode('utf-8'))
    elif ctype == 0x004E4942:
        bc = body
    off += 8 + clen

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def acc(i):
    a = js['accessors'][i]
    n = NC[a['type']]
    dt = CT[a['componentType']]
    bv = js['bufferViews'][a['bufferView']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    st = bv.get('byteStride') or np.dtype(dt).itemsize * n
    if st == np.dtype(dt).itemsize * n:
        return np.frombuffer(bc, dtype=dt, count=a['count'] * n, offset=base).reshape(a['count'], n)
    return np.stack([np.frombuffer(bc, dtype=dt, count=n, offset=base + k * st) for k in range(a['count'])])


print(f'{glb}\n')
rows = []
for mi, m in enumerate(js['meshes']):
    name = m.get('name', f'mesh{mi}').split('/')[-1].split('.')[0]
    vol = 0.0
    ntri = 0
    rad = []
    for p in m['primitives']:
        pos = acc(p['attributes']['POSITION']).astype(np.float64)
        idx = acc(p['indices']).reshape(-1).astype(np.int64) if 'indices' in p else np.arange(len(pos))
        tri = pos[idx.reshape(-1, 3)]
        v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
        vol += float(np.einsum('ij,ij->i', v0, np.cross(v1, v2)).sum() / 6.0)
        ntri += len(tri)
        if 'NORMAL' in p['attributes']:
            nrm = acc(p['attributes']['NORMAL']).astype(np.float64)
            c = pos.mean(axis=0)
            r = pos - c
            rn = np.linalg.norm(r, axis=1)
            ok = rn > 1e-6
            rad.append(float((np.einsum('ij,ij->i', nrm[ok], r[ok]) / rn[ok]).mean()))
    if ntri:
        rows.append((name, ntri, vol, float(np.mean(rad)) if rad else float('nan')))

rows.sort(key=lambda r: -abs(r[2]))
print(f'{"triangles":>9}  {"signed volume":>14}  {"normal.radial":>13}  mesh')
pos_vol = neg_vol = 0
for name, ntri, vol, radial in rows[:18]:
    print(f'{ntri:9d}  {vol:14.2f}  {radial:13.3f}  {name}')
for name, ntri, vol, radial in rows:
    if vol > 0:
        pos_vol += 1
    elif vol < 0:
        neg_vol += 1
print(f'\nmeshes with a positive signed volume (outward CCW winding): {pos_vol}')
print(f'meshes with a negative signed volume (inside-out winding) : {neg_vol}')
print()
if neg_vol > pos_vol:
    print('VERDICT: winding is INVERTED - the glTF front faces are the back of the geometry.')
else:
    print('VERDICT: winding matches the glTF convention for closed meshes.')
radials = [r[3] for r in rows if not np.isnan(r[3])]
if radials:
    neg = sum(1 for v in radials if v < 0)
    print(f'normals pointing away from the centre of mass: {len(radials) - neg}/{len(radials)} '
          f'(negative would mean inverted shading)')
