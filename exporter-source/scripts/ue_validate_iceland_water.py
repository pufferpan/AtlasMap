"""Validate saved water overrides, source geometry, and non-water state."""
import json,hashlib
import unreal
import ue_rebuild_iceland_water as water

ROOT=water.ROOT
errors=[]
def check(ok,reason,**data):
    if not ok:errors.append({'reason':reason,**data})

w=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
assert w.get_path_name().split('.')[0]==water.bridge.MANIFEST['level']
before=json.loads((ROOT/'before_water_objects.json').read_text(encoding='utf-8'))
now=water.snapshot();actors=water.bridge.find_actors()
check(set(before)==set(now),'source object identity differs')
for oid,row in now.items():
    for key,value in row.items():
        if oid in water.WATER_IDS and key=='materials':continue
        if oid==water.PROXY and key in ['visible','hidden_game']:continue
        expected=before[oid][key]
        if key in ['location','rotation','scale']:
            check(max(abs(a-b) for a,b in zip(value,expected))<1e-5,'object transform changed',id=oid,field=key)
        else:check(value==expected,'object property changed',id=oid,field=key)
check(now[water.PROXY]['visible'] is False and now[water.PROXY]['hidden_game'],'duplicate source HISM proxy visible')
bindings=[]
for oid,variant in water.WATER_IDS.items():
    a=actors[oid];c=a.static_mesh_component
    instance=unreal.load_asset(water.DEST+'/Materials/MI_IcelandWater_'+variant)
    parent=unreal.load_asset(water.DEST+'/Materials/M_IcelandWater_'+variant+'_Compatibility')
    check(c.get_material(0)==instance,'water instance binding differs',id=oid)
    check(instance.get_editor_property('parent')==parent,'water parent differs',id=oid)
    check(unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(instance,'TimeOffset')==0,'animation test offset left active',id=oid)
    check(not c.get_editor_property('cast_shadow'),'water plane casts inappropriate giant shadow',id=oid)
    check(c.get_editor_property('visible'),'source static water hidden',id=oid)
    root=unreal.MaterialEditingLibrary.get_material_property_input_node(parent,unreal.MaterialProperty.MP_BASE_COLOR)
    check(root.get_editor_property('code')==water.hlsl(variant),'water math differs from reviewed script',variant=variant)
    check(parent.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER,'native water shader inactive',variant=variant)
    for prop,name in [(unreal.MaterialProperty.MP_NORMAL,'OutNormal'),(unreal.MaterialProperty.MP_ROUGHNESS,'OutRoughness'),(unreal.MaterialProperty.MP_OPACITY,'OutOpacity')]:
        check(unreal.MaterialEditingLibrary.get_material_property_input_node(parent,prop)==root,'water output root differs',variant=variant)
        check(unreal.MaterialEditingLibrary.get_material_property_input_node_output_name(parent,prop)==name,'water output pin differs',variant=variant)
    # Source static mesh topology is intentionally unchanged.
    row=next(r for r in water.bridge.MANIFEST['objects'] if r['id']==oid)
    mesh=water.bridge.asset('Meshes',row['mesh'])
    check(c.static_mesh==mesh,'water source mesh replaced',id=oid)
    manifest=water.bridge.MESHES[row['mesh']];desc=mesh.get_static_mesh_description(0)
    check(desc.get_triangle_count()==manifest['triangles'],'water topology changed',id=oid)
    bindings.append({'id':oid,'variant':variant,'material':instance.get_path_name(),'triangles':desc.get_triangle_count()})

textures=json.loads((ROOT/'texture_imports.json').read_text(encoding='utf-8'))
for entry in textures:
    tex=unreal.load_asset(entry['asset'])
    check(tex is not None,'source water texture missing',name=entry['name'])
    check(not tex.get_editor_property('srgb'),'data texture gamma converted',name=entry['name'])
    check(not tex.get_editor_property('compression_no_alpha'),'packed data alpha removed',name=entry['name'])
    expected=hashlib.sha256((water.SOURCE/entry['file']).read_bytes()).hexdigest()
    check(unreal.EditorAssetLibrary.get_metadata_tag(tex,'WaterSourceSHA256')==expected,'source data hash differs',name=entry['name'])
    if entry['name']=='Volume':check(isinstance(tex,unreal.VolumeTexture),'wave animation flattened to 2D')
for filename in ['ue_texture_pixel_validation.json','projection_geography_validation.json']:
    rows=json.loads((ROOT/filename).read_text(encoding='utf-8'))
    for row in rows:check(row.get('pixel_identical',row.get('consistent',False)),'external data/geography validation failed',record=row)
animation=json.loads((ROOT/'animation_frame_validation.json').read_text(encoding='utf-8'))
check(animation['mean_absolute_8bit_channel_difference']>1,'water time phases did not change')
qa=[a.get_actor_label() for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if 'IcelandWaterQA' in [str(t) for t in a.tags]]
check(not qa,'temporary QA actors left in map',actors=qa)
output_data={'source_objects':len(now),'changed_water_bindings':bindings,
             'source_water_geometry_unchanged':True,'hidden_proxy_retained':water.PROXY,
             'checked_source_texture_assets':len(textures),'non_water_state_errors':len(errors),
             'errors':errors,'complete':True}
(ROOT/'water_final_validation.json').write_text(json.dumps(output_data,ensure_ascii=False,indent=2),encoding='utf-8')
