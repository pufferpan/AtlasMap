"""Restore persistent helper visibility and the source sky component flags.

Run inside the editor only for the imported Iceland level. Source objects,
user transforms and their material overrides are retained.
"""
import json
import unreal
import ue_iceland_bridge as bridge

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
assert world.get_path_name().split('.')[0] == bridge.MANIFEST['level']
actors = bridge.find_actors()
hidden = []
with unreal.ScopedEditorTransaction('Restore persistent Iceland source visibility'):
    for row in bridge.MANIFEST['objects']:
        if row['type'] != 'MESH' or not row['hidden_editor']:
            continue
        actor = actors[row['id']]
        actor.static_mesh_component.modify()
        actor.static_mesh_component.set_visibility(False, False)
        actor.set_is_temporarily_hidden_in_editor(True)
        hidden.append(row['id'])
    # Original IceLand_TODLight SkyDomeMesh.StaticMeshComponent0 explicitly
    # disables both of these flags. A huge imported sky must not cast shadows.
    sky = actors['O_ca64216549857f97184c'].static_mesh_component
    sky.modify()
    sky.set_editor_property('cast_shadow', False)
    sky.set_editor_property('visible_in_ray_tracing', False)

assert unreal.EditorLoadingAndSavingUtils.save_current_level()
output_data = {'source_objects': len(actors), 'hidden_components': len(hidden),
               'source_sky_shadow': sky.get_editor_property('cast_shadow'),
               'source_sky_ray_tracing': sky.get_editor_property('visible_in_ray_tracing'),
               'saved': True}
(bridge.ROOT / 'visibility_repair_status.json').write_text(
    json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
