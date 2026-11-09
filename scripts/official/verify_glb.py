"""Validate a GLB produced by `dfmap merge` without any 3D library.

Checks the container, the JSON graph, every bufferView/accessor bound, and
recomputes scene statistics so the numbers can be cross-checked against
merge_report.json.
"""
import json
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = sys.argv[1] if len(sys.argv) > 1 else r"G:\AAAAAmanp鐮旂┒\out\AZ-5\scene.glb"
raw = open(path, "rb").read()
print(f"file: {path}  ({len(raw)/1048576:.2f} MB)")

magic, version, length = struct.unpack_from("<III", raw, 0)
assert magic == 0x46546C67, "bad magic"
print(f"container: magic=glTF version={version} declared_length={length} actual={len(raw)}")
assert length == len(raw), "declared length != file size"

# --- chunks ---
off, chunks = 12, []
while off < len(raw):
    clen, ctype = struct.unpack_from("<II", raw, off)
    chunks.append((ctype, off + 8, clen))
    off += 8 + clen
names = {0x4E4F534A: "JSON", 0x004E4942: "BIN"}
for ctype, o, clen in chunks:
    print(f"  chunk {names.get(ctype, hex(ctype))}: offset={o} len={clen}")
assert chunks[0][0] == 0x4E4F534A, "first chunk must be JSON"
assert len(chunks) == 2, f"expected 2 chunks, got {len(chunks)}"

json_len, json_off = chunks[0][2], chunks[0][1]
bin_len, bin_off = chunks[1][2], chunks[1][1]
gltf = json.loads(raw[json_off:json_off + json_len].decode("utf-8").rstrip())

print(f"\nasset: {gltf['asset']}")
print(f"scenes={len(gltf.get('scenes', []))} nodes={len(gltf.get('nodes', []))} "
      f"meshes={len(gltf.get('meshes', []))} accessors={len(gltf.get('accessors', []))} "
      f"bufferViews={len(gltf.get('bufferViews', []))}")

# --- buffers ---
declared = gltf["buffers"][0]["byteLength"]
print(f"buffer declared={declared}  bin chunk={bin_len}")
assert declared <= bin_len, "declared buffer exceeds BIN chunk"

# --- bufferView / accessor bounds ---
COMP = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
errors = []
for i, bv in enumerate(gltf["bufferViews"]):
    if bv.get("buffer", 0) != 0:
        errors.append(f"bufferView {i}: non-zero buffer index")
    end = bv.get("byteOffset", 0) + bv["byteLength"]
    if end > declared:
        errors.append(f"bufferView {i}: ends at {end} > buffer {declared}")
for i, a in enumerate(gltf["accessors"]):
    if "bufferView" not in a:
        continue
    bv = gltf["bufferViews"][a["bufferView"]]
    need = a["count"] * NCOMP[a["type"]] * COMP[a["componentType"]]
    have = bv["byteLength"] - a.get("byteOffset", 0)
    if need > have:
        errors.append(f"accessor {i}: needs {need} bytes, view has {have}")
print(f"structural errors: {len(errors)}")
for e in errors[:10]:
    print("  !!", e)

# --- mesh stats + bounds ---
tris = verts = 0
gmin = [float("inf")] * 3
gmax = [float("-inf")] * 3
for m in gltf["meshes"]:
    for p in m["primitives"]:
        pa = gltf["accessors"][p["attributes"]["POSITION"]]
        verts += pa["count"]
        if "indices" in p:
            tris += gltf["accessors"][p["indices"]]["count"] // 3
        if "min" in pa:
            for k in range(3):
                gmin[k] = min(gmin[k], pa["min"][k])
                gmax[k] = max(gmax[k], pa["max"][k])
print(f"\ngeometry: {verts} vertices, {tris} triangles")
print(f"mesh-local bounds (m): min=({gmin[0]:.1f}, {gmin[1]:.1f}, {gmin[2]:.1f}) "
      f"max=({gmax[0]:.1f}, {gmax[1]:.1f}, {gmax[2]:.1f})")

# --- instance translation bounds (scene extent in glTF space) ---
tmin = [float("inf")] * 3
tmax = [float("-inf")] * 3
n_inst = 0
for n in gltf["nodes"]:
    if "matrix" not in n:
        continue
    t = n["matrix"][12:15]
    n_inst += 1
    for k in range(3):
        tmin[k] = min(tmin[k], t[k])
        tmax[k] = max(tmax[k], t[k])
print(f"\ninstances (mesh nodes): {n_inst}")
if n_inst:
    print(f"instance-origin bounds (m): min=({tmin[0]:.1f}, {tmin[1]:.1f}, {tmin[2]:.1f}) "
          f"max=({tmax[0]:.1f}, {tmax[1]:.1f}, {tmax[2]:.1f})")
    print(f"scene size (m): {(tmax[0]-tmin[0]):.0f} x {(tmax[1]-tmin[1]):.0f} x {(tmax[2]-tmin[2]):.0f}")

print("\nVERDICT: " + ("OK" if not errors else f"{len(errors)} STRUCTURAL ERRORS"))

