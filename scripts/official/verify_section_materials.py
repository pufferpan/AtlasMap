import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np
from iceland_validate import attributes, fstring, reference

root=Path(sys.argv[1])
bundle=json.loads((root/"repair_bundle.json").read_text(encoding="utf-8-sig"))
matches=[]
failures=[]
unavailable=[]
for item in bundle["meshes"]:
    path=Path("E:/FModelNew/Save")/(item["asset"].rsplit(".",1)[0]+".uemodel")
    if not path.exists():continue
    try:
        _,indices=reference(path)
        if hashlib.sha256(indices.astype("<u4").tobytes()).hexdigest()!=item["index_sha256"]:
            unavailable.append({"asset":item["asset"],"reason":"reference index order differs"})
            continue
        data=path.read_bytes()
        _,offset=fstring(data,8)
        offset+=1
        _,offset=fstring(data,offset)
        _,offset=fstring(data,offset)
        lods=attributes(data,offset+1)["LODS"]
        _,offset=fstring(lods,4)
        source=attributes(lods,offset)["MATERIALS"]
        count=struct.unpack_from("<i",source)[0]
        offset=4
        faces=np.fromfile(root/item["face_material_file"],dtype="<u2")
        labels=np.array([s.rsplit(".",1)[-1].rsplit("/",1)[-1].lower() for s in item["materials"]])
        ok=True
        for _ in range(count):
            name,offset=fstring(source,offset)
            material_path,offset=fstring(source,offset)
            first,num=struct.unpack_from("<ii",source,offset)
            offset+=8
            actual=labels[faces[first//3:first//3+num]]
            if len(actual)!=num or np.any(actual!=name.lower()):
                failures.append({"asset":item["asset"],"expected_material":name,"first_index":first,"triangles":num,"actual_materials":sorted(set(actual))})
                ok=False
        if ok:matches.append(item["asset"])
    except Exception as ex:
        unavailable.append({"asset":item["asset"],"reason":str(ex)})
report={"matched_meshes":len(matches),"failures":failures,"unsupported_references":unavailable,"matches":matches}
(root/"section_material_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k!="matches"},indent=2))
assert not failures
