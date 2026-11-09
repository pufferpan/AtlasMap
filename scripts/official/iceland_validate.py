"""Independent checks on exported GLBs and matching FModel UEMODEL assets."""
import json
import struct
import sys
from pathlib import Path

import numpy as np


def fstring(data, offset):
    count = struct.unpack_from("<i", data, offset)[0]
    assert 0 <= count < 1000000
    return data[offset + 4:offset + 4 + count].decode(), offset + 4 + count


def attributes(data, offset):
    count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    result = {}
    for _ in range(count):
        name, offset = fstring(data, offset)
        size = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        result[name] = data[offset:offset + size]
        offset += size
    return result


def reference(path, with_uv=False):
    data = path.read_bytes()
    assert data[:8] == b"UEFORMAT"
    identifier, offset = fstring(data, 8)
    assert identifier == "UEMODEL"
    version = data[offset]
    assert version == 10
    _, offset = fstring(data, offset + 1)
    _, offset = fstring(data, offset)
    assert data[offset] == 0, "compressed reference"
    lods = attributes(data, offset + 1)["LODS"]
    _, offset = fstring(lods, 4)
    lod = attributes(lods, offset)
    n = struct.unpack_from("<i", lod["VERTICES"])[0]
    positions = np.frombuffer(lod["VERTICES"], "<f4", offset=4, count=n * 3).reshape(-1, 3)
    n = struct.unpack_from("<i", lod["INDICES"])[0]
    indices = np.frombuffer(lod["INDICES"], "<u4", offset=4, count=n)
    if with_uv:
        uv = None
        if "TEXCOORDS" in lod:
            chunk = lod["TEXCOORDS"]
            if struct.unpack_from("<i",chunk)[0] > 0:
                _,offset = fstring(chunk,4)
                count = struct.unpack_from("<i",chunk,offset)[0]
                uv = np.frombuffer(chunk,"<f4",offset=offset+4,count=count*2).reshape(-1,2)
        return positions,indices,uv
    return positions, indices


def main(root):
    root = Path(root)
    seen = set()
    checked = references = equivalent = uv_matches = 0
    uv_mismatches = []
    mismatches, unavailable = [], []
    for file in root.glob("*/split/*.glb"):
        raw = file.read_bytes()
        magic, version, length = struct.unpack_from("<III", raw)
        assert magic == 0x46546C67 and version == 2 and length == len(raw)
        jl = struct.unpack_from("<I", raw, 12)[0]
        document = json.loads(raw[20:20 + jl])
        binary = raw[28 + jl:]
        for view in document["bufferViews"]:
            assert view.get("byteOffset", 0) + view["byteLength"] <= len(binary)

        def accessor(index):
            a = document["accessors"][index]
            view = document["bufferViews"][a["bufferView"]]
            dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[a["componentType"]]
            components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
            return np.frombuffer(binary, dtype, a["count"] * components,
                                 view.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(a["count"], components)

        for mesh in document["meshes"]:
            name = mesh["name"]
            if name in seen:
                continue
            seen.add(name)
            checked += 1
            primitive = mesh["primitives"][0]
            positions = accessor(primitive["attributes"]["POSITION"])
            indices = np.concatenate([accessor(p["indices"]).ravel() for p in mesh["primitives"]])
            assert len(indices) % 3 == 0 and indices.max() < len(positions)
            assert np.isfinite(positions).all()
            package = name.rsplit(".", 1)[0]
            path = Path("E:/FModelNew/Save") / (package + ".uemodel")
            if not path.exists():
                continue
            try:
                ref_pos, ref_idx, ref_uv = reference(path,with_uv=True)
            except Exception as exc:
                unavailable.append({"asset": name, "reason": str(exc)})
                continue
            references += 1
            if ref_pos.shape != positions.shape:
                mismatches.append({"asset": name, "reason": "different vertex count", "exported": len(positions), "reference": len(ref_pos)})
                continue
            delta = float(np.max(np.abs(positions - ref_pos[:, [0, 2, 1]] * 0.01)))
            if delta > 0.001:
                mismatches.append({"asset": name, "reason": "different positions/version", "delta_m": delta})
                continue
            # Sections may reorder triangles. Compare the unordered triangle set.
            a, b = np.sort(indices.reshape(-1, 3), axis=1), np.sort(ref_idx.reshape(-1, 3), axis=1)
            a = a[np.lexsort(a.T[::-1])]
            b = b[np.lexsort(b.T[::-1])]
            if not np.array_equal(a, b):
                mismatches.append({"asset": name, "reason": "matching vertices but different topology", "exported_triangles": len(a), "reference_triangles": len(b)})
                continue
            equivalent += 1
            if ref_uv is not None and "TEXCOORD_0" in primitive["attributes"]:
                actual_uv = accessor(primitive["attributes"]["TEXCOORD_0"])
                if actual_uv.shape == ref_uv.shape and np.allclose(actual_uv,ref_uv,atol=0.00001):
                    uv_matches += 1
                else:
                    uv_mismatches.append({"asset":name,"max_delta":float(np.max(np.abs(actual_uv-ref_uv))) if actual_uv.shape==ref_uv.shape else None})
    result = {"unique_meshes_checked": checked, "readable_FModel_references": references,
              "exact_geometry_matches": equivalent, "reference_mismatches": mismatches,
              "unsupported_references": unavailable,"exact_uv_matches":uv_matches,"uv_mismatches":uv_mismatches}
    (root / "diagnostics" / "geometry_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
