"""Independently parse a .uemodel written by dfmap, following the published spec:

    https://github.com/h4lfheart/UEFormat/blob/main/docs/generic.md
    https://github.com/h4lfheart/UEFormat/blob/main/docs/uemodel.md

Nothing from dfmap is imported here - this is a from-scratch reader, so it validates the
binary layout rather than agreeing with the writer by construction.
"""
import struct
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = sys.argv[1] if len(sys.argv) > 1 else r"G:\AAAAAmanp研究\out\SafeHouse\scene.uemodel"
data = open(path, "rb").read()
print(f"file: {path}  ({len(data)/1048576:.2f} MB)\n")


class R:
    def __init__(self, buf):
        self.b = buf
        self.p = 0

    def take(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise EOFError(f"want {n} bytes at {self.p}, have {len(v)}")
        self.p += n
        return v

    def u8(self): return struct.unpack("<B", self.take(1))[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def f32(self): return struct.unpack("<f", self.take(4))[0]

    def fstring(self):
        n = self.i32()
        if n < 0 or n > 1 << 20:
            raise ValueError(f"implausible FString length {n} at {self.p - 4}")
        return self.take(n).decode("utf-8", "replace")


r = R(data)
magic = r.take(8)
assert magic == b"UEFORMAT", f"bad magic {magic!r}"
identifier = r.fstring()
version = r.u8()
object_name = r.fstring()
object_path = r.fstring()
compressed = r.u8()
print(f"magic      : {magic.decode()}")
print(f"identifier : {identifier}")
print(f"version    : {version}   (UEFormat latest = 10)")
print(f"object     : {object_name}")
print(f"objectPath : {object_path}")
print(f"compressed : {bool(compressed)}")
assert identifier == "UEMODEL", "identifier is not UEMODEL"
assert not compressed, "compressed bodies are not expected here"


def attribute_set(reader):
    """FDataAttributeSet = int count + count * (FString name, int byteSize, byte[] data)."""
    out = {}
    n = reader.i32()
    for _ in range(n):
        name = reader.fstring()
        size = reader.i32()
        out[name] = reader.take(size)
    return out


def parse_attr(reader):
    out = {}
    n = reader.i32()
    for _ in range(n):
        fs = reader.fstring()
        size = reader.i32()
        out[fs] = reader.take(size)
    return out


root = attribute_set(r)
print(f"\nroot attributes: {list(root)}")
assert "LODS" in root, "no LODS attribute"

lr = R(root["LODS"])
lod_count = lr.i32()
print(f"LODs       : {lod_count}")

for li in range(lod_count):
    lod_name = lr.fstring()
    attrs = attribute_set(lr)
    print(f"\n--- LOD {li}: {lod_name} ---")
    print(f"    attributes: {list(attrs)}")

    ar = R(attrs["VERTICES"])
    vcount = ar.i32()
    assert len(attrs["VERTICES"]) == 4 + vcount * 12, "VERTICES byte size mismatch"
    varr = np.frombuffer(attrs["VERTICES"], dtype=np.float32, count=vcount * 3, offset=4).reshape(-1, 3)
    print(f"    VERTICES   : {vcount:,}")
    print(f"      bounds (UE cm): X {varr[:,0].min():.1f}..{varr[:,0].max():.1f}  "
          f"Y {varr[:,1].min():.1f}..{varr[:,1].max():.1f}  Z {varr[:,2].min():.1f}..{varr[:,2].max():.1f}")
    print(f"      finite: {bool(np.isfinite(varr).all())}")

    if "NORMALS" in attrs:
        nr = R(attrs["NORMALS"])
        ncount = nr.i32()
        sample = struct.unpack_from("<f3f", attrs["NORMALS"], 4)
        print(f"    NORMALS    : {ncount:,}  (entry = BinormalSign + FVector = 16 B, "
              f"first={tuple(round(x, 3) for x in sample)})")
        assert len(attrs["NORMALS"]) == 4 + ncount * 16, "NORMALS byte size mismatch"

    if "TEXCOORDS" in attrs:
        tr = R(attrs["TEXCOORDS"])
        chans = tr.i32()
        for _ in range(chans):
            cn = tr.fstring()
            uvcount = tr.i32()
            print(f"    TEXCOORDS  : channel '{cn}', {uvcount:,} UVs")

    ir = R(attrs["INDICES"])
    icount = ir.i32()
    assert len(attrs["INDICES"]) == 4 + icount * 4, "INDICES byte size mismatch"
    idx = struct.unpack_from(f"<{min(icount, 6000000)}I", attrs["INDICES"], 4)
    print(f"    INDICES    : {icount:,}  ({icount // 3:,} triangles)  max={max(idx)}")
    assert max(idx) < vcount, f"index {max(idx)} out of range for {vcount} vertices"

    if "MATERIALS" in attrs:
        mr = R(attrs["MATERIALS"])
        mcount = mr.i32()
        print(f"    MATERIALS  : {mcount}")
        total_faces = 0
        for mi in range(min(mcount, 4)):
            name = mr.fstring(); mpath = mr.fstring()
            first = mr.i32(); faces = mr.i32()
            print(f"      [{mi}] {name!r} path={mpath!r} firstIndex={first} numFaces={faces}")
        for mi in range(4, mcount):
            mr.fstring(); mr.fstring(); mr.i32(); mr.i32()
        print(f"      ... {mcount} slots total")

print(f"\nconsumed {r.p} of {len(data)} bytes; trailing {len(data) - r.p}")
print("\nVERDICT: OK")
