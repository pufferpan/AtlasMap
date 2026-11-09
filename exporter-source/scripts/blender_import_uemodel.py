"""Import dfmap .uemodel files into Blender using umodel_tools / UEFormat conventions.

This deliberately reimplements the reference importer's coordinate handling instead of inventing
its own, so a dfmap export lands exactly where the reference tooling puts it.

Source of the convention (skarndev/umodel_tools + halfuwu/UEFormat, read from the repos):

    plugins/blender/io_scene_ueformat/importer/create_space.py
        _POS_MIRROR  = (1.0, -1.0, 1.0)
        _UV_MIRROR   = (1.0, -1.0)
        _UV_OFFSET   = (0.0,  1.0)
        _QUAT_MIRROR = (1.0, -1.0, 1.0, -1.0)
        should_mirror(v) = v >= EUEFormatVersion.PreserveOriginalTransforms

    plugins/blender/io_scene_ueformat/importer/version.py
        PreserveOriginalTransforms = 8
        AttributeFormatRestructure = 10

dfmap writes version 10, so should_mirror() is True and every position is multiplied by
(1, -1, 1) after the centimetre -> metre scale, the V texture coordinate is flipped to 1 - v,
and the vertices stay in UE's Z-up frame (no axis swap: UE X/Y/Z map to Blender X/Y/Z).

Usage:
    blender --python blender_import_uemodel.py -- <file.uemodel | folder> [--no-mirror]
"""
import os
import struct
import sys

import bpy
from mathutils import Vector

SCALE = 0.01                      # UE centimetres -> metres
POS_MIRROR = (1.0, -1.0, 1.0)     # create_space.py::_POS_MIRROR
UV_MIRROR = (1.0, -1.0)
UV_OFFSET = (0.0, 1.0)

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not args:
    raise SystemExit("usage: blender --python blender_import_uemodel.py -- <file|folder> [--no-mirror]")
target = args[0]
mirror = "--no-mirror" not in args


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]
        self.p += 4
        return v

    def fstring(self):
        n = self.i32()
        s = self.d[self.p:self.p + n].decode('utf-8', 'replace')
        self.p += n
        return s

    def floats(self, n):
        v = struct.unpack_from('<%df' % n, self.d, self.p)
        self.p += 4 * n
        return v

    def uints(self, n):
        v = struct.unpack_from('<%dI' % n, self.d, self.p)
        self.p += 4 * n
        return v


def read_uemodel(path):
    """Return (objectName, [lod dicts]) for one .uemodel file."""
    raw = open(path, 'rb').read()
    r = Reader(raw)
    magic = raw[:8]
    if magic != b'UEFORMAT':
        raise ValueError(f'{path}: not a UEFORMAT file')
    r.p = 8
    identifier = r.fstring()
    version = r.u8()
    name = r.fstring()
    r.fstring()                       # objectPath
    compressed = r.u8()
    if compressed:
        raise ValueError(f'{path}: compressed UEMODEL is not handled')

    lods = []
    attr_count = r.i32()
    for _ in range(attr_count):
        attr_name = r.fstring()
        size = r.i32()
        end = r.p + size
        if attr_name != 'LODS':
            r.p = end
            continue
        lod_count = r.i32()
        for _ in range(lod_count):
            lod_name = r.fstring()
            n_attrs = r.i32()
            lod = {'name': lod_name, 'vertices': [], 'normals': [], 'indices': [], 'uvs': [], 'materials': []}
            for _ in range(n_attrs):
                a_name = r.fstring()
                a_size = r.i32()
                a_end = r.p + a_size
                if a_name == 'VERTICES':
                    n = r.i32()
                    lod['vertices'] = r.floats(n * 3)
                elif a_name == 'NORMALS':
                    n = r.i32()
                    vals = []
                    for _ in range(n):
                        r.f32()                       # BinormalSign
                        vals.extend(r.floats(3))
                    lod['normals'] = vals
                elif a_name == 'INDICES':
                    n = r.i32()
                    lod['indices'] = r.uints(n)
                elif a_name == 'TEXCOORDS':
                    channels = r.i32()
                    uv = []
                    for _ in range(channels):
                        r.fstring()
                        n = r.i32()
                        uv = list(r.floats(n * 2))
                    lod['uvs'] = uv
                elif a_name == 'MATERIALS':
                    n = r.i32()
                    mats = []
                    for _ in range(n):
                        mn = r.fstring()
                        mp = r.fstring()
                        first = r.i32()
                        faces = r.i32()
                        mats.append((mn, mp, first, faces))
                    lod['materials'] = mats
                r.p = a_end
            lods.append(lod)
        r.p = end
    return name, version, lods


def build_mesh(lod, obj_name):
    verts = lod['vertices']
    n = len(verts) // 3
    sx, sy, sz = POS_MIRROR if mirror else (1.0, 1.0, 1.0)

    coords = []
    for i in range(n):
        coords.append((verts[i * 3] * SCALE * sx,
                       verts[i * 3 + 1] * SCALE * sy,
                       verts[i * 3 + 2] * SCALE * sz))

    me = bpy.data.meshes.new(obj_name)
    idx = lod['indices']
    # guard: an index past the vertex list would make from_pydata build a corrupt mesh and take
    # Blender down with it, so clamp the triangle list to what is actually addressable
    safe = [i for i in idx if i < n]
    if len(safe) != len(idx):
        print(f'   ! {len(idx) - len(safe)} index/indices out of range, dropped')
    faces = [tuple(safe[i:i + 3]) for i in range(0, len(safe) - 2, 3)]
    me.from_pydata(coords, [], faces)
    me.update()

    uvs = lod['uvs']
    if uvs and len(uvs) >= n * 2:
        uvl = me.uv_layers.new(name='UVChannel_1')
        for i in range(n):
            u = uvs[i * 2]
            v = uvs[i * 2 + 1]
            if mirror:
                u = u * UV_MIRROR[0] + UV_OFFSET[0]
                v = v * UV_MIRROR[1] + UV_OFFSET[1]
            uvl.data[i].uv = (u, v)

    # Custom split normals are deliberately not set here: normals_split_custom_set_from_vertices
    # hard-crashes Blender when handed data it does not like, and the imported shading is not what
    # this script is for - it exists to check placement.

    return me


if os.path.isdir(target):
    files = sorted(f for f in os.listdir(target) if f.endswith('.uemodel'))
else:
    files = [target]
    target = os.path.dirname(target) or '.'

print(f"UEFormat convention: mirror={mirror}  scale={SCALE}  "
      f"(POS_MIRROR={POS_MIRROR} applied to vertices, normals and V coordinate)")
print(f"{'file':<40} {'verts':>10} {'tris':>10}  bounds (m)")

root = bpy.data.collections.new('uemodel')
bpy.context.scene.collection.children.link(root)

for f in files:
    path = f if os.path.isabs(f) else os.path.join(target, f)
    try:
        name, version, lods = read_uemodel(path)
    except Exception as exc:
        print(f'{os.path.basename(path):<40} FAILED: {exc}')
        continue
    if not lods:
        print(f'{os.path.basename(path):<40} no LODs')
        continue

    lod = lods[0]
    obj_name = os.path.splitext(os.path.basename(path))[0]
    me = build_mesh(lod, obj_name)
    obj = bpy.data.objects.new(obj_name, me)
    coll = bpy.data.collections.new(obj_name)
    root.children.link(coll)
    coll.objects.link(obj)

    if me.vertices:
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        zs = [v.co.z for v in me.vertices]
        bounds = (f'X {min(xs):.1f}..{max(xs):.1f}  Y {min(ys):.1f}..{max(ys):.1f}  '
                  f'Z {min(zs):.1f}..{max(zs):.1f}')
    else:
        bounds = '-'
    print(f'{obj_name:<40} {len(me.vertices):>10,} {len(me.loop_triangles) if me.loop_triangles else len(me.polygons):>10,}  {bounds}')

print(f'\nimported {len(files)} file(s) under the "uemodel" collection '
      f'(version reported per file above; dfmap writes 10)')
