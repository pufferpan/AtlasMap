"""Write lossless float16 DDS cubemap from the game's decoded BC6H faces."""
import json,struct,hashlib
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path('D:/AtlasMap-tooling/out/Iceland/audit/environment_query/lighting')
faces=np.stack([np.fromfile(ROOT/f'SCb0_19_2/face{i}_float32_rgba.bin','<f4').reshape(128,128,4) for i in range(6)])
assert np.isfinite(faces).all() and faces[:,:,:,:3].max()>1
assert np.all(faces[:,:,:,3]==1)
# DDS DX10, R16G16B16A16_FLOAT. Six faces retain the native +X,-X,+Y,-Y,+Z,-Z order.
pf=struct.pack('<8I',32,4,0x30315844,0,0,0,0,0)
header=struct.pack('<7I',124,0x100F,128,128,128*8,0,1)+bytes(44)+pf+struct.pack('<5I',0x1008,0xFE00,0,0,0)
assert len(header)==124
dx10=struct.pack('<5I',10,3,4,1,0)
dds=b'DDS '+header+dx10+faces.astype('<f2').tobytes()
(ROOT/'SCb0_19_2_RGBA16F.dds').write_bytes(dds)
readback=np.frombuffer(dds,offset=148,dtype='<f2').astype(np.float32).reshape(faces.shape)
assert np.array_equal(readback,faces)
rgba=np.fromfile(ROOT/'Iceland_Skybox_PC/layer0.bin',np.uint8).reshape(1024,2048,4)[:,:,[2,1,0,3]]
Image.fromarray(rgba,'RGBA').save(ROOT/'Iceland_Skybox_PC_RGBM.png')
# Keep source RGBM data exact; TC_HDR_RGBM requires HDR decode in UE material.
report={'cube_file':'SCb0_19_2_RGBA16F.dds','cube_faces':6,'cube_size':128,'cube_format':'DXGI_R16G16B16A16_FLOAT','cube_roundtrip_exact':True,'cube_face_mean_rgb':faces[:,:,:,:3].mean((1,2)).tolist(),'cube_max_rgb':faces[:,:,:,:3].max((0,1,2)).tolist(),'cube_sha256':hashlib.sha256(dds).hexdigest(),'sky_source_texture':'Iceland_Skybox_PC','sky_compression':'TC_HDR_RGBM','sky_srgb':False,'sky_raw_png':'Iceland_Skybox_PC_RGBM.png','sky_alpha_byte':32,'source_HDRScale':0.7,'note':'The original Cube PackedData=0xA0000006 uses bit29 in its UE4 cooked layout; current CUE4Parse incorrectly treats it as UE5 CPU-copy. Manual native mip parsing followed by existing BC6H block decoder preserves HDR half precision; diffuse GI2D/PRT and game-specific exposure conversion are not reconstructed.'}
(ROOT/'source_sky_decode_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
