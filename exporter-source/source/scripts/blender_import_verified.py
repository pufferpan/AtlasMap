"""Import a new dfmap GLB/split run, restore source state, and validate bounds.

blender --background --factory-startup --python blender_import_verified.py --
    <scene.glb | split-directory | export-directory> [--save new.blend]

Existing scene objects are retained. Never run an old repair script merely
because it appears in a historical log. Full metadata survives as JSON strings.
"""
import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path


def read_glb_json(path):
    with Path(path).open('rb') as stream:
        magic, version, total = struct.unpack('<III', stream.read(12))
        if magic != 0x46546C67 or version != 2:
            raise ValueError('Expected glTF 2.0 GLB: ' + str(path))
        size, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A:
            raise ValueError('GLB JSON chunk missing: ' + str(path))
        return json.loads(stream.read(size).decode('utf-8').rstrip(' \0'))


def expected_bounds(entry):
    if 'blenderBoundsMinM' in entry and 'blenderBoundsMaxM' in entry:
        return entry['blenderBoundsMinM'], entry['blenderBoundsMaxM']
    lo, hi = entry.get('ueBoundsMin'), entry.get('ueBoundsMax')
    if lo is None or hi is None:
        return None
    return [lo[0] / 100, -hi[1] / 100, lo[2] / 100], [hi[0] / 100, -lo[1] / 100, hi[2] / 100]


def source_hidden(source):
    flags = source.get('visibility', {})
    return (flags.get('renderable') is False or flags.get('hiddenInGame') is True
            or flags.get('visible') is False or flags.get('ownerHidden') is True
            or flags.get('editorOnly') is True)


def source_for_object(name, records):
    if name in records:
        return records[name]
    # Blender appends numeric suffixes when names collide in an existing scene.
    base = re.sub(r'\.\d{3,}$', '', name)
    return records.get(base)


def main(argv=None):
    import bpy
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('--save')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--bounds-tolerance-m', type=float, default=.05)
    options = parser.parse_args(argv)
    source = Path(options.input).resolve()
    save_path = Path(options.save).resolve() if options.save else None
    if save_path and save_path.exists() and not options.overwrite:
        raise FileExistsError('Save target already exists; choose a new file: ' + str(save_path))
    if source.is_dir() and (source / 'split/manifest.json').exists():
        source = source / 'split'
    if source.is_dir():
        manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8-sig'))
        entries = manifest['levels']
    else:
        if source.suffix.lower() != '.glb':
            raise ValueError('Input must be a GLB or split export directory')
        entries = [{'file': source.stem, 'glb': source.name}]
    root = source if source.is_dir() else source.parent
    report = {'input': str(source), 'axis': 'Blender metres = UE centimetres (x,-y,z)/100',
              'files': [], 'errors': [], 'source_metadata_objects': 0,
              'source_hidden_objects': 0, 'existing_objects_retained': len(bpy.data.objects)}
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    for entry in entries:
        path = root / entry['glb']
        if not path.is_file():
            report['errors'].append({'file': str(path), 'reason': 'missing GLB'})
            continue
        doc = read_glb_json(path)
        records = {node.get('name', ''): node.get('extras', {}).get('dfmap')
                   for node in doc.get('nodes', []) if node.get('extras', {}).get('dfmap')}
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(path))
        imported = [obj for obj in bpy.data.objects if obj not in before]
        meshes = [obj for obj in imported if obj.type == 'MESH']
        collection = bpy.data.collections.new('map_' + entry.get('file', path.stem))
        scene.collection.children.link(collection)
        bounds_lo, bounds_hi = np.full(3, np.inf), np.full(3, -np.inf)
        matched_ids, hidden_ids = set(), set()
        for obj in imported:
            for old in list(obj.users_collection):
                old.objects.unlink(obj)
            collection.objects.link(obj)
            meta = source_for_object(obj.name, records)
            if meta:
                obj['map_source_json'] = json.dumps(meta, ensure_ascii=False, separators=(',', ':'))
                for key, value in [('map_source_id', meta.get('sourceId')),
                                   ('map_source_level', meta.get('sourceLevel')),
                                   ('map_source_component', meta.get('sourceComponentPath')),
                                   ('source_level', meta.get('sourceLevel')),
                                   ('source', meta.get('unrealMeshPath'))]:
                    if value is not None:
                        obj[key] = value
                matched_ids.add(meta['sourceId'])
                obj['map_collision_json'] = json.dumps(meta.get('collision', {}), ensure_ascii=False)
                obj['map_override_materials_json'] = json.dumps(meta.get('overrideMaterials', []), ensure_ascii=False)
                if source_hidden(meta):
                    obj.hide_render = True
                    obj.hide_viewport = True
                    obj.hide_set(True)
                    hidden_ids.add(meta['sourceId'])
            if obj.type == 'MESH' and len(obj.data.vertices):
                coords = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
                obj.data.vertices.foreach_get('co', coords)
                matrix = np.asarray(obj.matrix_world, dtype=np.float64)
                world = coords.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
                bounds_lo = np.minimum(bounds_lo, world.min(axis=0))
                bounds_hi = np.maximum(bounds_hi, world.max(axis=0))
        expected_ids = {meta['sourceId'] for meta in records.values()}
        missing = sorted(expected_ids - matched_ids)
        if missing:
            report['errors'].append({'file': path.name, 'reason': 'source metadata not matched', 'source_ids': missing})
        row = {'file': path.name, 'source_level': entry.get('sourceLevel', entry.get('level')),
               'mesh_objects': len(meshes), 'source_metadata_objects': len(matched_ids),
               'source_hidden_objects': len(hidden_ids), 'source_ids': sorted(matched_ids)}
        expected = expected_bounds(entry)
        if expected and meshes:
            delta = float(max(np.abs(bounds_lo - expected[0]).max(), np.abs(bounds_hi - expected[1]).max()))
            row['bounds_error_m'] = delta
            if not math.isfinite(delta) or delta > options.bounds_tolerance_m:
                report['errors'].append({'file': path.name, 'reason': 'bounds mismatch', 'error_m': delta})
        report['files'].append(row)
        report['source_metadata_objects'] += len(matched_ids)
        report['source_hidden_objects'] += len(hidden_ids)
        print('ATLASMAP_IMPORT', json.dumps({key: val for key, val in row.items() if key != 'source_ids'}, ensure_ascii=False))
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.clip_end = 1000000.0
                area.spaces.active.clip_start = .05
    report['complete'] = not report['errors']
    target = root / 'blender_import_validation.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if save_path and report['complete']:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(save_path), compress=True)
    print('ATLASMAP_IMPORT_REPORT', str(target), 'PASS' if report['complete'] else 'FAILED')
    if report['errors']:
        raise RuntimeError('Import validation failed; see ' + str(target))
    return report


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
