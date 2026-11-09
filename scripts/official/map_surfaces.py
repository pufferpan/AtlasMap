"""Source-driven water/translucency semantics shared by Blender and UE export."""
import json
import math
import re

def surface_settings(source):
    resolved=source.get('resolved') or {}
    if not resolved.get('MasterPath') and not source.get('chain'):return {}
    props={};scalars={};vectors={};switches={}
    for row in reversed(source.get('chain') or []):
        p=(row.get('value') or {}).get('Properties') or {}
        props.update({k:v for k,v in p.items() if k!='BasePropertyOverrides'})
        override=p.get('BasePropertyOverrides',{})
        for key in ('BlendMode','ShadingModel','TwoSided','OpacityMaskClipValue'):
            if key in override and override.get('bOverride_'+key,False):props[key]=override[key]
        for key,target in (('ScalarParameterValues',scalars),('VectorParameterValues',vectors)):
            for entry in p.get(key,[]):target[entry['ParameterInfo']['Name']]=entry['ParameterValue']
        for entry in p.get('StaticParameters',{}).get('StaticSwitchParameters',[]):
            if entry.get('bOverride',True):switches[entry['ParameterInfo']['Name']]=entry['Value']
    scalars={**resolved.get('ScalarParameters',{}),**scalars}
    vectors={**resolved.get('VectorParameters',{}),**vectors}
    switches={**resolved.get('SwitchParameters',{}),**switches}
    def scalar(names,default):
        for name in names:
            value=scalars.get(name)
            if isinstance(value,(int,float)) and math.isfinite(value):return float(value)
        return default
    blend=str(props.get('BlendMode','')).lower()
    master=(resolved.get('MasterPath') or '').split('/')[-1].lower()
    shading=str(props.get('ShadingModel',''))+str(props.get('ShadingModels',''))
    # Use the actual shader family, never an instance name like WaterTank.
    water=('singlelayerwater' in shading.lower() or 'ocean' in master or
           bool(re.search(r'(?:^|_)water(?:_|hd|master|\.)',master)))
    kind='water' if water else 'translucent' if any(x in blend for x in ('translucent','alphacomposite','additive')) or 'thintranslucent' in shading.lower() else 'masked' if 'masked' in blend else 'opaque'
    if not source:return {}
    opacity=scalar(('Opacity','GlassOpacity','WaterOpacity','OpacityScale'),None)
    if opacity is None:
        lo=scalar(('OpacityMaskMin',),0.0);hi=scalar(('OpacityMaskMax',),1.0)
        opacity=(lo+hi)*.5 if kind=='translucent' else .4 if water else 1.0
    result={'kind':kind,'blend_mode':props.get('BlendMode','BLEND_Opaque'),
        'ior':max(1,min(2.5,scalar(('IOR','IndexOfRefraction','Refraction'),1.333 if water else 1.45))),
        'opacity':max(0,min(1,opacity)),
        'roughness':max(0,min(1,scalar(('WaterRoughnessMin','GlassRoughness','BlurRoughness','Roughness'),.08 if water else .12))),
        'specular':max(0,min(1,scalar(('Specular',),.5))),
        'clip':scalar(('OpacityMaskClipValue',),float(props.get('OpacityMaskClipValue',.333))),
        'master':resolved.get('MasterPath'), 'source':source,
        'thin_glass':kind=='translucent' and ('thintranslucent' in shading.lower() or 'glass' in (str(props.get('PhysMaterial',''))+master+(resolved.get('Path') or '')).lower()) and 'additive' not in blend,
        'refraction_depth_bias':max(0,scalar(('RefractionDepthBias',),0)),
        'compatibility':'Native surface approximation; cooked game shader math and runtime water simulation are not reconstructed.'}
    for name in ('GlassColor','GlassTint','TransmissionColor','ColorTint','Color'):
        value=vectors.get(name)
        if value is not None and result['thin_glass']:
            result['transmittance_color']=[max(0,min(1,float(value.get(k,1) if isinstance(value,dict) else value[i]))) for i,k in enumerate(('R','G','B'))]
            break
    result['frosted_glass']=result['thin_glass'] and ('BlurRoughness' in scalars or 'blurryglass' in master)
    if result['frosted_glass']:
        result['frosted_blur_radius']=max(0,min(.08,scalar(('Distance',),result['roughness']*.02)))
    if water:
        def vector(name):
            v=vectors.get(name)
            return [v.get(k,0) for k in ('R','G','B','A')] if isinstance(v,dict) else v
        color=vector('WaterBaseColorTranslucency0')
        if color:result['color']=color[:3]
        absorption=vector('SurfaceAbsorption0') or vector('DeepWaterSurfaceAbsorption')
        scatter=vector('SurfaceScattering0') or vector('DeepWater_SurfaceScattering0')
        if absorption:
            result['absorption']=[1/max(1,float(x)*max(1,float(absorption[3]))) for x in absorption[:3]]
        if scatter:result['scattering']=[max(0,float(x))*max(0,float(scatter[3])) for x in scatter[:3]]
        result['normal_speed']=scalar(('DetailWaveUVSpeed',),0)*.01
        result['normal_scale']=scalar(('DetailWaveUVScale',),1)
    if 'TwoSided' in props or 'bTwoSided' in props:result['two_sided']=bool(props.get('TwoSided',props.get('bTwoSided')))
    return result


def apply_blender_surfaces(root,materials):
    path=root/'source-render'/'materials.json'
    if not path.exists():return
    sources=json.loads(path.read_text(encoding='utf-8-sig'))
    report=[]
    for material in materials:
        source=sources.get(material.get('unrealMaterialPath'))
        if not source:continue
        settings=surface_settings(source)
        if not settings:
            report.append({'material':material.name,'status':'source_unavailable','source':material.get('unrealMaterialPath')})
            continue
        material['map_surface']=json.dumps(settings,ensure_ascii=False)
        if 'two_sided' in settings:material.use_backface_culling=not settings['two_sided']
        if not material.use_nodes:continue
        shader=next((n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if not shader:continue
        kind=settings['kind']
        if kind in ('translucent','water'):
            material.surface_render_method='BLENDED'
            if hasattr(material,'use_transparency_overlap'):material.use_transparency_overlap=False
            for name in ('Alpha','Metallic','Roughness','IOR','Transmission Weight'):
                for link in list(shader.inputs[name].links):material.node_tree.links.remove(link)
            shader.inputs['Alpha'].default_value=1.0
            shader.inputs['Transmission Weight'].default_value=1-settings['opacity']
            shader.inputs['IOR'].default_value=settings['ior']
            shader.inputs['Roughness'].default_value=settings['roughness']
            shader.inputs['Metallic'].default_value=0
            if settings.get('transmittance_color') is not None:
                for link in list(shader.inputs['Base Color'].links):material.node_tree.links.remove(link)
                shader.inputs['Base Color'].default_value=(*settings['transmittance_color'],1)
            if kind=='water':
                shader.inputs['Base Color'].default_value=(*settings.get('color',[.01,.035,.045]),1)
                texture=source.get('textures',{}).get('Normal')
                if texture:
                    import bpy
                    image=bpy.data.images.load(str(root/'source-render'/texture['RelativePath']),check_existing=True)
                    image.colorspace_settings.name='Non-Color'
                    tex=material.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
                    normal=material.node_tree.nodes.new('ShaderNodeNormalMap')
                    material.node_tree.links.new(tex.outputs['Color'],normal.inputs['Color'])
                    material.node_tree.links.new(normal.outputs['Normal'],shader.inputs['Normal'])
            # Saved Principled transmission provides physical glass in Cycles;
            # keep render opacity separately for UE's translucent surface.
            if hasattr(material,'use_raytrace_refraction'):material.use_raytrace_refraction=True
        elif kind=='masked':
            color=shader.inputs['Base Color']
            image_node=color.links[0].from_node if color.is_linked else None
            if image_node and image_node.type=='TEX_IMAGE':
                material.node_tree.links.new(image_node.outputs['Alpha'],shader.inputs['Alpha'])
        elif kind=='opaque':
            for link in list(shader.inputs['Alpha'].links):material.node_tree.links.remove(link)
            shader.inputs['Alpha'].default_value=1.0
        report.append({'material':material.name,'kind':kind,'source':material.get('unrealMaterialPath')})
    (root/'surface_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
