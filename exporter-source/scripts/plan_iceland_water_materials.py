"""Summarize source inheritance and explicit native-water compatibility choices.

Offline only. Does not edit Unreal assets, Blender scenes, or root import plans.
"""
import json
from pathlib import Path

ROOT=Path('D:/AtlasMap-tooling/out/Iceland')
OUT=ROOT/'water_rebuild/20261031'
SOURCE=OUT/'material_source'
AUDIT=ROOT/'audit/water_source/shader'

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def vector(v):return [v.get(k,0.0) for k in ['R','G','B','A']]

defaults={'scalars':{},'vectors':{},'textures':{},'switches':{}}
default_conflicts=[]
for file in list(AUDIT.glob('MF_*.json'))+list(SOURCE.glob('MF_*.json'))+[AUDIT/'M_Ocean_Coastline.json']:
    for obj in read(file):
        typ=obj['type'];p=obj.get('value',{}).get('Properties',{});name=p.get('ParameterName')
        if not name:continue
        if typ=='MaterialExpressionScalarParameter':kind,value='scalars',p.get('DefaultValue',0.0)
        elif typ=='MaterialExpressionVectorParameter':kind,value='vectors',vector(p.get('DefaultValue',{}))
        elif typ in ['MaterialExpressionStaticSwitchParameter','MaterialExpressionStaticBoolParameter']:kind,value='switches',p.get('DefaultValue',False)
        elif 'TextureObjectParameter' in typ:kind,value='textures',p.get('Texture',{}).get('ObjectPath')
        else:continue
        if name in defaults[kind] and defaults[kind][name]!=value:
            default_conflicts.append({'kind':kind,'name':name,'previous':defaults[kind][name],'next':value,'file':file.name})
        defaults[kind][name]=value

paths={p.stem:p for p in SOURCE.glob('*.json') if p.stem.startswith(('Mi_','MI_'))}
def resolve(name):
    obj=next(o for o in read(paths[name]) if 'MaterialInstance' in o['type'])
    p=obj['value']['Properties'];parent=p['Parent']['ObjectPath'].rsplit('/',1)[-1].split('.')[0]
    if parent=='M_Ocean_Coastline':result=json.loads(json.dumps(defaults));chain=['M_Ocean_Coastline']
    else:result=resolve(parent);chain=result.pop('inheritance_chain')
    for key,kind in [('ScalarParameterValues','scalars'),('VectorParameterValues','vectors'),('TextureParameterValues','textures')]:
        for entry in p.get(key,[]):
            value=entry.get('ParameterValue');name_=entry['ParameterInfo']['Name']
            result[kind][name_]=vector(value) if kind=='vectors' else value.get('ObjectPath') if kind=='textures' and value else value
    for entry in p.get('StaticParameters',{}).get('StaticSwitchParameters',[]):
        if entry.get('bOverride',False):result['switches'][entry['ParameterInfo']['Name']]=entry['Value']
    result['inheritance_chain']=chain+[name]
    return result

variants={name:resolve(name) for name in paths}
coast=variants['Mi_WaterHD_IceLand_Coastline']
deep=variants['Mi_WaterHD_IceLand_CoastlineDeepWater']
far=variants['MI_M_WaterHD_IceLand_FarMesh']
assert coast['switches']['UseSingleLayerWater'] is True
assert deep['switches']['UseSingleLayerWater'] is False
assert far['switches']['UseSingleLayerWater'] is False

def native_volume(params,shallow=False):
    vec=params['vectors']
    a=vec['Shoreline_SurfaceAbsorption' if shallow else 'DeepWaterSurfaceAbsorption']
    s=vec['Shoreline_SurfaceScattering' if shallow else 'DeepWater_SurfaceScattering0']
    return {'absorption_inverse_cm':[1.0/max(v,1.0) for v in a[:3]],
            'scattering_inverse_cm':[max(v,0)*max(s[3],0) for v in s[:3]],
            'uninterpreted_absorption_alpha':a[3],
            'status':'explicit physical compatibility interpretation; original conversion math stripped'}

projection=coast['vectors']['WaterDataProjectPos']
expected=[194531.73-2*600,-186331.44+2*600+(600-100)*128,
          2*(512*2*(600-100)-(512+1)*(600-100)),2*(600-100)*128]
assert all(abs(x-y)<.02 for x,y in zip(projection,expected))
plan={
 'source_variants':variants,
 'default_conflicts':default_conflicts,
 'projection':{
   'parameter':'WaterDataProjectPos','value':projection,'MI_branch':True,
   'center_size_proven_by':'BP_FluxCoastlineMesh SetTextureProjectPos(Map=0) bytecode; matches actor position, mesh extent600, FixBoundOffset100, Rows512, Cols128',
   'source_actor_location_xy':[194531.73,-186331.44],
   'bounds_xy':[[projection[0]-projection[2]/2,projection[1]-projection[3]/2],[projection[0]+projection[2]/2,projection[1]+projection[3]/2]],
   'candidate_native_uv':'(WorldPosition.xy-WaterDataProjectPos.xy)/WaterDataProjectPos.zw+0.5',
   'y_orientation':'positive world Y to positive texture V, supported by parent geographic/texture inspection; final shore point validation required',
   'do_not_use':'MPC default center194531.73,-115661.44,size513000,129000; active MI branch has different bounds',
   'D1_channels':'not proven; MF_CoastlineDataGet has no retained computational expressions',
   'D2_channels':'not proven; do not label any channel ground depth without geographic/height validation',
   'water_heightmap':'Iceland_Water_Heightmap_R16 is water-surface height for water query/underwater logic; not established as seabed height'
 },
 'component_bindings':{
   'SM_WaterPlan_In_Iceland_01':'Mi_WaterHD_IceLand_Coastline',
   'SM_WaterPlan_In_Iceland_02':'Mi_WaterHD_IceLand_CoastlineDeepWater',
   'SM_WaterPlan_In_Iceland_03':'Mi_WaterHD_IceLand_CoastlineDeepWater',
   'SM_WaterPlan_Out_1':'MI_M_WaterHD_IceLand_FarMesh'
 },
 'native_compatibility':{
   'coastline':{'volume':native_volume(coast,True),'base_color':[0,0,0],
       'roughness_min':coast['scalars']['WaterRoughnessMin'],'phase_g_candidate':coast['scalars']['SurfacePhaseG1'],
       'color_scale_behind_water':coast['vectors']['Shoreline_ColorBehind'][:3],
       'specular_candidate':coast['vectors']['WaterSpecular'][0]/.08,
       'specular_note':'Treat source WaterSpecular.r as dielectric F0 only as explicit compatibility interpretation, not proven original channel semantics'},
   'deep_water':{'source_UseSingleLayerWater':False,'source_DeepWater':True,
       'volume_if_native_fallback_is_chosen':native_volume(deep,False),
       'note':'Prefer separate surface/opaque deep-water compatibility branch. If using native SLW for expedience, record deliberate native fallback rather than claim source static switch restored.'},
   'far_water':{'source_UseSingleLayerWater':False,'source_EnableFoam':False,'source_UseDetailWave':False,
       'note':'No shore foam or detailed WPO; retain large-distance normal motion and source environment reflection.'},
   'surface_normals':'Use source normal/volume animation at unchanged non-color encoding; 3D wave texture channel decode is not recovered here.',
   'absorption_warning':'Never feed source RGB148/269/350 directly into native SLW coefficient pins; native exp(-distance*coefficient) would extinguish light within 1cm.',
   'foam':'Use source texture/profile and conservative geographically verified shore mask. Do not invent R=depth/G=foam labels for unproven packed channels.',
   'camera_depth':'Native SLW pass handles its own behind-water depth. Do not insert unsupported opaque SceneDepth custom lookups without actual shader compile/readback validation.'
 },
 'runtime_visibility':'Original Near/Far HISM are false after construction; PC runtime primarily uses static In01/02/03+Out_1. Keep old equivalent HISM proxy retained but hidden; do not stack both surfaces.',
 'validation_required':['Source IDs and non-water object transforms/materials unchanged','Four water components bound by full source override paths','D1/D2 highest mip preserved; non-color channels never gamma-converted','UV projection checked at independent land/sea and island points','Native water shaders compile in active renderer, not just tool return','Time-separated normal/foam frames change while source geometry remains stable','Underwater/shoreline remains explicitly incomplete if native volume or gameplay interaction absent']
}
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'water_material_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'variants':len(variants),'projection':projection,'coastSLW':True,'deepSLW':False,'farSLW':False},ensure_ascii=False))
