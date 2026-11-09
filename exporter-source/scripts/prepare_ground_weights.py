"""Decode the ground's G16 layer-ID/weight pages without changing geometry."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

root=Path("D:/AtlasMap-tooling/out/Iceland/revised/ground_material")
source=json.loads((root/"ground_sources.json").read_text(encoding="utf-8-sig"))
width=height=4096
packed=np.zeros((height,width),dtype=np.uint16)
coverage=np.zeros((height,width),dtype=np.bool_)
for page in source["pages"]:
    x,y=page["x"]*128,page["y"]*128
    data=np.fromfile(root/page["file"],"<u2").reshape(page["height"],page["width"])
    packed[y:y+data.shape[0],x:x+data.shape[1]]=data
    coverage[y:y+data.shape[0],x:x+data.shape[1]]=True
layer_a=packed>>11
layer_b=(packed>>3)&31
weight_b=packed&7
assert not np.any(packed&0x700)
assert layer_a.max()<len(source["layers"]) and layer_b.max()<len(source["layers"])
assert np.array_equal(((layer_a<<11)|(layer_b<<3)|weight_b).astype(np.uint16),packed)
rgba=np.stack((layer_a,layer_b,weight_b,coverage.astype(np.uint8)*255),axis=-1).astype(np.uint8)
origin=source["actor"]["OriginTextureSize"]
rgba=rgba[:origin["Y"],:origin["X"]]
Image.fromarray(rgba,"RGBA").save(root/"terrain_layer_ids_weights.png")
report={"format":"G16: layer A bits 11..15, layer B bits 3..7, blend bits 0..2; reserved bits 8..10 zero",
        "pages":len(source["pages"]),"size":[origin["X"],origin["Y"]],"layers":len(source["layers"]),
        "lossless_roundtrip":True,"active_layer_ids":sorted(set(np.unique(layer_a[coverage]).tolist()+np.unique(layer_b[coverage]).tolist())),
        "coverage_pixels":int(np.count_nonzero(rgba[:,:,3])),
        "image":"terrain_layer_ids_weights.png"}
pure=(layer_a==layer_b)&coverage
mixed=(layer_a!=layer_b)&coverage
forward=reverse=edges=0
for dy,dx in [(0,1),(1,0)]:
    select=pure[:height-dy,:width-dx]&mixed[dy:,dx:]
    adjacent=layer_a[:height-dy,:width-dx][select]
    a,b=layer_a[dy:,dx:][select],layer_b[dy:,dx:][select]
    weight=weight_b[dy:,dx:][select]/7
    valid=(adjacent==a)|(adjacent==b)
    forward+=float(np.where(adjacent[valid]==a[valid],weight[valid],1-weight[valid]).sum())
    reverse+=float(np.where(adjacent[valid]==b[valid],weight[valid],1-weight[valid]).sum())
    edges+=int(valid.sum())
report["weight_direction_boundary_score"]={"forward":forward/edges,"reverse":reverse/edges,"tested_edges":edges}
assert forward<reverse
(root/"ground_weight_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report,indent=2))
