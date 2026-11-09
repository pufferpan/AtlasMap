"""Suppress HLOD0 proxies only when the same source cell has detail meshes.

Static exports load every level together. Unlike game streaming they cannot
switch HLOD cells off automatically. Match source paths, never texture colour
or display names; unmatched distant proxies must remain visible.
"""
import json
import re

REVISION = 'source-cell-hlod0-v1'
DETAIL = re.compile(r'^(.*?/Runtime/)(BigMeshGroup|MidMeshGroup|SmallMeshGroup)/\2_(-?\d+)_(-?\d+)\.umap$', re.I)
PROXY = re.compile(r'^(.*?/Runtime/)HLOD/HLOD0_(-?\d+)_(-?\d+)\.umap$', re.I)


def source(row):
    data = row.get('dfmap') or row.get('properties', {}).get('map_source') or {}
    return json.loads(data) if isinstance(data, str) else data


def covered_proxies(instances):
    cells = set()
    for row in instances:
        data = source(row)
        match = DETAIL.match(str(data.get('sourceLevel', '')).replace('\\', '/'))
        visibility = data.get('visibility') or {}
        if match and not (row.get('hidden_render') or visibility.get('hiddenInGame')
                          or visibility.get('ownerHidden') or visibility.get('visible') is False
                          or visibility.get('renderable') is False):
            cells.add((match[1].casefold(), int(match[3]), int(match[4])))
    result = {}
    for row in instances:
        data = source(row)
        match = PROXY.match(str(data.get('sourceLevel', '')).replace('\\', '/'))
        if match and (match[1].casefold(), int(match[2]), int(match[3])) in cells:
            identity = data.get('sourceId')
            if not identity:
                raise ValueError('HLOD proxy lacks stable source ID: ' + str(data.get('sourceLevel')))
            result[identity] = data['sourceLevel']
    return result


def apply_manifest(manifest, instances):
    covered = covered_proxies(instances)
    suppressed = []
    for obj in manifest['objects']:
        data = source(obj)
        if obj.get('type') == 'MESH' and data.get('sourceId') in covered:
            suppressed.append(dict(object_id=obj['id'], source_id=data['sourceId'],
                                   source_level=covered[data['sourceId']]))
            obj['hidden_render'] = True
            obj['hidden_editor'] = True
            obj['map_lod_policy'] = REVISION
    manifest['counts']['hidden_render_meshes'] = sum(
        o.get('type') == 'MESH' and bool(o.get('hidden_render')) for o in manifest['objects'])
    report = dict(complete=True, revision=REVISION, suppressed=len(suppressed), objects=suppressed)
    manifest['lod_policy'] = report
    return report
