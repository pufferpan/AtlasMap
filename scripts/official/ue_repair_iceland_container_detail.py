"""Preserve decoded container paint/rust detail in the compatibility shader.

The cooked source does not preserve its full layer expression. This explicitly
documented approximation keeps the original tint and masks, modulates the paint
by the real albedo, and mixes base roughness instead of replacing it everywhere.
The original parent remains intact for comparison/reversal.
"""
import json
import unreal
import ue_iceland_bridge as bridge

assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_path_name().split('.')[0] == bridge.MANIFEST['level']
original = bridge.DEST + '/Materials/Master_68b5f503eb0217e2'
destination = bridge.DEST + '/Materials/Master_Container_SourceDetail_Compatibility'
parent = unreal.load_asset(destination)
if parent is None:
    parent = unreal.EditorAssetLibrary.duplicate_asset(original, destination)
assert isinstance(parent, unreal.Material)
root = unreal.MaterialEditingLibrary.get_material_property_input_node(parent, unreal.MaterialProperty.MP_BASE_COLOR)
old = unreal.MaterialEditingLibrary.get_material_property_input_node(unreal.load_asset(original), unreal.MaterialProperty.MP_BASE_COLOR).get_editor_property('code')
paint = '(float4(K_0,K_1,K_2,1.0)).rgb'
assert old.count(paint) == 1
code = old.replace(paint, '(Tex_0).rgb*' + paint)
code = code.replace('OutRoughness=saturate(1.0);', 'OutRoughness=saturate(lerp((Tex_3).g,1.0,saturate((Tex_1).r)));')
root.set_editor_property('code', code)
bridge.metadata(parent, 'CompatibilityApproximation', 'Source albedo modulates paint tint to retain rust/paint detail; base roughness mixed by source mask. Full original layer math was stripped.')
bridge.metadata(parent, 'OriginalParent', original)
unreal.MaterialEditingLibrary.recompile_material(parent)
bridge.save(parent)
changed = []
for row in bridge.INSTANCE_PLAN['instances']:
    if 'Props_Industrial_Container' not in row['source_name'] or row['parent'] != 'Master_68b5f503eb0217e2':
        continue
    obj = bridge.asset('Materials', row['id'])
    unreal.MaterialEditingLibrary.set_material_instance_parent(obj, parent)
    unreal.MaterialEditingLibrary.update_material_instance(obj)
    assert obj.get_editor_property('parent') == parent
    for name, value in row['scalars'].items():
        assert abs(unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(obj, name) - value) < 1e-5
    for name, value in row['textures'].items():
        assert unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(obj, name) == bridge.asset('Textures', value)
    bridge.save(obj)
    changed.append(row['id'])
report = {'parent': destination, 'original_parent': original, 'instances': changed, 'count': len(changed),
          'textures_and_tints_unchanged': True, 'shader_code': code,
          'note': 'Compatibility detail-preserving approximation, not a recovered native game formula.'}
(bridge.ROOT / 'container_detail_compatibility_repair.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
output_data = {'parent': destination, 'changed_instances': len(changed), 'texture_and_tint_validation': 'passed'}
