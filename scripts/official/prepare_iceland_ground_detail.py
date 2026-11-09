"""Build source-derived high-frequency colour and bilinear layer-weight textures."""
import json
from pathlib import Path
import numpy as np
from PIL import Image

root=Path('D:/AtlasMap-tooling/out/Iceland/revised')
folder=root/'ground_detail'
source=json.loads((root/'ground_material/ground_sources.json').read_text(encoding='utf-8-sig'))
decoded=json.loads((folder/'texture_files.json').read_text())
files={row['source']:row['texture'] for row in decoded['textures']}
normal_paths=(root.parent/'audit/ground_normal_paths.txt').read_text().splitlines()
ratio_folder=folder/'colour_detail';ratio_folder.mkdir(exist_ok=True)
layers=[]
footprint=4033/8192
for index,layer in enumerate(source['layers']):
    entry=files[layer['source']]
    if entry is None:raise RuntimeError('Missing source albedo '+layer['source'])
    image=np.asarray(Image.open(folder/entry['RelativePath']).convert('RGB'),dtype=np.float32)/255
    linear=np.where(image<=.04045,image/12.92,((image+.055)/1.055)**2.4)
    height,width=linear.shape[:2]
    # Remove the frequencies already represented by the world-space RVT texel.
    sigma=footprint*layer['tiling']*width/2
    fy=np.fft.fftfreq(height)[:,None];fx=np.fft.rfftfreq(width)[None,:]
    gaussian=np.exp(-2*np.pi*np.pi*sigma*sigma*(fx*fx+fy*fy))
    low=np.empty_like(linear)
    for channel in range(3):
        low[:,:,channel]=np.fft.irfft2(np.fft.rfft2(linear[:,:,channel])*gaussian,s=(height,width)).real
    ratio=linear/np.maximum(low,.001)
    clipped=float(np.mean((ratio<0)|(ratio>4)))
    encoded=np.clip(np.rint(ratio/4*255),0,255).astype(np.uint8)
    filename='colour_detail/'+Path(entry['RelativePath']).stem+'_detail.png'
    Image.fromarray(encoded).save(folder/filename)
    normal=files.get(normal_paths[index])
    if not normal:raise RuntimeError('Missing source normal layer')
    layers.append(dict(index=index,source=layer['source'],albedo=entry['RelativePath'],normal_source=normal_paths[index],normal=normal['RelativePath'],
                       tiling=layer['tiling'],colour_detail=filename,ratio_decode_scale=4,
                       sigma_texels=sigma,clipped_channel_fraction=clipped,
                       effective_albedo_texels_per_metre=width*layer['tiling']))
    print('prepared layer',index,flush=True)

packed=np.asarray(Image.open(root/'ground_material/terrain_layer_ids_weights.png').convert('RGBA'))
a,b,weight=packed[:,:,0],packed[:,:,1],packed[:,:,2].astype(np.float32)/7
coverage=packed[:,:,3]>0
weight_files=[];max_error=0
for group in range(3):
    image=np.zeros((*a.shape,4),np.uint8)
    for channel in range(4):
        index=group*4+channel
        if index>=10:continue
        exact=((a==index)*(1-weight)+(b==index)*weight)*coverage
        quantized=np.clip(np.rint(exact*255),0,255).astype(np.uint8)
        max_error=max(max_error,float(np.max(np.abs(quantized.astype(np.float32)/255-exact))))
        image[:,:,channel]=quantized
    filename=f'layer_weights_{group}.png'
    Image.fromarray(image).save(folder/filename);weight_files.append(filename)
report={'layers':layers,'weight_files':weight_files,'weight_image_size':[a.shape[1],a.shape[0]],
        'maximum_weight_quantization_error':max_error,'rvt_footprint_metres':footprint,
        'method':'Linear-light periodic Gaussian high-pass from original albedos; RGB stores ratio/4. Source G16 layer weights expanded before bilinear sampling.'}
(folder/'ground_detail_sources.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'layers':len(layers),'maximum_weight_quantization_error':max_error}),flush=True)
