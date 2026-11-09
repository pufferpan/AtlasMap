"""Bypass UE's PNG transparent-RGB infill using lossless RGBA TGA input."""
import json
import unreal
import ue_iceland_bridge as bridge
rows=json.loads((bridge.ROOT/'binary_alpha_rgb_risk.json').read_text())
report=[]
for row in rows:
    factory=unreal.TextureFactory();factory.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_EDITOR_ICON);factory.set_editor_property('no_alpha',False)
    obj=bridge.import_task((bridge.ROOT/row['file']).with_suffix('.tga'),bridge.DEST+'/Textures',row['id'],factory=factory)
    for name,value in {'compression_settings':unreal.TextureCompressionSettings.TC_EDITOR_ICON,'srgb':row['srgb'],'compression_no_alpha':False,
        'mip_gen_settings':unreal.TextureMipGenSettings.TMGS_SIMPLE_AVERAGE,'lod_group':unreal.TextureGroup.TEXTUREGROUP_CINEMATIC,
        'lod_bias':0,'max_texture_size':max(row['size']),'filter':unreal.TextureFilter.TF_BILINEAR}.items():obj.set_editor_property(name,value)
    if max(row['size'])>=4034:obj.set_editor_property('never_stream',True)
    bridge.metadata(obj,'BlenderSHA256',row['sha256']);bridge.metadata(obj,'BlenderSRGB',int(row['srgb']));bridge.metadata(obj,'BlenderPackedRGBAImport','TGA bypasses PNG RGB infill')
    bridge.save(obj);bridge._assets[bridge.package('Textures',row['id'])]=obj
    filename=bridge.ROOT/'validation'/(row['id']+'_ue.png')
    task=unreal.AssetExportTask();task.object=obj;task.filename=str(filename);task.automated=True;task.prompt=False;task.replace_identical=True;task.exporter=unreal.TextureExporterPNG()
    if not unreal.Exporter.run_asset_export_task(task):raise RuntimeError('Cannot export packed texture for independent pixel check')
    report.append({'id':row['id'],'source':row['file'],'exported':str(filename)})
(bridge.ROOT/'packed_rgba_repair.json').write_text(json.dumps(report,indent=2))
output_data={'repaired':len(report)}
