"""Read saved schema-v2 imports and verify persistent visibility and overrides.

blender --background imported.blend --python-exit-code 1 --python this.py
"""
import json
from pathlib import Path
import bpy

rows=[]
errors=[]
for obj in bpy.context.scene.objects:
    text=obj.get('map_source_json')
    if not text:continue
    source=json.loads(text)
    flags=source.get('visibility',{})
    hidden=flags.get('renderable') is False
    if hidden and not (obj.hide_render and obj.hide_viewport):
        errors.append({'id':source['sourceId'],'reason':'source hidden flags did not persist'})
    expected=[value for value in source.get('overrideMaterials',[]) if value]
    actual=[slot.material.get('unrealMaterialPath') for slot in obj.material_slots if slot.material]
    for path in expected:
        if path not in actual:errors.append({'id':source['sourceId'],'reason':'override not bound in saved Blender material slots','expected':path,'actual':actual})
    rows.append({'id':source['sourceId'],'hidden':hidden,'material_paths':actual})
report={'file':bpy.data.filepath,'source_objects':len(rows),'hidden_objects':sum(r['hidden'] for r in rows),'errors':errors,'complete':not errors,'objects':rows}
path=Path(bpy.data.filepath).with_suffix('.saved_validation.json')
path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('ATLASMAP_SAVED_VALIDATION',len(rows),'objects',len(errors),'errors',str(path))
if errors:raise RuntimeError('Saved source visibility or material overrides differ')
