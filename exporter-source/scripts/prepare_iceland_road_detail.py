"""Extract high-frequency colour from the original road albedos."""
import json
from pathlib import Path
import numpy as np
from PIL import Image

root=Path('D:/AtlasMap-tooling/out/Iceland/revised')
folder=root/'road_detail'
definitions=json.loads((root/'material_refresh/material_refresh.json').read_text())['materials']
textures={row['source']:row['texture'] for row in json.loads((folder/'texture_files.json').read_text())['textures']}
rows=[]
for path,definition in definitions.items():
    if 'M_Road_2layerDetail_HD' not in (definition.get('MasterPath') or ''):continue
    parameters=definition['texture_parameters'];entry=textures[parameters['BaseColorMap']['source']]
    image=np.asarray(Image.open(folder/entry['RelativePath']).convert('RGB'),np.float32)/255
    linear=np.where(image<=.04045,image/12.92,((image+.055)/1.055)**2.4)
    h,w=linear.shape[:2];sigma=32*w/2048
    fy=np.fft.fftfreq(h)[:,None];fx=np.fft.rfftfreq(w)[None,:]
    kernel=np.exp(-2*np.pi*np.pi*sigma*sigma*(fx*fx+fy*fy))
    low=np.empty_like(linear)
    for channel in range(3):low[:,:,channel]=np.fft.irfft2(np.fft.rfft2(linear[:,:,channel])*kernel,s=(h,w)).real
    detail=np.clip(np.rint(linear/np.maximum(low,.001)/4*255),0,255).astype(np.uint8)
    filename=Path(entry['RelativePath']).stem+'_detail.png';Image.fromarray(detail).save(folder/filename)
    rows.append({'material':path,'colour_detail':filename,'source_albedo':parameters['BaseColorMap']['source'],
                 'normal':textures[parameters['NormalMap']['source']]['RelativePath'],
                 'hra':textures[parameters['HRAMap']['source']]['RelativePath'],
                 'original_normal_file':definition['normal'],'original_hra_file':parameters['HRAMap']['file'],
                 'sigma_texels':sigma,'ratio_decode_scale':4,'size':[w,h]})
(folder/'road_detail_sources.json').write_text(json.dumps({'materials':rows,'method':'Periodic linear-light high-pass; source road UVs retained'},indent=2))
print('Prepared road colour detail:',len(rows))
